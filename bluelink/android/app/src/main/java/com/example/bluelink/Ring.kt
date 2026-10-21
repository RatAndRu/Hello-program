package com.example.bluelink

import android.os.Handler
import java.util.UUID

/**
 * Умное кольцо (HerzRing Vision и подобные).
 *
 * Почему отдельный файл: кольцо — не очки. У него другой набор сервисов и другой
 * протокол, и отправлять ему команды очков нельзя (очки на это отвечают потоком
 * ошибок «нет характеристики», а кольцо просто игнорирует записи).
 *
 * Что здесь есть и насколько это проверено:
 *
 * 1. Определение семейства по набору сервисов, а не по названию. Названия врут,
 *    сервисы — нет. Совпадение A00A + B002 + B003 — это семейство RWfit
 *    (его же называют JieLi/Realtek). Источник: открытый разбор официального
 *    приложения com.rw.revivalfit (проект PulseLoopiOS, файлы RWfitProtocol.swift,
 *    RWfitJLCodec.swift, RWfitEncoder.swift). Там же формат кадров и CRC.
 * 2. Два формата кадров этого семейства: современный 0xAB (JieLi) и старый 0x7E
 *    (Realtek). Какой из них у конкретного кольца — заранее неизвестно, поэтому
 *    приложение пробует современный и по ответу подтверждает выбор.
 * 3. HID-сервис 0x1812: кольца отдают взмахи как отчёты HID. Мы читаем карту
 *    отчётов (2A4B), разбираем её и переводим нажатия в человеческие названия
 *    («свайп вперёд», «нажатие»). Это честный разбор, а не догадка по байтам.
 * 4. Пульс и прочее: команда «включить измерение» современного формата
 *    (06 09 00 тип 05 01). Ответ приходит записями по 6 байт. Пока не
 *    подтверждено на этом кольце — приложение так и пишет.
 *
 * Всё, что не подтверждено ответом устройства, помечается в интерфейсе как
 * «предположение».
 */
object Ring {

    fun uuid(code: Int): UUID =
        UUID.fromString(String.format("%08x-0000-1000-8000-00805f9b34fb", code))

    // Семейство RWfit (JieLi/Realtek): один сервис, запись в B002, ответы в B003.
    val SVC_DATA: UUID = uuid(0xA00A)
    val CH_WRITE: UUID = uuid(0xB002)
    val CH_NOTIFY: UUID = uuid(0xB003)

    // Маркеры платформы. Их наличие подсказывает формат кадров (JieLi), но
    // решение всё равно принимается по валидному ответу с верным CRC.
    val SVC_FF00: UUID = uuid(0xFF00)
    val SVC_AE00: UUID = uuid(0xAE00)
    val SVC_TELINK_OTA: UUID = UUID.fromString("00010203-0405-0607-0809-0a0b0c0d1912")

    // Неизвестный производительский сервис, который тоже встречается у колец.
    val SVC_0BC0: UUID = uuid(0x0BC0)
    val CH_0BC1: UUID = uuid(0x0BC1)
    val CH_0BC2: UUID = uuid(0x0BC2)

    // HID: взмахи и нажатия.
    val SVC_HID: UUID = uuid(0x1812)
    val CH_REPORT_MAP: UUID = uuid(0x2A4B)
    val CH_REPORT: UUID = uuid(0x2A4D)
    val CH_HID_INFO: UUID = uuid(0x2A4A)

    /**
     * Каналы, по которым кольцо может говорить. Их несколько, потому что по GATT
     * нельзя угадать, какой из производительских сервисов «главный»: у RWfit это
     * A00A, но у похожих прошивок команды идут в FF00 или 0BC0. Мы пробуем все
     * и оставляем тот, который ответил.
     */
    data class Channel(
        val title: String,
        val service: UUID,
        val write: UUID?,
        val notify: UUID?,
        val family: String
    )

    val CHANNEL_DATA = Channel("A00A → B003", SVC_DATA, CH_WRITE, CH_NOTIFY, "RWfit / JieLi")
    val CHANNEL_FF00 = Channel("FF00 → FF01", SVC_FF00, uuid(0xFF02), uuid(0xFF01), "неизвестный (FF00)")
    val CHANNEL_0BC0 = Channel("0BC0 → 0BC2", SVC_0BC0, CH_0BC1, CH_0BC2, "неизвестный (0BC0)")

    fun channels(): List<Channel> = listOf(CHANNEL_DATA, CHANNEL_FF00, CHANNEL_0BC0)

