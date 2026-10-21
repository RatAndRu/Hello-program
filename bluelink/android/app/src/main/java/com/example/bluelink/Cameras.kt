package com.example.bluelink

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors

/** Работа с Wi-Fi: список сетей и подключение к точке доступа очков. */
class WifiHelper(private val ctx: Context) {

    private val cm: ConnectivityManager? =
        ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
    private var callback: ConnectivityManager.NetworkCallback? = null

    @SuppressLint("MissingPermission")
    fun scanNetworks(): List<Pair<String, Int>> {
        return try {
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                ?: return emptyList()
            @Suppress("DEPRECATION")
            wm.startScan()
            @Suppress("DEPRECATION")
            wm.scanResults
                .map { it.SSID to it.level }
                .filter { it.first.isNotBlank() }
                .distinctBy { it.first }
                .sortedByDescending { it.second }
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun openWifiSettings() {
        try {
            ctx.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (ignored: Exception) {
        }
    }

    /** Подключает телефон к точке доступа устройства. Соединение живёт, пока не вызовут release(). */
    fun requestNetwork(ssid: String, password: String, timeoutMs: Long, done: (Network?, String?) -> Unit) {
        if (Build.VERSION.SDK_INT < 29) {
            done(null, "Автоподключение к Wi-Fi доступно с Android 10. Подключитесь к сети «$ssid» вручную.")
            return
        }
        val manager = cm ?: run {
            done(null, "Wi-Fi недоступен")
            return
        }
        release()
        val specifier = try {
            WifiNetworkSpecifier.Builder().setSsid(ssid).apply {
                if (password.isNotBlank()) setWpa2Passphrase(password)
            }.build()
        } catch (e: Exception) {
            done(null, "Некорректные данные Wi-Fi: ${e.message}")
            return
        }
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(specifier)
            .build()
        var answered = false
        val handler = Handler(Looper.getMainLooper())
        val timeout = Runnable {
            if (!answered) {
                answered = true
                done(null, "Сеть «$ssid» не ответила. Проверьте, что устройство включено и раздаёт Wi-Fi.")
            }
        }
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                if (answered) return
                answered = true
                handler.removeCallbacks(timeout)
                done(network, null)
            }

            override fun onUnavailable() {
                if (answered) return
                answered = true
                handler.removeCallbacks(timeout)
                done(null, "Не удалось подключиться к Wi-Fi «$ssid». Можно подключиться вручную в настройках.")
            }
        }
        callback = cb
        try {
            manager.requestNetwork(request, cb, timeoutMs.toInt())
            handler.postDelayed(timeout, timeoutMs + 1500)
        } catch (e: SecurityException) {
            done(null, "Нет разрешения на подключение к Wi-Fi. Разрешите геолокацию или подключитесь вручную.")
        } catch (e: Exception) {
            done(null, "Wi-Fi: ${e.message}")
        }
    }

    fun release() {
        val cb = callback ?: return
        callback = null
        try {
            cm?.unregisterNetworkCallback(cb)
        } catch (ignored: Exception) {
        }
    }
}

/**
 * Движок съёмки: превращает профиль устройства в конкретные действия
 * (BLE-команда, Wi-Fi запрос или встроенная демонстрация) и отдаёт готовый JPEG.
 */
class GlassesCamera(
    private val ctx: Context,
    private val ble: BleCentral,
    private val wifi: WifiHelper
) {
    interface Listener {
        fun onCaptureStatus(status: String, detail: String = "")
        fun onPhoto(file: File, bytes: ByteArray, source: String)
        fun onCameraLog(line: String)
    }

    var listener: Listener? = null

    private val io = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val store = PhotoStore(ctx)

    private var capturing = false
    private var currentProfile: DeviceProfile? = null

    private var collect: ByteArrayOutputStream? = null
    private var collectChar: UUID? = null
    private var framing = "jpeg"
    private var expectedSize = -1
    private var timeoutRunnable: Runnable? = null
    private var lastProgressAt = 0L
    private var tail = ByteArray(0)

    fun isCapturing(): Boolean = capturing

    fun capture(profile: DeviceProfile) {
        val spec = profile.camera
        if (spec == null) {
            listener?.onCaptureStatus("У профиля нет камеры", "Выберите другой профиль или добавьте камеру в настройках профиля.")
            return
        }
        if (capturing) {
            listener?.onCaptureStatus("Уже снимаю…", "Подождите, идёт передача снимка.")
            return
        }
        capturing = true
        currentProfile = profile
        when (spec.mode) {
            "demo" -> demoCapture(spec)
            "http" -> httpCapture(profile, spec)
            "ble" -> bleCapture(profile, spec)
            else -> fail("Неизвестный режим камеры: ${spec.mode}")
        }
    }

    /**
     * Слушает произвольный канал и ждёт JPEG: так ловим кадр у устройств,
     * которые не описаны профилем (например, очки HeyCyan шлют данные на DE5BF729).
     */
    fun listenForJpeg(service: UUID, char: UUID, seconds: Int = 20) {
        if (capturing) {
            listener?.onCaptureStatus("Уже снимаю…", "Подождите, идёт передача снимка.")
            return
        }
        capturing = true
        currentProfile = null
        framing = "jpeg"
        expectedSize = -1
        lastProgressAt = 0
        tail = ByteArray(0)
        collect = ByteArrayOutputStream()
        collectChar = char
        listener?.onCaptureStatus("Жду кадр от очков…", "Слушаю ${GattNames.uuidLabel(char)}")
        listener?.onCameraLog("Слушаю поток с ${GattNames.uuidLabel(char)} — ищу JPEG")
        timeoutRunnable = Runnable {
            if (capturing) {
                val got = collect?.size() ?: 0
                if (got > 500) {
                    finishBle("По таймауту, но данные получены")
                } else {
                    fail("Кадр не пришёл", "За ${seconds} с получено $got байт. Похоже, фото отдаётся по Wi-Fi.")
                }
            }
        }.also { handler.postDelayed(it, seconds * 1000L) }
        ble.subscribe(service, char, true)
    }

    fun cancel() {
        finishInternal(null, "Съёмка отменена")
    }

    private fun fail(message: String, detail: String = "") {
        if (!capturing) return
        capturing = false
        cleanupBle()
        wifi.release()
        listener?.onCaptureStatus(message, detail)
        listener?.onCameraLog("Камера: $message")
    }

    // ---------- Демонстрация ----------

    private fun demoCapture(spec: CameraSpec) {
        listener?.onCaptureStatus("Демо-очки: снимаю…", "Это встроенная имитация — железо не нужно.")
        io.execute {
            Thread.sleep(900)
            val bytes = try {
                ctx.assets.open(spec.demoAsset).use { it.readBytes() }
            } catch (e: Exception) {
                null
            }
            if (bytes == null || bytes.size < 100) {
                fail("Демо-снимок не найден", "Файл ${spec.demoAsset} отсутствует в приложении.")
                return@execute
            }
            deliver(bytes, "demo", "Демо: умные очки")
        }
    }

    // ---------- Wi-Fi / HTTP ----------

    private fun httpCapture(profile: DeviceProfile, spec: CameraSpec) {
        listener?.onCaptureStatus("Готовлю камеру…", profile.name)
        val ssid = spec.wifiSsid.trim()
        if (ssid.isNotEmpty()) {
            listener?.onCaptureStatus("Подключаюсь к Wi-Fi очков…", "Сеть «$ssid»")
            wifi.requestNetwork(ssid, spec.wifiPassword, 15_000) { network, error ->
                if (network == null) {
                    fail("Не удалось подключиться к Wi-Fi", error ?: "")
                } else {
                    listener?.onCameraLog("Wi-Fi: подключено к «$ssid»")
                    afterWifi(profile, spec, network)
                }
            }
        } else {
            afterWifi(profile, spec, null)
        }
    }

    private fun afterWifi(profile: DeviceProfile, spec: CameraSpec, network: Network?) {
        if (spec.triggerChar != null && ble.connectedDevice != null) {
            listener?.onCaptureStatus("Отправляю команду съёмки…", "BLE → ${GattNames.uuidLabel(spec.triggerChar)}")
            ble.write(spec.service, spec.triggerChar, spec.trigger)
        }
        listener?.onCaptureStatus("Жду снимок…", spec.httpUrl)
        io.execute {
            Thread.sleep(spec.waitMs.toLong())
            listener?.onCaptureStatus("Скачиваю снимок…", spec.httpUrl)
            val bytes = httpGet(spec.httpUrl, network)
            if (bytes == null || bytes.size < 500) {
                fail("Камера не отдала снимок", "Проверьте адрес ${spec.httpUrl} и что телефон в Wi-Fi сети устройства.")
                return@execute
            }
            deliver(bytes, "wifi", profile.name)
        }
    }

    private fun httpGet(url: String, network: Network?): ByteArray? {
        var connection: HttpURLConnection? = null
        return try {
            connection = if (network != null) {
                network.openConnection(URL(url)) as HttpURLConnection
            } else {
                URL(url).openConnection() as HttpURLConnection
            }
            connection.connectTimeout = 8000
            connection.readTimeout = 15000
            connection.requestMethod = "GET"
            connection.instanceFollowRedirects = true
            if (connection.responseCode !in 200..299) {
                listener?.onCameraLog("HTTP ${connection.responseCode} от $url")
                return null
            }
            connection.inputStream.use { it.readBytes() }
        } catch (e: Exception) {
            listener?.onCameraLog("HTTP ошибка: ${e.message}")
            null
        } finally {
            try {
                connection?.disconnect()
            } catch (ignored: Exception) {
            }
        }
    }

    // ---------- Камера по BLE-потоку ----------

    private fun bleCapture(profile: DeviceProfile, spec: CameraSpec) {
        if (ble.connectedDevice == null) {
            fail("Нет BLE-соединения", "Сначала подключитесь к устройству во вкладке «Поиск».")
            return
        }
        val dataChar = spec.dataChar
        if (dataChar == null) {
            fail("В профиле не указана характеристика данных", "Камере по BLE нужна характеристика, в которую устройство шлёт JPEG.")
            return
        }
        framing = spec.framing
        expectedSize = -1
        lastProgressAt = 0
        tail = ByteArray(0)
        collect = ByteArrayOutputStream()
        collectChar = dataChar
        listener?.onCaptureStatus("Подписываюсь на поток снимка…", GattNames.uuidLabel(dataChar))
        val ok = ble.subscribe(spec.service, dataChar, true)
        listener?.onCameraLog(if (ok) "Подписка на ${GattNames.uuidLabel(dataChar)} включена" else "Подписка не удалась")
        if (spec.triggerChar != null) {
            listener?.onCaptureStatus("Отправляю команду съёмки…", bytesToHex(spec.trigger))
            // Небольшая пауза: подписка на уведомления должна успеть примениться до команды.
            handler.postDelayed({
                if (capturing) ble.write(spec.service, spec.triggerChar, spec.trigger)
            }, 700)
        }
        timeoutRunnable = Runnable {
            if (capturing) {
                val got = collect?.size() ?: 0
                if (got > 500) {
                    finishBle("По таймауту, но данные получены")
                } else {
                    fail("Устройство не прислало снимок", "Получено $got байт. Проверьте UUID характеристик в профиле.")
                }
            }
        }.also { handler.postDelayed(it, 25_000) }
    }

    /** Сюда приходят все уведомления BLE; снимок собирается из них. */
    fun feed(service: UUID, char: UUID, value: ByteArray) {
        if (!capturing || collect == null) return
        val target = collectChar ?: return
        if (char != target) return
        val buffer = collect ?: return
        buffer.write(value)
        val size = buffer.size()

        when (framing) {
            "sizeHeader" -> {
                if (expectedSize < 0 && size >= 4) {
                    val head = buffer.toByteArray()
                    expectedSize = (head[0].toInt() and 0xFF) or
                        ((head[1].toInt() and 0xFF) shl 8) or
                        ((head[2].toInt() and 0xFF) shl 16) or
                        ((head[3].toInt() and 0xFF) shl 24)
                    listener?.onCameraLog("Заголовок кадра: $expectedSize байт")
                }
                if (expectedSize > 0 && size >= 4 + expectedSize) {
                    finishBle("Пакет получен")
                    return
                }
            }
            else -> {
                // Хвостовое окно вместо копирования всего буфера на каждом пакете.
                tail = if (tail.isEmpty()) value.copyOf() else tail + value
                if (tail.size > 64) tail = tail.copyOfRange(tail.size - 64, tail.size)
                if (size > 4 && endsWithJpegMarker(tail)) {
                    finishBle("JPEG получен")
                    return
                }
            }
        }

        val now = System.currentTimeMillis()
        if (now - lastProgressAt > 700) {
            lastProgressAt = now
            listener?.onCaptureStatus("Получаю снимок…", "$size байт")
        }
    }

    private fun endsWithJpegMarker(window: ByteArray): Boolean {
        if (window.size < 2) return false
        val from = (window.size - 12).coerceAtLeast(0)
        for (i in window.size - 2 downTo from) {
            if ((window[i].toInt() and 0xFF) == 0xFF && (window[i + 1].toInt() and 0xFF) == 0xD9) return true
        }
        return false
    }

    private fun finishBle(reason: String) {
        val data = collect?.toByteArray() ?: return
        val jpeg = extractJpeg(data) ?: data
        if (jpeg.size < 200) {
            fail("Снимок слишком маленький", "Получено ${jpeg.size} байт — вероятно, это не JPEG.")
            return
        }
        listener?.onCameraLog("Снимок получен: ${jpeg.size} байт ($reason)")
        deliver(jpeg, "ble", currentProfile?.name ?: "BLE-устройство")
    }

    private fun extractJpeg(data: ByteArray): ByteArray? {
        var start = -1
        for (i in 0 until data.size - 1) {
            if ((data[i].toInt() and 0xFF) == 0xFF && (data[i + 1].toInt() and 0xFF) == 0xD8) {
                start = i
                break
            }
        }
        if (start < 0) return null
        var end = data.size
        var i = data.size - 2
        while (i > start) {
            if ((data[i].toInt() and 0xFF) == 0xFF && (data[i + 1].toInt() and 0xFF) == 0xD9) {
                end = i + 2
                break
            }
            i -= 1
        }
        return data.copyOfRange(start, end)
    }

    private fun cleanupBle() {
        timeoutRunnable?.let { handler.removeCallbacks(it) }
        timeoutRunnable = null
        val spec = currentProfile?.camera
        val target = collectChar
        val wasCollecting = collect != null
        collect = null
        collectChar = null
        expectedSize = -1
        tail = ByteArray(0)
        if (wasCollecting && spec != null && target != null) {
            try {
                ble.subscribe(spec.service, target, false)
            } catch (ignored: Exception) {
            }
        }
    }

    private fun finishInternal(bytes: ByteArray?, message: String) {
        if (capturing) {
            capturing = false
            cleanupBle()
            wifi.release()
            if (bytes == null) listener?.onCaptureStatus(message)
        }
    }

    private fun deliver(bytes: ByteArray, source: String, deviceName: String) {
        val file = store.save(bytes, source)
        capturing = false
        cleanupBle()
        wifi.release()
        if (file == null) {
            listener?.onCaptureStatus("Не удалось сохранить снимок")
            return
        }
        listener?.onCaptureStatus("Готово", "${bytes.size / 1024} КБ · $deviceName")
        listener?.onPhoto(file, bytes, source)
        listener?.onCameraLog("Сохранено: ${file.name} (${bytes.size / 1024} КБ)")
    }
}

/** Снимки: файлы в приватной папке приложения + экспорт в системную галерею. */
class PhotoStore(private val ctx: Context) {

