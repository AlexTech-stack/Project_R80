package de.r80.companion

/**
 * Google Maps' navigation notification -> [Guidance]. Not an official interface, so the
 * parsing is lenient and anything it does not understand degrades to maneuver "unknown"
 * with the app's own text (the HU shows that text). Known layout ("classic card"):
 *   title    distance to the next maneuver   "70 m", "1,2 km"
 *   text     road                              "Hauptstraße"
 *   subText  time · distance · arrival         "10 min · 3.2 km · 12:36 AM ETA"
 * The maneuver itself is only in the arrow image (large icon); see [IconTable].
 * Pure Kotlin, no Android types, so it runs in the JVM unit tests.
 */
object MapsParser {
    const val PACKAGE = "com.google.android.apps.maps"
    const val SOURCE = "google_maps"

    data class Fields(val title: String?, val text: String?, val subText: String?, val bigText: String? = null)

    private const val SP = "[\\s\\u00A0\\u202F]*"
    private val DISTANCE = Regex("^(\\d+(?:[.,]\\d+)?)$SP(km|m|mi|ft|yd)\\.?$", RegexOption.IGNORE_CASE)
    private val HOURS = Regex("(\\d+)$SP(h|hr|hrs|std\\.?|stunden?|hours?)(?![a-z])", RegexOption.IGNORE_CASE)
    private val MINUTES = Regex("(\\d+)$SP(min\\.?|mins|minuten?|minutes?)(?![a-z])", RegexOption.IGNORE_CASE)
    private val SEPARATORS = Regex("[·•|]")

    fun parse(f: Fields, icon: IconTable.Entry?): Guidance? {
        val title = f.title?.trim()?.takeIf { it.isNotEmpty() }
        val road = f.text?.trim()?.takeIf { it.isNotEmpty() }
        if (title == null && road == null) return null
        val dist = title?.let { distance(it) }
        val summary = (f.subText ?: f.bigText)?.let { summary(it) }
        val maneuver = icon?.maneuver ?: "unknown"
        return Guidance(
            source = SOURCE,
            maneuver = maneuver,
            modifier = icon?.modifier,
            exit = icon?.exit,
            distanceM = dist,
            street = road,
            // Not a distance in the title (rerouting, arrived, a new layout): show the app's own words.
            text = if (dist == null) listOfNotNull(title, road).joinToString(" · ") else null,
            remainingM = summary?.second,
            remainingS = summary?.first,
        )
    }

    /** "70 m", "1,2 km", "0.3 mi" -> metres; null if it is not just a distance. */
    fun distance(s: String): Double? {
        val m = DISTANCE.matchEntire(s.trim()) ?: return null
        val v = m.groupValues[1].replace(',', '.').toDoubleOrNull() ?: return null
        return when (m.groupValues[2].lowercase()) {
            "km" -> v * 1000
            "mi" -> v * 1609.344
            "ft" -> v * 0.3048
            "yd" -> v * 0.9144
            else -> v
        }
    }

    /** "1 h 5 min" / "1 Std. 5 Min." / "12 min" -> seconds; null if no duration. */
    fun duration(s: String): Double? {
        val h = HOURS.find(s)?.groupValues?.get(1)?.toIntOrNull()
        val min = MINUTES.find(s)?.groupValues?.get(1)?.toIntOrNull()
        if (h == null && min == null) return null
        return ((h ?: 0) * 3600 + (min ?: 0) * 60).toDouble()
    }

    /** "10 min · 3.2 km · 12:36 AM ETA" -> (remaining seconds, remaining metres), each null if missing. */
    fun summary(s: String): Pair<Double?, Double?> {
        var secs: Double? = null
        var metres: Double? = null
        for (part in s.split(SEPARATORS).map { it.trim() }) {
            val d = distance(part)
            if (d != null) {
                if (metres == null) metres = d
            } else if (secs == null) {
                secs = duration(part)
            }
        }
        return secs to metres
    }
}
