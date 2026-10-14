package com.example.pinphotoswidget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.io.File
import java.io.FileOutputStream
import kotlin.math.max

/**
 * Минимальное нативное ядро: выбирает фото -> сохраняет копию для виджета -> обновляет виджет.
 * В "боевой" версии сюда подключается Capacitor, и фото приходит из PWA одной кнопкой "На виджет".
 */
class MainActivity : AppWidgetActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 48, 48, 48) }
        root.addView(TextView(this).apply { text = "📌 ЗакрепФото — виджет\n\n1. Выбери фото\n2. Добавь виджет на рабочий стол (долгое нажатие → Виджеты)\n3. Смена иконки: кнопки ниже (activity-alias)"; textSize = 17f })
        root.addView(Button(this).apply { text = "Выбрать фото для виджета"; setOnClickListener { pick() } })
        root.addView(Button(this).apply { text = "Иконка: обычная"; setOnClickListener { IconSwitcher.setIcon(this@MainActivity, IconSwitcher.NORMAL) } })
        root.addView(Button(this).apply { text = "Иконка: огненная 🔥 (как стрик Duolingo)"; setOnClickListener { IconSwitcher.setIcon(this@MainActivity, IconSwitcher.FIRE) } })
        root.addView(Button(this).apply { text = "Иконка: сонная 😴"; setOnClickListener { IconSwitcher.setIcon(this@MainActivity, IconSwitcher.SLEEPY) } })
        setContentView(root)
    }

    private fun pick() = startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
        addCategory(Intent.CATEGORY_OPENABLE); type = "image/*"
    }, 42)

    @Deprecated("прототип")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri: Uri = data?.data ?: return
        if (requestCode != 42 || resultCode != RESULT_OK) return
        val bmp = MediaStore.Images.Media.getBitmap(contentResolver, uri)
        // Ужимаем под виджет: виджетам нельзя слать огромные Bitmap (лимит Binder ~1MB)
        val scale = 720f / max(bmp.width, bmp.height)
        val small = if (scale < 1) Bitmap.createScaledBitmap(bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true) else bmp
        FileOutputStream(File(filesDir, PinnedPhotoWidget.FILE_NAME)).use { small.compress(Bitmap.CompressFormat.JPEG, 88, it) }
        getSharedPreferences(PinnedPhotoWidget.PREFS, MODE_PRIVATE).edit().putString("caption", "Закреплённое фото").apply()
        PinnedPhotoWidget.updateAll(this)
        val ids = AppWidgetManager.getInstance(this).getAppWidgetIds(ComponentName(this, PinnedPhotoWidget::class.java))
        if (ids.isEmpty()) android.widget.Toast.makeText(this, "Фото сохранено. Теперь добавь виджет на рабочий стол.", android.widget.Toast.LENGTH_LONG).show()
    }
}

// Маленький базовый тип, чтобы не тянуть AppCompat в прототип
open class AppWidgetActivity : Activity()