    enum class Framing(val label: String) {
        JIELI("современный (0xAB)"),
        LEGACY("старый (0x7E)")
    }

    /** Что мы поняли о найденном устройстве. */
    data class Detection(
        val ring: Boolean,
        val family: String,
        val framing: Framing?,
        val reasons: List<String>,
        val hasHid: Boolean,
        val hasDataService: Boolean
    )

    private fun shorts(services: List<GattServiceInfo>): Set<Int> =
        services.mapNotNull { GattNames.shortCode(it.uuid) }.toSet()

    fun detect(services: List<GattServiceInfo>): Detection {
        val s = shorts(services)
        val reasons = ArrayList<String>()
        var score = 0
        var family = "неизвестное"

        if (SVC_DATA in services.map { it.uuid } || 0xA00A in s) {
            score += 3
            family = "RWfit / JieLi"
            reasons.add("есть сервис данных A00A")
        }
        if (0xB002 in s) {
            score += 2
            reasons.add("есть характеристика записи B002")
        }
        if (0xB003 in s) {
            score += 2
            reasons.add("есть характеристика ответов B003")
        }
        if (0x0BC0 in s) {
            score += 1
            if (family == "неизвестное") family = "кольцо с сервисом 0BC0"
            reasons.add("есть производительский сервис 0BC0")
        }
        val hasHid = 0x1812 in s
        if (hasHid) {
            score += 1
            reasons.add("есть HID-сервис 1812 (взмахи)")
        }

        val hasData = (0xA00A in s) && (0xB003 in s)
        val framing = when {
            hasData && (0xFF00 in s || 0xAE00 in s) -> Framing.JIELI
            hasData -> Framing.JIELI
            else -> null
        }
        if (framing != null) {
            reasons.add(
                "формат кадров предварительно " + framing.label +
                    (if (0xFF00 in s) " (маркер FF00)" else "")
            )
        }

        return Detection(
            ring = score >= 2 && (hasData || 0x0BC0 in s),
            family = family,
            framing = framing,
            reasons = reasons,
            hasHid = hasHid,
            hasDataService = hasData
        )
    }

    // ---------- Форматы кадров ----------

    /** CRC-16/ARC (полином 0xA001, начальное 0) — как в современном формате. */
    fun crc16Arc(data: ByteArray, from: Int = 0, to: Int = data.size): Int {
        var crc = 0
        for (i in from until to) {
            crc = crc xor (data[i].toInt() and 0xFF)
            for (bit in 0 until 8) {
                crc = if (crc and 1 != 0) (crc shr 1) xor 0xA001 else crc shr 1
            }
        }
        return crc and 0xFFFF
    }

    /** XOR-сумма для старого формата. */
    fun xorSum(data: ByteArray): Int {
        var x = 0
        for (b in data) x = x xor (b.toInt() and 0xFF)
        return x and 0xFF
    }

    /**
     * Современный кадр: AB флаг длина(2, старший вперёд) CRC(2) полезная нагрузка.
     * Полезная нагрузка начинается с тройки {команда, ключ, флаг}.
     */
    fun jlFrame(payload: ByteArray, ack: Boolean = false): ByteArray {
        val crc = crc16Arc(payload)
        val out = ByteArray(6 + payload.size)
        out[0] = 0xAB.toByte()
        out[1] = if (ack) 0x11 else 0x01
        out[2] = ((payload.size shr 8) and 0xFF).toByte()
        out[3] = (payload.size and 0xFF).toByte()
        out[4] = ((crc shr 8) and 0xFF).toByte()
        out[5] = (crc and 0xFF).toByte()
        System.arraycopy(payload, 0, out, 6, payload.size)
        return out
    }

    /** Старый кадр: 7E 01 команда флаги длина серийный(2, старший вперёд) XOR нагрузка. */
    fun legacyFrame(cmd: Int, payload: ByteArray = ByteArray(0), serial: Int): ByteArray {
        val out = ByteArray(8 + payload.size)
        out[0] = 0x7E
        out[1] = 0x01
        out[2] = cmd.toByte()
        out[3] = 0x00
        out[4] = payload.size.toByte()
        out[5] = ((serial shr 8) and 0xFF).toByte()
        out[6] = (serial and 0xFF).toByte()
        out[7] = if (payload.isEmpty()) 0 else xorSum(payload).toByte()
        System.arraycopy(payload, 0, out, 8, payload.size)
        return out
    }

    data class JlFrame(val flag: Int, val cmd: Int, val key: Int, val keyFlag: Int, val payload: ByteArray)

