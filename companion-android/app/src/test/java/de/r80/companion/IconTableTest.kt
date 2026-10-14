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

    @Test fun sameArrowAtAnotherSizeAndPaddingMatches() {
        val small = Fingerprint.of(arrow(40, 40, 3, 2), 40, 40)!!
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

    @Test fun tableFromJson() {
        val fp = Fingerprint.of(arrow(40, 40, 3, 2), 40, 40)!!
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
