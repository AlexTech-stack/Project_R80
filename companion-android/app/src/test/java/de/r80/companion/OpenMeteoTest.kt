package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** open-meteo's answer (timeformat=unixtime, timezone=auto) as the HU's weather message. */
class OpenMeteoTest {
    // shaped like a real answer for Munich in summer time (UTC+2); trimmed to what we ask for
    private val answer = """
        {"latitude":48.14,"longitude":11.58,"utc_offset_seconds":7200,"timezone":"Europe/Berlin","elevation":520.0,
         "current_units":{"time":"unixtime","temperature_2m":"°C","weather_code":"wmo code"},
         "current":{"time":1792584000,"interval":900,"temperature_2m":11.4,"weather_code":2},
         "daily":{"time":[1792533600,1792620000,1792706400,1792792800],"weather_code":[3,61,0,71],
                  "temperature_2m_max":[13.1,10.2,12.7,2.0],"temperature_2m_min":[5.8,4.9,-1.5,-3.2]}}
    """.trimIndent()

    @Test fun answerBecomesTheWeatherMessage() {
        val w = OpenMeteo.parse(answer)
        assertEquals(Weather("open-meteo", 1792584000, 11.4, 2, listOf(
            Weather.Day("2026-10-21", 3, 13.1, 5.8), Weather.Day("2026-10-22", 61, 10.2, 4.9),
            Weather.Day("2026-10-23", 0, 12.7, -1.5), Weather.Day("2026-10-24", 71, 2.0, -3.2))), w)
    }

    @Test fun noDailyPartIsNoDays() {
        val w = OpenMeteo.parse("""{"utc_offset_seconds":0,"current":{"time":5,"temperature_2m":-3.5,"weather_code":71}}""")
        assertEquals(Weather("open-meteo", 5, -3.5, 71), w)
    }

    @Test fun missingCurrentIsAnError() {
        try { OpenMeteo.parse("""{"daily":{}}"""); throw AssertionError("accepted") } catch (_: IllegalArgumentException) {}
    }

    @Test fun requestRoundsTheCoordinates() {
        val url = OpenMeteo.url(48.137154, 11.576124)
        assertTrue(url, url.contains("latitude=48.14&longitude=11.58"))
        assertTrue(url, url.startsWith("https://api.open-meteo.com/v1/forecast?"))
    }
}