    /** Сборка современного формата из потока уведомлений. */
    class JlFramer {
        private val buf = java.io.ByteArrayOutputStream()

        fun reset() = buf.reset()

        fun push(chunk: ByteArray): List<JlFrame> {
            buf.write(chunk)
            val out = ArrayList<JlFrame>()
            while (true) {
                var data = buf.toByteArray()
                if (data.isEmpty()) break
                var start = 0
                while (start < data.size && (data[start].toInt() and 0xFF) != 0xAB) start += 1
                if (start > 0) {
                    buf.reset()
                    buf.write(data, start, data.size - start)
                    continue
                }
                if (data.size < 6) break
                val flag = data[1].toInt() and 0xFF
                val len = ((data[2].toInt() and 0xFF) shl 8) or (data[3].toInt() and 0xFF)
                if (flag !in listOf(0x01, 0x11, 0x21) || len < 3 || len > 4096) {
                    buf.reset()
                    buf.write(data, 1, data.size - 1)
                    continue
                }
                if (data.size < len + 6) break
                val payload = data.copyOfRange(6, len + 6)
                val crc = ((data[4].toInt() and 0xFF) shl 8) or (data[5].toInt() and 0xFF)
                val frame = JlFrame(flag, payload[0].toInt() and 0xFF, payload[1].toInt() and 0xFF,
                    payload[2].toInt() and 0xFF, payload)
                if (crc16Arc(payload) == crc) out.add(frame)
                buf.reset()
                buf.write(data, 6 + len, data.size - (6 + len))
            }
            return out
        }
    }

    data class LegacyFrame(val cmd: Int, val payload: ByteArray, val serial: Int)

    /** Сборка старого формата. Многопакетные ответы здесь не встречаются. */
    class LegacyFramer {
        fun push(value: ByteArray): List<LegacyFrame> {
            if (value.size < 8 || (value[0].toInt() and 0xFF) != 0x7E) return emptyList()
            val cmd = value[2].toInt() and 0xFF
            val len = value[4].toInt() and 0xFF
            if (value.size < 8 + len) return emptyList()
            val serial = ((value[5].toInt() and 0xFF) shl 8) or (value[6].toInt() and 0xFF)
            val payload = value.copyOfRange(8, 8 + len)
            val check = value[7].toInt() and 0xFF
            if (len > 0 && xorSum(payload) != check) return emptyList()
            return listOf(LegacyFrame(cmd, payload, serial))
        }
    }

    // ---------- Расшифровка цифр здоровья ----------

    enum class Metric { BATTERY, FIRMWARE, HEART_RATE, SPO2, HRV, STRESS, TEMPERATURE, PRESSURE, UNKNOWN }

    data class Reading(val metric: Metric, val value: Int, val extra: String = "")

    /**
     * Разбор ответа современного формата. Полезная нагрузка начинается с тройки
     * {команда, ключ, флаг}: у живых измерений это 02 ключ 10, значение — в
     * записях по 6 байт (время 4 байта старшим вперёд + значение).
     */
    fun readJl(frame: JlFrame): List<Reading> {
        val p = frame.payload
        val out = ArrayList<Reading>()
        when (frame.cmd to frame.key) {
            0x02 to 0x03 -> if (p.size >= 4) out.add(Reading(Metric.BATTERY, p[3].toInt() and 0xFF))
            0x02 to 0x04 -> if (p.size >= 6) {
                out.add(
                    Reading(
                        Metric.FIRMWARE,
                        p[3].toInt() and 0xFF,
                        "${p[3].toInt() and 0xFF}.${p[4].toInt() and 0xFF}.${p[5].toInt() and 0xFF}"
                    )
                )
            }
            0x02 to 0x24 -> series(p) { item -> Reading(Metric.HEART_RATE, item[4].toInt() and 0xFF) }.let { out.addAll(it) }
            0x02 to 0x4E -> series(p) { item -> Reading(Metric.SPO2, item[4].toInt() and 0xFF) }.let { out.addAll(it) }
            0x02 to 0x69 -> series(p) { item -> Reading(Metric.HRV, item[4].toInt() and 0xFF) }.let { out.addAll(it) }
            0x02 to 0x4F -> series(p) { item -> Reading(Metric.STRESS, item[4].toInt() and 0xFF) }.let { out.addAll(it) }
            0x02 to 0x30 -> series(p) { item ->
                Reading(Metric.TEMPERATURE, item[4].toInt() and 0xFF, String.format("%.1f", (item[4].toInt() and 0xFF) + (item[5].toInt() and 0xFF) / 10.0))
            }.let { out.addAll(it) }
        }
        return out.filter { it.value > 0 }
    }

