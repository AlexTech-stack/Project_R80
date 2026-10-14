package de.r80.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Recognises the maneuver from the navigation app's arrow image. An image becomes a
 * small fingerprint (content cropped, centred in a square, averaged down to 16 x 16
 * alpha values), which is compared with known fingerprints (assets/maneuver_icons.json,
 * built from captured notifications). Alpha only, so the arrow's colour does not matter;
 * cropping makes it independent of padding and screen density.
 * Pure Kotlin, no Android types, so it runs in the JVM unit tests.
 */
object Fingerprint {
    const val SIZE = 16

    /** alpha: w * h values 0..255, row by row. Null if the image is empty. */
    fun of(alpha: IntArray, w: Int, h: Int): IntArray? {
        var x0 = w; var y0 = h; var x1 = -1; var y1 = -1
        for (y in 0 until h) for (x in 0 until w) if (alpha[y * w + x] >= 64) {
            if (x < x0) x0 = x; if (x > x1) x1 = x
            if (y < y0) y0 = y; if (y > y1) y1 = y
        }
        if (x1 < 0) return null
        val side = maxOf(x1 - x0 + 1, y1 - y0 + 1)
        val offX = (side - (x1 - x0 + 1)) / 2
        val offY = (side - (y1 - y0 + 1)) / 2
        val sum = LongArray(SIZE * SIZE)
        for (y in y0..y1) for (x in x0..x1) {
            val cx = ((x - x0 + offX) * SIZE) / side
            val cy = ((y - y0 + offY) * SIZE) / side
            sum[cy * SIZE + cx] += alpha[y * w + x].toLong()
        }
        val cellArea = side.toDouble() * side / (SIZE * SIZE)
        return IntArray(SIZE * SIZE) { minOf(255, (sum[it] / cellArea).toInt()) }
    }

    /** 0 = identical .. 1 = completely different. */
    fun distance(a: IntArray, b: IntArray): Double {
        var d = 0L
        for (i in a.indices) d += kotlin.math.abs(a[i] - b[i])
        return d.toDouble() / (a.size * 255)
    }

    fun toHex(fp: IntArray): String = fp.joinToString("") { "%02x".format(it) }
    fun fromHex(s: String): IntArray? =
        if (s.length != SIZE * SIZE * 2) null else IntArray(SIZE * SIZE) { s.substring(it * 2, it * 2 + 2).toInt(16) }
}

class IconTable(val entries: List<Entry>, private val threshold: Double = 0.08) {
    data class Entry(val maneuver: String, val modifier: String?, val exit: Int?, val fp: IntArray, val note: String? = null)

    /** The closest known arrow, if close enough. */
    fun match(fp: IntArray?): Entry? {
        if (fp == null) return null
        return entries.map { it to Fingerprint.distance(fp, it.fp) }
            .filter { it.second <= threshold }
            .minByOrNull { it.second }?.first
    }

    companion object {
        /** {"icons": [{"maneuver": "turn", "modifier": "right", "exit": 2, "fp": "<512 hex>", "note": "..."}]} */
        fun parse(json: String): IconTable {
            val root = Json.parseToJsonElement(json).jsonObject
            val entries = root["icons"]?.jsonArray.orEmpty().mapNotNull { e ->
                val o = e as? JsonObject ?: return@mapNotNull null
                val maneuver = o["maneuver"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                val modifier = (o["modifier"] as? JsonPrimitive)?.contentOrNull
                val fp = o["fp"]?.jsonPrimitive?.contentOrNull?.let { Fingerprint.fromHex(it) } ?: return@mapNotNull null
                if (maneuver !in Protocol.MANEUVERS || (modifier != null && modifier !in Protocol.MODIFIERS)) return@mapNotNull null
                Entry(maneuver, modifier, (o["exit"] as? JsonPrimitive)?.intOrNull, fp, (o["note"] as? JsonPrimitive)?.contentOrNull)
            }
            return IconTable(entries)
        }
    }
}
