package de.r80.companion

import android.app.Notification
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.Icon
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Reads Google Maps' navigation notification (needs notification access, granted by the
 * user in the system settings) and turns it into [Guidance] for the link. With capture
 * switched on, every Google Maps notification is also recorded ([Capture]) so the parser
 * and the arrow table can be built from real data.
 */
class MapsListenerService : NotificationListenerService() {
    private var icons: IconTable? = null
    private var navKey: String? = null

    override fun onListenerConnected() {
        icons = try {
            IconTable.parse(assets.open("maneuver_icons.json").bufferedReader().readText())
        } catch (e: Exception) {
            IconTable(emptyList())
        }
        activeNotifications?.filter { it.packageName == MapsParser.PACKAGE }?.forEach { onNotificationPosted(it) }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName != MapsParser.PACKAGE) return
        val n = sbn.notification
        val extras = n.extras
        val fields = MapsParser.Fields(
            title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString(),
            text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString(),
            subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString(),
            bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString(),
        )
        val bitmap = n.getLargeIcon()?.let { render(it) }
        val fp = bitmap?.let { fingerprint(it) }
        if (Settings.capture(this)) Capture.record(this, sbn, describe(extras), bitmap, fp)
        if (!isNavigation(n)) return
        navKey = sbn.key
        val g = MapsParser.parse(fields, icons?.match(fp))
        AppState.setGuidance(g, listOfNotNull(fields.title, fields.text, fields.subText).joinToString(" | "))
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        if (sbn.key == navKey) {
            navKey = null
            AppState.setGuidance(null, "")
        }
    }

    private fun isNavigation(n: Notification) =
        n.category == Notification.CATEGORY_NAVIGATION || (n.flags and Notification.FLAG_ONGOING_EVENT) != 0

    private fun render(icon: Icon): Bitmap? = try {
        val d = icon.loadDrawable(this) ?: throw IllegalStateException("no drawable")
        val w = d.intrinsicWidth.takeIf { it > 0 } ?: 96
        val h = d.intrinsicHeight.takeIf { it > 0 } ?: 96
        Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888).also {
            d.setBounds(0, 0, w, h)
            d.draw(Canvas(it))
        }
    } catch (e: Exception) {
        null
    }

    private fun fingerprint(b: Bitmap): IntArray? {
        val px = IntArray(b.width * b.height)
        b.getPixels(px, 0, b.width, 0, 0, b.width, b.height)
        return Fingerprint.of(IntArray(px.size) { px[it] ushr 24 }, b.width, b.height)
    }

    private fun describe(extras: Bundle): Map<String, String> =
        extras.keySet().sorted().associateWith { k ->
            @Suppress("DEPRECATION")
            when (val v = extras.get(k)) {
                null -> "null"
                is CharSequence -> v.toString()
                is Array<*> -> v.joinToString(" | ") { it.toString() }
                else -> "<${v.javaClass.simpleName}> $v"
            }
        }
}
