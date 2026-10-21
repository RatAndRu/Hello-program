package com.example.bluelink

import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiNetworkSpecifier
import android.net.wifi.p2p.WifiP2pConfig
import android.net.wifi.p2p.WifiP2pInfo
import android.net.wifi.p2p.WifiP2pManager
import android.net.wifi.WpsInfo
import android.os.Build
import android.os.Looper
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Забирает медиа с очков по их Wi-Fi.
 *
 * Почему отдельный канал: по Bluetooth очки отдают только миниатюру снимка.
 * Полноразмерные фото, видео и звук лежат в их памяти и отдаются по HTTP:
 *
 *   GET http://<очки>/files/media.config   — список файлов, по одному в строке
 *   GET http://<очки>/files/<имя>          — сам файл
 *
 * Сеть очков — их собственная точка доступа. Логин и пароль очки присылают
 * в ответ на команду «режим передачи файлов» (BC 41 … 02 01 04), а адрес —
 * шлюз, который выдаёт эта точка доступа (либо отдельный ответ с dataType 3).
 *
 * Особенности, найденные на живых очках (иначе ничего не скачивается):
 *   - сервер требует заголовок User-Agent: без него отвечает 400;
 *   - соединение не переиспользуется: каждый запрос — новое, Connection: close;
 *   - запросы нужно отправлять именно через сеть очков, иначе телефон уйдёт
 *     в мобильный интернет и ничего не найдёт.
 */
class GlassesMedia(private val ctx: Context, private val wifi: WifiHelper) {

    interface Listener {
        fun onStatus(text: String)
        fun onLog(line: String)
        fun onFiles(total: Int, names: List<String>)
        fun onProgress(index: Int, total: Int, name: String)
        fun onSaved(file: File, isImage: Boolean)
        fun onFinished(ok: Boolean, message: String)
    }

    private val io = Executors.newSingleThreadExecutor()
    private val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    @Volatile
    private var cancelled = false

    @Volatile
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    fun cancel() {
        cancelled = true
        releaseNetwork()
    }

    /**
     * Подключиться к точке доступа очков и скачать всё, что есть в памяти.
     * [p2pIp] — адрес из ответа очков, если он был.
     */
    fun sync(ssid: String, password: String, p2pIp: String?, deviceName: String = "", listener: Listener) {
        cancelled = false
        io.execute {
            try {
                runSync(ssid, password, p2pIp, deviceName, listener)
            } catch (e: Exception) {
                listener.onFinished(false, "Wi-Fi очков: ${e.message ?: e.javaClass.simpleName}")
            }
        }
    }

    private fun runSync(ssid: String, password: String, p2pIp: String?, deviceName: String, l: Listener) {
        var network: Network? = null
        if (ssid.isNotBlank()) {
            l.onLog("Wi-Fi очков: сеть «$ssid»" + if (password.isBlank()) " (без пароля)" else "")
            l.onStatus("Подключаюсь к сети «$ssid»…")
            network = join(ssid, password, 30_000)
        } else {
            l.onLog("Сеть очков не назвалась — пробую Wi-Fi Direct, как это делает их приложение")
        }
        if (network == null) {
            // Очки могут поднимать не точку доступа, а P2P-группу: тогда имени сети
            // в BLE-ответе нет вообще, и подключиться можно только через Wi-Fi Direct.
            l.onStatus("Пробую прямое соединение с очками (Wi-Fi Direct)…")
            network = p2pJoin(deviceName, p2pIp, 30_000)
            if (network != null) {
                l.onLog("Wi-Fi Direct: соединение с очками установлено")
            }
        }
        if (network == null) {
            // Возможно, к сети очков уже подключились вручную в настройках телефона.
            network = anyWifiNetwork()
            if (network != null) {
                l.onLog("Сеть очков не открылась автоматически — использую текущий Wi-Fi телефона")
            }
        }
        if (network == null) {
            l.onFinished(
                false,
                "Не удалось подключиться к очкам ни по имени сети, ни через Wi-Fi Direct. " +
                    "Проверьте, что очки подняли Wi-Fi (индикатор на очках), и нажмите «Повторить выгрузку»."
            )
            return
        }
        val net: Network = network
        try {
            if (cancelled) return
            l.onStatus("Ищу файлы на очках…")
            val addresses = candidates(net, p2pIp)
            l.onLog("Проверяю адреса: ${addresses.joinToString()}")
            var base: String? = null
            var config = ""
            for (address in addresses) {
                if (cancelled) return
                val url = "http://$address/files/media.config"
                val text = httpText(net, url)
                if (text != null) {
                    base = address
                    config = text
                    l.onLog("Список файлов получен с $address (${text.length} символов)")
                    break
                }
            }
            if (base == null) {
                l.onFinished(
                    false,
                    "Очки в сети, но HTTP-сервер не ответил. Проверьте, что очки действительно " +
                        "подняли Wi-Fi (индикатор на очках), и повторите."
                )
                return
            }
            val names = config.lineSequence()
                .map { it.trim().trimStart('/', '\\') }
                .filter { it.isNotEmpty() && !it.contains(' ') }
                .filter { it.contains('.') }
                .toList()
            l.onFiles(names.size, names)
            if (names.isEmpty()) {
                l.onFinished(false, "Очки подключились, но список файлов пуст — в памяти нет новых снимков.")
                return
            }
            var saved = 0
            var failed = 0
            names.forEachIndexed { index, name ->
                if (cancelled) return
                l.onProgress(index + 1, names.size, name)
                val bytes = httpBytes(net, "http://$base/files/$name")
                if (bytes == null || bytes.isEmpty()) {
                    failed += 1
                    l.onLog("Не скачался: $name")
                } else {
                    val file = save(name, bytes)
                    if (file != null) {
                        saved += 1
                        l.onSaved(file, isImage(name))
                        l.onLog("Скачано: $name (${bytes.size / 1024} КБ)")
                    } else {
                        failed += 1
                        l.onLog("Не удалось сохранить: $name")
                    }
                }
            }
            l.onFinished(
                saved > 0,
                "Готово: $saved из ${names.size} файлов сохранено" +
                    if (failed > 0) ", $failed не удалось" else ""
            )
        } finally {
            releaseNetwork()
        }
    }

