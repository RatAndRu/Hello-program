package com.example.bluelink

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioManager
import android.media.MediaPlayer
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Surface
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Настоящее живое видео с очков — если прошивка его отдаёт.
 *
 * По Bluetooth видео не проходит: канал даёт около килобайта в секунду, а кадру
 * нужно в сотни раз больше. Зато в прошивке очков (по разбору открытого проекта
 * CyanBridge, docs/LIVE_PREVIEW_TEST_MODE.md) есть отдельное приложение
 * `ai_glass_livestream` на стеке live555: RTSP-сервер на порту 554 с потоком
 * `testH264VideoStreamer`. Очки поднимают Wi-Fi (P2P), и телефон может
 * подключиться к их сети и проиграть поток.
 *
 * Честная оговорка: включение этого режима командой по Bluetooth в открытых
 * источниках не подтверждено. Поэтому мы не «включаем» его, а проверяем:
 * подключаемся к сети очков и пробуем стандартные адреса. Если поток не
 * отвечает — в интерфейсе так и написано, а не «видео загружается».
 */
class LiveVideo(private val ctx: Context) {

    interface Listener {
        fun onStatus(text: String)
        fun onLog(line: String)
        fun onPlaying(url: String)
        fun onFailed(reason: String)
        fun onStopped()
    }

    private val io = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    private var player: MediaPlayer? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    @Volatile private var cancelled = false
    @Volatile private var bound: Network? = null
    private var surface: Surface? = null

    private val ports = intArrayOf(554, 8554, 8080)
    private val paths = arrayOf("testH264VideoStreamer", "live", "stream", "h264", "")

    fun setSurface(surface: Surface?) {
        this.surface = surface
        try {
            player?.setSurface(surface)
        } catch (ignored: Exception) {
        }
    }

    fun isPlaying(): Boolean = try {
        player?.isPlaying == true
    } catch (e: Exception) {
        false
    }

    fun start(ssid: String, password: String, ipHint: String?, l: Listener) {
        cancelled = false
        if (ssid.isBlank()) {
            l.onFailed(
                "Очки не сообщили имя своей Wi-Fi-сети, значит их сеть ещё не поднята. " +
                    "Сначала нажмите «Файлы с очков» → «Включить Wi-Fi», затем повторите."
            )
            return
        }
        l.onStatus("Подключаюсь к сети очков «$ssid»…")
        io.execute {
            val network = join(ssid, password, 25_000)
            if (cancelled) return@execute
            if (network == null) {
                l.onFailed("Сеть очков не открылась. Проверьте, что очки подняли Wi-Fi, и повторите.")
                return@execute
            }
            if (bound == null) {
                try {
                    cm?.bindProcessToNetwork(network)
                    bound = network
                } catch (ignored: Exception) {
                }
            }
            val addresses = candidates(network, ipHint)
            l.onLog("Живое видео: проверяю адреса " + addresses.joinToString())
            val urls = ArrayList<String>()
            for (address in addresses) {
                if (cancelled) return@execute
                for (port in ports) {
                    if (!portOpen(network, address, port)) continue
                    l.onLog("Живое видео: порт $port открыт на $address")
                    for (path in paths) {
                        urls.add(if (path.isEmpty()) "rtsp://$address:$port/" else "rtsp://$address:$port/$path")
                    }
                }
            }
            if (urls.isEmpty()) {
                l.onFailed(
                    "Сеть очков есть, но RTSP-порт (554) закрыт: эта прошивка живое видео не отдаёт. " +
                        "Остаётся режим «кадры» — он работает по Bluetooth."
                )
                return@execute
            }
            ui.post { tryUrls(urls, 0, l) }
        }
    }

