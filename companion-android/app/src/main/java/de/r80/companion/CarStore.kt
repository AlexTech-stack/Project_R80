package de.r80.companion

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import java.io.File

/**
 * The car as the app last heard of it, kept on the phone (files/car.json) for when the
 * driver is away from it: the last car_status, when it came, and where the car was parked
 * (the phone's position when the ignition went off or the link ended). The parking
 * position never leaves the phone.
 */
object CarStore {
    data class Parked(val lat: Double, val lon: Double, val accuracyM: Double?, val time: Long)
    data class Saved(val status: CarStatus, val receivedAt: Long, val parked: Parked?)

    @Volatile private var cache: Saved? = null
    @Volatile private var loaded = false

    private fun file(ctx: Context) = File(ctx.filesDir, "car.json")

    fun get(ctx: Context): Saved? {
        if (!loaded) {
            cache = try { decode(file(ctx).readText()) } catch (_: Exception) { null }
            loaded = true
        }
        return cache
    }

    fun saveStatus(ctx: Context, s: CarStatus, now: Long = System.currentTimeMillis() / 1000) {
        val old = get(ctx)
        write(ctx, Saved(s, now, old?.parked))
    }

    fun saveParked(ctx: Context, p: Parked) {
        val old = get(ctx) ?: return            // no car known yet: nothing to park
        write(ctx, old.copy(parked = p))
    }

    @Synchronized private fun write(ctx: Context, s: Saved) {
        cache = s
        loaded = true
        val tmp = File(ctx.filesDir, "car.json.tmp")
        tmp.writeText(encode(s))
        tmp.renameTo(file(ctx))
    }

    fun encode(s: Saved): String = JsonObject(buildMap {
        val st = s.status
        put("received", JsonPrimitive(s.receivedAt))
        put("status", JsonObject(buildMap {
            put("time", JsonPrimitive(st.time)); put("final", JsonPrimitive(st.final))
            fun n(k: String, v: Double?) { v?.let { put(k, JsonPrimitive(it)) } }
            n("fuel_pct", st.fuelPct); n("range_km", st.rangeKm); n("odometer_km", st.odometerKm)
            n("battery_v", st.batteryV); n("outside_c", st.outsideC); n("service_km", st.serviceKm)
            n("service_days", st.serviceDays)
            st.accent?.let { put("accent", JsonPrimitive(it)) }
            st.trip?.let { t -> put("trip", JsonObject(buildMap {
                t.km?.let { put("km", JsonPrimitive(it)) }; t.minutes?.let { put("minutes", JsonPrimitive(it)) }
                t.avgKmh?.let { put("avg_kmh", JsonPrimitive(it)) }
            })) }
            put("warnings", JsonArray(st.warnings.map {
                JsonObject(mapOf("severity" to JsonPrimitive(it.severity), "text" to JsonPrimitive(it.text)))
            }))
        }))
        s.parked?.let { p -> put("parked", JsonObject(buildMap {
            put("lat", JsonPrimitive(p.lat)); put("lon", JsonPrimitive(p.lon)); put("time", JsonPrimitive(p.time))
            p.accuracyM?.let { put("accuracy_m", JsonPrimitive(it)) }
        })) }
    }).toString()

    fun decode(text: String): Saved? {
        val o = Json.parseToJsonElement(text).jsonObject
        val st = o["status"] as? JsonObject ?: return null
        // the stored status has the protocol's own fields: read it the same way
        val status = (Protocol.parse(JsonObject(st + ("type" to JsonPrimitive("car_status"))).toString())
            as? Protocol.HuMessage.Status)?.status ?: return null
        val parked = (o["parked"] as? JsonObject)?.let { p ->
            val lat = (p["lat"] as? JsonPrimitive)?.doubleOrNull ?: return@let null
            val lon = (p["lon"] as? JsonPrimitive)?.doubleOrNull ?: return@let null
            Parked(lat, lon, (p["accuracy_m"] as? JsonPrimitive)?.doubleOrNull, (p["time"] as? JsonPrimitive)?.longOrNull ?: 0)
        }
        return Saved(status, (o["received"] as? JsonPrimitive)?.longOrNull ?: status.time, parked)
    }
}
