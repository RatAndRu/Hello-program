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
    /** Что кольцо само заявило в меню возможностей. */
    var menuText = ""
    var menu: Ring.Menu? = null
        private set
    var measureState = ""
        private set
    var lastReading = ""
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
    /** Что уже попробовали и что из этого получило ответ — для честного отчёта. */
    val probeLog = ArrayList<String>()
    /** Всё, что кольцо реально сообщило, с временем — не пропадает при переподключении. */
    val readingsLog = ArrayList<String>()
    private var replies = 0
    private var readsAsked = 0
    private var subscribedOnce = false
    /** Сырые чтения характеристик кольца: что удалось прочитать без команд. */
    val rawReads = LinkedHashMap<String, String>()
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
        // Заряд, версию и последние измерения НЕ обнуляем: кольцо отдаёт их редко,
        // и после переподключения они бы исчезали с экрана.
        if (readingsLog.isEmpty() && lastReading.isNotBlank()) readingsLog.add(lastReading)
        capabilitiesText = ""
        menuText = ""
        menu = null
        measureState = ""
        lastReading = ""
        lastGesture = ""
        gestureCount = 0
        hidReportCount = 0
        reportMapSummary = ""
        hidMap = null
        gestureLog.clear()
        probeLog.clear()
        rawReads.clear()
        replies = 0
        readsAsked = 0
        subscribedOnce = false
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
        later(500) { readAllReadable() }
        later(700) { readReportMap() }
        later(1100) { firstProbes() }
        later(6200) { if (!framingConfirmed) probeOtherChannels() }
        // Даже когда кольцо уже отвечало, история измерений — самый надёжный
        // источник цифр: live-кадры приходят далеко не у всех прошивок.
        later(7500) { if (framingConfirmed) history() }
        later(4200) { fallbackProbe() }
        later(6500) { probeOtherChannels() }
        later(11000) {
            if (!framingConfirmed) {
                status = buildString {
                    append("Кольцо не ответило ни на один проверенный канал. ")
                    append("Это не поломка: у многих колец производительский канал закрыт, ")
                    append("а наружу отдаётся только пульт (HID). ")
                    append("Нажатия при этом ловятся как клавиши телефона — включите карточку «Кольцо как пульт» ниже.")
                }
                log("Кольцо: ни современный (0xAB), ни старый (0x7E) формат не ответил; каналы: " +
                    probeLog.joinToString("; "))
                changed()
            }
        }
    }

    private fun subscribeAll() {
        if (subscribedOnce) return
        subscribedOnce = true
        val services = currentServices
        for (svc in services) {
            if (svc.uuid == Ring.SVC_DATA && svc.chars.any { it.uuid == Ring.CH_NOTIFY }) {
                ble.subscribe(Ring.SVC_DATA, Ring.CH_NOTIFY, true)
                log("Кольцо: подписался на ответы (A00A → B003)")
            }
            if (svc.uuid == Ring.SVC_HID) {
                // Отчётов бывает несколько с ОДНИМ И ТЕМ ЖЕ UUID (2A4D) — поэтому
                // подписываемся на каждое вхождение отдельно, по его номеру.
                // Раньше подписывались на все экземпляры 2A4D подряд, и Android 13
                // отвечал «Need BLUETOOTH PRIVILEGED permission» на второй и далее.
                // Теперь берём первый экземпляр, на который подписка вообще возможна:
                // так меньше нагрузки на связь и кольцо не отваливается.
                var ordinal = 0
                var done = false
                var total = 0
                for (ch in svc.chars) {
                    if (GattNames.shortCode(ch.uuid) != 0x2A4D) continue
                    val myIndex = ordinal
                    ordinal += 1
                    if (!ch.notifiable) continue
                    total += 1
                    if (done) continue
                    ble.subscribe(Ring.SVC_HID, ch.uuid, true, myIndex)
                    done = true
                }
                if (done) {
                    log("Кольцо: подписался на HID-отчёты (1 из $total) — жду взмахов")
                    if (total > 1) {
                        log("Кольцо: остальные $total-1 отчётов HID Android не отдаёт приложению " +
                            "(нужно системное разрешение BLUETOOTH_PRIVILEGED)")
                    }
                }
            }
        }
    }

    /**
     * Читаем всё, что кольцо вообще разрешает читать. Это не «команды», а обычное
     * чтение GATT: оно безопасно и иногда сразу отдаёт заряд — у многих колец он
     * лежит в первой характеристике производительского сервиса.
     */
    private fun readAllReadable() {
        var asked = 0
        for (svc in currentServices) {
            if (svc.uuid != Ring.SVC_DATA && svc.uuid != Ring.SVC_FF00 && svc.uuid != Ring.SVC_0BC0) continue
            for (ch in svc.chars) {
                if (!ch.readable) continue
                if (GattNames.shortCode(ch.uuid) == 0x2A4B) continue
                ble.read(svc.uuid, ch.uuid)
                asked += 1
            }
        }
        if (asked > 0) log("Кольцо: читаю $asked характеристик без записи команд")
        readsAsked = asked
    }

    private fun readReportMap() {
        for (svc in currentServices) {
            if (svc.uuid != Ring.SVC_HID) continue
            val ch = svc.chars.firstOrNull { it.uuid == Ring.CH_REPORT_MAP && it.readable } ?: continue
            ble.read(Ring.SVC_HID, ch.uuid)
            log("Кольцо: читаю карту HID-отчётов (2A4B)")
        }
    }

    /**
     * Порядок как в официальном SDK: инициализация сеанса, часовой пояс, время,
     * меню возможностей, при необходимости — пароль. Без времени и меню кольцо
     * молча игнорирует команды измерения.
     */
    private fun firstProbes() {
        if (framingConfirmed) return
        sendJl(Ring.jlSessionInit())
        later(400) { sendJlTimezone() }
        later(900) { sendJlTime() }
        later(1400) { sendJl(Ring.jlFeatures()) }
        later(1900) { sendJl(Ring.jlBattery()) }
        later(2400) { sendJl(Ring.jlDeviceInfo()) }
        later(2900) { maybeAuthenticate() }
    }

    private fun sendJlTimezone() {
        val tz = java.util.TimeZone.getDefault()
        val offsetSeconds = tz.getOffset(System.currentTimeMillis()) / 1000
        sendJl(Ring.jlTimezone(offsetSeconds))
        log("Кольцо: передаю часовой пояс (${offsetSeconds / 3600} ч)")
    }

    private fun sendJlTime() {
        val now = java.util.Calendar.getInstance()
        sendJl(
            Ring.jlTimeSync(
                now.get(java.util.Calendar.YEAR),
                now.get(java.util.Calendar.MONTH) + 1,
                now.get(java.util.Calendar.DAY_OF_MONTH),
                now.get(java.util.Calendar.HOUR_OF_DAY),
                now.get(java.util.Calendar.MINUTE),
                now.get(java.util.Calendar.SECOND)
            )
        )
        log("Кольцо: передаю текущее время")
    }

    private fun maybeAuthenticate() {
        val m = menu ?: return
        if (!m.requiresPassword) return
        sendJl(Ring.jlAuthenticate())
        log("Кольцо: меню требует пароль — отправляю стандартный пароль 0000")
    }

    private fun fallbackProbe() {
        if (framingConfirmed) return
        sendLegacy(Ring.legacyBattery(nextSerial()))
        later(900) { sendLegacy(Ring.legacyFrame(0x00, ByteArray(0), nextSerial())) }
    }

    /**
     * Другие производительственные каналы. У части колец команды живут не в A00A,
     * а в FF00 или 0BC0. Мы пишем туда те же проверочные кадры и слушаем ответ.
     */
    private fun probeOtherChannels() {
        if (framingConfirmed) return
        for (channel in Ring.channels()) {
            if (channel.service == Ring.SVC_DATA) continue
            val svc = currentServices.firstOrNull { it.uuid == channel.service } ?: continue
            val hasWrite = svc.chars.any { it.uuid == channel.write }
            if (!hasWrite) {
                probeLog.add("${channel.title}: нет характеристики записи")
                continue
            }
            channel.notify?.let { n ->
                if (svc.chars.any { it.uuid == n && it.notifiable }) {
                    ble.subscribe(channel.service, n, true)
                    log("Кольцо: подписался на ${channel.title}")
                }
            }
            ble.write(channel.service, channel.write!!, Ring.jlBattery(), false)
            probeLog.add("${channel.title}: послал запрос заряда (0xAB)")
            later(1200) {
                ble.write(channel.service, channel.write!!, Ring.legacyBattery(nextSerial()), false)
                probeLog.add("${channel.title}: послал запрос заряда (0x7E)")
            }
        }
        log("Кольцо: проверяю дополнительные каналы — " +
            (probeLog.takeLast(4).joinToString("; ").ifBlank { "их нет" }))
    }

    private fun nextSerial(): Int {
        legacySerial = if (legacySerial >= 65535) 1 else legacySerial + 1
        return legacySerial
    }

    private var lastHistoryAt = 0L
    private var lastSendAt = 0L

    /**
     * Запись в кольцо. Раньше команды уходили пачками: кольцо отвечало потоком,
     * а потом связь рвалась. Теперь между кадрами держим паузу и не пишем,
     * когда сеанс уже завершён.
     */
    private fun sendJl(frame: ByteArray) {
        if (!active) return
        val now = System.currentTimeMillis()
        val wait = (lastSendAt + 220) - now
        lastSendAt = maxOf(now, lastSendAt + 220)
        if (wait <= 0) {
            ble.write(Ring.SVC_DATA, Ring.CH_WRITE, frame, false)
        } else {
            later(wait) { ble.write(Ring.SVC_DATA, Ring.CH_WRITE, frame, false) }
        }
    }

    private fun sendLegacy(frame: ByteArray) {
        ble.write(Ring.SVC_DATA, Ring.CH_WRITE, frame, false)
    }

    /**
     * Подписки живут только до переподключения. После каждого нового списка
     * сервисов подписываемся заново — иначе кольцо измеряет, а мы ничего не видим.
     */
    fun ensureSubscriptions(services: List<GattServiceInfo>) {
        currentServices = services
        active = true
        subscribedOnce = false
        subscribeAll()
        later(600) { readReportMap() }
        if (!framingConfirmed) {
            later(900) { firstProbes() }
        } else {
            // Протокол уже подтверждён — просто напоминаем кольцу, кто мы,
            // и просим последние измерения.
            later(400) { sendJl(Ring.jlSessionInit()) }
            later(1500) { history() }
        }
        log("Кольцо: восстановил подписки после подключения")
    }

    /** Забрать последние измерения из памяти кольца (история, а не live). */
    fun history() {
        // Не чаще раза в 8 секунд: кольцо отвечает потоком кадров, и частые
        // запросы подряд приводили к обрыву связи.
        val now = System.currentTimeMillis()
        if (now - lastHistoryAt < 8000) {
            log("Кольцо: историю только что запрашивали — подожду")
            return
        }
        lastHistoryAt = now
        if (!active) return
        if (!framingConfirmed) {
            status = "Кольцо ещё не ответило — историю не запрашиваю."
            changed()
            return
        }
        sendJl(Ring.jlHistory(Ring.Measure.HEART_RATE))
        later(1200) { sendJl(Ring.jlHistory(Ring.Measure.SPO2)) }
        later(2400) { sendJl(Ring.jlHistory(Ring.Measure.HRV)) }
        later(3600) { sendJl(Ring.jlHistory(Ring.Measure.STRESS)) }
        status = "Прошу у кольца последние измерения из памяти."
        measureState = "запрос истории отправлен"
        log("Кольцо: запрос истории 05 03 10 / 05 09 10 / 05 0A 10")
        changed()
    }

    /** Пользователь нажал «измерить пульс». */
    fun measure(kind: String) {
        if (!active) {
            status = "Кольцо не подключено — сначала подключитесь к нему."
            changed()
            return
        }
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
        measureState = "команда отправлена, жду ответ кольца"
        // У этой прошивки live-кадры могут не приходить вовсе (в 2.3 так и было).
        // Через 12 секунд молчания сами забираем последнее измерение из памяти.
        later(12_000) {
            if (framingConfirmed) {
                measureState = "live-кадры не пришли — забираю измерение из памяти кольца"
                log("Кольцо: ответа на измерение нет, запрашиваю историю")
                history()
            }
        }
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
        if ((service == Ring.SVC_DATA || service == Ring.SVC_FF00 || service == Ring.SVC_0BC0) &&
            char != Ring.CH_NOTIFY && readsAsked > 0
        ) {
            val key = GattNames.uuidLabel(service) + " / " + GattNames.uuidLabel(char)
            rawReads[key] = hex(value.take(16).toByteArray()) + (if (value.size > 16) " …(${value.size} Б)" else "")
            log("Кольцо: чтение $key → ${hex(value.take(8).toByteArray())}")
            changed()
            return true
        }
        if (service == Ring.SVC_FF00 || service == Ring.SVC_0BC0) {
            // Ответ на проверочный кадр в «чужом» сервисе — тоже настоящий ответ.
            replies += 1
            probeLog.add(
                GattNames.uuidLabel(service) + " → " + GattNames.uuidLabel(char) +
                    ": " + hex(value.take(20).toByteArray())
            )
            log("Кольцо: ответ в канале ${GattNames.uuidLabel(service)} — " + hex(value.take(20).toByteArray()))
            changed()
            return true
        }
        if (service == Ring.SVC_DATA && char == Ring.CH_NOTIFY) {
            var handled = false
            replies += 1
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

    private fun remember(text: String) {
        lastReading = text
        readingsLog.add(0, text)
        while (readingsLog.size > 20) readingsLog.removeAt(readingsLog.size - 1)
    }

    private fun applyJl(frame: Ring.JlFrame) {
        log(
            "Кольцо → " + String.format("%02X %02X %02X", frame.cmd, frame.key, frame.keyFlag) +
                "  " + hex(frame.payload)
        )
        if (frame.cmd == 0x02 && frame.key == 0x63) {
            val parsed = Ring.functionMenu(frame.payload)
            if (parsed != null) {
                menu = parsed
                menuText = if (parsed.streams.isEmpty())
                    "кольцо не заявило ни одного потока данных"
                else
                    "кольцо заявляет: " + parsed.streams.joinToString(", ") +
                        (if (parsed.requiresPassword) " · нужен пароль" else "")
                log("Кольцо: меню возможностей — $menuText")
                maybeAuthenticate()
            }
        }
        Ring.measureStatus(frame)?.let { st ->
            measureState = Ring.measureStatusText(st)
            log("Кольцо: измерение — $measureState")
            changed()
        }
        for (r in Ring.readJl(frame)) {
            when (r.metric) {
                Ring.Metric.BATTERY -> {
                    battery = r.value
                    capabilitiesText = "заряд сообщает"
                }
                Ring.Metric.FIRMWARE -> firmware = r.extra
                Ring.Metric.HEART_RATE -> {
                    heartRate = r.value
                    remember(timeStamp() + "  пульс $r.value уд/мин")
                }
                Ring.Metric.SPO2 -> {
                    spo2 = r.value
                    remember(timeStamp() + "  кислород $r.value%")
                }
                Ring.Metric.STRESS -> {
                    stress = r.value
                    remember(timeStamp() + "  стресс $r.value")
                }
                Ring.Metric.HRV -> remember(timeStamp() + "  HRV $r.value")
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
