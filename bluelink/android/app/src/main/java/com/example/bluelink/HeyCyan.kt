package com.example.bluelink

import java.util.Calendar
import java.util.UUID

/**
 * Протокол очков HeyCyan / Goodway W630 (и родственных «умных очков» на SDK com.oudmon.ble).
 *
 * Всё восстановлено из официального SDK `glasses_sdk_20250723_v01.aar`
 * (классы `BaseReqCmd`, `BleConsumer`, `LargeDataHandler`, `CommandHandle`, `Constants`).
 *
 * В устройстве ДВА независимых канала команд:
 *
 *  1) Канал управления — сервис 6E40FFF0:
 *       пишем в 6E400002, слушаем 6E400003.
 *       Кадр ровно 16 байт: [команда][данные… нули][сумма всех предыдущих байт & 0xFF].
 *       Ответ: первый байт = команда | 0x80, второй байт — статус, последний — та же сумма.
 *
 *  2) Канал «больших данных» — сервис DE5BF728:
 *       пишем в DE5BF72A, слушаем DE5BF729.
 *       Кадр: BC | тип | длина(2, младшим вперёд) | CRC16(2, младшим вперёд) | данные.
 *       CRC16 = Modbus (init 0xFFFF, полином 0xA001).
 *
 * Тип в канале 2 — это и есть «команда»: 0x41 — управление очками (камера),
 * 0x42 — заряд, 0x40 — синхронизация времени, 0x43 — сведения об устройстве и т.д.
 *
 * Сами фотографии по Bluetooth не идут: очки поднимают Wi-Fi точку доступа,
 * а приложение тянет файлы по HTTP. BLE — только команды и статусы.
 */
object HeyCyan {

