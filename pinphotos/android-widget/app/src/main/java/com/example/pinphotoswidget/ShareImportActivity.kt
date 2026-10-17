package com.example.pinphotoswidget

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.widget.Toast
import java.util.concurrent.Executors

/**
 * Приём фото через системное «Поделиться»:
 * «ЗакрепФото» появляется в списке приложений у фотографий и сразу сохраняет их себе.
 */
class ShareImportActivity : Activity() {
    private val io = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val uris = collectUris(intent)
        if (uris.isEmpty()) { Toast.makeText(this, "Нет изображений", Toast.LENGTH_SHORT).show(); finish(); return }

        io.execute {
            var saved = 0
            for (uri in uris) {
                try {
                    val mime = contentResolver.getType(uri)?.takeIf { it.startsWith("image/") || it.startsWith("video/") }
                        ?: intent.type?.takeIf { it.startsWith("image/") || it.startsWith("video/") }
                        ?: "image/jpeg"
                    if (!mime.startsWith("image/") && !mime.startsWith("video/")) continue
                    // Потоково: большое видео нельзя читать целиком в ByteArray — это роняет приложение по памяти.
                    val input = contentResolver.openInputStream(uri) ?: continue
                    PhotoStore.importStream(this, input, mime, displayName(uri))
                    saved++
                } catch (e: Exception) { }
            }
            runOnUiThread {
                Toast.makeText(this, if (saved > 0) "Сохранено в «ЗакрепФото»: $saved" else "Не удалось сохранить фото", Toast.LENGTH_LONG).show()
                startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
                finish()
            }
        }
    }

    private fun collectUris(source: Intent?): List<Uri> {
        if (source == null) return emptyList()
        val result = mutableListOf<Uri>()
        if (source.action == Intent.ACTION_SEND_MULTIPLE) {
            val list: ArrayList<Uri>? = if (Build.VERSION.SDK_INT >= 33) {
                source.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            } else {
                @Suppress("DEPRECATION") source.getParcelableArrayListExtra(Intent.EXTRA_STREAM)
            }
            list?.let { result.addAll(it) }
        }
        if (result.isEmpty()) {
            val one: Uri? = if (Build.VERSION.SDK_INT >= 33) {
                source.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            } else {
                @Suppress("DEPRECATION") source.getParcelableExtra(Intent.EXTRA_STREAM)
            }
            one?.let { result.add(it) }
        }
        return result
    }

    private fun displayName(uri: Uri): String {
        var name = "Фото"
        try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) name = c.getString(0) ?: name
            }
        } catch (e: Exception) { }
        return name.substringBeforeLast('.').ifBlank { "Фото" }
    }
}