    private fun series(payload: ByteArray, item: (ByteArray) -> Reading): List<Reading> {
        val out = ArrayList<Reading>()
        var offset = 3
        while (offset + 6 <= payload.size) {
            val rec = payload.copyOfRange(offset, offset + 6)
            out.add(item(rec))
            offset += 6
        }
        return out
    }

    /** Разбор ответа старого формата: заряд — команда 0x01, третий байт — процент. */
    fun readLegacy(frame: LegacyFrame): List<Reading> {
        val p = frame.payload
        return when (frame.cmd) {
            0x01, 0x60 -> if (p.size >= 3) listOf(Reading(Metric.BATTERY, p[2].toInt() and 0xFF)) else emptyList()
            else -> emptyList()
        }
    }

    // ---------- Команды ----------

    fun jlSessionInit(): ByteArray = jlFrame(byteArrayOf(0x03, 0x02, 0x20, 0, 0, 0, 1))

    fun jlBattery(): ByteArray = jlFrame(byteArrayOf(0x02, 0x03, 0x10))

    /** Часовой пояс в четвертях часа: 02 02 00 <четверти> 01. */
    fun jlTimezone(offsetSeconds: Int): ByteArray {
        val quarters = (offsetSeconds / 900.0).toInt().coerceIn(-48, 56)
        return jlFrame(byteArrayOf(0x02, 0x02, 0x00, quarters.toByte(), 0x01))
    }

    /** Проверка привязки старого формата: команда 0x02 без данных. */
    fun legacyBindStatus(serial: Int): ByteArray = legacyFrame(0x02, ByteArray(0), serial)

    fun jlDeviceInfo(): ByteArray = jlFrame(byteArrayOf(0x02, 0x04, 0x10))

    fun jlFeatures(): ByteArray = jlFrame(byteArrayOf(0x02, 0x63, 0x10))

    fun jlTimeSync(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int): ByteArray =
        jlFrame(
            byteArrayOf(
                0x02, 0x01, 0x00,
                (year - 2000).toByte(), month.toByte(), day.toByte(),
                hour.toByte(), minute.toByte(), second.toByte()
            )
        )

    /** Тип измерения: 0x03 пульс, 0x09 кислород, 0x0D стресс, 0x0A HRV. */
    object Measure {
        const val HEART_RATE = 0x03
        const val SPO2 = 0x09
        const val STRESS = 0x0D
        const val HRV = 0x0A
    }

    fun jlRealtime(type: Int, on: Boolean): ByteArray =
        jlFrame(byteArrayOf(0x06, 0x09, 0x00, type.toByte(), 0x05, if (on) 0x01 else 0x00))

    fun legacyBattery(serial: Int): ByteArray = legacyFrame(0x01, ByteArray(0), serial)
}

/**
 * Разбор карты HID-отчётов (характеристика 2A4B).
 *
 * Карта — это последовательность «айтемов» дескриптора HID. Нам нужны поля
 * ввода: для каждого известно, на каком бите отчёта оно лежит, сколько бит
 * занимает и какой HID-код (usage) означает. Дальше нажатие декодируется
 * честно, по битам, а не «на глаз».
 */
object HidMap {

    data class Field(
        val reportId: Int,
        val page: Int,
        val usage: Int,
        val offset: Int,
        val size: Int,
        val variable: Boolean
    )

    data class Map(val fields: List<Field>, val usesReportIds: Boolean) {
        val reportIds: List<Int> get() = fields.map { it.reportId }.distinct().sorted()
    }

