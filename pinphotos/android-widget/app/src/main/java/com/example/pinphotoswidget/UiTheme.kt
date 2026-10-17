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
        activity.recreate()
    }

    fun color(context: Context, attr: Int): Int {
        val value = TypedValue()
        context.theme.resolveAttribute(attr, value, true)
        return value.data
    }
}
