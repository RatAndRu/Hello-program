package com.example.bluelink

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/** Сколько пакетов пришло по характеристике и что в них было. */
class NotifStat {
    var count: Int = 0
    var bytes: Int = 0
    var first: ByteArray? = null
    var last: ByteArray? = null
    var lastAt: Long = 0
}

data class ReportInputs(
    val ctx: Context,
    val appVersion: String,
    val connName: String,
    val connAddress: String,
    val connState: String,
    val transport: String,
    val mtu: Int,
    val services: List<GattServiceInfo>,
    val opStatus: Map<String, Int>,
    val notifStats: Map<String, NotifStat>,
    val logs: List<String>,
    val scanItem: ScanItem?,
    val bondText: String,
    val sdpProfiles: List<UUID>,
    val crash: String?,
    val extraNotes: List<String>
)

/**
 * Текстовый отчёт: всё, что приложение реально знает об устройстве.
 * Формат — обычный текст, чтобы его можно было скопировать и переслать.
 */
object Report {

    fun build(i: ReportInputs): String {
        val out = StringBuilder()
        val stamp = SimpleDateFormat("dd.MM.yyyy HH:mm:ss", Locale("ru")).format(Date())

        out.appendLine("BlueLink · отчёт о диагностике")
        out.appendLine("Версия приложения: ${i.appVersion}")
        out.appendLine("Дата: $stamp")
        out.appendLine("Телефон: ${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        out.appendLine("Разрешения: ${permissionsText(i.ctx)}")
        out.appendLine()

        out.appendLine("=== УСТРОЙСТВО ===")
        out.appendLine("Имя: ${i.connName.ifBlank { "—" }}")
        out.appendLine("Адрес: ${i.connAddress.ifBlank { "—" }}")
        val type = when (i.scanItem?.deviceType) {
            1 -> "CLASSIC"
            2 -> "LE"
            3 -> "DUAL (LE + классический)"
            else -> "неизвестен"
        }
        out.appendLine("Тип устройства: $type")
        out.appendLine("Сопряжение: ${i.bondText}")
        i.scanItem?.let { item ->
            if (item.rssi != 0) out.appendLine("RSSI при сканировании: ${item.rssi} dBm")
            if (item.txPower != Int.MIN_VALUE) out.appendLine("Мощность передатчика (реклама): ${item.txPower} dBm")
            if (item.serviceUuids.isNotEmpty()) {
                out.appendLine("Сервисы в рекламе: ${item.serviceUuids.joinToString(", ") { "${GattNames.shortHex(it)} ${GattNames.uuidName(it) ?: ""}".trim() }}")
            }
            if (item.manufacturerData.isNotEmpty()) {
                for ((id, data) in item.manufacturerData) {
                    out.appendLine(
                        "Данные производителя 0x${String.format("%04X", id)}: " +
                            bytesToHex(data.take(32).toByteArray()) +
                            "  |" + bytesToAscii(data.take(16).toByteArray()) + "|"
                    )
                }
            }
        }
        out.appendLine("Состояние: ${i.connState}${if (i.transport.isNotBlank()) " · транспорт ${i.transport}" else ""} · MTU ${i.mtu}")
        out.appendLine(
            "SDP-профили (классические каналы): " +
                if (i.sdpProfiles.isEmpty()) "не запрашивались или их нет"
                else i.sdpProfiles.joinToString(", ") { u ->
                    GattNames.classicName(u)?.let { "$it (${GattNames.shortHex(u)})" }
                        ?: GattNames.uuidName(u)?.let { "$it (${GattNames.shortHex(u)})" }
                        ?: u.toString()
                }
        )
        out.appendLine()

        out.appendLine("=== СЕРВИСЫ И ХАРАКТЕРИСТИКИ: ${i.services.size} ===")
        if (i.services.isEmpty()) {
            out.appendLine("GATT-таблица пуста: устройство не отдало ни одного сервиса.")
        }
        for ((index, svc) in i.services.withIndex()) {
            out.appendLine("[${index + 1}] ${svc.uuid}")
            out.appendLine("    ${GattNames.serviceName(svc.uuid)} (${GattNames.shortHex(svc.uuid)}) · характеристик: ${svc.chars.size}")
            for (ch in svc.chars) {
                val props = StringBuilder()
                if (ch.readable) props.append("R")
                if (ch.writable) props.append("W")
                if (ch.notifiable) props.append("N")
                if (ch.properties and android.bluetooth.BluetoothGattCharacteristic.PROPERTY_BROADCAST != 0) props.append("B")
                if (ch.properties and android.bluetooth.BluetoothGattCharacteristic.PROPERTY_EXTENDED_PROPS != 0) props.append("E")
                out.appendLine("    · ${ch.uuid}")
                out.appendLine("      ${GattNames.charName(ch.uuid)} (${GattNames.shortHex(ch.uuid)}) свойства: ${props.ifEmpty { "—" }}")
                if (ch.descriptors.isNotEmpty()) {
                    out.appendLine("      дескрипторы: ${ch.descriptors.joinToString(", ") { it.toString() }}")
                }
                val ops = StringBuilder()
                for (kind in listOf("read", "write", "notify")) {
                    val st = i.opStatus["$kind|${svc.uuid}|${ch.uuid}"]
                    if (st != null) ops.append("$kind=${GattNames.gattStatusText(st)}; ")
                }
                if (ops.isNotEmpty()) out.appendLine("      операции: $ops")
                val value = ch.value ?: i.notifStats["${svc.uuid}|${ch.uuid}"]?.last
                if (value != null && value.isNotEmpty()) {
                    val head = value.take(40).toByteArray()
                    out.appendLine("      значение: ${bytesToHex(head)}${if (value.size > 40) " … (${value.size} байт)" else ""}")
                    out.appendLine("      как текст: |${bytesToAscii(head)}|")
                }
            }
        }
        out.appendLine()

        out.appendLine("=== ПАКЕТЫ ОТ УСТРОЙСТВА ===")
        if (i.notifStats.isEmpty()) {
            out.appendLine("За время работы не пришло ни одного уведомления от устройства.")
        } else {
            for ((key, stat) in i.notifStats) {
                val parts = key.split("|")
                val charUuid = parts.getOrNull(1) ?: key
                out.appendLine("$charUuid (${GattNames.charName(UUID.fromString(charUuid))}): пакетов ${stat.count}, байт ${stat.bytes}")
                stat.first?.let { out.appendLine("   первый: ${bytesToHex(it.take(32).toByteArray())}") }
                stat.last?.let { out.appendLine("   последний: ${bytesToHex(it.take(32).toByteArray())}") }
            }
        }
        out.appendLine()

        out.appendLine("=== ВЫВОДЫ ===")
        for (hint in hints(i)) out.appendLine("• $hint")
        for (note in i.extraNotes) out.appendLine("• $note")
        out.appendLine()

        i.crash?.let {
            out.appendLine("=== ПОСЛЕДНЯЯ ОШИБКА ПРИЛОЖЕНИЯ ===")
            out.appendLine(it.take(4000))
            out.appendLine()
        }

        out.appendLine("=== ЖУРНАЛ (${i.logs.size} строк) ===")
        if (i.logs.isEmpty()) out.appendLine("Журнал пуст.")
        for (line in i.logs) out.appendLine(line)

        return out.toString()
    }

    private fun permissionsText(ctx: Context): String {
        val names = if (Build.VERSION.SDK_INT >= 31) {
            listOf(
                android.Manifest.permission.BLUETOOTH_SCAN,
                android.Manifest.permission.BLUETOOTH_CONNECT
            )
        } else {
            listOf(
                android.Manifest.permission.ACCESS_FINE_LOCATION,
                android.Manifest.permission.ACCESS_COARSE_LOCATION
            )
        }
        return names.joinToString(", ") { name ->
            val granted = ctx.checkSelfPermission(name) == android.content.pm.PackageManager.PERMISSION_GRANTED
            name.substringAfterLast('.') + "=" + if (granted) "есть" else "НЕТ"
        }
    }

    /** Короткие выводы по собранным данным: что мешает и куда смотреть дальше. */
    private fun hints(i: ReportInputs): List<String> {
        val hints = ArrayList<String>()
        val authStatuses = i.opStatus.values.filter { it == 5 || it == 15 || it == 8 || it == 12 }
        val sdpNames = i.sdpProfiles.mapNotNull { GattNames.classicName(it) }

        if (i.connState != "CONNECTED") {
            hints.add("Соединение не установлено — сначала нужно подключиться; без него данных не будет.")
        }
        if (i.connState == "CONNECTED" && i.services.isEmpty()) {
            hints.add(
                "GATT-таблица пуста. Возможные причины: устройство требует сопряжение до чтения, " +
                    "работает только по классическим профилям или отдаёт данные исключительно своему приложению."
            )
        }
        if (authStatuses.isNotEmpty()) {
            hints.add(
                "Операции вернули код ${authStatuses.distinct().joinToString(", ") { GattNames.gattStatusText(it) }} — " +
                    "устройство требует аутентификацию или шифрование: нужно системное сопряжение (кнопка «Сопряжение»)."
            )
        }
        if (i.bondText.startsWith("не сопряжено") && i.services.isNotEmpty()) {
            hints.add("Устройство не сопряжено. Если чтение/запись даёт ошибки — попробуйте сопряжение.")
        }
        if (sdpNames.any { it.contains("A2DP") || it.contains("HFP") || it.contains("AVRCP") }) {
            hints.add(
                "По SDP устройство объявляет себя как аудиоустройство (${sdpNames.joinToString(", ")}). " +
                    "Это классический Bluetooth: данных в GATT, скорее всего, нет — только звук через систему."
            )
        }
        if (sdpNames.any { it.contains("SPP") || it.contains("OBEX") || it.contains("HID") }) {
            hints.add(
                "В SDP есть последовательный/сервисный канал (${sdpNames.joinToString(", ")}). Значит, обмен может идти " +
                    "по RFCOMM — это уже не GATT, такие каналы телефоны третьим приложениям не отдают, " +
                    "но сам факт говорит, что протокол закрытый."
            )
        }
        if (i.notifStats.isEmpty() && i.services.isNotEmpty()) {
            hints.add(
                "Устройство молчит: ни одного уведомления. Возможно, нужно сначала отправить команду " +
                    "(«Писать» в GATT или камера), либо данные идут только по Wi-Fi."
            )
        }
        if (i.scanItem?.manufacturerData?.isNotEmpty() == true) {
            hints.add(
                "В рекламе есть данные производителя — по их префиксу можно опознать вендора и протокол " +
                    "(это хороший признак, что устройство открытое)."
            )
        }
        return hints
    }

    fun saveToFile(ctx: Context, text: String): File? = try {
        val dir = File(ctx.filesDir, "reports").apply { mkdirs() }
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        File(dir, "bluelink-report-$stamp.txt").apply { writeText(text) }
    } catch (e: Exception) {
        null
    }
}

/**
 * Автоматический обход устройства: читает все читаемые характеристики
 * и подписывается на все уведомления, чтобы поймать то, что устройство шлёт само.
 */
class DeviceAuditor(
    private val ble: BleCentral,
    private val onStep: (String) -> Unit,
    private val onDone: (String) -> Unit
) {
    private val handler = Handler(Looper.getMainLooper())
    private var running = false
    private var index = 0
    private val queue = ArrayList<Pair<UUID, UUID>>()   // (сервис, характеристика)
    private val readable = HashSet<String>()

    fun isRunning(): Boolean = running

    fun start() {
        if (running) {
            onDone("Обход уже идёт")
            return
        }
        val services = ble.services
        if (services.isEmpty()) {
            onDone("GATT пуст — обходить нечего. Сначала нужно получить сервисы устройства.")
            return
        }
        running = true
        index = 0
        queue.clear()
        readable.clear()
        for (svc in services) {
            for (ch in svc.chars) {
                if (ch.readable) {
                    queue.add(svc.uuid to ch.uuid)
                    readable.add("${svc.uuid}|${ch.uuid}")
                }
            }
        }
        onStep("Всего характеристик: ${services.sumOf { it.chars.size }}, читаемых: ${queue.size}. Начинаю обход…")
        if (queue.isEmpty()) {
            subscribeAll()
        } else {
            next()
        }
    }

    fun stop() {
        running = false
    }

    private fun next() {
        if (!running) return
        if (index >= queue.size) {
            subscribeAll()
            return
        }
        val (svc, ch) = queue[index]
        index += 1
        onStep("Чтение ${index}/${queue.size}: ${GattNames.charName(ch)} (${GattNames.shortHex(ch)})")
        ble.read(svc, ch)
        handler.postDelayed({ next() }, 400)
    }

    private fun subscribeAll() {
        if (!running) return
        var subscribedCount = 0
        for (svc in ble.services) {
            for (ch in svc.chars) {
                if (ch.notifiable) {
                    ble.subscribe(svc.uuid, ch.uuid, true)
                    subscribedCount += 1
                }
            }
        }
        onStep("Подписался на уведомления: $subscribedCount. Слушаю устройство 10 секунд…")
        handler.postDelayed({
            if (!running) return@postDelayed
            running = false
            val stats = ble.opStatus
            val failed = stats.filterValues { it != 0 }
            onDone(
                "Обход завершён. Прочитано ${queue.size} характеристик, подписок $subscribedCount, " +
                    "ошибок операций: ${failed.size}. Подробности — в отчёте."
            )
        }, 10_000)
    }
}
