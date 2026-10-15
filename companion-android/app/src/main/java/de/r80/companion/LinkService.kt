package de.r80.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
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
            val transports: () -> Transport
            if (Settings.transport(this) == "wifi") {
                val address = Settings.parseAddress(Settings.huAddress(this)) ?: return fail("bad HU address")
                transports = { TcpTransport(address.first, address.second) }
            } else {
                val adapter = getSystemService(BluetoothManager::class.java)?.adapter ?: return fail("no Bluetooth")
                val device = Settings.huDevice(this).takeIf { BluetoothAdapter.checkBluetoothAddress(it) }
                    ?: return fail("no headunit chosen")
                transports = { BluetoothTransport(adapter, device) }
            }
            link = Link(
                transports = transports,
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

    private fun fail(why: String): Int {
        AppState.setLink(Link.Status(Link.State.STOPPED, why))
        stopSelf()
        return START_NOT_STICKY
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
