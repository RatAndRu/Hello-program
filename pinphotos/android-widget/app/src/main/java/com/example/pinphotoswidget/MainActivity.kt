package com.example.pinphotoswidget

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import kotlin.math.max

/**
 * ЕДИНОЕ приложение «ЗакрепФото»: интерфейс PWA внутри WebView + нативные возможности Android.
 * Одна иконка в лаунчере (переключаемая алиасами), один APK, плюс виджет рабочего стола.
 *
 * Веб-файлы (../index.html, app.js, ...) Gradle копирует в assets при сборке — см. app/build.gradle.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            @Suppress("DEPRECATION") databaseEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            useWideViewPort = true
            loadWithOverviewMode = true
        }
        web.webViewClient = WebViewClient()
        // Открытие системной галереи из <input type="file"> внутри WebView
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView, callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                val intent = params.createIntent()
                return try { startActivityForResult(intent, FILE_CHOOSER); true }
                catch (e: Exception) { fileCallback = null; false }
            }
        }
        web.addJavascriptInterface(NativeBridge(), "PinPhotosNative")
        web.loadUrl("file:///android_asset/index.html")
    }

    /** Мост PWA -> Android: виджет и динамическая иконка. Вызывается из app.js. */
    inner class NativeBridge {
        @JavascriptInterface
        fun setWidgetPhoto(dataUrl: String, caption: String) {
            try {
                val bytes = Base64.decode(dataUrl.substringAfter(",", dataUrl), Base64.DEFAULT)
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return
                // Виджетам нельзя слать огромные Bitmap (лимит Binder ~1MB) — ужимаем
                val scale = 880f / max(bmp.width, bmp.height)
                val small = if (scale < 1) Bitmap.createScaledBitmap(
                    bmp, (bmp.width * scale).toInt().coerceAtLeast(1),
                    (bmp.height * scale).toInt().coerceAtLeast(1), true
                ) else bmp
                FileOutputStream(File(filesDir, PinnedPhotoWidget.FILE_NAME)).use {
                    small.compress(Bitmap.CompressFormat.JPEG, 88, it)
                }
                getSharedPreferences(PinnedPhotoWidget.PREFS, MODE_PRIVATE)
                    .edit().putString("caption", caption.ifBlank { "ЗакрепФото" }).apply()
                runOnUiThread {
                    PinnedPhotoWidget.updateAll(this@MainActivity)
                    Toast.makeText(this@MainActivity, "Фото установлено в виджет", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this@MainActivity, "Не удалось обновить виджет", Toast.LENGTH_SHORT).show() }
            }
        }

        @JavascriptInterface
        fun setIcon(state: String) {
            val alias = when (state) {
                "FIRE" -> IconSwitcher.FIRE
                "SLEEPY" -> IconSwitcher.SLEEPY
                else -> IconSwitcher.NORMAL
            }
            runOnUiThread {
                IconSwitcher.setIcon(this@MainActivity, alias)
                Toast.makeText(this@MainActivity, "Иконка переключена", Toast.LENGTH_SHORT).show()
            }
        }

        // ---------- Нативное хранилище фото (надёжная замена IndexedDB в WebView) ----------

        @JavascriptInterface
        fun listPhotos(): String = synchronized(storeLock) {
            val out = JSONArray()
            val meta = readMeta()
            for (i in 0 until meta.length()) {
                val item = JSONObject(meta.getJSONObject(i).toString())
                val file = File(photoDir(), item.getString("file"))
                if (!file.exists()) continue
                val dataUrl = "data:" + item.optString("mime", "image/jpeg") + ";base64," +
                    Base64.encodeToString(file.readBytes(), Base64.NO_WRAP)
                item.put("dataUrl", dataUrl)
                out.put(item)
            }
            out.toString()
        }

        @JavascriptInterface
        fun savePhoto(dataUrl: String, name: String): String = synchronized(storeLock) {
            photoDir().mkdirs()
            val mime = dataUrl.substringAfter("data:", "image/jpeg").substringBefore(";")
            val ext = when (mime) { "image/png" -> "png"; "image/webp" -> "webp"; else -> "jpg" }
            val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
            val fileName = "$id.$ext"
            File(photoDir(), fileName).writeBytes(Base64.decode(dataUrl.substringAfter(",", dataUrl), Base64.DEFAULT))
            val item = JSONObject()
                .put("id", id).put("name", name.ifBlank { "Фото" }).put("album", "Разное")
                .put("tags", JSONArray()).put("note", "").put("pinned", false).put("widget", false)
                .put("createdAt", System.currentTimeMillis()).put("file", fileName).put("mime", mime)
            val meta = readMeta(); meta.put(item); writeMeta(meta)
            JSONObject(item.toString()).put("dataUrl", dataUrl).toString()
        }

        @JavascriptInterface
        fun updatePhoto(json: String) = synchronized(storeLock) {
            val upd = JSONObject(json); val meta = readMeta()
            for (i in 0 until meta.length()) {
                val item = meta.getJSONObject(i)
                if (item.getString("id") == upd.getString("id")) {
                    listOf("name", "album", "note").forEach { item.put(it, upd.optString(it)) }
                    item.put("tags", upd.optJSONArray("tags") ?: JSONArray())
                    item.put("pinned", upd.optBoolean("pinned")); item.put("widget", upd.optBoolean("widget"))
                }
            }
            writeMeta(meta)
        }

        @JavascriptInterface
        fun deletePhoto(id: String) = synchronized(storeLock) {
            val meta = readMeta(); val kept = JSONArray()
            for (i in 0 until meta.length()) {
                val item = meta.getJSONObject(i)
                if (item.getString("id") == id) File(photoDir(), item.getString("file")).delete() else kept.put(item)
            }
            writeMeta(kept)
        }

        @JavascriptInterface
        fun requestPinWidget() {
            runOnUiThread {
                val manager = AppWidgetManager.getInstance(this@MainActivity)
                val provider = ComponentName(this@MainActivity, PinnedPhotoWidget::class.java)
                val supported = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager.isRequestPinAppWidgetSupported
                if (supported && manager.requestPinAppWidget(provider, null, null)) {
                    Toast.makeText(this@MainActivity, "Подтверди добавление виджета", Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(this@MainActivity,
                        "Этот лаунчер не умеет добавлять виджет из приложения. Долгое нажатие по рабочему столу → Виджеты → «Закреплённое фото»",
                        Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private val storeLock = Any()
    private fun photoDir() = File(filesDir, "photos")
    private fun readMeta(): JSONArray {
        val f = File(photoDir(), "meta.json")
        return if (f.exists()) try { JSONArray(f.readText()) } catch (e: Exception) { JSONArray() } else JSONArray()
    }
    private fun writeMeta(meta: JSONArray) { photoDir().mkdirs(); File(photoDir(), "meta.json").writeText(meta.toString()) }

    @Deprecated("нужен для file chooser")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == FILE_CHOOSER) {
            val result = WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            fileCallback?.onReceiveValue(result)
            fileCallback = null
        }
    }

    @Deprecated("назад внутри приложения")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    companion object { const val FILE_CHOOSER = 1001 }
}