    // ---------- Wi-Fi Direct (P2P) ----------
    //
    // Очки умеют поднимать не только точку доступа, но и P2P-группу. В этом случае
    // имени сети и пароля в BLE-ответе нет вообще, и единственный способ
    // подключиться — WifiP2pManager, как это делает официальное приложение.
    // Группой владеют очки (GO), телефон — клиент; адрес очков приходит
    // в сведениях о соединении.

    private var p2pReceiver: BroadcastReceiver? = null

    @Volatile
    private var p2pGoAddress: String? = null

    @SuppressLint("MissingPermission")
    private fun p2pJoin(deviceName: String, ipHint: String?, timeoutMs: Long): Network? {
        val manager = ctx.getSystemService(Context.WIFI_P2P_SERVICE) as? WifiP2pManager ?: return null
        val channel = try {
            manager.initialize(ctx, Looper.getMainLooper(), null)
        } catch (e: Exception) {
            null
        } ?: return null

        // 1. Поиск: у очков в P2P обычно имя модели или имя BLE-устройства.
        var peers: List<android.net.wifi.p2p.WifiP2pDevice> = emptyList()
        try {
            manager.discoverPeers(channel, null)
        } catch (e: Exception) {
            return null
        }
        for (i in 0 until 8) {
            if (cancelled) return null
            val latch = CountDownLatch(1)
            try {
                manager.requestPeers(channel) { list ->
                    peers = list?.deviceList?.toList() ?: emptyList()
                    latch.countDown()
                }
            } catch (e: Exception) {
                return null
            }
            latch.await(2, TimeUnit.SECONDS)
            if (peers.isNotEmpty()) break
            Thread.sleep(600)
        }
        if (peers.isEmpty()) return null

        val hint = deviceName.substringBefore(" (").trim()
        val target = peers.firstOrNull { hint.isNotBlank() && it.deviceName.contains(hint, true) }
            ?: peers.firstOrNull { it.deviceName.contains("glass", true) || it.deviceName.contains("hey", true) }
            ?: peers.first()

        // 2. Соединение и ожидание сведений о группе.
        val connected = CountDownLatch(1)
        var groupAddress: String? = null
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                if (intent?.action != WifiP2pManager.WIFI_P2P_CONNECTION_CHANGED_ACTION) return
                try {
                    manager.requestConnectionInfo(channel) { info: WifiP2pInfo ->
                        if (info.groupFormed) {
                            groupAddress = info.groupOwnerAddress?.hostAddress
                            p2pGoAddress = groupAddress
                            connected.countDown()
                        }
                    }
                } catch (ignored: Exception) {
                }
            }
        }
        p2pReceiver = receiver
        try {
            ctx.registerReceiver(receiver, IntentFilter(WifiP2pManager.WIFI_P2P_CONNECTION_CHANGED_ACTION))
        } catch (e: Exception) {
            return null
        }

        val config = WifiP2pConfig()
        config.deviceAddress = target.deviceAddress
        config.wps.setup = WpsInfo.PBC
        try {
            manager.connect(channel, config, null)
        } catch (e: Exception) {
            unregisterP2p()
            return null
        }

        val ok = try {
            connected.await(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (e: InterruptedException) {
            false
        }
        if (!ok) {
            unregisterP2p()
            return null
        }
        // Группа поднялась — ждём, пока Android покажет сеть с адресом P2P.
        val network = waitForP2pNetwork(8000)
        if (network != null) {
            try {
                cm?.bindProcessToNetwork(network)
            } catch (ignored: Exception) {
            }
        }
        return network
    }

    private fun waitForP2pNetwork(timeoutMs: Long): Network? {
        val manager = cm ?: return null
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val found = try {
                manager.allNetworks.firstOrNull { network ->
                    val lp = manager.getLinkProperties(network) ?: return@firstOrNull false
                    val iface = lp.interfaceName ?: ""
                    iface.startsWith("p2p") ||
                        lp.linkAddresses.any { it.address.hostAddress?.startsWith("192.168.49.") == true }
                }
            } catch (e: Exception) {
                null
            }
            if (found != null) return found
            Thread.sleep(400)
        }
        return null
    }

    private fun unregisterP2p() {
        p2pReceiver?.let {
            try {
                ctx.unregisterReceiver(it)
            } catch (ignored: Exception) {
            }
        }
        p2pReceiver = null
    }

    // ---------- Сеть очков ----------

    @SuppressLint("MissingPermission")
    private fun join(ssid: String, password: String, timeoutMs: Long): Network? {
        if (Build.VERSION.SDK_INT < 29) return null
        val manager = cm ?: return null
        releaseNetwork()
        val specifier = try {
            WifiNetworkSpecifier.Builder().setSsid(ssid).apply {
                if (password.length >= 8) setWpa2Passphrase(password)
            }.build()
        } catch (e: Exception) {
            return null
        }
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(specifier)
            .build()
        val latch = CountDownLatch(1)
        var found: Network? = null
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                if (found == null) found = network
                latch.countDown()
            }

            override fun onUnavailable() {
                latch.countDown()
            }
        }
        return try {
            networkCallback = cb
            manager.requestNetwork(request, cb)
            val ok = latch.await(timeoutMs, TimeUnit.MILLISECONDS)
            if (ok) found else null
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    private fun releaseNetwork() {
        unregisterP2p()
        networkCallback?.let { callback ->
            try {
                cm?.unregisterNetworkCallback(callback)
            } catch (ignored: Exception) {
            }
        }
        networkCallback = null
        wifi.release()
    }

    /** Любая Wi-Fi-сеть, к которой телефон уже подключён (ручной режим). */
    @SuppressLint("MissingPermission")
    private fun anyWifiNetwork(): Network? {
        val manager = cm ?: return null
        return try {
            manager.allNetworks.firstOrNull { network ->
                val caps = manager.getNetworkCapabilities(network) ?: return@firstOrNull false
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
            }
        } catch (e: Exception) {
            null
        }
    }

    /** Адрес очков: шлюз их точки доступа плюс известные заводские варианты. */
    @SuppressLint("MissingPermission")
    private fun candidates(network: Network, p2pIp: String?): List<String> {
        val out = LinkedHashSet<String>()
        try {
            val lp: LinkProperties? = cm?.getLinkProperties(network)
            lp?.routes?.firstOrNull { it.isDefaultRoute }?.gateway?.hostAddress?.let { out.add(it) }
            if (Build.VERSION.SDK_INT >= 30) {
                lp?.dhcpServerAddress?.hostAddress?.let { out.add(it) }
            }
        } catch (ignored: Exception) {
        }
        if (!p2pIp.isNullOrBlank()) out.add(p2pIp)
        p2pGoAddress?.let { out.add(it) }
        out.addAll(listOf("192.168.4.1", "192.168.49.1", "192.168.43.1", "192.168.1.1", "192.168.0.1"))
        return out.toList()
    }

    // ---------- HTTP ----------

    private fun open(network: Network, url: String, timeoutMs: Int): HttpURLConnection? {
        return try {
            val connection = network.openConnection(URL(url)) as HttpURLConnection
            connection.connectTimeout = timeoutMs
            connection.readTimeout = timeoutMs * 2
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            // Сервер очков отвечает 400 без «нормального» User-Agent и не умеет keep-alive.
            connection.setRequestProperty("User-Agent", "okhttp/4.9.2")
            connection.setRequestProperty("Connection", "close")
            connection.setRequestProperty("Accept-Encoding", "identity")
            connection
        } catch (e: Exception) {
            null
        }
    }

    private fun httpText(network: Network, url: String): String? {
        val connection = open(network, url, 4000) ?: return null
        return try {
            if (connection.responseCode != 200) return null
            connection.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        } catch (e: Exception) {
            null
        } finally {
            try {
                connection.disconnect()
            } catch (ignored: Exception) {
            }
        }
    }

    private fun httpBytes(network: Network, url: String): ByteArray? {
        val connection = open(network, url, 8000) ?: return null
        return try {
            if (connection.responseCode != 200) return null
            connection.inputStream.use { it.readBytes() }
        } catch (e: Exception) {
            null
        } finally {
            try {
                connection.disconnect()
            } catch (ignored: Exception) {
            }
        }
    }

    // ---------- Сохранение ----------

    private fun isImage(name: String): Boolean {
        val lower = name.lowercase()
        return lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".png")
    }

    private fun save(name: String, bytes: ByteArray): File? {
        return try {
            val safe = name.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(80)
            val dir = if (isImage(name)) File(ctx.filesDir, "photos") else File(ctx.filesDir, "glasses_media")
            dir.mkdirs()
            val file = File(dir, "wl_$safe")
            file.writeBytes(bytes)
            file
        } catch (e: Exception) {
            null
        }
    }
}
