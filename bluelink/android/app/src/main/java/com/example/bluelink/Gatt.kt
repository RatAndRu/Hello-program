package com.example.bluelink

import android.bluetooth.BluetoothGattCharacteristic
import java.util.UUID

/** Одна характеристика GATT в удобном для интерфейса виде. */
data class GattCharInfo(
    val uuid: UUID,
    val properties: Int,
    val value: ByteArray? = null,
    val descriptors: List<UUID> = emptyList()
) {
    val readable: Boolean
        get() = (properties and BluetoothGattCharacteristic.PROPERTY_READ) != 0
    val writable: Boolean
        get() = (properties and (
            BluetoothGattCharacteristic.PROPERTY_WRITE or
                BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE
            )) != 0
    val notifiable: Boolean
        get() = (properties and (
            BluetoothGattCharacteristic.PROPERTY_NOTIFY or
                BluetoothGattCharacteristic.PROPERTY_INDICATE
            )) != 0

    fun props(): String {
        val out = StringBuilder()
        if (readable) out.append("R")
        if (writable) out.append("W")
        if (notifiable) out.append("N")
        return out.toString()
    }
}

data class GattServiceInfo(val uuid: UUID, val chars: List<GattCharInfo>)

/** Расшифровка стандартных UUID: без этого список характеристик — просто набор цифр. */
object GattNames {

    private val services = mapOf(
        0x1800 to "Generic Access",
        0x1801 to "Generic Attribute",
        0x1805 to "Current Time Service",
        0x1809 to "Health Thermometer",
        0x180A to "Device Information",
        0x180D to "Heart Rate",
        0x180F to "Battery Service",
        0x1810 to "Blood Pressure",
        0x1812 to "Human Interface Device",
        0x1816 to "Cycling Speed & Cadence",
        0x1818 to "Cycling Power",
        0x181A to "Environmental Sensing",
        0x181C to "User Data",
        0x181F to "Continuous Glucose Monitoring",
        0x1826 to "Fitness Machine",
        0x1844 to "Audio Input Control",
        0x1846 to "Volume Control",
        0x1848 to "Media Control",
        0x184E to "Audio Stream Control",
        0xFE59 to "Nordic Secure DFU",
        0xFE9F to "Google Fast Pair",
        0xFEA0 to "Google Fast Pair (старый)",
        0xFEA6 to "GoPro / управление камерой",
        0xFFE0 to "UART / производитель (FFE0)",
        0xFFE5 to "Производитель (FFE5)",
        0xFFF0 to "Производитель (FFF0)"
    )

    private val chars = mapOf(
        0x2A00 to "Device Name",
        0x2A01 to "Appearance",
        0x2A04 to "Peripheral Preferred Connection Parameters",
        0x2A05 to "Service Changed",
        0x2A19 to "Battery Level",
        0x2A23 to "System ID",
        0x2A24 to "Model Number",
        0x2A25 to "Serial Number",
        0x2A26 to "Firmware Revision",
        0x2A27 to "Hardware Revision",
        0x2A28 to "Software Revision",
        0x2A29 to "Manufacturer Name",
        0x2A2A to "IEEE 11073-20601 Regulatory Certification",
        0x2A37 to "Heart Rate Measurement",
        0x2A38 to "Body Sensor Location",
        0x2A39 to "Heart Rate Control Point",
        0x2A4A to "HID Information",
        0x2A4B to "Report Map",
        0x2A4C to "HID Control Point",
        0x2A4D to "Report",
        0x2A4E to "Protocol Mode",
        0x2A5B to "CSC Measurement",
        0x2A63 to "Cycling Power Measurement",
        0x2A6E to "Temperature",
        0x2A6F to "Humidity",
        0x2A6D to "Pressure",
        0x2A76 to "UV Index",
        0x2A98 to "Weight Measurement",
        0x2A9D to "Weight Scale Feature",
        0x2AA6 to "Central Address Resolution",
        0x2AC9 to "Aggregate",
        0x2B18 to "Volume State",
        0x2B7D to "Volume Flags"
    )

    fun uuidName(uuid: UUID): String? {
        val short = shortCode(uuid) ?: return null
        return services[short] ?: chars[short]
    }

    fun serviceName(uuid: UUID): String = uuidName(uuid) ?: "Неизвестный сервис"

    fun charName(uuid: UUID): String = chars[shortCode(uuid) ?: -1] ?: services[shortCode(uuid) ?: -1] ?: "Характеристика"

    /** 16-битный код из UUID вида 0000XXXX-0000-1000-8000-00805f9b34fb. */
    fun shortCode(uuid: UUID): Int? {
        val s = uuid.toString().lowercase()
        if (!s.endsWith("-0000-1000-8000-00805f9b34fb")) return null
        if (!s.startsWith("0000")) return null
        val hex = s.substring(4, 8)
        return hex.toIntOrNull(16)
    }

    fun shortHex(uuid: UUID): String {
        val code = shortCode(uuid)
        return if (code != null) String.format("0x%04X", code) else uuid.toString().substring(0, 8) + "…"
    }