    private fun tryUrls(urls: List<String>, index: Int, l: Listener) {
        if (cancelled) return
        if (index >= urls.size) {
            l.onFailed(
                "Очки приняли подключение, но поток не открылся. " +
                    "Значит, этот режим включается только их родным приложением."
            )
            return
        }
        val url = urls[index]
        l.onStatus("Пробую поток: $url")
        val created = MediaPlayer()
        player = created
        var done = false
        val timeout = Runnable {
            if (!done) {
                done = true
                try {
                    created.reset()
                    created.release()
                } catch (ignored: Exception) {
                }
                if (player === created) player = null
                tryUrls(urls, index + 1, l)
            }
        }
        created.setOnPreparedListener { mp ->
            if (done) {
                try {
                    mp.release()
                } catch (ignored: Exception) {
                }
                return@setOnPreparedListener
            }
            done = true
            ui.removeCallbacks(timeout)
            try {
                mp.start()
                surface?.let { mp.setSurface(it) }
            } catch (ignored: Exception) {
            }
            l.onLog("Живое видео: поток открылся — $url")
            l.onStatus("Идёт живое видео с очков")
            l.onPlaying(url)
        }
        created.setOnErrorListener { _, what, extra ->
            if (!done) {
                done = true
                ui.removeCallbacks(timeout)
                try {
                    created.reset()
                    created.release()
                } catch (ignored: Exception) {
                }
                if (player === created) player = null
                l.onLog("Живое видео: $url не открылся (код $what/$extra)")
                tryUrls(urls, index + 1, l)
            }
            true
        }
        try {
            created.setAudioStreamType(AudioManager.STREAM_MUSIC)
            created.setDataSource(url)
            created.prepareAsync()
            ui.postDelayed(timeout, 6000)
        } catch (e: Exception) {
            done = true
            ui.removeCallbacks(timeout)
            tryUrls(urls, index + 1, l)
        }
    }

    fun stop() {
        cancelled = true
        ui.post {
            try {
                player?.let {
                    if (it.isPlaying) it.stop()
                    it.reset()
                    it.release()
                }
            } catch (ignored: Exception) {
            }
            player = null
            try {
                cm?.bindProcessToNetwork(null)
            } catch (ignored: Exception) {
            }
            bound = null
            networkCallback?.let {
                try {
                    cm?.unregisterNetworkCallback(it)
                } catch (ignored: Exception) {
                }
            }
            networkCallback = null
        }
    }

    fun release() {
        stop()
        io.shutdownNow()
    }

    @SuppressLint("MissingPermission")
    private fun join(ssid: String, password: String, timeoutMs: Long): Network? {
        if (Build.VERSION.SDK_INT < 29) return null
        val manager = cm ?: return null
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
            if (latch.await(timeoutMs, TimeUnit.MILLISECONDS)) found else null
        } catch (e: Exception) {
            null
        }
    }

    @SuppressLint("MissingPermission")
    private fun candidates(network: Network, ipHint: String?): List<String> {
        val out = LinkedHashSet<String>()
        try {
            val lp = cm?.getLinkProperties(network)
            lp?.routes?.firstOrNull { it.isDefaultRoute }?.gateway?.hostAddress?.let { out.add(it) }
            if (Build.VERSION.SDK_INT >= 30) lp?.dhcpServerAddress?.hostAddress?.let { out.add(it) }
            lp?.linkAddresses?.forEach { addr ->
                val host = addr.address.hostAddress ?: return@forEach
                val prefix = host.substringBeforeLast('.', "")
                if (prefix.isNotBlank()) out.add("$prefix.1")
            }
        } catch (ignored: Exception) {
        }
        if (!ipHint.isNullOrBlank()) out.add(ipHint)
        out.addAll(listOf("192.168.49.1", "192.168.4.1", "192.168.43.1", "192.168.1.1"))
        return out.toList()
    }

    private fun portOpen(network: Network, host: String, port: Int): Boolean {
        return try {
            val socket = network.socketFactory.createSocket() as Socket
            socket.connect(InetSocketAddress(host, port), 1200)
            socket.close()
            true
        } catch (e: Exception) {
            false
        }
    }
}
