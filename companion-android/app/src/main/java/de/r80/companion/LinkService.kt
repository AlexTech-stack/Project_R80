package de.r80.companion

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

/**
 * Keeps the link to the HU while the app is in the background (a foreground service,
 * so Android does not stop it during a drive) and passes every guidance change on.
 */
class LinkService : Service() {
    private var link: Link? = null
    private val onChange: () -> Unit = { link?.update(AppState.guidance) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        if (link == null) {
            val address = Settings.parseAddress(Settings.huAddress(this))
            if (address == null) {
                AppState.setLink(Link.Status(Link.State.STOPPED, "bad HU address"))
                stopSelf()
                return START_NOT_STICKY
            }
            link = Link(
                transports = { TcpTransport(address.first, address.second) },
                device = "${Build.MANUFACTURER} ${Build.MODEL}",
                version = BuildConfig.VERSION_NAME,
                onStatus = { AppState.setLink(it) },
            ).also {
                it.update(AppState.guidance)
                it.start()
            }
            AppState.listen(onChange)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        AppState.unlisten(onChange)
        link?.stop()
        link = null
        super.onDestroy()
    }

    private fun notification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_link), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_r80)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.link_running))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL = "link"
        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, LinkService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, LinkService::class.java))
    }
}
