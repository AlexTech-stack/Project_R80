package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.InputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** The phone's session logic against a fake HU on a local TCP socket. */
class LinkTest {
    private class FakeHu(heartbeatS: Double = 0.2) : AutoCloseable {
        val server = ServerSocket(0)
        val lines = LinkedBlockingQueue<String>()
        @Volatile var socket: Socket? = null
        private val hello = """{"type":"hello","proto":1,"app":"r80-hu","version":"t","caps":[],"heartbeat_s":$heartbeatS}""" + "\n"

        init {
            Thread {
                while (!server.isClosed) {
                    val s = try { server.accept() } catch (_: Exception) { break }
                    socket = s
                    Thread { read(s.getInputStream(), s) }.apply { isDaemon = true; start() }
                }
            }.apply { isDaemon = true; start() }
        }

        private fun read(input: InputStream, s: Socket) {
            val r = LineReader(input)
            while (true) {
                val line = try { r.next() } catch (_: Exception) { null } ?: break
                lines.put(line)
                if (line.contains("\"type\":\"hello\"")) s.getOutputStream().write(hello.toByteArray())
            }
        }

        fun next(type: String, timeoutMs: Long = 3000): String {
            val end = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < end) {
                val l = lines.poll(50, TimeUnit.MILLISECONDS) ?: continue
                if (l.contains("\"type\":\"$type\"")) return l
            }
            throw AssertionError("no $type within $timeoutMs ms")
        }

        override fun close() = server.close()
    }

    private fun link(hu: FakeHu, status: MutableList<Link.State>) =
        Link({ TcpTransport("127.0.0.1", hu.server.localPort) }, "Test phone", "t", { synchronized(status) { status += it.state } })

    @Test fun helloGuidanceHeartbeatBye() = FakeHu().use { hu ->
        val states = mutableListOf<Link.State>()
        val link = link(hu, states)
        link.update(Guidance("google_maps", "turn", "right", distanceM = 300.0))
        link.start()
        assertTrue(hu.next("hello").contains("\"device\":\"Test phone\""))
        assertTrue("current guidance right after hello", hu.next("guidance").contains("\"modifier\":\"right\""))
        link.update(Guidance("google_maps", "turn", "right", distanceM = 300.0))     // unchanged: not sent again
        link.update(null)
        assertTrue(hu.next("guidance").contains("\"active\":false"))
        hu.next("heartbeat", 1000)                                                    // HU asked for 0.2 s
        link.stop()
        hu.next("bye")
        Thread.sleep(300)
        synchronized(states) { assertEquals(listOf(Link.State.CONNECTING, Link.State.CONNECTED, Link.State.STOPPED), states) }
    }

    @Test fun reconnectsAndResendsTheCurrentGuidance() = FakeHu().use { hu ->
        val link = link(hu, mutableListOf())
        link.update(Guidance("google_maps", "roundabout", exit = 2))
        link.start()
        hu.next("hello")
        hu.next("guidance")
        hu.socket!!.close()                                                            // HU goes away
        hu.next("hello", 5000)                                                         // back after the backoff
        assertTrue(hu.next("guidance").contains("\"exit\":2"))
        link.stop()
    }
}
