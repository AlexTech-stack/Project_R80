package de.r80.companion

import java.security.MessageDigest

/** An update file of the HU software (r80-hu-<version>.r80u from the project's releases). */
class UpdateFile(val version: String, val bytes: ByteArray) {
    val sha256: String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    val size: Long get() = bytes.size.toLong()
}

/** What the screen shows about the HU's software and an update on its way. */
data class UpdateProgress(
    val huVersion: String = "",
    val huPending: String = "",
    val state: String = "",
    val message: String = "",
    /** The version this phone brings (downloaded), "" = none. */
    val offering: String = "",
    val sent: Long = 0,
    val size: Long = 0,
)

/**
 * Brings an update file to the HU over the link (docs/companion-protocol.md, software updates):
 * offers it when the HU runs and waits for something older, then sends it in pieces, at most
 * [Protocol.UPDATE_WINDOW] before an update_ack, from where the HU says (a transfer that broke
 * off goes on). The HU checks and installs it; this only reports what it hears. Offered once per
 * connection. No Android here: the link calls it on its thread, tests call it directly.
 */
class UpdateSender(private val onProgress: (UpdateProgress) -> Unit = {}) {
    @Volatile private var file: UpdateFile? = null
    private var hu: UpdateStatus? = null
    private var id = 0
    private var offered = false            // this connection: offered once (refused, done or failed)
    private var active = false             // an offer is out
    private var streaming = false          // the HU said receiving: send pieces
    private var doneSent = false
    private var sent = 0L
    private var acked = 0L

    /** Sending now (the link then polls faster). */
    val busy: Boolean get() = streaming

    /** A newly downloaded file (or none); offered at the next chance. */
    fun setFile(f: UpdateFile?) {
        if (f?.version != file?.version) offered = false
        file = f
        report()
    }

    /** A new connection: nothing offered on it yet. */
    fun reset() {
        hu = null
        offered = false
        active = false
        streaming = false
        doneSent = false
        report()
    }

    /** The HU's update_status; returns lines to send. */
    fun onStatus(st: UpdateStatus): List<String> {
        hu = st
        when {
            active && st.state == "receiving" && st.id == id -> {
                streaming = true
                sent = st.received ?: 0
                acked = sent
            }
            active && (st.state == "refused" || (st.state == "failed" && !doneSent)) -> stopOffer()
            doneSent && st.state in setOf("ready", "failed") -> stopOffer()
        }
        report()
        return offerIfDue()
    }

    fun onAck(ackId: Int, received: Long) {
        if (ackId != id || !streaming) return
        acked = received
        report()
    }

    /** The next pieces (and update_done once all are acknowledged), or an offer that is due now. */
    fun pump(): List<String> {
        val f = file
        if (!streaming || f == null) return offerIfDue()
        val out = mutableListOf<String>()
        while (sent < f.size && sent - acked < Protocol.UPDATE_WINDOW * Protocol.MAX_CHUNK) {
            val n = minOf(Protocol.MAX_CHUNK.toLong(), f.size - sent).toInt()
            out += Protocol.updateChunk(id, sent, f.bytes.copyOfRange(sent.toInt(), sent.toInt() + n))
            sent += n
        }
        if (acked >= f.size && !doneSent) {
            out += Protocol.updateDone(id)
            doneSent = true
            streaming = false
        }
        return out
    }

    private fun stopOffer() {
        active = false
        streaming = false
        doneSent = false
        offered = true
    }

    private fun offerIfDue(): List<String> {
        val f = file ?: return emptyList()
        val st = hu ?: return emptyList()
        if (active || offered || st.state in setOf("receiving", "checking", "unpacking")) return emptyList()
        if (!Versions.newer(f.version, st.version)) return emptyList()
        if (st.pending.isNotEmpty() && !Versions.newer(f.version, st.pending)) return emptyList()
        id += 1
        active = true
        sent = 0
        acked = 0
        report()
        return listOf(Protocol.updateOffer(id, f.version, f.size, f.sha256))
    }

    private fun report() {
        val st = hu
        onProgress(UpdateProgress(st?.version ?: "", st?.pending ?: "", st?.state ?: "", st?.message ?: "",
            file?.version ?: "", if (streaming || doneSent) acked else 0, file?.size ?: 0))
    }
}
