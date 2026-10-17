package com.example.pinphotoswidget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
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
      try {
        claimPendingNames(context)
        ids.forEach { widgetId ->
            if (autoEnabled(context, widgetId)) {
                val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                val now = System.currentTimeMillis()
                val last = prefs.getLong("lastshift_$widgetId", 0L)
                val intervalMs = intervalMinutes(context, widgetId).toLong() * 60_000L
                if (now - last >= intervalMs) {
                    shift(context, +1, widgetId)
                    prefs.edit().putLong("lastshift_$widgetId", now).apply()
                }
            }
            render(context, manager, widgetId, javaClass)
        }
      } catch (e: Throwable) {
        // Виджетный broadcast не должен убивать процесс приложения.
        try { java.io.File(context.filesDir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(e)) } catch (ignored: Exception) { }
      }
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        // Независимые копии удалённого виджета больше не нужны.
        appWidgetIds.forEach { widgetId ->
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove("name_$widgetId").apply()
            setWidgetPhotoIds(context, widgetId, emptyList())
            // Старые независимые копии из v1.6, если остались, чистим; обычные оригиналы не трогаем.
            PhotoStore.list(context).filter { it.widgetId == widgetId }.forEach { PhotoStore.delete(context, it) }
        }
        super.onDeleted(context, appWidgetIds)
    }

    // Тапы по стрелкам ‹ › на самом виджете: ручное листание
    override fun onReceive(context: Context, intent: Intent) {
      try {
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
      } catch (e: Throwable) {
        try { java.io.File(context.filesDir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(e)) } catch (ignored: Exception) { }
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

        fun getWidgetPhotoIds(context: Context, widgetId: Int): MutableList<String> {
            val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("refs_$widgetId", "") ?: ""
            return raw.split(',').filter { it.isNotBlank() }.toMutableList()
        }
        fun setWidgetPhotoIds(context: Context, widgetId: Int, ids: Collection<String>) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("refs_$widgetId", ids.distinct().joinToString(",")).apply()
        }
        fun widgetsContaining(context: Context, photoId: String): Set<Int> =
            installedWidgetIds(context).filter { photoId in getWidgetPhotoIds(context, it) }.toSet()
        fun setPhotoWidgets(context: Context, photoId: String, chosen: Collection<Int>) {
            installedWidgetIds(context).forEach { widgetId ->
                val ids = getWidgetPhotoIds(context, widgetId)
                if (widgetId in chosen) { if (photoId !in ids) ids.add(photoId) } else ids.remove(photoId)
                setWidgetPhotoIds(context, widgetId, ids)
            }
        }
        fun hideUi(context: Context, widgetId: Int): Boolean =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("hideui_$widgetId", false)
        fun setHideUi(context: Context, widgetId: Int, hidden: Boolean) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("hideui_$widgetId", hidden).apply()
            updateAll(context)
        }

        fun autoEnabled(context: Context, widgetId: Int): Boolean =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("auto_$widgetId", true)
        fun setAutoEnabled(context: Context, widgetId: Int, enabled: Boolean) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("auto_$widgetId", enabled).apply()
        }
        fun intervalMinutes(context: Context, widgetId: Int): Int =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt("interval_$widgetId", 30)
        fun setIntervalMinutes(context: Context, widgetId: Int, minutes: Int) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putInt("interval_$widgetId", minutes).apply()
        }
        fun clearWidget(context: Context, widgetId: Int) {
            setWidgetPhotoIds(context, widgetId, emptyList())
            PhotoStore.list(context).filter { it.widgetId == widgetId }.forEach { PhotoStore.delete(context, it) }
        }

        fun widgetName(context: Context, widgetId: Int): String {
            val name = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString("name_$widgetId", "")?.trim().orEmpty()
            return name.ifBlank { "Виджет №$widgetId" }
        }
        fun setWidgetName(context: Context, widgetId: Int, name: String) {
            val clean = name.trim().take(40)
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("name_$widgetId", clean).apply()
            updateAll(context)
        }
        /** Имя вводится до установки виджета, когда ID ещё не существует. Присваиваем первому новому ID. */
        fun queuePendingWidgetName(context: Context, name: String) {
            val clean = name.trim().take(40)
            if (clean.isEmpty()) return
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val current = prefs.getString("pending_names", "") ?: ""
            val queue = (current.split('\n').filter { it.isNotBlank() } + clean)
            prefs.edit().putString("pending_names", queue.joinToString("\n")).apply()
        }
        fun claimPendingNames(context: Context) {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            var queue = (prefs.getString("pending_names", "") ?: "").split('\n').filter { it.isNotBlank() }.toMutableList()
            if (queue.isEmpty()) return
            val editor = prefs.edit()
            installedWidgetIds(context).forEach { widgetId ->
                val hasName = !prefs.getString("name_$widgetId", "").isNullOrBlank()
                if (!hasName && queue.isNotEmpty()) editor.putString("name_$widgetId", queue.removeAt(0))
            }
            editor.putString("pending_names", queue.joinToString("\n")).apply()
        }

        fun installedWidgetIds(context: Context): List<Int> {
            val manager = AppWidgetManager.getInstance(context)
            return PROVIDERS.flatMap { cls -> manager.getAppWidgetIds(ComponentName(context, cls)).toList() }.distinct().sorted()
        }

        fun photosForWidget(context: Context, widgetId: Int): List<Photo> {
            val refs = getWidgetPhotoIds(context, widgetId)
            if (refs.isNotEmpty()) {
                val all = PhotoStore.list(context)
                val lockedNames = PhotoStore.lockedAlbumNames(context)
                val result = refs.mapNotNull { id -> all.firstOrNull { it.id == id && it.widgetId == 0 } }
                    .filter { photo -> photo.albums.none { it in lockedNames } }
                // Удаление оригинала автоматически убирает его из всех виджетов: битые ссылки подчищаем.
                if (result.size != refs.size) setWidgetPhotoIds(context, widgetId, result.map { it.id })
                return PhotoStore.dedupeForDisplay(result)
            }
            val all = PhotoStore.list(context)
            val own = all.filter { it.widgetId == widgetId }
            if (own.isNotEmpty()) return PhotoStore.dedupeForDisplay(own)
            // Миграция со старых версий: прежде виджеты жили на общем списке закреплённых.
            val lockedNames = PhotoStore.lockedAlbumNames(context)
            return all.filter { photo -> photo.widgetId == 0 && photo.pinned && photo.albums.none { it in lockedNames } }
        }

        /** ЗАВИСИМАЯ модель: в виджет добавляется ссылка на оригинал, а не копия файла.
         *  Удаление оригинала автоматически убирает фото из всех виджетов. */
        fun addCopiesToWidgets(context: Context, sourceIds: Collection<String>, widgetIds: Collection<Int>): Int {
            var added = 0
            val valid = PhotoStore.list(context).filter { it.widgetId == 0 }.map { it.id }.toSet()
            for (widgetId in widgetIds) {
                val ids = getWidgetPhotoIds(context, widgetId)
                for (id in sourceIds) if (id in valid && id !in ids) { ids.add(id); added++ }
                setWidgetPhotoIds(context, widgetId, ids)
            }
            if (added > 0) updateAll(context)
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
            try {
                val manager = AppWidgetManager.getInstance(context)
                PROVIDERS.forEach { cls ->
                    val ids = manager.getAppWidgetIds(ComponentName(context, cls))
                    ids.forEach { widgetId ->
                        try { render(context, manager, widgetId, cls) } catch (e: Throwable) {
                            try { java.io.File(context.filesDir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(e)) } catch (ignored: Exception) { }
                        }
                    }
                }
            } catch (e: Throwable) { }
        }

        private fun render(context: Context, manager: AppWidgetManager, widgetId: Int, cls: Class<out PinnedPhotoWidgetBase>) {
            // Виджет следует теме приложения (светлая/тёмная), а не только системе.
            val layout = if (UiTheme.isDark(context)) R.layout.widget_pinned_photo_dark else R.layout.widget_pinned_photo
            val views = RemoteViews(context.packageName, layout)
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

            val cleanMode = hideUi(context, widgetId)
            if (cleanMode) {
                // Чистый режим: только фото. Никаких стрелок, лупы, подписи и рамки-подложки.
                views.setViewVisibility(R.id.widget_controls, android.view.View.GONE)
                views.setViewVisibility(R.id.widget_zoom, android.view.View.GONE)
                views.setViewPadding(R.id.widget_root, 0, 0, 0, 0)
                views.setInt(R.id.widget_root, "setBackgroundResource", R.drawable.widget_clean_bg)
            } else {
                views.setViewVisibility(R.id.widget_controls, android.view.View.VISIBLE)
                views.setViewVisibility(R.id.widget_zoom, android.view.View.VISIBLE)
                val pad = (8 * context.resources.displayMetrics.density).toInt()
                views.setViewPadding(R.id.widget_root, pad, pad, pad, pad)
                views.setInt(R.id.widget_root, "setBackgroundResource",
                    if (UiTheme.isDark(context)) R.drawable.widget_bg_dark else R.drawable.widget_bg)
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
