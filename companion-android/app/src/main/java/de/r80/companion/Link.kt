package de.r80.companion

import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/** A byte stream to the HU. TCP for development (navd --tcp); Bluetooth RFCOMM later. */
interface Transport : Closeable {
    val description: String
    /** Connects; throws on failure. */
    fun open(): Pair<InputStream, OutputStream>
}

class TcpTransport(private val host: String, private val port: Int) : Transport {
    private var socket: Socket? = null
    override val description = "$host:$port (TCP)"
    override fun open(): Pair<InputStream, OutputStream> {
        val s = Socket()
        s.connect(InetSocketAddress(host, port), 3000)
        s.tcpNoDelay = true
        socket = s
        return s.getInputStream() to s.getOutputStream()
    }
    override fun close() {
        try { socket?.close() } catch (_: Exception) {}
    }
}

/**
 * The phone's side of a companion link session (docs/companion-protocol.md, "Session"):
 * connect, hello, wait for the HU's hello, send the current guidance, keep the link alive
 * with heartbeats, notice a silent HU after 3 x heartbeat_s, reconnect. Runs on its own
 * threads; [update] may be called from anywhere.
 */
class Link(
    private val transports: () -> Transport,
    private val device: String?,
    private val version: String,
    private val onStatus: (Status) -> Unit,
    private val clock: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    enum class State { STOPPED, CONNECTING, CONNECTED, WAITING }
    data class Status(val state: State, val detail: String = "")

    @Volatile private var running = false
    @Volatile private var current: Guidance? = null
    @Volatile private var transport: Transport? = null
    private val outbox = LinkedBlockingQueue<String>()
    private var thread: Thread? = null

    fun start() {
        if (running) return
        running = true
        thread = Thread(::loop, "r80-link").apply { isDaemon = true; start() }
    }

    /** Ends the link; an open session still says bye to the HU. */
    fun stop() {
        running = false
        thread?.interrupt()
    }

    /** The guidance to show; sent when it changed and again after every reconnect. */
    fun update(g: Guidance?) {
        if (g == current) return
        current = g
        outbox.put(Protocol.guidance(g))
    }

    private fun loop() {
        var backoffMs = 1000L
        while (running) {
            val t = transports()
            transport = t
            onStatus(Status(State.CONNECTING, t.description))
            try {
                session(t)
                backoffMs = 1000L
            } catch (e: Exception) {
                if (running) onStatus(Status(State.WAITING, "${t.description}: ${e.message ?: e.javaClass.simpleName}"))
            } finally {
                t.close()
            }
            if (!running) break
            try { Thread.sleep(backoffMs) } catch (_: InterruptedException) {}
            backoffMs = (backoffMs * 2).coerceAtMost(10_000L)
        }
        onStatus(Status(State.STOPPED))
    }

    private fun session(t: Transport) {
        val (input, output) = t.open()
        val incoming = LinkedBlockingQueue<Protocol.HuMessage>()
        val lastRx = AtomicLong(clock())
        val reader = Thread({
            try {
                val reader = LineReader(input)
                while (true) {
                    val line = reader.next() ?: break
                    lastRx.set(clock())
                    Protocol.parse(line)?.let { incoming.put(it) }
                }
            } catch (_: Exception) {
            }
            incoming.put(Protocol.HuMessage.Bye("link closed"))
        }, "r80-link-reader").apply { isDaemon = true; start() }

        fun send(s: String) {
            output.write(s.toByteArray(Charsets.UTF_8))
            output.flush()
        }
        try {
            send(Protocol.hello("r80-companion", version, device, listOf("guidance")))
            val hello = incoming.poll(5, TimeUnit.SECONDS) ?: throw IllegalStateException("no hello from the HU")
            if (hello is Protocol.HuMessage.Bye) throw IllegalStateException("refused: ${hello.reason}")
            if (hello !is Protocol.HuMessage.Hello) throw IllegalStateException("HU did not start with hello")
            if (hello.proto != Protocol.VERSION) throw IllegalStateException("HU speaks protocol ${hello.proto}")
            val heartbeatMs = ((hello.heartbeatS ?: 2.0) * 1000).toLong()
            outbox.clear()
            send(Protocol.guidance(current))
            var lastTx = clock()
            onStatus(Status(State.CONNECTED, t.description))
            while (running) {
                val msg = try {
                    outbox.poll(heartbeatMs / 4, TimeUnit.MILLISECONDS)
                } catch (_: InterruptedException) {
                    null    // stop(): the loop ends and says bye
                }
                if (msg != null) {
                    send(msg)
                    lastTx = clock()
                } else if (clock() - lastTx >= heartbeatMs) {
                    send(Protocol.heartbeat())
                    lastTx = clock()
                }
                when (val m = incoming.poll()) {
                    is Protocol.HuMessage.Bye -> throw IllegalStateException("HU closed the link (${m.reason ?: "no reason"})")
                    else -> {}
                }
                if (clock() - lastRx.get() > 3 * heartbeatMs) throw IllegalStateException("HU silent")
            }
            send(Protocol.bye("user"))
        } finally {
            reader.interrupt()
        }
    }
}

/** Splits a byte stream into lines; drops lines longer than Protocol.MAX_LINE. */
class LineReader(private val input: InputStream) {
    private val buf = ByteArrayOutputStream()
    private var overlong = false

    fun next(): String? {
        while (true) {
            val b = input.read()
            if (b < 0) return null
            if (b == '\n'.code) {
                val bytes = buf.toByteArray()
                buf.reset()
                if (overlong) { overlong = false; continue }
                return String(bytes, Charsets.UTF_8).trimEnd('\r')
            }
            if (!overlong) {
                buf.write(b)
                if (buf.size() > Protocol.MAX_LINE) { overlong = true; buf.reset() }
            }
        }
    }
}
