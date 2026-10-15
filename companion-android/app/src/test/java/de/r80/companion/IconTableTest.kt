package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class IconTableTest {
    /** An "L"-shaped right-turn arrow body in a w x h image with padding, scaled by s. */
    private fun arrow(w: Int, h: Int, pad: Int, s: Int, mirror: Boolean = false): IntArray {
        val a = IntArray(w * h)
        fun set(x: Int, y: Int) {
            val xx = if (mirror) w - 1 - x else x
            if (xx in 0 until w && y in 0 until h) a[y * w + xx] = 255
        }
        for (i in 0 until 10 * s) for (t in 0 until 2 * s) set(pad + t, pad + 4 * s + i)          // stem
        for (i in 0 until 8 * s) for (t in 0 until 2 * s) set(pad + i, pad + 4 * s + t)           // bar to the right
        for (i in 0 until 4 * s) for (t in 0 until s) { set(pad + 6 * s + i, pad + 4 * s - i + t); set(pad + 6 * s + i, pad + 5 * s + i + t) }
        return a
    }

    /** Real notification arrows are 72 px and more (density dependent); 16 x 16 cells resolve them. */
    @Test fun sameArrowAtAnotherSizeAndPaddingMatches() {
        val small = Fingerprint.of(arrow(80, 80, 10, 4), 80, 80)!!
        val big = Fingerprint.of(arrow(120, 120, 20, 6), 120, 120)!!
        val mirrored = Fingerprint.of(arrow(120, 120, 20, 6, mirror = true), 120, 120)!!
        val same = Fingerprint.distance(small, big)
        val other = Fingerprint.distance(small, mirrored)
        assertTrue("same arrow: $same", same < 0.08)
        assertTrue("mirrored arrow: $other", other > 0.15)

        val table = IconTable(listOf(IconTable.Entry("turn", "right", null, small)))
        assertEquals("right", table.match(big)?.modifier)
        assertNull(table.match(mirrored))
        assertNull(Fingerprint.of(IntArray(100), 10, 10))
    }

    /** The shipped table (assets/maneuver_icons.json, from captured Google Maps drives). */
    @Test fun shippedTableIsConsistent() {
        val file = java.io.File("src/main/assets/maneuver_icons.json")
        val raw = kotlinx.serialization.json.Json.parseToJsonElement(file.readText())
            .let { it as kotlinx.serialization.json.JsonObject }["icons"] as kotlinx.serialization.json.JsonArray
        val table = IconTable.parse(file.readText())
        assertEquals("every entry valid", raw.size, table.entries.size)
        val sha1 = java.security.MessageDigest.getInstance("SHA-1")
        for (e in table.entries) {
            val id = sha1.digest(Fingerprint.toHex(e.fp).toByteArray()).joinToString("") { "%02x".format(it) }.take(12)
            assertEquals("id matches the fingerprint", id, e.id)
            assertEquals("${e.id} recognises itself", e, table.match(e.fp))
        }
        // Different meanings must not be confusable; the only close pair is "head toward"
        // (dashed) vs "straight on": both straight arrows.
        val close = mutableListOf<String>()
        for ((i, a) in table.entries.withIndex()) for (b in table.entries.drop(i + 1)) {
            if (Fingerprint.distance(a.fp, b.fp) <= 0.08 && (a.maneuver to a.modifier) != (b.maneuver to b.modifier))
                close += setOf(a.maneuver, b.maneuver).sorted().joinToString("/") + " " + a.modifier
        }
        assertEquals(listOf("continue/depart straight"), close)
    }

    @Test fun tableFromJson() {
        val fp = Fingerprint.of(arrow(80, 80, 10, 4), 80, 80)!!
        val hex = Fingerprint.toHex(fp)
        assertEquals(fp.toList(), Fingerprint.fromHex(hex)!!.toList())
        val t = IconTable.parse("""{"icons": [
            {"maneuver": "turn", "modifier": "right", "fp": "$hex", "note": "test"},
            {"maneuver": "jump", "fp": "$hex"},
            {"maneuver": "turn", "fp": "short"}]}""")
        assertEquals(1, t.entries.size)
        assertNotNull(t.match(fp))
        assertEquals(0, IconTable.parse("""{"icons": []}""").entries.size)
    }
}
