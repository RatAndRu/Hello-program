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
        ids.forEach { widgetId -> shift(context, +1, widgetId); render(context, manager, widgetId, javaClass) }
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        // Независимые копии удалённого виджета больше не нужны.
        appWidgetIds.forEach { widgetId ->
            PhotoStore.list(context).filter { it.widgetId == widgetId }.forEach { PhotoStore.delete(context, it) }
        }
        super.onDeleted(context, appWidgetIds)
    }

    // Тапы по стрелкам ‹ › на самом виджете: ручное листание
    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        val widgetId = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        when (intent.action) {
            ACTION_PREV -> { shift(context, -1, widgetId); updateAll(context) }
            ACTION_NEXT -> { shift(context, +1, widgetId); updateAll(context) }
            ACTION_ZOOM -> {
                val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                val key = "zoom_$widgetId"
                prefs.edit().putBoolean(key, !prefs.getBoolean(key, false)).apply()
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

        fun installedWidgetIds(context: Context): List<Int> {
            val manager = AppWidgetManager.getInstance(context)
            return PROVIDERS.flatMap { cls -> manager.getAppWidgetIds(ComponentName(context, cls)).toList() }.distinct().sorted()
        }

        fun photosForWidget(context: Context, widgetId: Int): List<Photo> {
            val own = PhotoStore.list(context).filter { it.widgetId == widgetId }
            if (own.isNotEmpty()) return PhotoStore.dedupeForDisplay(own)
            // Миграция со старых версий: прежде виджеты жили на общем списке закреплённых.
            val lockedNames = PhotoStore.lockedAlbumNames(context)
            return PhotoStore.list(context).filter { photo -> photo.widgetId == 0 && photo.pinned && photo.albums.none { it in lockedNames } }
        }

        /** Добавляет независимые копии в выбранные виджеты. Внутри одного виджета дубликаты не создаём. */
        fun addCopiesToWidgets(context: Context, sourceIds: Collection<String>, widgetIds: Collection<Int>): Int {
            var added = 0
            val all = PhotoStore.list(context)
            for (widgetId in widgetIds) {
                for (id in sourceIds) {
                    val source = all.firstOrNull { it.id == id } ?: continue
                    val hash = PhotoStore.plainBytes(context, source)?.let { PhotoStore.sha256(it) } ?: source.hash
                    val exists = PhotoStore.list(context).any { it.widgetId == widgetId && it.hash == hash && hash.isNotEmpty() }
                    if (!exists && PhotoStore.duplicatePhoto(context, source, widgetId = widgetId) != null) added++
                }
            }
            return added
        }

        private fun shift(context: Context, delta: Int, widgetId: Int) {
            if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) return
            val size = photosForWidget(context, widgetId).size
            if (size == 0) return
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val key = "index_$widgetId"
            val cur = prefs.getInt(key, 0)
            prefs.edit().putInt(key, ((cur + delta) % size + size) % size).apply()
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
            val all = PhotoStore.list(context).filter { it.widgetId == 0 }
            val pinned = photosForWidget(context, widgetId)
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

            when {
                pinned.isNotEmpty() -> {
                    val idx = prefs.getInt("index_$widgetId", 0) % pinned.size
                    val photo = pinned[idx]
                    decodeForWidget(context, photo, prefs.getBoolean("zoom_$widgetId", false))?.let {
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
            views.setOnClickPendingIntent(R.id.widget_prev, navIntent(context, cls, ACTION_PREV, widgetId * 10 + 1, widgetId))
            views.setOnClickPendingIntent(R.id.widget_next, navIntent(context, cls, ACTION_NEXT, widgetId * 10 + 2, widgetId))
            views.setOnClickPendingIntent(R.id.widget_zoom, navIntent(context, cls, ACTION_ZOOM, widgetId * 10 + 3, widgetId))
            manager.updateAppWidget(widgetId, views)
        }

        private fun navIntent(context: Context, cls: Class<out PinnedPhotoWidgetBase>, action: String, code: Int, widgetId: Int): PendingIntent {
            val intent = Intent(context, cls).setAction(action).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)
            return PendingIntent.getBroadcast(context, code, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }

        /** Обычный режим — фото целиком под виджет; зум — увеличенный центральный фрагмент. */
        private fun decodeForWidget(context: Context, photo: Photo, zoomed: Boolean): Bitmap? {
            // RemoteViews: видео и GIF здесь всегда статичный кадр, анимацию виджеты Android не показывают.
            val bmp = PhotoStore.decodeBitmap(context, photo, 1100) ?: return null
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
