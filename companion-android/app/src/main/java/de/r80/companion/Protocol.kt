package de.r80.companion

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject

/**
 * Companion link protocol v1, the phone's side (docs/companion-protocol.md).
 * The HU's side is hu/services/companion_link.py; both are checked against
 * docs/companion-protocol-examples.jsonl. One JSON object per line, UTF-8, "\n".
 */
object Protocol {
    const val VERSION = 1
    const val MAX_LINE = 4096
    const val MAX_TEXT = 200
    const val SERVICE_UUID = "b4184390-fb7f-44db-9eaa-6985447914af"

    val MANEUVERS = setOf("depart", "turn", "continue", "merge", "fork", "on_ramp", "off_ramp",
        "roundabout", "uturn", "arrive", "unknown")
    val MODIFIERS = setOf("straight", "slight_left", "left", "sharp_left", "slight_right", "right", "sharp_right")

    fun hello(app: String, version: String, device: String?, caps: List<String>): String = line(buildMap {
        put("type", JsonPrimitive("hello"))
        put("proto", JsonPrimitive(VERSION))
        put("app", text(app))
        put("version", text(version))
        device?.let { put("device", text(it)) }
        put("caps", JsonArray(caps.map { text(it) }))
    })

    fun heartbeat(): String = line(mapOf("type" to JsonPrimitive("heartbeat")))

    fun bye(reason: String?): String = line(buildMap {
        put("type", JsonPrimitive("bye"))
        reason?.let { put("reason", text(it)) }
    })

    /** The whole current guidance; null = no guidance (ended or cancelled). */
    fun guidance(g: Guidance?): String = line(buildMap {
        put("type", JsonPrimitive("guidance"))
        put("active", JsonPrimitive(g != null))
        if (g != null) {
            put("source", text(g.source))
            put("maneuver", JsonObject(buildMap {
                put("type", JsonPrimitive(g.maneuver))
                g.modifier?.let { put("modifier", JsonPrimitive(it)) }
                g.exit?.let { put("exit", JsonPrimitive(it)) }
            }))
            g.distanceM?.let { put("distance_m", number(it)) }
            g.street?.let { put("street", text(it)) }
            g.text?.let { put("text", text(it)) }
            g.remainingM?.let { put("remaining_m", number(it)) }
            g.remainingS?.let { put("remaining_s", number(it)) }
        }
    })

    /** What the HU can send us. */
    sealed class HuMessage {
        data class Hello(val proto: Int, val heartbeatS: Double?) : HuMessage()
        data object Heartbeat : HuMessage()
        data class Bye(val reason: String?) : HuMessage()
        /** A type this version does not know: ignore it (forward compatibility). */
        data object Unknown : HuMessage()
    }

    /** Parses one line from the HU; null if it is not a valid message (drop it, keep the link). */
    fun parse(line: String): HuMessage? {
        val obj = try {
            Json.parseToJsonElement(line).jsonObject
        } catch (e: Exception) {
            return null
        }
        val type = (obj["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        return when (type) {
            "hello" -> {
                val proto = (obj["proto"] as? JsonPrimitive)?.intOrNull ?: return null
                val hb = (obj["heartbeat_s"] as? JsonPrimitive)?.doubleOrNull
                HuMessage.Hello(proto, hb?.takeIf { it > 0 && it.isFinite() })
            }
            "heartbeat" -> HuMessage.Heartbeat
            "bye" -> HuMessage.Bye((obj["reason"] as? JsonPrimitive)?.takeIf { it.isString }?.content)
            "guidance" -> if ((obj["active"] as? JsonPrimitive)?.booleanOrNull == null) null else HuMessage.Unknown
            else -> HuMessage.Unknown
        }
    }

    private fun text(s: String) = JsonPrimitive(s.take(MAX_TEXT))

    /** Whole numbers without ".0", like the HU side writes them. */
    private fun number(v: Double): JsonPrimitive {
        require(v.isFinite() && v >= 0) { "number $v must be finite and >= 0" }
        return if (v == Math.rint(v) && v < 1e15) JsonPrimitive(v.toLong()) else JsonPrimitive(v)
    }

    private fun line(fields: Map<String, kotlinx.serialization.json.JsonElement>): String {
        val s = JsonObject(fields).toString() + "\n"
        require(s.toByteArray(Charsets.UTF_8).size <= MAX_LINE) { "message longer than $MAX_LINE bytes" }
        return s
    }
}

/** One guidance state as the protocol carries it (see docs/companion-protocol.md). */
data class Guidance(
    val source: String,
    val maneuver: String,
    val modifier: String? = null,
    val exit: Int? = null,
    val distanceM: Double? = null,
    val street: String? = null,
    val text: String? = null,
    val remainingM: Double? = null,
    val remainingS: Double? = null,
) {
    init {
        require(maneuver in Protocol.MANEUVERS) { "unknown maneuver $maneuver" }
        require(modifier == null || modifier in Protocol.MODIFIERS) { "unknown modifier $modifier" }
        require(exit == null || exit in 1..99) { "exit $exit outside 1..99" }
    }
}
