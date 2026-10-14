package de.r80.companion

import android.content.Context

/** The app's few settings, in SharedPreferences. */
object Settings {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("r80", Context.MODE_PRIVATE)

    /** Where the HU listens during development: navd --tcp PORT on the PC ("host:port"). */
    fun huAddress(ctx: Context): String = prefs(ctx).getString("hu_address", "192.168.1.10:47800")!!
    fun setHuAddress(ctx: Context, v: String) = prefs(ctx).edit().putString("hu_address", v.trim()).apply()

    /** "bluetooth" (the HU, paired) or "wifi" (development: navd --tcp on a PC). */
    fun transport(ctx: Context): String = prefs(ctx).getString("transport", "bluetooth")!!
    fun setTransport(ctx: Context, v: String) = prefs(ctx).edit().putString("transport", v).apply()

    /** Bluetooth address of the paired HU. */
    fun huDevice(ctx: Context): String = prefs(ctx).getString("hu_device", "")!!
    fun setHuDevice(ctx: Context, v: String) = prefs(ctx).edit().putString("hu_device", v).apply()

    fun capture(ctx: Context): Boolean = prefs(ctx).getBoolean("capture", false)
    fun setCapture(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("capture", v).apply()

    /** "host:port" -> pair, or null if malformed. */
    fun parseAddress(s: String): Pair<String, Int>? {
        val i = s.lastIndexOf(':')
        if (i <= 0) return null
        val port = s.substring(i + 1).toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
        return s.substring(0, i).trim().takeIf { it.isNotEmpty() }?.let { it to port }
    }
}
