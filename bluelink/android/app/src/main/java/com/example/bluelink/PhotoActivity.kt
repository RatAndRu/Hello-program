package com.example.bluelink

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.FileProvider
import java.io.File

/** Просмотр снимка: сохранить в галерею, отправить, удалить. */
class PhotoActivity : Activity() {

    private lateinit var file: File
    private var pendingExport = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val path = intent.getStringExtra("path")
        if (path == null) {
            finish()
            return
        }
        file = File(path)
        if (!file.exists()) {
            Toast.makeText(this, "Снимок не найден", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)

        val image = ImageView(this)
        image.scaleType = ImageView.ScaleType.FIT_CENTER
        loadImage(image)
        root.addView(
            image,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        // Верхняя панель
        val top = LinearLayout(this)
        top.orientation = LinearLayout.HORIZONTAL
        top.gravity = Gravity.CENTER_VERTICAL
        top.setPadding(dp(12), dp(12), dp(12), dp(12))
        val back = txt("←", 26, Pal.TEXT, bold = true)
        back.setPadding(dp(10), dp(2), dp(18), dp(2))
        back.setOnClickListener { finish() }
        top.addView(back)
        val title = column()
        title.addView(txt("Снимок", 15, Pal.TEXT, bold = true))
        val date = java.text.SimpleDateFormat("d MMMM, HH:mm:ss", java.util.Locale("ru"))
            .format(java.util.Date(file.lastModified()))
        title.addView(txt("$date · ${file.length() / 1024} КБ", 11, Pal.MUTED))
        top.addView(title, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(
            top,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.TOP
            )
        )

        // Нижняя панель действий
        val bottom = LinearLayout(this)
        bottom.orientation = LinearLayout.HORIZONTAL
        bottom.gravity = Gravity.CENTER_VERTICAL
        bottom.setPadding(dp(12), dp(12), dp(12), dp(20))
        bottom.background = roundRect(ColorUtils.withAlpha(Color.BLACK, 0xCC), 0)
        val share = actionButton("Поделиться", primary = true) { sharePhoto() }
        val gallery = actionButton("В галерею", primary = false) { exportToGallery() }
        val delete = actionButton("Удалить", primary = false) {
            if (file.delete()) {
                Toast.makeText(this, "Снимок удалён", Toast.LENGTH_SHORT).show()
                finish()
            }
        }
        bottom.addView(share)
        bottom.addView(gallery)
        bottom.addView(delete)
        root.addView(
            bottom,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM
            )
        )

        setContentView(root)
    }

    private fun loadImage(image: ImageView) {
        try {
            val bounds = BitmapFactory.Options()
            bounds.inJustDecodeBounds = true
            BitmapFactory.decodeFile(file.path, bounds)
            val screen = resources.displayMetrics.widthPixels
            var sample = 1
            while (bounds.outWidth / (sample * 2) >= screen) sample *= 2
            val bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
            if (bitmap != null) image.setImageBitmap(bitmap)
        } catch (ignored: Exception) {
        }
    }

    private fun sharePhoto() {
        try {
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "image/jpeg"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(intent, "Отправить снимок"))
        } catch (e: Exception) {
            Toast.makeText(this, "Не удалось отправить: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun exportToGallery() {
        if (Build.VERSION.SDK_INT >= 29 ||
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        ) {
            doExport()
        } else {
            pendingExport = true
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_STORAGE)
        }
    }

    private fun doExport() {
        val ok = PhotoStore(this).exportToGallery(file)
        Toast.makeText(
            this,
            if (ok) "Сохранено в Pictures/BlueLink" else "Не удалось сохранить в галерею",
            Toast.LENGTH_SHORT
        ).show()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_STORAGE && pendingExport) {
            pendingExport = false
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) doExport()
        }
    }

    companion object {
        private const val REQ_STORAGE = 200
    }
}
