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
 * Как это работает на живых очках (сверено с открытым приложением, которое
 * управляет теми же очками):
 *   - команда «снять фото» — это кадр 0x41 канала B: BC 41 03 00 CRC 02 01 01;
 *   - очки отвечают таким же кадром, где есть код ошибки и текущий режим.
 *     Ноль в коде ошибки = команда реально выполнена, и это единственное
 *     доказательство (эхо собственной записи доказательством не является);
 *   - сам кадр забирается миниатюрой: BC FD [01 номер часть], очки отдают
 *     JPEG частями и в приложении он склеивается целиком;
 *   - видео и звук остаются в памяти очков: полноразмерные файлы отдаёт только
 *     Wi-Fi очков (HTTP), по Bluetooth их не передают.
 *
 * Запись в канал A (6E400002) очки иногда просто возвращают эхом. Это значит,
 * что байты дошли до устройства, но ничего не доказывает про выполнение.
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

    /**
     * Поток 0x59. В вендорском SDK эта команда называется ACTION_GPT_UPLOAD (89 = 0x59)
     * и идёт в паре с запросом ИИ-помощника: это звук с микрофона очков, который
     * приложение отправляет в облако на распознавание. Видео в этом потоке нет —
     * скорость около 1.5 КБ/с, кадру её не хватит.
     */
    fun isStreamFrame(value: ByteArray): Boolean =
        isBigFrame(value) && (value[1].toInt() and 0xFF) == 0x59

    /** Что это за поток, по-человечески. */
    fun streamName(value: ByteArray): String =
        if (isStreamFrame(value)) "звук с микрофона для ИИ-помощника" else "служебный поток"

    // ---------- Управление очками (кадр 0x41 канала B) ----------
    //
    // Восстановлено из SDK и сверено с работающим открытым приложением
    // (FerSaiyan/Alternative-HeyCyan-App-and-SDK, MainActivity.kt: btnCamera / controlVideoRecording).
    // Полезная нагрузка всегда [0x02, 0x01, что_делать]:
    //   01 — снять фото (одиночный кадр)
    //   02 — начать запись видео, 03 — остановить
    //   04 — включить Wi-Fi и режим передачи файлов
    //   05 — обновление прошивки
    //   06 — фото для ИИ + качество в двух байтах (06 q q)
    //   07 — ИИ-собеседник, 0B — остановить его
    //   08 — начать запись звука, 0C — остановить
    //   0F — Wi-Fi «без питания» (SDK так отвечает на неудачный сценарий)
    //
    // Ответ очков: BC 41 .. [02, 01, что_просили, код_ошибки, что_сейчас].
    // Код ошибки 0 = принято и работает. Именно этот байт — доказательство,
    // а не факт того, что наша запись ушла в GATT.

    // Полный перечень из вендорского enum QCOperatorDeviceMode (0x00–0x13).
    // Всё, что ≥ 0x14, прошивка не понимает.
    object Work {
        const val PHOTO = 0x01
        const val VIDEO_START = 0x02
        const val VIDEO_STOP = 0x03
        const val TRANSFER = 0x04
        const val OTA = 0x05
        const val PHOTO_AI = 0x06
        const val ASSISTANT = 0x07
        const val AUDIO_START = 0x08
        /** TransferStop — единственный штатный выход из режима передачи файлов. */
        const val TRANSFER_STOP = 0x09
        const val FACTORY_RESET = 0x0A
        const val STOP_AI = 0x0B
        const val AUDIO_STOP = 0x0C
        const val FIND_DEVICE = 0x0D
        const val RESTART = 0x0E
        const val NO_POWER_P2P = 0x0F
        const val SPEAK_START = 0x10
        const val SPEAK_STOP = 0x11
        const val TRANSLATE_START = 0x12
        const val TRANSLATE_STOP = 0x13
    }

    /** «Сделай то-то» для очков. */
    fun control(work: Int, extra: ByteArray = ByteArray(0)): ByteArray =
        byteArrayOf(0x02, 0x01, work.toByte()) + extra

    /**
     * Качество кадра для ИИ-съёмки. Официальный сэмпл шлёт [02 01 06 q q 02],
     * то есть значение дважды и завершающий байт 02.
     */
    fun photoQuality(q: Int): ByteArray =
        byteArrayOf(0x02, 0x01, Work.PHOTO_AI.toByte(), q.toByte(), q.toByte(), 0x02)

    /** Ответ очков на команду 0x41: что просили, код ошибки и что сейчас происходит. */
    data class GlassState(val work: Int, val error: Int, val running: Int)

    fun glassState(value: ByteArray): GlassState? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x41) return null
        if (value.size < 11) return null
        // Ответ на команду: [02, 01, что_просили, код, что_сейчас].
        // Ответ на запрос настроек начинается с [01, ...] — это не состояние команды.
        if ((value[6].toInt() and 0xFF) != 0x02) return null
        if ((value[7].toInt() and 0xFF) != 0x01) return null
        return GlassState(
            work = value[8].toInt() and 0xFF,
            error = value[9].toInt() and 0xFF,
            running = value[10].toInt() and 0xFF
        )
    }

    /** Сколько фото, видео и записей лежит в памяти очков (ответ на 0x41 02 04). */
    data class MediaCounts(val photos: Int, val videos: Int, val records: Int)

    fun mediaCounts(value: ByteArray): MediaCounts? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x41) return null
        if (value.size < 14) return null
        if ((value[7].toInt() and 0xFF) != 0x04) return null
        fun at(i: Int) = (value[i].toInt() and 0xFF) or ((value[i + 1].toInt() and 0xFF) shl 8)
        return MediaCounts(at(8), at(10), at(12))
    }

    /**
     * Запрос миниатюры последнего снимка: BC FD [01, номер, номер>>8].
     * Очки отвечают серией таких же кадров, в каждом — сколько всего частей,
     * номер этой части и кусок JPEG. Полноразмерный файл по Bluetooth не ходит,
     * а миниатюра приходит целиком.
     */
    fun thumbnailRequest(index: Int): ByteArray =
        bigFrame(0xFD, byteArrayOf(0x01, (index and 0xFF).toByte(), ((index shr 8) and 0xFF).toByte()))

    // ---------- Запросы настроек (кадр 0x41 с началом [01, тип]) ----------
    //
    // Ответ: [01, тип, ...]. Тип 2 — видео (угол, длительность в секундах),
    // тип 3 — адрес очков в их Wi-Fi, тип 4 — количество файлов,
    // тип 6 — длительность записи звука.

    fun query(dataType: Int): ByteArray = byteArrayOf(0x01, dataType.toByte())

    /** Установить предельную длительность видео: [02, 02, 00, младший, старший]. */
    fun setVideoDuration(seconds: Int): ByteArray = byteArrayOf(
        0x02, 0x02, 0x00, (seconds and 0xFF).toByte(), ((seconds shr 8) and 0xFF).toByte()
    )

    /** Установить предельную длительность записи звука: [02, 06, 00, младший, старший]. */
    fun setAudioDuration(seconds: Int): ByteArray = byteArrayOf(
        0x02, 0x06, 0x00, (seconds and 0xFF).toByte(), ((seconds shr 8) and 0xFF).toByte()
    )

    /** Длительность видео в секундах из ответа на запрос [01, 02]. */
    fun videoDuration(value: ByteArray): Int? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x41) return null
        if (value.size < 11) return null
        if ((value[6].toInt() and 0xFF) != 0x01) return null
        if ((value[7].toInt() and 0xFF) != 0x02) return null
        return (value[9].toInt() and 0xFF) or ((value[10].toInt() and 0xFF) shl 8)
    }

    /** Адрес очков в их Wi-Fi из ответа на запрос [01, 03]. */
    fun deviceIp(value: ByteArray): String? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x41) return null
        if (value.size < 14) return null
        if ((value[6].toInt() and 0xFF) != 0x01) return null
        if ((value[7].toInt() and 0xFF) != 0x03) return null
        val a = value[10].toInt() and 0xFF
        val b = value[11].toInt() and 0xFF
        val c = value[12].toInt() and 0xFF
        val d = value[13].toInt() and 0xFF
        if (a == 0 && b == 0 && c == 0 && d == 0) return null
        return "$a.$b.$c.$d"
    }

    /** Имя и пароль точки доступа очков из ответа на команду режима передачи. */
    data class WifiCreds(val ssid: String, val password: String)

    fun transferCredentials(value: ByteArray): WifiCreds? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x41) return null
        if (value.size < 12) return null
        if ((value[6].toInt() and 0xFF) != 0x02) return null
        if ((value[8].toInt() and 0xFF) != Work.TRANSFER) return null
        // После кода ошибки и текущего режима идут: длина, имя сети, длина, пароль.
        var i = 11
        if (i >= value.size) return null
        val nameLen = value[i].toInt() and 0xFF
        if (nameLen <= 0 || nameLen > 32 || i + 1 + nameLen > value.size) return null
        val ssid = String(value, i + 1, nameLen, Charsets.UTF_8)
        i += 1 + nameLen
        if (i >= value.size) return WifiCreds(ssid, "")
        val passLen = value[i].toInt() and 0xFF
        if (passLen <= 0 || passLen > 63 || i + 1 + passLen > value.size) return WifiCreds(ssid, "")
        val pass = String(value, i + 1, passLen, Charsets.UTF_8)
        if (ssid.isBlank()) return null
        return WifiCreds(ssid, pass)
    }

    /**
     * Кадр «я ещё здесь» для текущего режима: BC 45 [режим, 01].
     * Без него очки считают, что хозяин отвязался, и сами завершают запись.
     * Для режима передачи файлов это же держит Wi-Fi открытым.
     */
    fun heartbeat(work: Int): ByteArray = bigFrame(0x45, byteArrayOf(work.toByte(), 0x01))

    /** Голосовое пробуждение помощника (тип 0x44): [02, 01] — микрофон включён. */
    fun aiVoiceWakePayload(on: Boolean): ByteArray =
        byteArrayOf(0x02, if (on) 0x01 else 0x00)

    fun aiVoiceWake(on: Boolean): ByteArray = bigFrame(0x44, aiVoiceWakePayload(on))

    data class ThumbChunk(val total: Int, val index: Int, val data: ByteArray)

    fun thumbChunk(value: ByteArray): ThumbChunk? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0xFD) return null
        if (value.size < 11) return null
        val total = (value[7].toInt() and 0xFF) or ((value[8].toInt() and 0xFF) shl 8)
        val index = (value[9].toInt() and 0xFF) or ((value[10].toInt() and 0xFF) shl 8)
        val data = if (value.size > 11) value.copyOfRange(11, value.size) else ByteArray(0)
        return ThumbChunk(total, index, data)
    }

    /**
     * Громкость очков (команда 0x51). Раскладка из официального SDK
     * (`LargeDataHandler.setVolumeControl`): {2,1,min,max,curr, 2,min,max,curr,
     * 3,min,max,curr, тип}. Отдельной «громкости сигнала съёмки» в SDK нет —
     * поэтому 0 % может убрать писк, только если прошивка играет его через
     * системную громкость. Это проверяем опытом, а не обещаем.
     */
    fun volumePayload(music: Int, call: Int, system: Int, type: Int = 1): ByteArray = byteArrayOf(
        0x02, 0x01, 0x00, 0x64, music.toByte(),
        0x02, 0x00, 0x64, call.toByte(),
        0x03, 0x00, 0x64, system.toByte(),
        type.toByte()
    )

    fun volumeSet(music: Int, call: Int, system: Int, type: Int = 1): ByteArray =
        bigFrame(0x51, volumePayload(music, call, system, type))

    fun volumeGet(): ByteArray = bigFrame(0x51, byteArrayOf(0x01))

    /** Человеческое имя рабочего режима очков. */
    fun workName(code: Int): String = when (code) {
        0x00 -> "ожидание"
        0x01 -> "фото"
        0x02 -> "видеозапись идёт"
        0x03 -> "видеозапись остановлена"
        0x04 -> "передача файлов по Wi-Fi"
        0x05 -> "обновление прошивки"
        0x06 -> "фото (ИИ)"
        0x07 -> "распознавание речи"
        0x08 -> "запись звука"
        0x09 -> "выход из режима передачи"
        0x0A -> "сброс настроек"
        0x0B -> "распознавание речи остановлено"
        0x0C -> "запись звука остановлена"
        0x0D -> "поиск очков"
        0x0E -> "перезапуск"
        0x0F -> "сброс Wi-Fi (без питания)"
        0x10 -> "голос: начало"
        0x11 -> "голос: стоп"
        0x12 -> "перевод: старт"
        0x13 -> "перевод: стоп"
        0xFF -> "нет данных (очки не сообщили режим)"
        else -> "неизвестный режим $code"

    }

    /** Режимы, в которых камера занята и команды съёмки не выполняются. */
    fun cameraBusy(work: Int): Boolean = work == Work.TRANSFER || work == Work.OTA

    // ---------- События очков (тип 0x73) ----------

    data class DeviceEvent(val type: Int, val value: Int)

    fun deviceEvent(value: ByteArray): DeviceEvent? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x73) return null
        if (value.size < 8) return null
        return DeviceEvent(
            type = value[6].toInt() and 0xFF,
            value = value[7].toInt() and 0xFF
        )
    }

    /**
     * Адрес очков в их Wi-Fi из события 0x08 (Bytes 7..10).
     * Именно так SDK сообщает адрес P2P-интерфейса — он нужен и для выгрузки
     * файлов, и для попытки живого видео по RTSP.
     */
    fun p2pIp(value: ByteArray): String? {
        if (!isBigFrame(value)) return null
        if ((value[1].toInt() and 0xFF) != 0x73) return null
        if (value.size < 11) return null
        if ((value[6].toInt() and 0xFF) != 0x08) return null
        val a = value[7].toInt() and 0xFF
        val b = value[8].toInt() and 0xFF
        val c = value[9].toInt() and 0xFF
        val d = value[10].toInt() and 0xFF
        if (a == 0 && b == 0 && c == 0 && d == 0) return null
        return "$a.$b.$c.$d"
    }

    /** 73 09 FF — очки не смогли поднять Wi-Fi; SDK в ответ шлёт «сброс Wi-Fi». */
    fun wifiFailed(value: ByteArray): Boolean {
        val e = deviceEvent(value) ?: return false
        return e.type == 0x09 && e.value == 0xFF
    }

    fun eventName(type: Int): String = when (type) {
        0x01 -> "состояние устройства"
        0x02 -> "результат ИИ-снимка"
        0x03 -> "микрофон включён"
        0x04 -> "ход обновления прошивки"
        0x07 -> "обновление прошивки завершено"
        0x08 -> "адрес очков в Wi-Fi"
        0x09 -> "Wi-Fi очков"
        0x0B -> "отсчёт состояния"
        0x0F -> "перевод: пауза"
        0x10 -> "перевод: продолжение"
        0x12 -> "состояние кнопки/датчика очков"
        else -> "событие 0x" + String.format("%02X", type)
    }

    /**
     * Склейка кадров канала B: очки режут длинный кадр на части по размеру MTU,
     * поэтому парсить надо поток, а не отдельные уведомления.
     */
    class BigFramer {
        private val buf = java.io.ByteArrayOutputStream()

        fun push(chunk: ByteArray): List<ByteArray> {
            buf.write(chunk)
            val out = ArrayList<ByteArray>()
            while (true) {
                var data = buf.toByteArray()
                if (data.isEmpty()) break
                var start = 0
                while (start < data.size && (data[start].toInt() and 0xFF) != 0xBC) start += 1
                if (start > 0) {
                    buf.reset()
                    buf.write(data, start, data.size - start)
                    continue
                }
                if (data.size < 6) break
                val len = (data[2].toInt() and 0xFF) or ((data[3].toInt() and 0xFF) shl 8)
                if (len < 0 || len > 4096) {
                    buf.reset()
                    buf.write(data, 1, data.size - 1)
                    continue
                }
                if (data.size < 6 + len) break
                out.add(data.copyOfRange(0, 6 + len))
                buf.reset()
                buf.write(data, 6 + len, data.size - (6 + len))
            }
            return out
        }

        fun reset() {
            buf.reset()
        }
    }

    data class Battery(val level: Int, val charging: Boolean)

    fun batteryInfo(value: ByteArray): Battery? {
        if (isBigFrame(value) && (value[1].toInt() and 0xFF) == 0x42 && value.size > 7) {
            val level = value[6].toInt() and 0xFF
            if (level in 1..100) return Battery(level, (value[7].toInt() and 0xFF) == 1)
        }
        if (value.size == FRAME_LEN && (value[0].toInt() and 0x7F) == 0x03) {
            val level = value[1].toInt() and 0xFF
            if (level in 1..100) return Battery(level, (value[2].toInt() and 0xFF) == 1)
        }
        return null
    }

    /** Названия режимов работы очков (из GlassModelControlResponse SDK). */
    fun modeName(code: Int): String = when (code) {
        1 -> "фото"
        2 -> "видео"
        4 -> "запись голоса"
        5 -> "обновление"
        6 -> "запись разговора"
        7, 8 -> "ожидание"
        11, 12 -> "передача файлов"
        18 -> "ИИ-режим"
        else -> "режим $code"
    }

    /** Человеческое описание ответа — то, что показываем пользователю. */
    fun friendly(value: ByteArray): String? {
        if (isBigFrame(value)) {
            val type = value[1].toInt() and 0xFF
            val payload = if (value.size > 6) value.copyOfRange(6, value.size) else ByteArray(0)
            return when (type) {
                0x42 -> batteryInfo(value)?.let {
                    "заряд ${it.level}%" + if (it.charging) ", заряжается" else ""
                }
                0xFD -> thumbChunk(value)?.let { ch ->
                    if (ch.total <= 0) "миниатюр на очках пока нет"
                    else "миниатюра: часть ${ch.index + 1} из ${ch.total} (${ch.data.size} байт)"
                }
                0x41 -> glassState(value)?.let { st ->
                    if (st.error == 0) {
                        "очки подтвердили: ${workName(st.work)}" +
                            if (st.running != st.work) " · сейчас: ${workName(st.running)}" else ""
                    } else {
                        "очки отказали (код ${st.error}) · сейчас: ${workName(st.running)}"
                    }
                } ?: mediaCounts(value)?.let {
                    "на очках: ${it.photos} фото, ${it.videos} видео, ${it.records} записей"
                } ?: "очки ответили: " + hex(payload.take(8).toByteArray())
                0x43 -> "сведения об устройстве получены"
                0x3E -> "режим подтверждён"
                else -> describeBig(value)
            }
        }
        if (value.size == FRAME_LEN) {
            val key = value[0].toInt() and 0x7F
            return when (key) {
                0x3E -> if (value.size > 3) {
                    val mode = value[2].toInt() and 0xFF
                    "очки перешли в режим «${modeName(mode)}»" +
                        if (value[3].toInt() != 0) " (статус ${value[3].toInt() and 0xFF})" else ""
                } else "режим подтверждён"
                0x02 -> "камера: команда принята"
                0x03 -> batteryInfo(value)?.let { "заряд ${it.level}%" }
                0x3C -> "поддержка функций получена"
                else -> describeCmd(value)
            }
        }
        return null
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
        // Счётчики файлов. Именно BC 41 02 04, а не миниатюры: 0xFD — это картинки.
        Probe(CH_SERIAL, 0x41, byteArrayOf(0x02, 0x04), "файлы в памяти (0x41)")
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
