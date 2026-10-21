package com.example.bluelink

import android.os.Handler
import java.util.UUID

/**
 * Сессия с кольцом: подписки, опрос, разбор ответов и взмахов.
 *
 * Приложение не «верит» в успех: формат кадров считается подтверждённым только
 * после ответа с правильным CRC. До этого в интерфейсе честно написано
 * «проверяю», а не «подключено».
 */
class RingSession(
    private val ble: BleCentral,
    private val ui: Handler,
    private val log: (String) -> Unit,
    private val changed: () -> Unit
) {

    var detection: Ring.Detection? = null
        private set
    var framing: Ring.Framing? = null
        private set
    var framingConfirmed = false
        private set
    var status = "Кольцо не подключено"
    var battery: Int? = null
        private set
    var firmware: String? = null
        private set
    var heartRate: Int? = null
        private set
    var spo2: Int? = null
        private set
    var stress: Int? = null
        private set
    var capabilitiesText = ""
        private set
    var lastGesture = ""
        private set
    var gestureCount = 0
        private set
    var hidReportCount = 0
        private set
    var reportMapSummary = ""
        private set
    val gestureLog = ArrayList<String>()

    private var currentServices: List<GattServiceInfo> = emptyList()

    /** Нажатие/взмах, распознанный по HID. Вызывается и для «неизвестных» отчётов. */
    var onGesture: ((String) -> Unit)? = null

    private val jl = Ring.JlFramer()
    private val legacy = Ring.LegacyFramer()
    private var legacySerial = 0
    private var hidMap: HidMap.Map? = null
    private var lastGestureAt = 0L
    private var lastGestureName = ""
    private var timers = ArrayList<Runnable>()
    private var active = false

    private fun later(delay: Long, block: () -> Unit) {
        val r = Runnable { if (active) block() }
        timers.add(r)
        ui.postDelayed(r, delay)
    }

    private fun clearTimers() {
        for (r in timers) ui.removeCallbacks(r)
        timers.clear()
    }

    fun reset() {
        active = false
        clearTimers()
        jl.reset()
        framingConfirmed = false
        framing = null
        detection = null
        status = "Кольцо не подключено"
        battery = null
        firmware = null
        heartRate = null
        spo2 = null
        stress = null
        capabilitiesText = ""
        lastGesture = ""
        gestureCount = 0
        hidReportCount = 0
        reportMapSummary = ""
        hidMap = null
        gestureLog.clear()
    }

    fun stop() {
        active = false
        clearTimers()
    }

    /** Запуск после обнаружения сервисов. */
    fun start(services: List<GattServiceInfo>) {
        reset()
        currentServices = services
        val d = Ring.detect(services)
        detection = d
        active = true
        if (!d.ring) {
            status = "Это не похоже на кольцо: нет сервисов A00A/B003 или 0BC0."
            changed()
            return
        }
        framing = d.framing
        status = "Кольцо найдено (${d.family}). Проверяю протокол…"
        log("Кольцо: семейство ${d.family}; " + d.reasons.joinToString("; "))
        changed()

        later(250) { subscribeAll() }
        later(700) { readReportMap() }
        later(1100) { firstProbes() }
        later(4200) { fallbackProbe() }
        later(9000) {
            if (!framingConfirmed) {
                status = "Кольцо не ответило ни на один из двух форматов кадров. " +
                    "Похоже, у этой прошивки свой протокол — команды писать не будем, " +
                    "чтобы не мешать кольцу. Взмахи (HID) при этом можем принимать."
                log("Кольцо: ни современный (0xAB), ни старый (0x7E) формат не ответил")
                changed()
            }
        }
    }

    private fun subscribeAll() {
        val services = currentServices
        for (svc in services) {
            if (svc.uuid == Ring.SVC_DATA && svc.chars.any { it.uuid == Ring.CH_NOTIFY }) {
                ble.subscribe(Ring.SVC_DATA, Ring.CH_NOTIFY, true)
                log("Кольцо: подписался на ответы (A00A → B003)")
            }
            if (svc.uuid == Ring.SVC_HID) {
                // Отчётов бывает несколько с ОДНИМ И ТЕМ ЖЕ UUID (2A4D) — поэтому
                // подписываемся на каждое вхождение отдельно, по его номеру.
                var ordinal = 0
                var ok = 0
                for (ch in svc.chars) {
                    if (GattNames.shortCode(ch.uuid) != 0x2A4D) continue
                    val myIndex = ordinal
                    ordinal += 1
                    if (!ch.notifiable) continue
                    ble.subscribe(Ring.SVC_HID, ch.uuid, true, myIndex)
                    ok += 1
                }
                if (ok > 0) {
                    log("Кольцо: подписался на HID-отчёты ($ok из $ordinal) — жду взмахов")
                }
            }
        }
    }

    private fun readReportMap() {
        for (svc in currentServices) {
            if (svc.uuid != Ring.SVC_HID) continue
            val ch = svc.chars.firstOrNull { it.uuid == Ring.CH_REPORT_MAP && it.readable } ?: continue
            ble.read(Ring.SVC_HID, ch.uuid)
            log("Кольцо: читаю карту HID-отчётов (2A4B)")
        }
    }

    private fun firstProbes() {
        if (framingConfirmed) return
        sendJl(Ring.jlSessionInit())
        later(500) { sendJl(Ring.jlBattery()) }
        later(1100) { sendJl(Ring.jlDeviceInfo()) }
        later(1700) { sendJl(Ring.jlFeatures()) }
    }

    private fun fallbackProbe() {
        if (framingConfirmed) return
        sendLegacy(Ring.legacyBattery(nextSerial()))
        later(900) { sendLegacy(Ring.legacyFrame(0x00, ByteArray(0), nextSerial())) }
    }

    private fun nextSerial(): Int {
        legacySerial = if (legacySerial >= 65535) 1 else legacySerial + 1
        return legacySerial
    }

    private fun sendJl(frame: ByteArray) {
        ble.write(Ring.SVC_DATA, Ring.CH_WRITE, frame, false)
    }

    private fun sendLegacy(frame: ByteArray) {
        ble.write(Ring.SVC_DATA, Ring.CH_WRITE, frame, false)
    }

    /** Пользователь нажал «измерить пульс». */
    fun measure(kind: String) {
        if (!framingConfirmed || framing != Ring.Framing.JIELI) {
            status = "Кольцо ещё не подтвердило протокол — измерение не запускаю."
            changed()
            return
        }
        val type = when (kind) {
            "spo2" -> Ring.Measure.SPO2
            "stress" -> Ring.Measure.STRESS
            else -> Ring.Measure.HEART_RATE
        }
        sendJl(Ring.jlRealtime(type, true))
        status = "Прошу кольцо измерить: " + when (type) {
            Ring.Measure.SPO2 -> "кислород"
            Ring.Measure.STRESS -> "стресс"
            else -> "пульс"
        } + ". Результат появится в уведомлениях."
        log("Кольцо: команда измерения (тип 0x" + String.format("%02X", type) + ")")
        changed()
    }

    /** Входящее уведомление. Возвращает true, если оно наше. */
    fun onValue(service: UUID, char: UUID, value: ByteArray): Boolean {
        if (!active) return false
        val short = GattNames.shortCode(char)
        if (service == Ring.SVC_HID && short == 0x2A4B) {
            parseReportMap(value)
            return true
        }
        if (service == Ring.SVC_HID && short == 0x2A4D) {
            handleHidReport(value)
            return true
        }
        if (service == Ring.SVC_DATA && char == Ring.CH_NOTIFY) {
            var handled = false
            for (frame in jl.push(value)) {
                handled = true
                if (!framingConfirmed) {
                    framing = Ring.Framing.JIELI
                    framingConfirmed = true
                    status = "Кольцо отвечает современным форматом (0xAB) — связь есть."
                    log("Кольцо: формат подтверждён — современный (0xAB), CRC верный")
                }
                applyJl(frame)
            }
            if (!handled) {
                for (frame in legacy.push(value)) {
                    handled = true
                    if (!framingConfirmed) {
                        framing = Ring.Framing.LEGACY
                        framingConfirmed = true
                        status = "Кольцо отвечает старым форматом (0x7E) — связь есть."
                        log("Кольцо: формат подтверждён — старый (0x7E), XOR верный")
                    }
                    applyLegacy(frame)
                }
            }
            if (handled) changed()
            return handled
        }
        return false
    }

    private fun applyJl(frame: Ring.JlFrame) {
        log(
            "Кольцо → " + String.format("%02X %02X %02X", frame.cmd, frame.key, frame.keyFlag) +
                "  " + hex(frame.payload)
        )
        for (r in Ring.readJl(frame)) {
            when (r.metric) {
                Ring.Metric.BATTERY -> {
                    battery = r.value
                    capabilitiesText = "заряд сообщает"
                }
                Ring.Metric.FIRMWARE -> firmware = r.extra
                Ring.Metric.HEART_RATE -> heartRate = r.value
                Ring.Metric.SPO2 -> spo2 = r.value
                Ring.Metric.STRESS -> stress = r.value
                else -> {}
            }
        }
    }

    private fun applyLegacy(frame: Ring.LegacyFrame) {
        log(
            "Кольцо → старый кадр, команда 0x" + String.format("%02X", frame.cmd) +
                "  " + hex(frame.payload)
        )
        for (r in Ring.readLegacy(frame)) {
            if (r.metric == Ring.Metric.BATTERY) battery = r.value
        }
    }

    private fun parseReportMap(bytes: ByteArray) {
        val map = HidMap.parse(bytes)
        hidMap = map
        reportMapSummary = "Полей ввода: ${map.fields.size}; отчёты: " +
            (map.reportIds.joinToString(", ") { it.toString() }.ifBlank { "без номеров" })
        status = "Карта HID прочитана: $reportMapSummary"
        log("Кольцо: карта HID разобрана — $reportMapSummary")
        if (map.fields.isEmpty()) {
            log("Кольцо: карта HID пустая или нестандартная; начало: " + hex(bytes.take(24).toByteArray()))
        }
        changed()
    }

    private fun handleHidReport(value: ByteArray) {
        hidReportCount += 1
        val map = hidMap
        if (map == null || map.fields.isEmpty()) {
            if (hidReportCount <= 3) {
                log("Кольцо: HID-отчёт без карты — " + hex(value.take(16).toByteArray()))
            }
            return
        }
        var reportId = 0
        var data = value
        if (map.usesReportIds && value.isNotEmpty()) {
            reportId = value[0].toInt() and 0xFF
            data = value.copyOfRange(1, value.size)
        }
        val active = HidMap.active(map, reportId, data)
            .filterNot { it.first == 0x01 && (it.second == 0x30 || it.second == 0x31) }
        if (active.isEmpty()) return

        val names = active.mapNotNull { (page, usage) ->
            HidMap.usageName(page, usage)
        }.distinct()
        val shown = if (names.isNotEmpty()) names.joinToString(" + ") else
            active.joinToString(" + ") { HidMap.rawPair(it.first, it.second) }

        val now = System.currentTimeMillis()
        if (shown == lastGestureName && now - lastGestureAt < 900) return
        lastGestureName = shown
        lastGestureAt = now
        lastGesture = shown
        gestureCount += 1
        val line = timeStamp() + "  " + shown + "  " +
            active.joinToString(" ") { HidMap.rawPair(it.first, it.second) }
        gestureLog.add(0, line)
        while (gestureLog.size > 40) gestureLog.removeAt(gestureLog.size - 1)
        log("Кольцо: взмах — $shown")
        onGesture?.invoke(shown)
        changed()
    }

    private fun timeStamp(): String {
        val f = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US)
        return f.format(java.util.Date())
    }

    private fun hex(bytes: ByteArray): String =
        bytes.joinToString(" ") { String.format("%02X", it) }
}