    val CTRL_SERVICE: UUID = UUID.fromString("6e40fff0-b5a3-f393-e0a9-e50e24dcca9e")
    val CTRL_WRITE: UUID = UUID.fromString("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
    val CTRL_NOTIFY: UUID = UUID.fromString("6e400003-b5a3-f393-e0a9-e50e24dcca9e")

    val SERIAL_SERVICE: UUID = UUID.fromString("de5bf728-d711-4e47-af26-65e3012a5dc7")
    val SERIAL_WRITE: UUID = UUID.fromString("de5bf72a-d711-4e47-af26-65e3012a5dc7")
    val SERIAL_NOTIFY: UUID = UUID.fromString("de5bf729-d711-4e47-af26-65e3012a5dc7")

    /** Кадр командного канала всегда 16 байт (Constants.CMD_DATA_LENGTH). */
    const val FRAME_LEN = 16

    const val CH_CTRL = "A"
    const val CH_SERIAL = "B"

    // ---------- Сборка кадров ----------

    /** CRC16/Modbus: init 0xFFFF, отражённый полином 0xA001. */
    fun crc16(data: ByteArray, offset: Int = 0, length: Int = data.size - offset): Int {
        var crc = 0xFFFF
        for (i in 0 until length) {
            crc = crc xor (data[offset + i].toInt() and 0xFF)
            for (bit in 0 until 8) {
                crc = if (crc and 1 != 0) (crc shr 1) xor 0xA001 else crc shr 1
            }
        }
        return crc and 0xFFFF
    }

    /** Кадр канала управления: [cmd][payload…][сумма]. */
    fun cmdFrame(cmd: Int, payload: ByteArray = ByteArray(0)): ByteArray {
        val out = ByteArray(FRAME_LEN)
        out[0] = cmd.toByte()
        val n = minOf(payload.size, FRAME_LEN - 2)
        System.arraycopy(payload, 0, out, 1, n)
        var sum = 0
        for (i in 0 until FRAME_LEN - 1) sum += out[i].toInt() and 0xFF
        out[FRAME_LEN - 1] = (sum and 0xFF).toByte()
        return out
    }

    /** Кадр канала больших данных: BC | тип | длина LE | CRC16 LE | данные. */
    fun bigFrame(type: Int, payload: ByteArray = ByteArray(0)): ByteArray {
        val out = ByteArray(6 + payload.size)
        out[0] = 0xBC.toByte()
        out[1] = type.toByte()
        out[2] = (payload.size and 0xFF).toByte()
        out[3] = ((payload.size shr 8) and 0xFF).toByte()
        if (payload.isEmpty()) {
            out[4] = 0xFF.toByte()
            out[5] = 0xFF.toByte()
        } else {
            val c = crc16(payload)
            out[4] = (c and 0xFF).toByte()
            out[5] = ((c shr 8) and 0xFF).toByte()
            System.arraycopy(payload, 0, out, 6, payload.size)
        }
        return out
    }

    /** Достаёт заряд из ответа любого канала, если он там есть. */
    fun batteryFrom(value: ByteArray): Int? {
        if (value.size == FRAME_LEN && (value[0].toInt() and 0x7F) == 0x03) {
            val level = value[1].toInt() and 0xFF
            if (level in 1..100) return level
        }
        if (isBigFrame(value)) {
            val type = value[1].toInt() and 0xFF
            if (type == 0x42 && value.size > 7) {
                val level = value[6].toInt() and 0xFF
                if (level in 1..100) return level
            }
        }
        return null
    }

    fun isBigFrame(value: ByteArray): Boolean =
        value.size >= 6 && (value[0].toInt() and 0xFF) == 0xBC

    // ---------- Разбор ответов ----------

    fun describe(value: ByteArray): String? {
        if (isBigFrame(value)) return describeBig(value)
        if (value.size == FRAME_LEN) return describeCmd(value)
        return null
    }

    fun describeCmd(frame: ByteArray): String {
        val raw = frame[0].toInt() and 0xFF
        val key = raw and 0x7F
        val err = raw and 0x80 != 0
        val body = hex(frame, 1, frame.size - 1)
        val name = cmdName(key)
        val sb = StringBuilder()
        sb.append("команда 0x").append(String.format("%02X", key))
        if (name.isNotEmpty()) sb.append(" (").append(name).append(")")
        if (key == 0x02 && frame.size > 1) {
            sb.append(" · ").append(
                when (frame[1].toInt()) {
                    4 -> "войти в режим съёмки"
                    5 -> "снять кадр"
                    6 -> "выйти из режима"
                    else -> "действие ${frame[1].toInt()}"
                }
            )
        }
        if (key == 0x3E && frame.size > 2) {
            sb.append(" · тип режима ").append(frame[2].toInt() and 0xFF)
        }
        sb.append(if (err) " · ответ очков" else " · подтверждение")
        sb.append(" · данные ").append(body)
        return sb.toString()
    }

    fun describeBig(frame: ByteArray): String {
        val type = frame[1].toInt() and 0xFF
        val len = (frame[2].toInt() and 0xFF) or ((frame[3].toInt() and 0xFF) shl 8)
        val crc = (frame[4].toInt() and 0xFF) or ((frame[5].toInt() and 0xFF) shl 8)
        val payload = if (frame.size > 6) frame.copyOfRange(6, frame.size) else ByteArray(0)
        val crcOk = payload.isNotEmpty() && crc16(payload) == crc
        val sb = StringBuilder()
        sb.append("тип 0x").append(String.format("%02X", type))
        val name = bigName(type)
        if (name.isNotEmpty()) sb.append(" (").append(name).append(")")
        sb.append(" · длина ").append(len).append("/").append(payload.size)
        if (payload.isNotEmpty()) sb.append(" · CRC ").append(if (crcOk) "ок" else "не сходится")
        if (payload.isNotEmpty()) sb.append(" · данные ").append(hex(payload))
        if (type == 0x42 && payload.isNotEmpty()) {
            sb.append(" · заряд ").append(payload[0].toInt() and 0xFF).append("%")
        }
        return sb.toString()
    }

    // ---------- Имена команд ----------

    fun cmdName(cmd: Int): String = when (cmd) {
        0x01 -> "установка времени"
        0x02 -> "камера"
        0x03 -> "заряд"
        0x04 -> "ОС телефона"
        0x3C -> "поддерживаемые функции"
        0x3E -> "управление режимом очков"
        0x3B -> "касание"
        0xA1 -> "ревизия приложения"
        0x93 -> "версии HW/FW"
        0x76 -> "энергосбережение"
        0x72 -> "уведомление"
        else -> ""
    }

    fun bigName(type: Int): String = when (type) {
        0x40 -> "синхронизация времени"
        0x41 -> "управление очками"
        0x42 -> "заряд"
        0x43 -> "сведения об устройстве"
        0x44 -> "голосовое пробуждение"
        0x45 -> "пульс"
        0x46 -> "проверка ношения"
        0x48 -> "голосовое воспроизведение"
        0x49 -> "включить BT"
        0x4A -> "аватар"
        0x52 -> "звук"
        0x2E -> "классический Bluetooth"
        0x59 -> "уведомления пакетами"
        0x74 -> "толчок файла"
        0x35 -> "температура"
        0x30 -> "старт файла"
        0x31 -> "инициализация файла"
        0x32 -> "следующий пакет"
        0x33 -> "проверка"
        0xFD -> "миниатюры снимков"
        0xFC -> "IP в модуль"
        else -> ""
    }

    // ---------- Готовые полезные кадры ----------

    /** Время: год%2000, месяц, день, часы, минуты, секунды — в BCD, 9 байт. */
    fun syncTimePayload(): ByteArray {
        val c = Calendar.getInstance()
        val out = ByteArray(9)
        out[0] = bcd(c.get(Calendar.YEAR) % 2000)
        out[1] = bcd(c.get(Calendar.MONTH) + 1)
        out[2] = bcd(c.get(Calendar.DAY_OF_MONTH))
        out[3] = bcd(c.get(Calendar.HOUR_OF_DAY))
        out[4] = bcd(c.get(Calendar.MINUTE))
        out[5] = bcd(c.get(Calendar.SECOND))
        out[6] = 1 // язык: en
        return out
    }

    private fun bcd(v: Int): Byte = (((v / 10) shl 4) or (v % 10)).toByte()

    // ---------- Опрос устройства ----------

    data class Probe(
        val channel: String,
        val type: Int,
        val payload: ByteArray,
        val title: String
    )

    /**
     * Минимальный набор запросов, который SDK шлёт сразу после подключения:
     * поддержка функций, версии, заряд, время — плюс попытка включить режим фото.
     */
    fun probes(): List<Probe> = listOf(
        Probe(CH_CTRL, 0x3C, ByteArray(0), "поддержка функций (0x3C)"),
        Probe(CH_CTRL, 0x03, ByteArray(0), "заряд (0x03)"),
        Probe(CH_CTRL, 0xA1, byteArrayOf(0x01), "ревизия приложения (0xA1)"),
        Probe(CH_SERIAL, 0x42, byteArrayOf(0x00, 0x00), "заряд по каналу B (0x42)"),
        Probe(CH_SERIAL, 0x43, byteArrayOf(0x00, 0x00), "сведения об устройстве (0x43)"),
        Probe(CH_SERIAL, 0x40, syncTimePayload(), "время (0x40)"),
        Probe(CH_CTRL, 0x3E, byteArrayOf(0x02, 0x01, 0x00), "режим очков: фото (0x3E)")
    )

    fun frameFor(channel: String, type: Int, payload: ByteArray): ByteArray =
        if (channel == CH_CTRL) cmdFrame(type, payload) else bigFrame(type, payload)

    // ---------- Утилиты ----------

    fun hex(data: ByteArray, from: Int = 0, to: Int = data.size): String {
        val sb = StringBuilder()
        for (i in from until minOf(to, data.size)) {
            if (sb.isNotEmpty()) sb.append(' ')
            sb.append(String.format("%02X", data[i].toInt() and 0xFF))
        }
        return sb.toString()
    }

    fun parseHex(text: String): ByteArray? {
        val clean = text.replace(Regex("[^0-9a-fA-F]"), "")
        if (clean.isEmpty() || clean.length % 2 != 0) return null
        return try {
            ByteArray(clean.length / 2) { i ->
                clean.substring(i * 2, i * 2 + 2).toInt(16).toByte()
            }
        } catch (e: Exception) {
            null
        }
    }
}
