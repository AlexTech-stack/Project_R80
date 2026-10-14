package de.r80.companion

import android.os.Handler
import android.os.Looper

/**
 * What the parts of the app share, in one process: the guidance the notification
 * listener read last, and the link's status. Listeners are called on the main thread.
 */
object AppState {
    @Volatile var guidance: Guidance? = null
        private set
    @Volatile var link: Link.Status = Link.Status(Link.State.STOPPED)
        private set
    /** Raw fields of the last Google Maps navigation notification, for the screen. */
    @Volatile var lastRaw: String = ""
        private set

    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableSetOf<() -> Unit>()

    fun setGuidance(g: Guidance?, raw: String) {
        guidance = g
        lastRaw = raw
        notifyAll()
    }

    fun setLink(s: Link.Status) {
        link = s
        notifyAll()
    }

    fun listen(l: () -> Unit) = synchronized(listeners) { listeners += l }
    fun unlisten(l: () -> Unit) = synchronized(listeners) { listeners -= l }

    private fun notifyAll() {
        val ls = synchronized(listeners) { listeners.toList() }
        main.post { ls.forEach { it() } }
    }
}
