package com.example.pinphotoswidget

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.provider.OpenableColumns
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.content.FileProvider
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
                val intent = params.createIntent().apply {
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    if (params.mode == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
                        putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    }
                }
                Log.d(TAG, "onShowFileChooser: mode=${params.mode}, intent=$intent")
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
        fun listPhotos(): String {
            return try { synchronized(storeLock) {
                lastError = ""
                val out = JSONArray()
                val meta = readMeta()
                for (i in 0 until meta.length()) {
                    val item = JSONObject(meta.getJSONObject(i).toString())
                    val file = File(photoDir(), item.getString("file"))
                    if (!file.exists()) { lastError = "В meta.json есть запись, но файл не найден: ${file.name}"; continue }
                    val dataUrl = "data:" + item.optString("mime", "image/jpeg") + ";base64," +
                        Base64.encodeToString(file.readBytes(), Base64.NO_WRAP)
                    item.put("dataUrl", dataUrl)
                    out.put(item)
                }
                Log.d(TAG, "listPhotos -> ${out.length()} photos")
                out.toString()
            } } catch (e: Exception) {
                lastError = "listPhotos: ${e.javaClass.simpleName}: ${e.message}"
                Log.e(TAG, "listPhotos failed", e)
                "[]"
            }
        }

        @JavascriptInterface
        fun savePhoto(dataUrl: String, name: String): String {
            return try { synchronized(storeLock) {
                Log.d(TAG, "savePhoto start: name=$name, dataUrlLength=${dataUrl.length}")
                val mime = dataUrl.substringAfter("data:", "image/jpeg").substringBefore(";")
                val bytes = Base64.decode(dataUrl.substringAfter(",", dataUrl), Base64.DEFAULT)
                if (bytes.isEmpty()) throw IllegalStateException("Получено пустое изображение (0 байт)")
                val item = savePhotoBytes(bytes, mime, name)
                JSONObject(item.toString()).put("ok", true).put("dataUrl", dataUrl).toString()
            } } catch (e: Exception) {
                lastError = "savePhoto: ${e.javaClass.simpleName}: ${e.message}"
                Log.e(TAG, "savePhoto failed", e)
                JSONObject().put("ok", false).put("error", lastError).toString()
            }
        }

        @JavascriptInterface
        fun updatePhoto(json: String): String {
            return try { synchronized(storeLock) {
                val upd = JSONObject(json); val meta = readMeta(); var found = false
                for (i in 0 until meta.length()) {
                    val item = meta.getJSONObject(i)
                    if (item.getString("id") == upd.getString("id")) {
                        found = true
                        listOf("name", "album", "note").forEach { item.put(it, upd.optString(it)) }
                        item.put("tags", upd.optJSONArray("tags") ?: JSONArray())
                        item.put("pinned", upd.optBoolean("pinned")); item.put("widget", upd.optBoolean("widget"))
                    }
                }
                if (!found) throw IllegalStateException("updatePhoto: фото не найдено в meta.json")
                writeMeta(meta)
                "OK"
            } } catch (e: Exception) {
                lastError = "updatePhoto: ${e.javaClass.simpleName}: ${e.message}"
                Log.e(TAG, "updatePhoto failed", e)
                "ERROR: $lastError"
            }
        }

        @JavascriptInterface
        fun deletePhoto(id: String): String {
            return try { synchronized(storeLock) {
                val meta = readMeta(); val kept = JSONArray()
                for (i in 0 until meta.length()) {
                    val item = meta.getJSONObject(i)
                    if (item.getString("id") == id) File(photoDir(), item.getString("file")).delete() else kept.put(item)
                }
                writeMeta(kept)
                "OK"
            } } catch (e: Exception) {
                lastError = "deletePhoto: ${e.javaClass.simpleName}: ${e.message}"
                Log.e(TAG, "deletePhoto failed", e)
                "ERROR: $lastError"
            }
        }

        @JavascriptInterface
        fun getLastError(): String = lastError

        @JavascriptInterface
        fun getStorageInfo(): String = synchronized(storeLock) {
            val meta = readMeta(); var bytes = 0L; val ids = JSONArray()
            for (i in 0 until meta.length()) {
                val item = meta.getJSONObject(i); ids.put(item.optString("id"))
                bytes += File(photoDir(), item.optString("file")).length()
            }
            JSONObject().put("native", true).put("sdk", Build.VERSION.SDK_INT)
                .put("count", meta.length()).put("bytes", bytes).put("ids", ids)
                .put("lastError", lastError).put("dir", photoDir().absolutePath).toString()
        }

        /** Полностью нативный выбор фото: читаем файл через ContentResolver, минуя Blob в WebView. */
        @JavascriptInterface
        fun pickPhotosNative() {
            runOnUiThread {
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "image/*"
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                try { startActivityForResult(intent, NATIVE_PICK) }
                catch (e: Exception) { Toast.makeText(this@MainActivity, "Не удалось открыть галерею: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }

        @JavascriptInterface
        fun sharePhoto(dataUrl: String, name: String): String {
            return try {
                val mime = dataUrl.substringAfter("data:", "image/jpeg").substringBefore(";")
                val bytes = Base64.decode(dataUrl.substringAfter(",", dataUrl), Base64.DEFAULT)
                if (bytes.isEmpty()) throw IllegalStateException("Пустое изображение")
                val ext = when (mime) { "image/png" -> "png"; "image/webp" -> "webp"; "image/gif" -> "gif"; else -> "jpg" }
                val safeName = name.ifBlank { "photo" }.replace(Regex("[^A-Za-z0-9А-Яа-яЁё _-]"), "_").take(60)
                val dir = File(cacheDir, "shared").apply { mkdirs() }
                val file = File(dir, "$safeName.$ext")
                file.writeBytes(bytes)
                val uri = FileProvider.getUriForFile(this@MainActivity, packageName + ".fileprovider", file)
                runOnUiThread {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = mime.ifBlank { "image/jpeg" }
                        putExtra(Intent.EXTRA_STREAM, uri)
                        putExtra(Intent.EXTRA_TEXT, name)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(send, "Поделиться фото"))
                }
                "OK bytes=${bytes.size} mime=$mime"
            } catch (e: Exception) {
                lastError = "sharePhoto: ${e.javaClass.simpleName}: ${e.message}"
                Log.e(TAG, "sharePhoto failed", e)
                "ERROR: $lastError"
            }
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
    @Volatile private var lastError: String = ""
    private fun photoDir() = File(filesDir, "photos")
    private fun savePhotoBytes(bytes: ByteArray, mime: String, name: String): JSONObject {
        photoDir().mkdirs()
        val ext = when (mime) { "image/png" -> "png"; "image/webp" -> "webp"; "image/gif" -> "gif"; else -> "jpg" }
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val fileName = "$id.$ext"
        File(photoDir(), fileName).writeBytes(bytes)
        val item = JSONObject()
            .put("id", id).put("name", name.ifBlank { "Фото" }).put("album", "Разное")
            .put("tags", JSONArray()).put("note", "").put("pinned", false).put("widget", false)
            .put("createdAt", System.currentTimeMillis()).put("file", fileName).put("mime", mime.ifBlank { "image/jpeg" })
        val meta = readMeta(); meta.put(item); writeMeta(meta)
        Log.d(TAG, "saved photo id=$id file=$fileName bytes=${bytes.size} mime=$mime")
        return item
    }
    private fun displayName(uri: Uri): String {
        var name = "Фото"
        try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) name = c.getString(0) ?: name
            }
        } catch (e: Exception) { Log.w(TAG, "displayName failed for $uri", e) }
        return name.substringBeforeLast('.').ifBlank { "Фото" }
    }
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
            Log.d(TAG, "FILE_CHOOSER resultCode=$resultCode, uris=${result?.toList()}")
            fileCallback?.onReceiveValue(result)
            fileCallback = null
        }
        if (requestCode == NATIVE_PICK) {
            var saved = 0; val errors = mutableListOf<String>()
            Log.d(TAG, "NATIVE_PICK resultCode=$resultCode, data=${data?.data}, clip=${data?.clipData?.itemCount}")
            if (resultCode == RESULT_OK && data != null) {
                val uris = mutableListOf<Uri>()
                data.clipData?.let { clip -> for (i in 0 until clip.itemCount) uris.add(clip.getItemAt(i).uri) }
                if (uris.isEmpty()) data.data?.let { uris.add(it) }
                synchronized(storeLock) {
                    for (uri in uris) {
                        try {
                            val bytes = contentResolver.openInputStream(uri)?.readBytes()
                                ?: throw IllegalStateException("openInputStream вернул null")
                            if (bytes.isEmpty()) throw IllegalStateException("Файл пустой (0 байт)")
                            savePhotoBytes(bytes, contentResolver.getType(uri) ?: "image/jpeg", displayName(uri))
                            saved++
                        } catch (e: Exception) {
                            lastError = "native import $uri: ${e.javaClass.simpleName}: ${e.message}"
                            errors.add(lastError); Log.e(TAG, "native import failed: $uri", e)
                        }
                    }
                }
            }
            val msg = when {
                saved > 0 && errors.isEmpty() -> "Нативно сохранено фото: $saved"
                saved > 0 -> "Сохранено: $saved, ошибок: ${errors.size}. ${errors.first()}"
                resultCode != RESULT_OK -> "Выбор фото отменён"
                else -> "Не удалось сохранить фото. ${errors.firstOrNull() ?: "Нет данных от галереи"}"
            }
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
            val jsMsg = JSONObject.quote(msg)
            web.evaluateJavascript(
                "window.onNativePhotosImported && window.onNativePhotosImported($saved, $jsMsg)", null
            )
        }
    }

    @Deprecated("назад внутри приложения")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    companion object {
        const val FILE_CHOOSER = 1001
        const val NATIVE_PICK = 1002
        const val TAG = "PinPhotos"
    }
}
