package de.r80.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

/** The phone's protocol side against docs/companion-protocol-examples.jsonl, which the
 *  HU side (hu/companion_link.py, BoAt TC_HU_020) checks too. */
class ProtocolTest {
    private val examples: List<String> = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "docs/companion-protocol-examples.jsonl") }
        .first { it.exists() }
        .readLines().filter { it.isNotBlank() }

    /** Same JSON, numbers compared by value (350 == 350.0). */
    private fun same(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.keys.all { same(a[it]!!, b[it]!!) }
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
        a is JsonPrimitive && b is JsonPrimitive && !a.isString && !b.isString && a.doubleOrNull != null ->
            a.doubleOrNull == b.doubleOrNull
        else -> a == b
    }

    private fun assertSameJson(expected: String, actual: String) {
        assertTrue("line ends with \\n", actual.endsWith("\n"))
        val e = Json.parseToJsonElement(expected)
        val a = Json.parseToJsonElement(actual)
        assertTrue("expected $e\n     got $a", same(e, a))
    }

    @Test fun buildersWriteTheSharedExamples() {
        val ours = mapOf(
            0 to Protocol.hello("r80-companion", "0.1.0", "Redmi Note 12 Pro 5G", listOf("guidance")),
            2 to Protocol.heartbeat(),
            3 to Protocol.guidance(Guidance("google_maps", "turn", "right", distanceM = 350.0, street = "Hauptstraße",
                remainingM = 8300.0, remainingS = 720.0)),
            4 to Protocol.guidance(Guidance("google_maps", "roundabout", exit = 2, distanceM = 120.0, street = "B27",
                remainingM = 7900.0, remainingS = 680.0)),
            5 to Protocol.guidance(Guidance("google_maps", "unknown", distanceM = 70.0, street = "Ringstraße", text = "Ringstraße")),
            6 to Protocol.guidance(null),
            7 to Protocol.bye("user"),
            9 to Protocol.weather(Weather("open-meteo", 1792584000, 11.4, 2, listOf(
                Weather.Day("2026-10-21", 3, 13.1, 5.8), Weather.Day("2026-10-22", 61, 10.2, 4.9),
                Weather.Day("2026-10-23", 0, 12.7, -1.5), Weather.Day("2026-10-24", 71, 2.0, -3.2)))),
            10 to Protocol.position(Position(1792584060, altM = 412.3, accuracyM = 6.0, headingDeg = 271.5)),
            11 to Protocol.position(Position(1792584120)),
            12 to Protocol.hello("r80-companion", "0.2.0", "Redmi Note 12 Pro 5G", Link.CAPS),
            16 to Protocol.mediaCmd("next"),
            17 to Protocol.mediaCmd("volume", 16),
            18 to Protocol.mediaCmd("seek", 90.5),
            19 to Protocol.mediaCmd("play_from", path = "albums/Kilometer%20Null", index = 2),
            20 to Protocol.browse(7, "albums"),
            23 to Protocol.updateOffer(1, "0.2.0", 368640,
                "5f0c6a1c3d2b4e8f9a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f"),
            25 to Protocol.updateChunk(1, 0, "r80-hu update".toByteArray()),
            27 to Protocol.updateDone(1),
        )
        for ((i, line) in ours) assertSameJson(examples[i], line)
    }

    @Test fun readsTheHusMessages() {
        assertEquals(Protocol.HuMessage.Hello(1, 2.0), Protocol.parse(examples[1]))
        assertEquals(Protocol.HuMessage.Heartbeat, Protocol.parse(examples[2]))
        assertEquals(Protocol.HuMessage.Bye("user"), Protocol.parse(examples[7]))
        assertEquals(Protocol.HuMessage.Hello(1, 2.0, listOf("weather", "position")), Protocol.parse(examples[8]))
        assertEquals(Protocol.HuMessage.Status(CarStatus(1792590000, false, 62.5, 471.0, 187432.4, 14.2, -3.5, 6400.0, 112.0,
            CarStatus.Trip(43.7, 52.0, 50.0), emptyList(), "signal_red")), Protocol.parse(examples[13]))
        assertEquals(Protocol.HuMessage.Status(CarStatus(1792593600, true, fuelPct = 8.0, rangeKm = 60.0, serviceKm = -150.0,
            warnings = listOf(CarStatus.Warning("information", "Fuel low (8 %)"), CarStatus.Warning("notice", "Service overdue by 150 km")))),
            Protocol.parse(examples[14]))
        assertNull(Protocol.parse("""{"type":"car_status","final":true}"""))
        assertEquals(Protocol.HuMessage.Media(MediaState(true, "playing", "Library", listOf("Library", "USB"), "Night Drive",
            "Neon Autobahn", "Kilometer Null", 241.0, 37.5, 1792590000.25, false, true, 1, 6, "All tracks",
            listOf("Red Horizon" to "The Quattro Lines"), 14, 30, false)), Protocol.parse(examples[15]))
        assertEquals(Protocol.HuMessage.Browsed(BrowseResult(7, "albums", "Albums", 2, 0, listOf(
            BrowseResult.Entry("album", "albums/Kilometer%20Null", "Kilometer Null", "Neon Autobahn", -1),
            BrowseResult.Entry("album", "albums/V8%20Sessions", "V8 Sessions", "The Quattro Lines", -1)))), Protocol.parse(examples[21]))
        assertNull(Protocol.parse("""{"type":"media","status":"flying"}"""))
        assertEquals(Protocol.HuMessage.Update(UpdateStatus("0.1.0", "", "idle", "")), Protocol.parse(examples[22]))
        assertEquals(Protocol.HuMessage.Update(UpdateStatus("0.1.0", "", "receiving", "", 1, 0)), Protocol.parse(examples[24]))
        assertEquals(Protocol.HuMessage.UpdateAck(1, 13), Protocol.parse(examples[26]))
        assertEquals(Protocol.HuMessage.Update(UpdateStatus("0.1.0", "0.2.0", "ready", "0.2.0 starts with the next start of the HU")),
            Protocol.parse(examples[28]))
        assertNull(Protocol.parse("""{"type":"update_status","version":"0.1.0","state":"flying"}"""))
        assertEquals(Protocol.HuMessage.Unknown, Protocol.parse("""{"type":"lanes","lanes":[]}"""))
        assertNull(Protocol.parse("not json"))
        assertNull(Protocol.parse("""{"no":"type"}"""))
        assertNull(Protocol.parse("""{"type":"hello","app":"r80-hu"}"""))
    }

    @Test fun guidanceRejectsWhatTheHuWouldDrop() {
        for (bad in listOf({ Guidance("x", "jump") }, { Guidance("x", "turn", "up") }, { Guidance("x", "roundabout", exit = 0) },
                           { Protocol.guidance(Guidance("x", "turn", distanceM = -1.0)) },
                           { Protocol.guidance(Guidance("x", "turn", distanceM = Double.NaN)) })) {
            try { bad(); throw AssertionError("accepted") } catch (_: IllegalArgumentException) {}
        }
    }

    @Test fun weatherAndPositionRejectWhatTheHuWouldDrop() {
        for (bad in listOf({ Weather("x", 1, Double.NaN, 1) }, { Weather("x", 1, 5.0, 100) },
                           { Weather.Day("21.10.2026", 1, 1.0, 0.0) }, { Position(1, altM = 9500.0) },
                           { Position(1, headingDeg = 400.0) }, { Protocol.position(Position(1, accuracyM = -2.0)) })) {
            try { bad(); throw AssertionError("accepted") } catch (_: IllegalArgumentException) {}
        }
    }

    @Test fun positionRunsOnWhilePlaying() {
        val m = MediaState(true, "playing", "", emptyList(), "", "", "", 100.0, 10.0, 1000.0, false, false, null, null, "",
            emptyList(), null, null, false)
        assertEquals(15.0, m.positionAt(1005.0)!!, 1e-9)
        assertEquals(100.0, m.positionAt(2000.0)!!, 1e-9)                 // not past the end
        assertEquals(10.0, m.copy(status = "paused").positionAt(1005.0)!!, 1e-9)
    }

    @Test fun stringsAreCut() {
        val o = Json.parseToJsonElement(Protocol.guidance(Guidance("x", "turn", street = "S".repeat(500)))) as JsonObject
        assertEquals(Protocol.MAX_TEXT, (o["street"] as JsonPrimitive).content.length)
    }

    @Test fun lineReaderSplitsAndDropsOverlongLines() {
        val long = "x".repeat(Protocol.MAX_LINE + 10)
        val r = LineReader(ByteArrayInputStream("a\r\nb\n$long\nc\n".toByteArray()))
        assertEquals(listOf("a", "b", "c"), generateSequence { r.next() }.toList())
        val utf = LineReader(ByteArrayInputStream("Hauptstraße\n".toByteArray()))
        assertEquals("Hauptstraße", utf.next())
    }
}