    /** Названия классических профилей (SDP): по ним видно, какие каналы есть у устройства. */
    private val classic = mapOf(
        0x1101 to "SPP (последовательный порт)",
        0x1105 to "OBEX Object Push",
        0x110A to "A2DP Source (аудио)",
        0x110B to "A2DP Sink (аудио)",
        0x110C to "AVRCP Target",
        0x110D to "AVRCP Controller",
        0x110E to "AVRCP Remote Control",
        0x1112 to "HFP (громкая связь)",
        0x111E to "HFP Audio Gateway",
        0x111F to "HFP Hands-Free",
        0x1124 to "HID (человеческий интерфейс)",
        0x112D to "SIM Access",
        0x112F to "Phonebook Access (PCE)",
        0x1130 to "Phonebook Access (PSE)",
        0x1132 to "Message Access Server",
        0x1133 to "Message Notification Server",
        0x1200 to "PnP Information",
        0x1800 to "GAP",
        0x1843 to "MAP"
    )

    fun classicName(uuid: UUID): String? {
        val s = uuid.toString().lowercase()
        // Классические UUID вида 0000110b-0000-1000-8000-00805f9b34fb
        if (!s.endsWith("-0000-1000-8000-00805f9b34fb") || !s.startsWith("0000")) return null
        val code = s.substring(4, 8).toIntOrNull(16) ?: return null
        return classic[code]
    }

    fun gattStatusText(code: Int): String = when (code) {
        0 -> "0 (успех)"
        1 -> "1 (неверный handle)"
        2 -> "2 (чтение запрещено)"
        3 -> "3 (запись запрещена)"
        4 -> "4 (неверный пакет)"
        5 -> "5 (нужна аутентификация — обычно требуется сопряжение)"
        6 -> "6 (запрос не поддерживается)"
        7 -> "7 (неверное смещение)"
        8 -> "8 (недостаточно прав)"
        9 -> "9 (очередь подготовки заполнена)"
        10 -> "10 (атрибут не найден)"
        11 -> "11 (атрибут не длинный)"
        12 -> "12 (мал размер ключа)"
        13 -> "13 (неверная длина значения)"
        15 -> "15 (нужно шифрование — устройство закрыто)"
        137 -> "137 (устройство занято)"
        133 -> "133 (ошибка GATT, часто нужен повтор/переподключение)"
        else -> "$code (см. документацию Android)"
    }

    fun uuidLabel(uuid: UUID): String {
        val name = uuidName(uuid)
        return if (name != null) "$name (${shortHex(uuid)})" else uuid.toString()
    }

    /** Человеческое значение для известных характеристик. */
    fun describe(charUuid: UUID, value: ByteArray): String? {
        return when (shortCode(charUuid)) {
            0x2A19 -> if (value.isNotEmpty()) "Батарея: ${value[0].toInt() and 0xFF}%" else null
            0x2A00, 0x2A24, 0x2A25, 0x2A26, 0x2A27, 0x2A28, 0x2A29 ->
                String(value, Charsets.UTF_8).trim().ifEmpty { null }
            0x2A6E -> if (value.size >= 2) {
                val raw = (value[0].toInt() and 0xFF) or ((value[1].toInt() and 0xFF) shl 8)
                val signed = if (raw > 32767) raw - 65536 else raw
                "Температура: ${signed / 100.0} °C"
            } else null
            0x2A6F -> if (value.isNotEmpty()) "Влажность: ${(value[0].toInt() and 0xFF)}%" else null
            0x2A37 -> if (value.size >= 2) {
                val flags = value[0].toInt() and 0xFF
                val bpm = if ((flags and 0x01) != 0 && value.size >= 3)
                    (value[1].toInt() and 0xFF) or ((value[2].toInt() and 0xFF) shl 8)
                else value[1].toInt() and 0xFF
                "Пульс: $bpm уд/мин"
            } else null
            else -> null
        }
    }
}

fun bytesToHex(bytes: ByteArray): String =
    bytes.joinToString(" ") { String.format("%02X", it.toInt() and 0xFF) }

fun bytesToAscii(bytes: ByteArray): String {
    val out = StringBuilder()
    for (b in bytes) {
        val c = b.toInt() and 0xFF
        out.append(if (c in 32..126) c.toChar() else '.')
    }
    return out.toString()
}

/** "01 FF 2A" или "text:привет" -> байты. */
fun parsePayload(text: String): ByteArray {
    val trimmed = text.trim()
    if (trimmed.lowercase().startsWith("text:")) {
        return trimmed.substring(5).toByteArray(Charsets.UTF_8)
    }
    val clean = trimmed.replace(",", " ").replace("0x", "").replace("0X", "")
    if (clean.isEmpty()) return ByteArray(0)
    val parts = clean.split(Regex("\\s+")).filter { it.isNotEmpty() }
    val out = ByteArray(parts.size)
    for ((i, p) in parts.withIndex()) {
        if (p.length > 2) throw IllegalArgumentException("Байт «$p» длиннее двух символов")
        out[i] = (p.toInt(16) and 0xFF).toByte()
    }
    return out
}

/** hex-строка без пробелов, например 180f -> UUID. */
fun parseUuid(raw: String): UUID? {
    val s = raw.trim().lowercase().replace("0x", "")
    if (s.isEmpty()) return null
    if (s.length <= 4) {
        val code = s.padStart(4, '0')
        return UUID.fromString("0000$code-0000-1000-8000-00805f9b34fb")
    }
    if (s.length <= 8) {
        return UUID.fromString(s.padStart(8, '0') + "-0000-1000-8000-00805f9b34fb")
    }
    return try {
        UUID.fromString(s)
    } catch (e: Exception) {
        null
    }
}
