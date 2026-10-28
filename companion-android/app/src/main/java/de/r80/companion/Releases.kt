package de.r80.companion

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * The HU's software updates from the project's releases on GitHub (D12): the newest release's
 * r80-hu-<version>.r80u, downloaded into the app's files and offered to the HU over the link
 * ([UpdateSender]). Checked when the link comes up, at most every [EVERY_MS] (or now: "Check
 * now"). The phone needs no key: the HU checks the file's signature itself. Only the newest
 * file is kept.
 */
object Releases {
    const val REPO = "AlexTech-stack/Project_R80"
    const val EVERY_MS = 6 * 3600 * 1000L
    private const val MAX_SIZE = 50_000_000L
    private val NAME = Regex("""^r80-hu-(.+)\.r80u$""")

    data class Release(val version: String, val name: String, val url: String, val size: Long)

    /** The update file of GitHub's "latest release" answer, or null (no such file, not a version). */
    fun parseLatest(json: String): Release? {
        val o = try { Json.parseToJsonElement(json).jsonObject } catch (_: Exception) { return null }
        val assets = o["assets"] as? JsonArray ?: return null
        for (a in assets) {
            val obj = a as? JsonObject ?: continue
            val name = (obj["name"] as? JsonPrimitive)?.content ?: continue
            val version = NAME.matchEntire(name)?.groupValues?.get(1) ?: continue
            val url = (obj["browser_download_url"] as? JsonPrimitive)?.content ?: continue
            val size = (obj["size"] as? JsonPrimitive)?.longOrNull ?: continue
            if (Versions.valid(version) && url.startsWith("https://") && size in 1..MAX_SIZE) return Release(version, name, url, size)
        }
        return null
    }

    private fun dir(ctx: Context) = File(ctx.filesDir, "updates").apply { mkdirs() }

    /** The downloaded file of the newest version, if any. */
    fun stored(ctx: Context): UpdateFile? {
        val f = dir(ctx).listFiles()?.mapNotNull { f -> NAME.matchEntire(f.name)?.let { it.groupValues[1] to f } }
            ?.filter { Versions.valid(it.first) }
            ?.maxWithOrNull { a, b -> Versions.compare(a.first, b.first) ?: 0 } ?: return null
        return try { UpdateFile(f.first, f.second.readBytes()) } catch (_: Exception) { null }
    }

    /** Asks GitHub (if due, or now with force) and downloads a newer file. Returns what it did, for
     *  the screen. Blocking: call it off the main thread. */
    fun check(ctx: Context, force: Boolean = false): String {
        val now = System.currentTimeMillis()
        if (!force && now - Settings.updateChecked(ctx) < EVERY_MS) return Settings.updateResult(ctx)
        val result = try {
            val r = latest() ?: return remember(ctx, now, "no update file in the latest release")
            val have = stored(ctx)?.version
            if (have != null && Versions.compare(have, r.version)?.let { it >= 0 } == true) {
                "the newest is ${r.version}, here already"
            } else {
                download(ctx, r)
                "${r.version} downloaded"
            }
        } catch (e: Exception) {
            "could not check: ${e.message ?: e.javaClass.simpleName}"
        }
        return remember(ctx, now, result)
    }

    private fun remember(ctx: Context, now: Long, result: String): String {
        Settings.setUpdateChecked(ctx, now, result)
        return result
    }

    private fun get(url: String): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 10_000
        readTimeout = 20_000
        setRequestProperty("Accept", "application/vnd.github+json")
        setRequestProperty("User-Agent", "r80-companion")              // GitHub wants one
    }

    private fun latest(): Release? {
        val c = get("https://api.github.com/repos/$REPO/releases/latest")
        try {
            if (c.responseCode == 404) return null                     // no release yet
            if (c.responseCode != 200) throw IllegalStateException("GitHub answered ${c.responseCode}")
            return parseLatest(c.inputStream.bufferedReader().readText())
        } finally {
            c.disconnect()
        }
    }

    private fun download(ctx: Context, r: Release) {
        val d = dir(ctx)
        val part = File(d, r.name + ".part")
        val c = get(r.url).apply { setRequestProperty("Accept", "application/octet-stream") }
        try {
            if (c.responseCode != 200) throw IllegalStateException("download: GitHub answered ${c.responseCode}")
            c.inputStream.use { input -> part.outputStream().use { input.copyTo(it) } }
        } finally {
            c.disconnect()
        }
        if (part.length() != r.size) {
            part.delete()
            throw IllegalStateException("download incomplete (${part.length()} of ${r.size} bytes)")
        }
        part.renameTo(File(d, r.name))
        d.listFiles()?.filter { it.name != r.name }?.forEach { it.delete() }   // only the newest stays
    }
}
