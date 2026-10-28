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

    /** Send the weather and the altitude to the HU (needs the location permission). */
    fun shareSurroundings(ctx: Context): Boolean = prefs(ctx).getBoolean("surroundings", true)
    fun setShareSurroundings(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("surroundings", v).apply()

    /** The driver wants the link on (Connect pressed, not Disconnect): the app starts it again when opened. */
    fun linkWanted(ctx: Context): Boolean = prefs(ctx).getBoolean("link_wanted", false)
    fun setLinkWanted(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("link_wanted", v).apply()

    /** Bring the HU's software updates from the project's releases (D12). */
    fun bringUpdates(ctx: Context): Boolean = prefs(ctx).getBoolean("updates", true)
    fun setBringUpdates(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("updates", v).apply()

    /** When the releases were last asked (ms) and what came of it. */
    fun updateChecked(ctx: Context): Long = prefs(ctx).getLong("update_checked", 0)
    fun updateResult(ctx: Context): String = prefs(ctx).getString("update_result", "")!!
    fun setUpdateChecked(ctx: Context, at: Long, result: String) =
        prefs(ctx).edit().putLong("update_checked", at).putString("update_result", result).apply()

    /** The voice assistant: answer the HU's questions with the user's LLM (the key is in [Secret]). */
    fun assistant(ctx: Context): Boolean = prefs(ctx).getBoolean("assistant", true)
    fun setAssistant(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("assistant", v).apply()
    /** The LLM: an OpenAI-compatible chat completions API and its model. */
    fun llmUrl(ctx: Context): String = prefs(ctx).getString("llm_url", Llm.DEFAULT_URL)!!
    fun llmModel(ctx: Context): String = prefs(ctx).getString("llm_model", Llm.DEFAULT_MODEL)!!
    fun setLlm(ctx: Context, url: String, model: String) = prefs(ctx).edit()
        .putString("llm_url", url.trim().ifEmpty { Llm.DEFAULT_URL }).putString("llm_model", model.trim().ifEmpty { Llm.DEFAULT_MODEL }).apply()

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
