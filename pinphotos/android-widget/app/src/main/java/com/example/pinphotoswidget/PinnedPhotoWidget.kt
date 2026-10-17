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
    // Периодический апдейт от системы (~30 мин): листаем на следующее фото
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        shift(context, +1)
        ids.forEach { render(context, manager, it, javaClass) }
    }

    // Тапы по стрелкам ‹ › на самом виджете: ручное листание
    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        when (intent.action) {
            ACTION_PREV -> { shift(context, -1); updateAll(context) }
            ACTION_NEXT -> { shift(context, +1); updateAll(context) }
            ACTION_ZOOM -> {
                val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                prefs.edit().putBoolean(KEY_ZOOM, !prefs.getBoolean(KEY_ZOOM, false)).apply()
                updateAll(context)
            }
        }
    }

    companion object {
        const val ACTION_PREV = "com.example.pinphotoswidget.WIDGET_PREV"
        const val ACTION_NEXT = "com.example.pinphotoswidget.WIDGET_NEXT"
        const val ACTION_ZOOM = "com.example.pinphotoswidget.WIDGET_ZOOM"
        private const val PREFS = "pinphotos_widget"
        private const val KEY_INDEX = "rotation_index"
        private const val KEY_ZOOM = "zoomed"

        val PROVIDERS: List<Class<out PinnedPhotoWidgetBase>> = listOf(
            PinnedPhotoWidget2x2::class.java,
            PinnedPhotoWidget3x2::class.java,
            PinnedPhotoWidget4x2::class.java,
            PinnedPhotoWidget4x3::class.java
        )

        private fun shift(context: Context, delta: Int) {
            val lockedNames = PhotoStore.lockedAlbumNames(context)
            val size = PhotoStore.list(context).count { it.pinned && it.album !in lockedNames }
            if (size == 0) return
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val cur = prefs.getInt(KEY_INDEX, 0)
            prefs.edit().putInt(KEY_INDEX, ((cur + delta) % size + size) % size).apply()
        }

        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            PROVIDERS.forEach { cls ->
                val ids = manager.getAppWidgetIds(ComponentName(context, cls))
                ids.forEach { render(context, manager, it, cls) }
            }
        }

        private fun render(context: Context, manager: AppWidgetManager, widgetId: Int, cls: Class<out PinnedPhotoWidgetBase>) {
            val views = RemoteViews(context.packageName, R.layout.widget_pinned_photo)
            val all = PhotoStore.list(context)
            val lockedNames = PhotoStore.lockedAlbumNames(context)
            val pinned = all.filter { it.pinned && it.album !in lockedNames }
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

            when {
                pinned.isNotEmpty() -> {
                    val idx = prefs.getInt(KEY_INDEX, 0) % pinned.size
                    val photo = pinned[idx]
                    decodeForWidget(photo.fileIn(PhotoStore.dir(context)).absolutePath, prefs.getBoolean(KEY_ZOOM, false))?.let {
                        views.setImageViewBitmap(R.id.widget_image, it)
                    } ?: views.setImageViewResource(R.id.widget_image, R.drawable.widget_placeholder)
                    views.setTextViewText(R.id.widget_caption,
                        if (pinned.size > 1) "📌 ${photo.name} · ${idx + 1}/${pinned.size}" else "📌 ${photo.name}")
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
            views.setOnClickPendingIntent(R.id.widget_image, open)
            views.setOnClickPendingIntent(R.id.widget_caption, open)
            // Стрелки: отдельные зоны тапа, листание без открытия приложения
            views.setOnClickPendingIntent(R.id.widget_prev, navIntent(context, cls, ACTION_PREV, 1))
            views.setOnClickPendingIntent(R.id.widget_next, navIntent(context, cls, ACTION_NEXT, 2))
            views.setOnClickPendingIntent(R.id.widget_zoom, navIntent(context, cls, ACTION_ZOOM, 3))
            manager.updateAppWidget(widgetId, views)
        }

        private fun navIntent(context: Context, cls: Class<out PinnedPhotoWidgetBase>, action: String, code: Int): PendingIntent {
            val intent = Intent(context, cls).setAction(action)
            return PendingIntent.getBroadcast(context, code, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }

        /** Обычный режим — фото целиком под виджет; зум — увеличенный центральный фрагмент. */
        private fun decodeForWidget(path: String, zoomed: Boolean): Bitmap? {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(path, bounds)
            if (bounds.outWidth <= 0) return null
            var sample = 1
            while (max(bounds.outWidth, bounds.outHeight) / sample > 1100) sample *= 2
            val bmp = BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
            if (!zoomed) return bmp
            val w = (bmp.width * 0.55f).toInt().coerceAtLeast(1)
            val h = (bmp.height * 0.55f).toInt().coerceAtLeast(1)
            return Bitmap.createBitmap(bmp, (bmp.width - w) / 2, (bmp.height - h) / 2, w, h)
        }
    }
}

// Варианты размера: при добавлении виджета система покажет их отдельными пунктами.
class PinnedPhotoWidget2x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget3x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget4x2 : PinnedPhotoWidgetBase()
class PinnedPhotoWidget4x3 : PinnedPhotoWidgetBase()
