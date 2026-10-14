package com.example.pinphotoswidget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.widget.RemoteViews
import kotlin.math.max

/**
 * Виджет: сам показывает ЗАКРЕПЛЁННЫЕ фото.
 * Несколько закреплённых — листает по таймеру обновления (updatePeriodMillis в widget_info_*.xml, 30 мин).
 * Нет закреплённых / нет фото — аккуратная заглушка.
 */
open class PinnedPhotoWidgetBase : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { render(context, manager, it) }
    }

    companion object {
        private const val PREFS = "pinphotos_widget"
        private const val KEY_INDEX = "rotation_index"

        val PROVIDERS: List<Class<out PinnedPhotoWidgetBase>> = listOf(
            PinnedPhotoWidget2x2::class.java,
            PinnedPhotoWidget3x2::class.java,
            PinnedPhotoWidget4x2::class.java,
            PinnedPhotoWidget4x3::class.java
        )

        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            PROVIDERS.forEach { cls ->
                val ids = manager.getAppWidgetIds(ComponentName(context, cls))
                ids.forEach { render(context, manager, it) }
            }
        }

        private fun render(context: Context, manager: AppWidgetManager, widgetId: Int) {
            val views = RemoteViews(context.packageName, R.layout.widget_pinned_photo)
            val all = PhotoStore.list(context)
            val pinned = all.filter { it.pinned }
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

            when {
                pinned.isNotEmpty() -> {
                    // Ротация: каждый апдейт — следующее закреплённое фото
                    val idx = prefs.getInt(KEY_INDEX, 0)
                    val photo = pinned[idx % pinned.size]
                    prefs.edit().putInt(KEY_INDEX, (idx + 1) % pinned.size).apply()
                    decodeScaled(photo.fileIn(PhotoStore.dir(context)).absolutePath)?.let {
                        views.setImageViewBitmap(R.id.widget_image, it)
                    } ?: views.setImageViewResource(R.id.widget_image, R.drawable.widget_placeholder)
                    views.setTextViewText(R.id.widget_caption,
                        if (pinned.size > 1) "📌 ${photo.name}  ·  ${idx % pinned.size + 1}/${pinned.size}" else "📌 ${photo.name}")
                }
                all.isNotEmpty() -> {
                    views.setImageViewResource(R.id.widget_image, R.drawable.widget_placeholder)
                    views.setTextViewText(R.id.widget_caption, "Закрепите фото 📌 — оно появится здесь")
                }
                else -> {
                    views.setImageViewResource(R.id.widget_image, R.drawable.widget_placeholder)
                    views.setTextViewText(R.id.widget_caption, "Добавьте фото в «ЗакрепФото»")
                }
            }

            val open = PendingIntent.getActivity(
                context, 0, Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widget_root, open)
            manager.updateAppWidget(widgetId, views)
        }

        private fun decodeScaled(path: String): Bitmap? {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(path, bounds)
            if (bounds.outWidth <= 0) return null
            var sample = 1
            while (max(bounds.outWidth, bounds.outHeight) / sample > 880) sample *= 2
            return BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
        }
    }
}

// Варианты размера: при добавлении виджета система покажет их отдельными пунктами.
class PinnedPhotoWidget2x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget3x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget4x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget4x3 : PinnedPhotoWidgetBase()
