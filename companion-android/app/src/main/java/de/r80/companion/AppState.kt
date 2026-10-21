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
    /** The weather and the position last sent to the HU (Surroundings), for the screen. */
    @Volatile var weather: Weather? = null
        private set
    @Volatile var position: Position? = null
        private set
    /** Raw fields of the last Google Maps navigation notification, for the screen. */
    @Volatile var lastRaw: String = ""
        private set

    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableSetOf<() -> Unit>()

    fun setGuidance(g: Guidance?, raw: String) {
        guidance = g
        lastRaw = raw
        fire()
    }

    /** The remote: what plays on the HU, the last browse page, and the way to send commands (LinkService). */
    @Volatile var media: MediaState? = null
        private set
    @Volatile var browsed: BrowseResult? = null
        private set
    @Volatile var sender: ((String) -> Unit)? = null
    fun setMedia(m: MediaState?) { media = m; fire() }
    fun setBrowsed(b: BrowseResult) { browsed = b; fire() }
    /** Sends a remote command / browse request to the HU (dropped without a link). */
    fun send(line: String) { sender?.invoke(line) }

    fun setWeather(w: Weather) { weather = w; fire() }
    /** CarStore changed (a car_status or the parking position). */
    fun carChanged() = fire()
    fun setPosition(p: Position) { position = p; fire() }

    fun setLink(s: Link.Status) {
        link = s
        fire()
    }

    fun listen(l: () -> Unit) = synchronized(listeners) { listeners += l }
    fun unlisten(l: () -> Unit) = synchronized(listeners) { listeners -= l }

    private fun fire() {
        val ls = synchronized(listeners) { listeners.toList() }
        main.post { ls.forEach { it() } }
    }
}
