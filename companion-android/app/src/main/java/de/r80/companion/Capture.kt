package de.r80.companion

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.provider.MediaStore
import android.service.notification.StatusBarNotification
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Capture mode: records every Google Maps notification (all text extras, category,
 * flags, the arrow's fingerprint) as one JSON line, and each different arrow image once
 * as PNG. Export puts everything into one zip in Downloads, to build the parser and
 * the arrow table (assets/maneuver_icons.json) from real drives. Stays on the phone
 * until exported; contains street names of the drive.
 */
object Capture {
    private var lastLine = ""

    private fun dir(ctx: Context) = File(ctx.filesDir, "capture").apply { mkdirs() }

    fun record(ctx: Context, sbn: StatusBarNotification, extras: Map<String, String>, icon: Bitmap?, fp: IntArray?) {
        val hex = fp?.let { Fingerprint.toHex(it) }
        val iconFile = hex?.let { "icon_" + java.security.MessageDigest.getInstance("SHA-1")
            .digest(it.toByteArray()).take(6).joinToString("") { b -> "%02x".format(b) } + ".png" }
        val n = sbn.notification
        val fields = linkedMapOf<String, kotlinx.serialization.json.JsonElement>(
            "category" to JsonPrimitive(n.category ?: ""),
            "channel" to JsonPrimitive(n.channelId ?: ""),
            "ongoing" to JsonPrimitive((n.flags and android.app.Notification.FLAG_ONGOING_EVENT) != 0),
            "icon_fp" to JsonPrimitive(hex ?: ""),
            "icon_file" to JsonPrimitive(iconFile ?: ""),
            "extras" to JsonObject(extras.mapValues { JsonPrimitive(it.value.take(500)) }),
        )
        val body = JsonObject(fields).toString()
        if (body == lastLine) return          // Maps re-posts the same state often
        lastLine = body
        val line = JsonObject(linkedMapOf("t" to JsonPrimitive(System.currentTimeMillis())) + fields).toString()
        synchronized(this) {
            File(dir(ctx), "notifications.jsonl").appendText(line + "\n")
            if (icon != null && iconFile != null) {
                val png = File(dir(ctx), iconFile)
                if (!png.exists()) png.outputStream().use { icon.compress(Bitmap.CompressFormat.PNG, 100, it) }
            }
        }
    }

    fun count(ctx: Context): Int =
        File(dir(ctx), "notifications.jsonl").takeIf { it.exists() }?.useLines { it.count() } ?: 0

    /** Zips the capture into Downloads/r80-capture-<time>.zip; returns its name. */
    fun export(ctx: Context): String {
        val name = "r80-capture-${System.currentTimeMillis() / 1000}.zip"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, "application/zip")
        }
        val uri = ctx.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("cannot create $name in Downloads")
        synchronized(this) {
            ctx.contentResolver.openOutputStream(uri)!!.use { out ->
                ZipOutputStream(out).use { zip ->
                    dir(ctx).listFiles()?.sortedBy { it.name }?.forEach { f ->
                        zip.putNextEntry(ZipEntry(f.name))
                        f.inputStream().use { it.copyTo(zip) }
                        zip.closeEntry()
                    }
                }
            }
        }
        return name
    }

    fun clear(ctx: Context) = synchronized(this) { dir(ctx).listFiles()?.forEach { it.delete() }; lastLine = "" }
}
