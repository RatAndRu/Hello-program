package com.example.obyom

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Choreographer
import android.view.Surface
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.content.ContentValues
import android.media.MediaScannerConnection
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.MimeTypeMap
import java.io.File
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * Объём: тонкая обёртка над веб-частью (obyom/web), которая лежит в assets.
 * Файлы отдаются с адреса https://appassets.androidplatform.net/ — это «безопасный»
 * (https) источник, поэтому браузерный движок разрешает камеру. Интернет не нужен.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private var pendingPermission: PermissionRequest? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    // Своя камера (Camera2): камера WebView на части телефонов «замирает», пока не коснёшься экрана
    private val cam by lazy { NativeCam(this) }
    @Volatile private var camWanted = false
    @Volatile private var camPermAsked = false
    @Volatile private var camDenied = false
    private var camResume = false
    private var keepAlive = false
    // пока идёт съёмка — просим WebView перерисовываться каждый кадр экрана (вторая известная ошибка: «не рисует без касания»)
    private val frameCb = object : Choreographer.FrameCallback {
        override fun doFrame(frameTimeNanos: Long) {
            if (!keepAlive) return
            web.invalidate()
            Choreographer.getInstance().postFrameCallback(this)
        }
    }
    private fun startKeepAlive() { if (keepAlive) return; keepAlive = true; Choreographer.getInstance().postFrameCallback(frameCb) }

    @Suppress("DEPRECATION")
    private fun camRotation(): Int {
        val r = when (windowManager.defaultDisplay.rotation) {
            Surface.ROTATION_90 -> 90; Surface.ROTATION_180 -> 180; Surface.ROTATION_270 -> 270; else -> 0
        }
        return (cam.sensorOrientation - r + 360) % 360
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        web = WebView(this)
        web.setBackgroundColor(0xFF0B0D12.toInt())
        setContentView(web)
        goImmersive()

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            textZoom = 100 // крупный системный шрифт не должен выталкивать кнопки за край экрана
            allowFileAccess = false
            allowContentAccess = false
            userAgentString = "$userAgentString ObyomAndroid/1.0"
        }

        web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false)
        web.addJavascriptInterface(NativeBridge(), "ObyomNative")

        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url
                if (url.host != HOST) return null
                var path = url.path?.trimStart('/') ?: ""
                if (path.isEmpty()) path = "index.html"
                return try {
                    val stream = assets.open(path)
                    WebResourceResponse(mimeOf(path), "utf-8", stream).apply {
                        responseHeaders = mapOf("Cache-Control" to "no-cache")
                    }
                } catch (e: Exception) {
                    WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), "".byteInputStream())
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == HOST) return false
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, request.url)) }
                return true
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread {
                    if (!request.resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) {
                        request.deny(); return@runOnUiThread
                    }
                    if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                    } else {
                        pendingPermission = request
                        requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA)
                    }
                }
            }

            override fun onShowFileChooser(
                webView: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                }
                return try {
                    startActivityForResult(Intent.createChooser(intent, "Открыть файл"), REQ_FILE)
                    true
                } catch (e: Exception) {
                    fileCallback = null
                    false
                }
            }
        }

        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else web.loadUrl("https://$HOST/index.html")
    }

    /** Мост для веб-части: сохранить файл в галерею / поделиться им. */
    inner class NativeBridge {
        @JavascriptInterface
        fun saveFile(b64: String, name: String, mime: String): String =
            try { val r = save(b64, name, mime); r.second } catch (e: Exception) { "Не удалось сохранить: ${e.message}" }

        @JavascriptInterface
        fun shareFile(b64: String, name: String, mime: String): String = try {
            val (uri, msg) = save(b64, name, mime)
            if (uri != null) {
                runOnUiThread {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = mime
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    runCatching { startActivity(Intent.createChooser(send, "Поделиться моделью")) }
                }
                ""
            } else msg
        } catch (e: Exception) { "Не удалось поделиться: ${e.message}" }

        // Большие файлы (3D-модели) — кусками: begin → append (base64) … → finish
        private val parts = HashMap<String, java.io.FileOutputStream>()
        private val partFiles = HashMap<String, File>()

        @JavascriptInterface
        fun begin(name: String): String {
            val id = System.nanoTime().toString()
            val f = File(cacheDir, "part_$id")
            partFiles[id] = f; parts[id] = java.io.FileOutputStream(f)
            return id
        }

        @JavascriptInterface
        fun append(id: String, b64: String): Boolean = try {
            parts[id]?.write(Base64.decode(b64, Base64.DEFAULT)); true
        } catch (e: Exception) { false }

        @JavascriptInterface
        fun finish(id: String, name: String, mime: String, share: Boolean): String = try {
            parts.remove(id)?.close()
            val f = partFiles.remove(id) ?: throw Exception("нет данных")
            val (uri, msg) = saveBytes(f.readBytes(), name, mime)
            f.delete()
            if (share && uri != null) {
                runOnUiThread {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = mime
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    runCatching { startActivity(Intent.createChooser(send, "Поделиться моделью")) }
                }
                ""
            } else msg
        } catch (e: Exception) { "Не удалось сохранить: ${e.message}" }

        @JavascriptInterface
        fun version(): String = "1.9"

        /** Включить свою камеру: "ok", "perm" (ждём разрешения — спросить ещё раз позже) или текст ошибки. */
        @JavascriptInterface
        fun camStart(w: Int, h: Int): String {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                if (camDenied) return "Нет разрешения на камеру — разреши его в настройках телефона (Приложения → Объём → Права)"
                if (!camPermAsked) { camPermAsked = true; runOnUiThread { requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA) } }
                return "perm"
            }
            camWanted = true
            val r = try { cam.start(w, h) } catch (e: Exception) { "камера: ${e.message}" }
            if (r == "ok") runOnUiThread { startKeepAlive() }
            return r
        }

        /** Свежий кадр после last: "поворот|id|w|h|jpeg-base64"; "" — нового пока нет; "E:текст" — ошибка. */
        @JavascriptInterface
        fun camFrame(last: Int): String {
            val f = cam.frame(last)
            return if (f.isEmpty() || f.startsWith("E:")) f else "${camRotation()}|$f"
        }

        /** Зафиксировать/отпустить экспозицию и баланс белого (съёмка: все кадры одной яркости и цвета). */
        @JavascriptInterface
        fun camLock(on: Boolean): String = cam.lock(on)

        @JavascriptInterface
        fun camStop() {
            camWanted = false; camResume = false
            cam.stop()
            runOnUiThread { keepAlive = false }
        }
    }

    /** Возвращает (uri для отправки или null, сообщение пользователю). */
    private fun save(b64: String, name: String, mime: String): Pair<Uri?, String> =
        saveBytes(Base64.decode(b64, Base64.DEFAULT), name, mime)

    private fun saveBytes(bytes: ByteArray, name: String, mime: String): Pair<Uri?, String> {
        val isImage = mime.startsWith("image/") && mime != "image/svg+xml"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                put(MediaStore.MediaColumns.MIME_TYPE, mime)
                put(MediaStore.MediaColumns.RELATIVE_PATH, (if (isImage) Environment.DIRECTORY_PICTURES else Environment.DIRECTORY_DOWNLOADS) + "/Объём")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val collection = if (isImage) MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                else MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val uri = contentResolver.insert(collection, values) ?: return null to "Не удалось создать файл"
            contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
            values.clear(); values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            contentResolver.update(uri, values, null, null)
            return uri to (if (isImage) "Сохранено в Галерею → Pictures/Объём" else "Сохранено в Загрузки → Объём")
        }
        // Android 8–9: нужно разрешение на запись в память
        if (checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            runOnUiThread { requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_STORAGE) }
            return null to "Разреши доступ к памяти и нажми ещё раз"
        }
        @Suppress("DEPRECATION")
        val dir = File(Environment.getExternalStoragePublicDirectory(if (isImage) Environment.DIRECTORY_PICTURES else Environment.DIRECTORY_DOWNLOADS), "Объём")
        dir.mkdirs()
        val file = File(dir, name)
        file.writeBytes(bytes)
        var uri: Uri? = null
        val lock = Object()
        MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), arrayOf(mime)) { _, u -> synchronized(lock) { uri = u; lock.notifyAll() } }
        synchronized(lock) { if (uri == null) lock.wait(3000) }
        return uri to "Сохранено: ${file.absolutePath}"
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_CAMERA) return
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        camPermAsked = false; camDenied = !granted
        val req = pendingPermission ?: return
        pendingPermission = null
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            req.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
        } else req.deny()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_FILE) {
            fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileCallback = null
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) goImmersive()
    }

    @Suppress("DEPRECATION")
    private fun goImmersive() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let {
                it.hide(WindowInsets.Type.systemBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onPause() {
        if (cam.running) { camResume = true; cam.stop() }
        keepAlive = false
        web.onPause(); super.onPause()
    }
    override fun onResume() {
        super.onResume(); web.onResume()
        if (camResume && camWanted && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            camResume = false
            if (cam.start(cam.reqW, cam.reqH) == "ok") startKeepAlive()
        }
    }
    override fun onDestroy() { cam.stop(); web.destroy(); super.onDestroy() }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    private fun mimeOf(path: String): String {
        val ext = path.substringAfterLast('.', "").lowercase()
        return when (ext) {
            "html", "htm" -> "text/html"
            "js", "mjs" -> "text/javascript"
            "css" -> "text/css"
            "json" -> "application/json"
            "webmanifest" -> "application/manifest+json"
            "png" -> "image/png"
            "jpg", "jpeg" -> "image/jpeg"
            "svg" -> "image/svg+xml"
            else -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        }
    }

    companion object {
        private const val HOST = "appassets.androidplatform.net"
        private const val REQ_CAMERA = 1
        private const val REQ_FILE = 2
        private const val REQ_STORAGE = 3
    }
}
