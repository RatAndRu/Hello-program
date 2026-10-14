package com.example.pinphotoswidget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.widget.RemoteViews
import java.io.File

/** Виджет рабочего стола: показывает закреплённое фото, тап открывает приложение. */
class PinnedPhotoWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { updateOne(context, manager, it) }
    }

    companion object {
        const val FILE_NAME = "pinned_widget.jpg"
        const val PREFS = "pinphotos_widget"

        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, PinnedPhotoWidget::class.java))
            ids.forEach { updateOne(context, manager, it) }
        }

        private fun updateOne(context: Context, manager: AppWidgetManager, id: Int) {
            val views = RemoteViews(context.packageName, R.layout.widget_pinned_photo)
            val file = File(context.filesDir, FILE_NAME)
            if (file.exists()) {
                BitmapFactory.decodeFile(file.absolutePath)?.let { views.setImageViewBitmap(R.id.widget_image, it) }
            }
            val caption = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("caption", "ЗакрепФото")
            views.setTextViewText(R.id.widget_caption, caption)
            val open = PendingIntent.getActivity(
                context, 0,
                Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widget_root, open)
            manager.updateAppWidget(id, views)
        }
    }
}
