package com.example.obyom

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

/**
 * Обработка скана идёт минутами. Пока она идёт, приложение держит «службу переднего плана» с уведомлением:
 * система не выгружает процесс, когда пользователь свернул «Объём» или погасил экран, а процессор не засыпает
 * (частичная блокировка сна). Сама обработка — в WebView (веб-поток), служба только защищает процесс.
 */
class ProcService : Service() {

    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Обработка скана…"
        val pct = intent?.getIntExtra(EXTRA_PCT, -1) ?: -1
        val n = build(this, text, pct, true)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) startForeground(ID_RUN, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(ID_RUN, n)
        if (wake == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "obyom:processing").apply {
                setReferenceCounted(false)
                acquire(3 * 60 * 60 * 1000L) // не дольше 3 ч — на случай, если обработка зависнет
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        runCatching { wake?.release() }
        wake = null
        super.onDestroy()
    }

    companion object {
        private const val CH_RUN = "obyom_proc"
        private const val CH_DONE = "obyom_done"
        private const val ID_RUN = 41
        private const val ID_DONE = 42
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_PCT = "pct"

        private fun channels(ctx: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (nm.getNotificationChannel(CH_RUN) == null)
                nm.createNotificationChannel(NotificationChannel(CH_RUN, "Обработка скана", NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
            if (nm.getNotificationChannel(CH_DONE) == null)
                nm.createNotificationChannel(NotificationChannel(CH_DONE, "Скан готов", NotificationManager.IMPORTANCE_DEFAULT))
        }

        private fun openApp(ctx: Context): PendingIntent {
            val i = Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            return PendingIntent.getActivity(ctx, 0, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }

        @Suppress("DEPRECATION")
        private fun build(ctx: Context, text: String, pct: Int, running: Boolean): Notification {
            channels(ctx)
            val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(ctx, if (running) CH_RUN else CH_DONE) else Notification.Builder(ctx)
            b.setSmallIcon(if (running) android.R.drawable.stat_notify_sync else android.R.drawable.stat_sys_download_done)
                .setContentTitle(if (running) "Объём — обработка" else "Объём")
                .setContentText(text)
                .setContentIntent(openApp(ctx))
                .setOnlyAlertOnce(true)
            if (running) { b.setOngoing(true); if (pct in 0..100) b.setProgress(100, pct, false) else b.setProgress(0, 0, true) }
            else b.setAutoCancel(true)
            return b.build()
        }

        fun start(ctx: Context, text: String) {
            val i = Intent(ctx, ProcService::class.java).putExtra(EXTRA_TEXT, text)
            runCatching { if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i) else ctx.startService(i) }
        }

        /** Обновить текст и процент в уведомлении (без перезапуска службы). */
        fun update(ctx: Context, text: String, pct: Int) {
            runCatching { ctx.getSystemService(NotificationManager::class.java).notify(ID_RUN, build(ctx, text, pct, true)) }
        }

        /** Обработка закончилась: убрать службу; если приложение свёрнуто — сообщить уведомлением. */
        fun stop(ctx: Context, doneText: String?, notify: Boolean) {
            runCatching { ctx.stopService(Intent(ctx, ProcService::class.java)) }
            if (notify && !doneText.isNullOrEmpty())
                runCatching { ctx.getSystemService(NotificationManager::class.java).notify(ID_DONE, build(ctx, doneText, -1, false)) }
        }
    }
}
