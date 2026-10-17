package com.example.pinphotoswidget

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager

/**
 * Смена иконки как у Duolingo: все варианты иконки ЗАРАНЕЕ лежат в приложении (activity-alias в манифесте),
 * код только включает один алиас и выключает остальные. Нарисовать новую иконку "на лету" система не даст.
 */
object IconSwitcher {
    const val NORMAL = ".IconNormal"
    const val FIRE = ".IconFire"
    const val SLEEPY = ".IconSleepy"
    const val SHAPED = ".IconShaped"
    private val ALL = listOf(NORMAL, FIRE, SLEEPY, SHAPED)

    fun setIcon(context: Context, active: String) {
        val pm = context.packageManager
        ALL.forEach { alias ->
            pm.setComponentEnabledSetting(
                ComponentName(context.packageName, context.packageName + alias),
                if (alias == active) PackageManager.COMPONENT_ENABLED_STATE_ENABLED else PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                PackageManager.DONT_KILL_APP
            )
        }
    }
}
