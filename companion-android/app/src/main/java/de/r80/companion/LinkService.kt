package de.r80.companion

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Keeps the link to the HU while the app is in the background (a foreground service,
 * so Android does not stop it during a drive) and passes every guidance change on, and
 * (Settings.shareSurroundings) the weather and the altitude ([Surroundings]).
 */
class LinkService : Service() {
    private var link: Link? = null
    private var surroundings: Surroundings? = null
    private var generation = 0                  // the current link's; a stopped one's callbacks are ignored
    private val onChange: () -> Unit = { link?.update(AppState.guidance) }
    private val updates = UpdateSender { AppState.setUpdate(it) }   // the HU's software updates (D12)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val located = Settings.shareSurroundings(this) && (
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED)
        startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE or
            (if (located) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0))
        if (intent?.action == RESTART && link != null) {      // another HU or transport chosen
            generation++
            surroundings?.stop()
            surroundings = null
            AppState.unlisten(onChange)
            link?.stop()
            link = null
        }
        if (link == null) {
            val gen = generation
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
                onStatus = onStatus@{ s ->
                    if (gen != generation) return@onStatus
                    // the link ends (the phone leaves the car, or the HU switched off): park here
                    if (AppState.link.state == Link.State.CONNECTED && s.state != Link.State.CONNECTED) {
                        park()
                        AppState.setMedia(null)          // the remote shows nothing it cannot control
                    }
                    if (s.state == Link.State.CONNECTED && AppState.link.state != Link.State.CONNECTED) checkUpdates(false)
                    AppState.setLink(s)
                },
                onMedia = { AppState.setMedia(it) },
                onBrowsed = { AppState.setBrowsed(it) },
                updates = updates,
                onCarStatus = { s ->
                    CarStore.saveStatus(this, s)
                    AppState.carChanged()
                    if (s.final) {
                        park()
                        notifyWarnings(s)
                    }
                },
            ).also {
                it.update(AppState.guidance)
                it.start()
            }
            AppState.listen(onChange)
            AppState.sender = { line -> link?.sendNow(line) }
            AppState.checkUpdates = { force -> checkUpdates(force) }
            updates.setFile(if (Settings.bringUpdates(this)) Releases.stored(this) else null)
            if (located) {
                surroundings = Surroundings(this,
                    onWeather = { w -> link?.updateWeather(w); AppState.setWeather(w) },
                    onPosition = { p -> link?.updatePosition(p); AppState.setPosition(p) },
                ).also { it.start() }
            }
        }
        return START_STICKY
    }

    /** Asks the project's releases (if due, or now) on its own thread; a newer file goes to the HU
     *  over the link when it is up. */
    private fun checkUpdates(force: Boolean) {
        val ctx = applicationContext
        if (!Settings.bringUpdates(ctx)) {
            updates.setFile(null)
            return
        }
        Thread({
            AppState.setUpdateCheck(Releases.check(ctx, force))
            updates.setFile(Releases.stored(ctx))
        }, "r80-releases").start()
    }

    /** Where the car is parked: the phone's position now (it is at the car), on its own thread. */
    private fun park() {
        val ctx = applicationContext
        Thread({
            val loc = try { Surroundings.locate(ctx) } catch (_: Exception) { null } ?: return@Thread
            CarStore.saveParked(ctx, CarStore.Parked(loc.latitude, loc.longitude,
                if (loc.hasAccuracy()) loc.accuracy.toDouble() else null, System.currentTimeMillis() / 1000))
            AppState.carChanged()
        }, "r80-park").start()
    }

    /** Warnings still open when the ignition went off: a notification, so the driver sees them later too. */
    private fun notifyWarnings(s: CarStatus) {
        if (s.warnings.isEmpty()) return
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CAR_CHANNEL, getString(R.string.channel_car), NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        nm.notify(2, Notification.Builder(this, CAR_CHANNEL)
            .setSmallIcon(R.drawable.ic_r80)
            .setContentTitle(resources.getQuantityString(R.plurals.warnings_open, s.warnings.size, s.warnings.size))
            .setContentText(s.warnings.joinToString(" · ") { it.text })
            .setStyle(Notification.BigTextStyle().bigText(s.warnings.joinToString("\n") { it.text }))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    private fun fail(why: String): Int {
        AppState.setLink(Link.Status(Link.State.STOPPED, why))
        stopSelf()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        AppState.sender = null
        AppState.checkUpdates = null
        AppState.setMedia(null)
        surroundings?.stop()
        surroundings = null
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
        private const val CAR_CHANNEL = "car"
        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, LinkService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, LinkService::class.java))
        private const val RESTART = "de.r80.companion.RESTART"
        /** The link with the HU and transport chosen now; only if it runs. */
        fun restart(ctx: Context) = ctx.startForegroundService(Intent(ctx, LinkService::class.java).setAction(RESTART))
    }
}
