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
import java.io.File
import java.io.FileOutputStream
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
    }

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
