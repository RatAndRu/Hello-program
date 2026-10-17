package com.example.pinphotoswidget

import android.app.Activity
import android.content.Context
import android.util.TypedValue

object UiTheme {
    private const val PREFS = "ui"
    private const val KEY_DARK = "dark"

    fun isDark(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_DARK, false)

    fun apply(activity: Activity) {
        activity.setTheme(if (isDark(activity)) R.style.AppThemeDark else R.style.AppThemeLight)
    }

    fun toggle(activity: Activity) {
        val prefs = activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.edit().putBoolean(KEY_DARK, !isDark(activity)).apply()
        // НЕ recreate() прямо из обработчика PopupMenu: меню ещё держит старое окно/anchor,
        // на ряде оболочек (HONOR) это роняет Activity при пересоздании.
        // Даём меню закрыться и только потом спокойно пересоздаём экран.
        activity.window?.decorView?.postDelayed({
            if (!activity.isFinishing && !activity.isDestroyed) {
                try { activity.recreate() } catch (e: Exception) {
                    // Запасной путь: обычный перезапуск главного экрана.
                    try {
                        val intent = activity.intent.addFlags(android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP)
                        activity.startActivity(intent); activity.finish()
                    } catch (ignored: Exception) { }
                }
            }
        }, 250)
    }

    fun color(context: Context, attr: Int): Int {
        val value = TypedValue()
        context.theme.resolveAttribute(attr, value, true)
        return value.data
    }
}