    fun parse(bytes: ByteArray): Map {
        var page = 0
        var reportId = 0
        var size = 0
        var count = 0
        var usesIds = false
        var usageMin = -1
        val usages = ArrayList<Int>()
        val cursor = HashMap<Int, Int>()
        val fields = ArrayList<Field>()
        val globals = ArrayList<IntArray>()
        var i = 0
        while (i < bytes.size) {
            val prefix = bytes[i].toInt() and 0xFF
            i += 1
            if (prefix == 0xFE) {
                if (i >= bytes.size) break
                val n = bytes[i].toInt() and 0xFF
                i += 1 + n
                continue
            }
            val n = if ((prefix and 0x03) == 3) 4 else prefix and 0x03
            val type = (prefix shr 2) and 0x03
            val tag = (prefix shr 4) and 0x0F
            if (i + n > bytes.size) break
            var raw = 0L
            for (k in 0 until n) raw = raw or ((bytes[i + k].toLong() and 0xFF) shl (8 * k))
            i += n
            val u = raw.toInt()
            when (type) {
                0 -> {
                    if (tag == 0x08) {
                        val variable = (u and 0x02) != 0
                        val slots = if (count > 0) count else 1
                        var off = cursor.getOrPut(reportId) { 0 }
                        for (slot in 0 until slots) {
                            val usage = when {
                                usages.isNotEmpty() && slot < usages.size -> usages[slot]
                                usages.isNotEmpty() -> usages.last()
                                usageMin >= 0 -> usageMin + slot
                                else -> 0
                            }
                            fields.add(Field(reportId, page, usage, off, size, variable))
                            off += size
                        }
                        cursor[reportId] = off
                    }
                    usages.clear()
                    usageMin = -1
                }
                1 -> when (tag) {
                    0x00 -> page = u
                    0x07 -> size = u
                    0x08 -> {
                        reportId = u
                        usesIds = true
                    }
                    0x09 -> count = u
                    0x0A -> globals.add(intArrayOf(page, reportId, size, count))
                    0x0B -> if (globals.isNotEmpty()) {
                        val saved = globals.removeAt(globals.size - 1)
                        page = saved[0]; reportId = saved[1]; size = saved[2]; count = saved[3]
                    }
                }
                2 -> when (tag) {
                    0x00 -> {
                        if (n == 4) {
                            page = ((raw shr 16) and 0xFFFF).toInt()
                            usages.add((raw and 0xFFFF).toInt())
                        } else {
                            usages.add(u)
                        }
                    }
                    0x01 -> usageMin = u
                }
            }
        }
        return Map(fields, usesIds)
    }

    /** Прочитать поле как целое (младшим битом вперёд — так устроены отчёты HID). */
    fun bits(data: ByteArray, offset: Int, size: Int): Int {
        var value = 0
        for (k in 0 until size) {
            val bit = offset + k
            val index = bit / 8
            if (index >= data.size) break
            if (((data[index].toInt() shr (bit % 8)) and 1) == 1) value = value or (1 shl k)
        }
        return value
    }

    /** Какие HID-коды сейчас «нажаты» в этом отчёте. */
    fun active(map: Map, reportId: Int, data: ByteArray): List<Pair<Int, Int>> {
        val out = ArrayList<Pair<Int, Int>>()
        for (field in map.fields) {
            if (field.reportId != reportId) continue
            if (field.size <= 0 || field.size > 16) continue
            val value = bits(data, field.offset, field.size)
            if (value == 0) continue
            if (field.variable) {
                out.add(field.page to field.usage)
            } else {
                out.add(field.page to value)
            }
        }
        return out
    }

    private val consumer = mapOf(
        0x30 to "питание", 0x40 to "меню", 0x41 to "выбор",
        0xB0 to "воспроизведение", 0xB1 to "пауза", 0xB3 to "вперёд",
        0xB4 to "назад", 0xB5 to "свайп вперёд", 0xB6 to "свайп назад",
        0xB7 to "стоп", 0xCD to "нажатие (плей/пауза)", 0xE2 to "без звука",
        0xE9 to "громче", 0xEA to "тише", 0x192 to "калькулятор",
        0x221 to "поиск", 0x223 to "домой", 0x224 to "назад (система)",
        0x225 to "вперёд (система)", 0x226 to "стоп (система)"
    )

    private val desktop = mapOf(
        0x30 to "движение X", 0x31 to "движение Y", 0x38 to "прокрутка",
        0x42 to "вверх", 0x43 to "вниз", 0x4F to "вправо", 0x50 to "влево"
    )

    private val keyboard = mapOf(
        0x4F to "вправо", 0x50 to "влево", 0x51 to "вниз", 0x52 to "вверх",
        0x28 to "Enter", 0x29 to "Esc", 0x2C to "пробел"
    )

    /** Человеческое название HID-кода; null, если код не опознан. */
    fun usageName(page: Int, usage: Int): String? = when (page) {
        0x0C -> consumer[usage]
        0x01 -> desktop[usage]
        0x07 -> keyboard[usage]
        0x09 -> "кнопка $usage"
        else -> null
    }

    /** Короткая подпись пары «страница/код» для журнала. */
    fun rawPair(page: Int, usage: Int): String =
        String.format("0x%02X:0x%02X", page, usage)
}
