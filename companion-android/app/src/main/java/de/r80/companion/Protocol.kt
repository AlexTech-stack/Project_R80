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
    const val MAX_LINE = 65536          // a voice assistant's conversation (assist_request) is the longest
    const val MAX_TEXT = 200
    const val SERVICE_UUID = "b4184390-fb7f-44db-9eaa-6985447914af"
    const val MAX_DAYS = 7
    /** Software updates of the HU (D12): bytes per update_chunk, chunks before an update_ack. */
    const val MAX_CHUNK = 2048
    const val UPDATE_WINDOW = 8

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
        data class Media(val media: MediaState) : HuMessage()
        data class Browsed(val result: BrowseResult) : HuMessage()
        data class Bye(val reason: String?) : HuMessage()
        data class Update(val status: UpdateStatus) : HuMessage()
        data class UpdateAck(val id: Int, val received: Long) : HuMessage()
        /** The voice assistant's question (caps assistant): messages, tools, max_tokens as the HU sent them. */
        data class AssistRequest(val id: Int, val request: JsonObject) : HuMessage()
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
            "media" -> media(obj)?.let { HuMessage.Media(it) }
            "browse_result" -> browseResult(obj)?.let { HuMessage.Browsed(it) }
            "update_status" -> {
                val state = str(obj, "state")?.takeIf { it in UPDATE_STATES } ?: return null
                HuMessage.Update(UpdateStatus(str(obj, "version") ?: return null, str(obj, "pending") ?: "", state,
                    str(obj, "message") ?: "", num(obj, "id")?.toInt(), num(obj, "received")?.toLong()))
            }
            "assist_request" -> {
                val id = num(obj, "id")?.toInt() ?: return null
                val messages = obj["messages"] as? JsonArray ?: return null
                if (messages.isEmpty() || messages.any { (it as? JsonObject)?.let { m -> str(m, "role") in ROLES } != true }) return null
                HuMessage.AssistRequest(id, obj)
            }
            "update_ack" -> {
                val id = num(obj, "id")?.toInt() ?: return null
                HuMessage.UpdateAck(id, num(obj, "received")?.toLong() ?: return null)
            }
            else -> HuMessage.Unknown
        }
    }

    /** A remote command (media_cmd); value: Boolean, Number or String as the command wants. */
    fun mediaCmd(cmd: String, value: Any? = null, path: String? = null, index: Int? = null): String = line(buildMap {
        put("type", JsonPrimitive("media_cmd"))
        put("cmd", JsonPrimitive(cmd))
        when (value) {
            is Boolean -> put("value", JsonPrimitive(value))
            is Number -> put("value", JsonPrimitive(value))
            is String -> put("value", text(value))
        }
        path?.let { put("path", text(it)) }
        index?.let { put("index", JsonPrimitive(it)) }
    })

    fun browse(id: Int, path: String, offset: Int = 0, count: Int = 20): String = line(mapOf(
        "type" to JsonPrimitive("browse"), "id" to JsonPrimitive(id), "path" to text(path),
        "offset" to JsonPrimitive(offset), "count" to JsonPrimitive(count.coerceIn(1, 20))))

    val UPDATE_STATES = setOf("idle", "receiving", "checking", "unpacking", "ready", "failed", "refused")

    fun updateOffer(id: Int, version: String, size: Long, sha256: String): String = line(mapOf(
        "type" to JsonPrimitive("update_offer"), "id" to JsonPrimitive(id), "version" to text(version),
        "size" to JsonPrimitive(size), "sha256" to JsonPrimitive(sha256)))

    fun updateChunk(id: Int, offset: Long, data: ByteArray): String {
        require(data.isNotEmpty() && data.size <= MAX_CHUNK) { "a chunk is 1 to $MAX_CHUNK bytes" }
        return line(mapOf("type" to JsonPrimitive("update_chunk"), "id" to JsonPrimitive(id), "offset" to JsonPrimitive(offset),
            "data" to JsonPrimitive(java.util.Base64.getEncoder().encodeToString(data))))
    }

    /** The voice assistant (caps assistant): the roles of the LLM's chat messages. */
    val ROLES = setOf("system", "user", "assistant", "tool")

    /** Whether this phone can answer for the voice assistant (an LLM, the user's key), and why not. */
    fun assistStatus(ready: Boolean, provider: String, model: String, reason: String): String = line(mapOf(
        "type" to JsonPrimitive("assist_status"), "ready" to JsonPrimitive(ready), "provider" to text(provider),
        "model" to text(model), "reason" to text(reason)))

    /** The LLM's message (role assistant: content, tool_calls, reasoning_content) for request [id]. */
    fun assistReply(id: Int, message: JsonObject, finish: String, usageIn: Int?, usageOut: Int?, ms: Long): String = line(buildMap {
        put("type", JsonPrimitive("assist_reply"))
        put("id", JsonPrimitive(id))
        put("ok", JsonPrimitive(true))
        put("message", message)
        put("finish", text(finish))
        put("usage", JsonObject(buildMap {
            usageIn?.let { put("in", JsonPrimitive(it)) }
            usageOut?.let { put("out", JsonPrimitive(it)) }
        }))
        put("ms", JsonPrimitive(ms))
    })

    /** No answer for request [id]: code no_key | bad_key | no_credit | busy | offline | timeout | server | other. */
    fun assistError(id: Int, code: String, error: String, ms: Long? = null): String = line(buildMap {
        put("type", JsonPrimitive("assist_reply"))
        put("id", JsonPrimitive(id))
        put("ok", JsonPrimitive(false))
        put("code", text(code))
        put("error", text(error))
        ms?.let { put("ms", JsonPrimitive(it)) }
    })

    fun updateDone(id: Int): String = line(mapOf("type" to JsonPrimitive("update_done"), "id" to JsonPrimitive(id)))

    private fun str(obj: JsonObject?, k: String) = (obj?.get(k) as? JsonPrimitive)?.takeIf { it.isString }?.content?.take(MAX_TEXT)
    private fun num(obj: JsonObject?, k: String) = (obj?.get(k) as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull
    private fun flag(obj: JsonObject?, k: String) = (obj?.get(k) as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull

    private fun media(o: JsonObject): MediaState? {
        val status = str(o, "status")?.takeIf { it in setOf("playing", "paused", "stopped") } ?: return null
        return MediaState(flag(o, "allowed") ?: false, status, str(o, "source") ?: "",
            (o["sources"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }.orEmpty(),
            str(o, "title") ?: "", str(o, "artist") ?: "", str(o, "album") ?: "", num(o, "duration_s"), num(o, "position_s"),
            num(o, "time"), flag(o, "shuffle") ?: false, flag(o, "repeat") ?: false, num(o, "track")?.toInt(),
            num(o, "tracks")?.toInt(), str(o, "queue") ?: "",
            (o["up_next"] as? JsonArray)?.mapNotNull { (it as? JsonObject)?.let { u -> (str(u, "title") ?: "") to (str(u, "artist") ?: "") } }.orEmpty(),
            num(o, "volume")?.toInt(), num(o, "volume_max")?.toInt(), flag(o, "muted") ?: false)
    }

    private fun browseResult(o: JsonObject): BrowseResult? {
        val id = num(o, "id")?.toInt() ?: return null
        val entries = (o["entries"] as? JsonArray)?.mapNotNull { e ->
            val eo = e as? JsonObject ?: return@mapNotNull null
            BrowseResult.Entry(str(eo, "kind") ?: return@mapNotNull null, str(eo, "id") ?: "", str(eo, "title") ?: "",
                str(eo, "subtitle") ?: "", num(eo, "index")?.toInt() ?: -1)
        }.orEmpty()
        return BrowseResult(id, str(o, "path") ?: "", str(o, "title") ?: "", num(o, "total")?.toInt() ?: -1,
            num(o, "offset")?.toInt() ?: 0, entries)
    }

    /** car_status -> [CarStatus]; null if time or final is missing. Unknown fields are ignored. */
    private fun carStatus(o: JsonObject): CarStatus? {
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

/** What plays on the HU and its volume (media): the remote's view. */
data class MediaState(
    val allowed: Boolean, val status: String, val source: String, val sources: List<String>,
    val title: String, val artist: String, val album: String, val durationS: Double?, val positionS: Double?,
    /** when positionS was measured, unix s */
    val time: Double?, val shuffle: Boolean, val repeat: Boolean, val track: Int?, val tracks: Int?,
    val queue: String, val upNext: List<Pair<String, String>>, val volume: Int?, val volumeMax: Int?, val muted: Boolean,
) {
    /** The position now: counted on from `time` while playing. */
    fun positionAt(nowS: Double): Double? {
        val p = positionS ?: return null
        val at = time ?: return p
        val now = if (status == "playing") p + (nowS - at).coerceAtLeast(0.0) else p
        return durationS?.let { now.coerceAtMost(it) } ?: now
    }
}

/** A page of the HU's browse tree (browse_result); total -1: no such list. */
data class BrowseResult(val id: Int, val path: String, val title: String, val total: Int, val offset: Int, val entries: List<Entry>) {
    /** kind: menu | folder | artist | album | track; id: the path to browse into; index: a track's place for play_from */
    data class Entry(val kind: String, val id: String, val title: String, val subtitle: String, val index: Int)
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

/** How the HU's software stands (update_status): what runs, what waits, how an update goes. */
data class UpdateStatus(val version: String, val pending: String, val state: String, val message: String,
                        val id: Int? = null, val received: Long? = null)
