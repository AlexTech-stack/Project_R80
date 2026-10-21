package de.r80.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.location.altitude.AltitudeConverter
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import kotlin.math.roundToLong

/**
 * What the phone knows about where the car is, for the HU (docs/companion-protocol.md):
 * the altitude about once a minute ([Position]: never the coordinates) and the weather
 * there about every 30 minutes ([Weather], from open-meteo.com: free, no key, data under
 * CC BY 4.0). The position comes from Android's own location service (no Google library);
 * open-meteo gets it rounded to about 1 km. Runs on its own thread while the link runs.
 */
class Surroundings(
    private val ctx: Context,
    private val onWeather: (Weather) -> Unit,
    private val onPosition: (Position) -> Unit,
) {
    private var executor: ScheduledExecutorService? = null
    private var lastWeatherAt = 0L          // ms, when the last weather fetch worked
    private var lastTryAt = 0L

    fun start() {
        if (executor != null) return
        executor = Executors.newSingleThreadScheduledExecutor { Thread(it, "r80-surroundings").apply { isDaemon = true } }
            .also { it.scheduleWithFixedDelay(::tick, 0, POSITION_S, TimeUnit.SECONDS) }
    }

    fun stop() {
        executor?.shutdownNow()
        executor = null
    }

    private fun tick() {
        if (!allowed(ctx)) return
        val loc = try { locate(ctx) } catch (e: Exception) { null } ?: return
        position(loc)?.let { onPosition(it) }
        val now = System.currentTimeMillis()
        val due = now - lastWeatherAt >= WEATHER_MS && now - lastTryAt >= RETRY_MS
        if (due) {
            lastTryAt = now
            try {
                onWeather(OpenMeteo.parse(fetch(OpenMeteo.url(loc.latitude, loc.longitude))))
                lastWeatherAt = now
            } catch (_: Exception) {
                // no internet or a bad answer: try again in RETRY_MS, the HU keeps the last weather
            }
        }
    }


    private fun position(loc: Location): Position? {
        var alt: Double? = null
        var acc: Double? = null
        if (loc.hasAltitude()) {
            try {
                AltitudeConverter().addMslAltitudeToLocation(ctx, loc)     // GNSS gives the height above the ellipsoid
                if (loc.hasMslAltitude()) {
                    alt = loc.mslAltitudeMeters
                    if (loc.hasMslAltitudeAccuracy()) acc = loc.mslAltitudeAccuracyMeters.toDouble()
                }
            } catch (_: Exception) {
            }
        }
        val heading = if (loc.hasBearing() && loc.hasSpeed() && loc.speed > 1f) loc.bearing.toDouble() else null
        if (alt == null && heading == null) return null
        return Position(loc.time / 1000, alt?.coerceIn(-500.0, 9000.0), acc, heading?.coerceIn(0.0, 360.0))
    }

    private fun fetch(url: String): String {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 10_000
        c.readTimeout = 10_000
        c.setRequestProperty("User-Agent", "R80-Companion/${BuildConfig.VERSION_NAME}")
        try {
            if (c.responseCode != 200) throw IllegalStateException("HTTP ${c.responseCode}")
            return c.inputStream.bufferedReader().use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    companion object {
        fun allowed(ctx: Context) =
            ctx.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                ctx.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        /** A current location (blocks up to FIX_TIMEOUT_S): the fused provider (GNSS, Wi-Fi, cells)
         *  if the phone has one, else GNSS; null without permission or fix. Not on the main thread. */
        @android.annotation.SuppressLint("MissingPermission")    // allowed() checks it
        fun locate(ctx: Context): Location? {
            if (!allowed(ctx)) return null
            val lm = ctx.getSystemService(LocationManager::class.java) ?: return null
            val provider = listOf(LocationManager.FUSED_PROVIDER, LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                .firstOrNull { lm.hasProvider(it) && lm.isProviderEnabled(it) } ?: return null
            var result: Location? = null
            val done = CountDownLatch(1)
            lm.getCurrentLocation(provider, null, Runnable::run) { result = it; done.countDown() }
            done.await(FIX_TIMEOUT_S, TimeUnit.SECONDS)
            return result ?: lm.getLastKnownLocation(provider)?.takeIf { System.currentTimeMillis() - it.time < 2 * 60_000 }
        }

        const val POSITION_S = 60L
        const val WEATHER_MS = 30 * 60_000L
        const val RETRY_MS = 5 * 60_000L
        const val FIX_TIMEOUT_S = 20L
    }
}

/** open-meteo.com's forecast API: the request and its answer as a [Weather]. */
object OpenMeteo {
    /** Coordinates rounded to 0.01° (about 1 km): enough for the weather, no more. */
    fun url(lat: Double, lon: Double): String {
        fun r(v: Double) = "%.2f".format(java.util.Locale.ROOT, (v * 100).roundToLong() / 100.0)
        return "https://api.open-meteo.com/v1/forecast?latitude=${r(lat)}&longitude=${r(lon)}" +
            "&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min" +
            "&timezone=auto&timeformat=unixtime&forecast_days=4"
    }

    /** The answer to [url]; throws if a field is missing. */
    fun parse(json: String): Weather {
        val o = Json.parseToJsonElement(json).jsonObject
        val offset = (o["utc_offset_seconds"] as? JsonPrimitive)?.longOrNull ?: 0L
        val cur = o["current"] as? JsonObject ?: throw IllegalArgumentException("no current weather")
        fun num(obj: JsonObject, k: String) = (obj[k] as? JsonPrimitive)?.doubleOrNull ?: throw IllegalArgumentException("no $k")
        fun arr(obj: JsonObject, k: String) = obj[k] as? JsonArray ?: throw IllegalArgumentException("no $k")
        val daily = o["daily"] as? JsonObject
        val days = if (daily == null) emptyList() else {
            val t = arr(daily, "time"); val c = arr(daily, "weather_code")
            val hi = arr(daily, "temperature_2m_max"); val lo = arr(daily, "temperature_2m_min")
            t.indices.mapNotNull { i ->
                val day = (t[i] as? JsonPrimitive)?.longOrNull ?: return@mapNotNull null
                val code = (c.getOrNull(i) as? JsonPrimitive)?.intOrNull ?: return@mapNotNull null
                val max = (hi.getOrNull(i) as? JsonPrimitive)?.doubleOrNull ?: return@mapNotNull null
                val min = (lo.getOrNull(i) as? JsonPrimitive)?.doubleOrNull ?: return@mapNotNull null
                // the day's local midnight as unix time: its local date
                Weather.Day(Instant.ofEpochSecond(day + offset).atOffset(ZoneOffset.UTC).toLocalDate().toString(), code, max, min)
            }
        }
        return Weather("open-meteo", (cur["time"] as? JsonPrimitive)?.longOrNull ?: throw IllegalArgumentException("no time"),
            num(cur, "temperature_2m"), num(cur, "weather_code").toInt(), days.take(Protocol.MAX_DAYS))
    }
}