    val dir: File get() = File(ctx.filesDir, "photos").apply { mkdirs() }

    fun save(bytes: ByteArray, source: String): File? {
        return try {
            val stamp = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US)
                .format(java.util.Date())
            val safeSource = source.replace(Regex("[^a-z0-9]"), "")
            var file = File(dir, "bl_${stamp}_$safeSource.jpg")
            var n = 1
            while (file.exists()) {
                file = File(dir, "bl_${stamp}_${safeSource}_$n.jpg")
                n += 1
            }
            file.writeBytes(bytes)
            file
        } catch (e: Exception) {
            null
        }
    }

    fun list(): List<File> =
        dir.listFiles { f -> f.isFile && f.name.endsWith(".jpg") }
            ?.sortedByDescending { it.lastModified() }
            ?: emptyList()

    fun delete(file: File): Boolean = try {
        file.delete()
    } catch (e: Exception) {
        false
    }

    fun sourceOf(file: File): String = when {
        file.name.contains("_demo") -> "демо-очки"
        file.name.contains("_wifi") -> "Wi-Fi камера"
        file.name.contains("_ble") -> "BLE-камера"
        else -> "устройство"
    }

    /** Копия в общую галерею (Pictures/BlueLink) — чтобы снимок был виден и вне приложения. */
    fun exportToGallery(file: File): Boolean {
        return try {
            val values = android.content.ContentValues()
            values.put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, file.name)
            values.put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            if (Build.VERSION.SDK_INT >= 29) {
                values.put(
                    android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                    "Pictures/BlueLink"
                )
            }
            val uri = ctx.contentResolver.insert(
                android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values
            ) ?: return false
            ctx.contentResolver.openOutputStream(uri)?.use { out ->
                file.inputStream().use { input -> input.copyTo(out) }
            } ?: return false
            true
        } catch (e: Exception) {
            false
        }
    }
}
