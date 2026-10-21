package de.r80.companion

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull

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
    const val MAX_DAYS = 7

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

    /** The weather where the phone is (see [Weather]); the HU asks for it with caps "weather". */
    fun weather(w: Weather): String = line(buildMap {
        put("type", JsonPrimitive("weather"))
        put("source", text(w.source))
        put("time", JsonPrimitive(w.time))
        put("now", JsonObject(mapOf("temp_c" to JsonPrimitive(w.tempC), "code" to JsonPrimitive(w.code))))
        put("days", JsonArray(w.days.take(MAX_DAYS).map {
            JsonObject(mapOf("date" to JsonPrimitive(it.date), "code" to JsonPrimitive(it.code),
                             "max_c" to JsonPrimitive(it.maxC), "min_c" to JsonPrimitive(it.minC)))
        }))
    })

    /** The altitude (never the coordinates); the HU asks for it with caps "position". */
    fun position(p: Position): String = line(buildMap {
        put("type", JsonPrimitive("position"))
        put("time", JsonPrimitive(p.time))
        p.altM?.let { put("alt_m", JsonPrimitive(it)) }
        p.accuracyM?.let { put("accuracy_m", number(it)) }
        p.headingDeg?.let { put("heading_deg", number(it)) }
    })

    /** What the HU can send us. */
    sealed class HuMessage {
        /** caps: what the HU wants besides guidance ("weather", "position"). */
        data class Hello(val proto: Int, val heartbeatS: Double?, val caps: List<String> = emptyList()) : HuMessage()
        data object Heartbeat : HuMessage()
        data class Status(val status: CarStatus) : HuMessage()
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
                val caps = (obj["caps"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
                HuMessage.Hello(proto, hb?.takeIf { it > 0 && it.isFinite() }, caps.orEmpty())
            }
            "heartbeat" -> HuMessage.Heartbeat
            "bye" -> HuMessage.Bye((obj["reason"] as? JsonPrimitive)?.takeIf { it.isString }?.content)
            "guidance" -> if ((obj["active"] as? JsonPrimitive)?.booleanOrNull == null) null else HuMessage.Unknown
            "car_status" -> carStatus(obj)?.let { HuMessage.Status(it) }
            else -> HuMessage.Unknown
        }
    }

    /** car_status -> [CarStatus]; null if time or final is missing. Unknown fields are ignored. */
    private fun carStatus(o: JsonObject): CarStatus? {
        fun num(obj: JsonObject?, k: String) = (obj?.get(k) as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull
        fun str(obj: JsonObject?, k: String) = (obj?.get(k) as? JsonPrimitive)?.takeIf { it.isString }?.content?.take(MAX_TEXT)
        val time = (o["time"] as? JsonPrimitive)?.longOrNull ?: return null
        val final = (o["final"] as? JsonPrimitive)?.booleanOrNull ?: return null
        val trip = (o["trip"] as? JsonObject)?.let { CarStatus.Trip(num(it, "km"), num(it, "minutes"), num(it, "avg_kmh")) }
        val warnings = (o["warnings"] as? JsonArray)?.mapNotNull { w ->
            val wo = w as? JsonObject ?: return@mapNotNull null
            val sev = str(wo, "severity") ?: return@mapNotNull null
            val text = str(wo, "text") ?: return@mapNotNull null
            CarStatus.Warning(sev, text)
        }.orEmpty()
        return CarStatus(time, final, num(o, "fuel_pct"), num(o, "range_km"), num(o, "odometer_km"), num(o, "battery_v"),
            num(o, "outside_c"), num(o, "service_km"), num(o, "service_days"), trip, warnings, str(o, "accent"))
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

/** How the car is, from the HU (car_status); null = the HU did not know it. final: the ignition went off. */
data class CarStatus(
    val time: Long,
    val final: Boolean,
    val fuelPct: Double? = null,
    val rangeKm: Double? = null,
    val odometerKm: Double? = null,
    val batteryV: Double? = null,
    val outsideC: Double? = null,
    val serviceKm: Double? = null,
    val serviceDays: Double? = null,
    val trip: Trip? = null,
    val warnings: List<Warning> = emptyList(),
    val accent: String? = null,
) {
    data class Trip(val km: Double?, val minutes: Double?, val avgKmh: Double?)
    /** severity: warning | information | notice */
    data class Warning(val severity: String, val text: String)
}

/** The weather as the protocol carries it: time in unix s, temperatures in °C, WMO codes. */
data class Weather(val source: String, val time: Long, val tempC: Double, val code: Int, val days: List<Day> = emptyList()) {
    init {
        require(tempC.isFinite() && tempC in -100.0..100.0) { "temperature $tempC" }
        require(code in 0..99) { "weather code $code" }
        require(time >= 0) { "time $time" }
    }

    /** date: YYYY-MM-DD, the phone's local date. */
    data class Day(val date: String, val code: Int, val maxC: Double, val minC: Double) {
        init {
            require(Regex("""\d{4}-\d{2}-\d{2}""").matches(date)) { "date $date" }
            require(code in 0..99) { "weather code $code" }
            require(maxC.isFinite() && minC.isFinite() && maxC in -100.0..100.0 && minC in -100.0..100.0) { "temperatures $maxC / $minC" }
        }
    }
}

/** What the HU gets from the phone's position: altitude above sea level, never coordinates. */
data class Position(val time: Long, val altM: Double? = null, val accuracyM: Double? = null, val headingDeg: Double? = null) {
    init {
        require(time >= 0) { "time $time" }
        require(altM == null || (altM.isFinite() && altM in -500.0..9000.0)) { "altitude $altM" }
        require(headingDeg == null || headingDeg in 0.0..360.0) { "heading $headingDeg" }
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
