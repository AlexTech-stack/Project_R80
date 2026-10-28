package de.r80.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phone's side of a software update (UpdateSender, Versions) against a HU played here. */
class UpdateSenderTest {
    private val file = UpdateFile("0.2.0", ByteArray(5 * Protocol.MAX_CHUNK + 100) { (it % 251).toByte() })

    private fun type(line: String) = Json.parseToJsonElement(line).jsonObject["type"]!!.jsonPrimitive.content
    private fun field(line: String, k: String) = Json.parseToJsonElement(line).jsonObject[k]!!.jsonPrimitive

    @Test fun versionsSortLikeTheHu() {
        val order = listOf("0.1.0-dev.2+a", "0.1.0-dev.10+b", "0.1.0", "0.1.1", "0.2.0-rc.1", "0.2.0", "0.10.0", "1.0.0")
        assertEquals(order, order.shuffled(java.util.Random(4)).sortedWith { a, b -> Versions.compare(a, b)!! })
        assertTrue(Versions.newer("0.1.0", "2cfdfdd"))          // a development build runs: any version is newer
        assertTrue(!Versions.newer("0.1.0", "0.1.0") && !Versions.newer("main", "0.1.0"))
    }

    @Test fun offersSendsAndFinishes() {
        val s = UpdateSender()
        s.setFile(file)
        val offer = s.onStatus(UpdateStatus("0.1.0", "", "idle", ""))
        assertEquals(listOf("update_offer"), offer.map(::type))
        val id = field(offer[0], "id").int
        assertEquals(file.sha256, field(offer[0], "sha256").content)
        assertTrue(s.pump().isEmpty())                                   // not before the HU says receiving
        s.onStatus(UpdateStatus("0.1.0", "", "receiving", "", id, 0))
        val first = s.pump()
        assertEquals(minOf(Protocol.UPDATE_WINDOW, 6), first.size)        // the window, at most
        var acked = 0L
        val got = mutableListOf<ByteArray>()
        var lines = first
        while (lines.isNotEmpty() && type(lines.last()) != "update_done") {
            for (l in lines.filter { type(it) == "update_chunk" }) {
                assertEquals(acked, field(l, "offset").long)
                val data = java.util.Base64.getDecoder().decode(field(l, "data").content)
                got += data
                acked += data.size
                s.onAck(id, acked)
            }
            lines = s.pump()
        }
        assertEquals("update_done", type(lines.last()))
        assertTrue(got.fold(ByteArray(0)) { a, b -> a + b }.contentEquals(file.bytes))
        assertTrue(s.onStatus(UpdateStatus("0.1.0", "0.2.0", "ready", "")).isEmpty())   // done: not offered again
        assertTrue(s.pump().isEmpty())
    }

    @Test fun goesOnWhereTheHuSays() {
        val s = UpdateSender()
        s.setFile(file)
        val id = field(s.onStatus(UpdateStatus("0.1.0", "", "idle", ""))[0], "id").int
        s.onStatus(UpdateStatus("0.1.0", "", "receiving", "", id, 4L * Protocol.MAX_CHUNK))
        assertEquals(4L * Protocol.MAX_CHUNK, field(s.pump()[0], "offset").long)
    }

    @Test fun offersOnlyWhatIsNewer() {
        val s = UpdateSender()
        s.setFile(file)
        assertTrue(s.onStatus(UpdateStatus("0.2.0", "", "idle", "")).isEmpty())          // runs it already
        s.reset()
        assertTrue(s.onStatus(UpdateStatus("0.1.0", "0.2.0", "ready", "")).isEmpty())    // waits for its start
        s.reset()
        val offer = s.onStatus(UpdateStatus("0.1.0", "", "idle", ""))
        assertEquals(1, offer.size)
        assertTrue(s.onStatus(UpdateStatus("0.1.0", "", "refused", "busy")).isEmpty())  // refused: once per connection
        s.reset()
        assertEquals(1, s.onStatus(UpdateStatus("0.1.0", "", "idle", "")).size)          // the next connection: again
    }
}
