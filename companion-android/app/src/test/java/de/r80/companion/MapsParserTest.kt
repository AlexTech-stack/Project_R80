package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MapsParserTest {
    @Test fun distances() {
        assertEquals(70.0, MapsParser.distance("70 m")!!, 0.0)
        assertEquals(1200.0, MapsParser.distance("1,2 km")!!, 0.01)
        assertEquals(1200.0, MapsParser.distance("1.2 km")!!, 0.01)
        assertEquals(482.8, MapsParser.distance("0.3 mi")!!, 0.1)
        assertEquals(152.4, MapsParser.distance("500 ft")!!, 0.1)
        assertNull(MapsParser.distance("Hauptstraße"))
        assertNull(MapsParser.distance("Rechts abbiegen in 70 m"))
    }

    @Test fun durations() {
        assertEquals(600.0, MapsParser.duration("10 min")!!, 0.0)
        assertEquals(720.0, MapsParser.duration("12 Min.")!!, 0.0)
        assertEquals(3900.0, MapsParser.duration("1 h 5 min")!!, 0.0)
        assertEquals(3900.0, MapsParser.duration("1 Std. 5 Min.")!!, 0.0)
        assertEquals(7200.0, MapsParser.duration("2 Std.")!!, 0.0)
        assertNull(MapsParser.duration("12:36 AM ETA"))
    }

    @Test fun summaryLine() {
        assertEquals(600.0 to 3200.0, MapsParser.summary("10 min · 3.2 km · 12:36 AM ETA"))
        assertEquals(3900.0 to 85000.0, MapsParser.summary("1 Std. 5 Min. · 85 km · Ankunft 17:42"))
        assertEquals(null to null, MapsParser.summary("Ankunft 17:42"))
    }

    @Test fun classicCardWithAKnownArrow() {
        val right = IconTable.Entry("turn", "right", null, IntArray(Fingerprint.SIZE * Fingerprint.SIZE))
        val g = MapsParser.parse(MapsParser.Fields("350 m", "Hauptstraße", "12 min · 8,3 km · 17:42 Ankunft"), right)!!
        assertEquals(Guidance("google_maps", "turn", "right", null, 350.0, "Hauptstraße", null, 8300.0, 720.0), g)
    }

    @Test fun unknownArrowStillGivesDistanceAndStreet() {
        val g = MapsParser.parse(MapsParser.Fields("70 m", "Ringstraße", null), null)!!
        assertEquals("unknown", g.maneuver)
        assertEquals(70.0, g.distanceM!!, 0.0)
        assertEquals("Ringstraße", g.street)
        assertNull(g.text)
    }

    @Test fun anotherLayoutFallsBackToTheAppsText() {
        val g = MapsParser.parse(MapsParser.Fields("Route wird neu berechnet", null, null), null)!!
        assertEquals("unknown", g.maneuver)
        assertNull(g.distanceM)
        assertEquals("Route wird neu berechnet", g.text)
        assertNull(MapsParser.parse(MapsParser.Fields(null, " ", null), null))
    }
}
