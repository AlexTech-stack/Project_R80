package de.r80.companion

import android.app.Activity
import android.content.res.ColorStateList
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView

/**
 * The remote (a passenger with the driver's phone): what plays on the HU and its volume,
 * laid out like the HU's Media screen, and the HU's browse tree (docs/companion-protocol.md:
 * media, media_cmd, browse). Built from AppState; [tick] moves the position on every second.
 */
class RemotePage(private val a: Activity) {
    val view = ScrollView(a)
    private var browsing = false
    private val stack = ArrayDeque<String>()            // the browse paths above the current one
    private var path = ""
    private var nextId = 1
    private var waiting = 0                             // the id of the page asked for
    private val entries = mutableListOf<BrowseResult.Entry>()
    private var listTitle = ""
    private var total = 0
    private var shownBrowse: BrowseResult? = null
    private var position: TextView? = null
    private var seek: SeekBar? = null
    private var dragging = false

    private fun dp(v: Float) = Hu.dp(a, v)
    private fun send(line: String) = AppState.send(line)
    private fun cmd(c: String, value: Any? = null) = send(Protocol.mediaCmd(c, value))

    fun show() {
        if (dragging) return                            // a rebuild would end the drag on the seek bar
        AppState.browsed?.let { if (it.id == waiting && it !== shownBrowse) take(it) }
        view.removeAllViews()
        view.addView(LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20f), dp(12f), dp(20f), dp(24f))
            val m = AppState.media
            when {
                AppState.link.state != Link.State.CONNECTED -> addView(Hu.text(a, a.getString(R.string.remote_no_link), 16f, Hu.mid))
                m == null -> addView(Hu.text(a, a.getString(R.string.remote_no_media), 16f, Hu.mid))
                browsing -> browse(this, m)
                else -> nowPlaying(this, m)
            }
        })
    }

    /** Every second: the position runs on while playing. */
    fun tick() {
        val m = AppState.media ?: return
        val pos = m.positionAt(System.currentTimeMillis() / 1000.0) ?: return
        position?.text = "${clock(pos)}  /  ${m.durationS?.let { clock(it) } ?: "–"}"
        if (!dragging) seek?.progress = pos.toInt()
    }

    // ---- now playing ------------------------------------------------------------
    private fun nowPlaying(col: LinearLayout, m: MediaState) {
        val ok = m.allowed
        if (!ok) col.addView(Hu.text(a, a.getString(R.string.remote_not_allowed), 14f).apply {
            setPadding(0, 0, 0, dp(12f))
        })
        if (m.sources.size > 1) col.addView(Hu.tabs(a, m.sources, m.sources.indexOf(m.source).coerceAtLeast(0)) { i ->
            if (ok && m.sources[i] != m.source) cmd("source", m.sources[i])
        }.let { tabs -> android.widget.HorizontalScrollView(a).apply { isHorizontalScrollBarEnabled = false; addView(tabs) } })

        col.addView(LinearLayout(a).apply {                       // the cover's place, and what plays
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(16f), 0, dp(8f))
            addView(FrameLayout(a).apply {
                background = android.graphics.drawable.GradientDrawable().apply { setStroke(dp(2f), Hu.accent) }
                addView(Hu.icon(a, if (m.source == "Library" || m.source == "Bluetooth") R.drawable.hu_music else R.drawable.hu_usb,
                    44f, Hu.dim).apply { layoutParams = FrameLayout.LayoutParams(dp(44f), dp(44f), Gravity.CENTER) })
                layoutParams = LinearLayout.LayoutParams(dp(104f), dp(104f))
            })
            addView(LinearLayout(a).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(18f), 0, 0, 0)
                addView(Hu.text(a, m.title.ifEmpty { "–" }, 22f).apply { maxLines = 2 })
                addView(Hu.text(a, m.artist, 16f, Hu.mid).apply { maxLines = 1 })
                addView(Hu.text(a, m.album, 14f, Hu.dim).apply { maxLines = 1 })
            })
        })

        val dur = m.durationS
        seek = SeekBar(a).apply {
            max = (dur ?: 0.0).toInt().coerceAtLeast(1)
            isEnabled = ok && dur != null && dur > 0
            progressTintList = ColorStateList.valueOf(Hu.accent)
            progressBackgroundTintList = ColorStateList.valueOf(Hu.dim)
            thumbTintList = ColorStateList.valueOf(Hu.accent)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar, p: Int, fromUser: Boolean) {}
                override fun onStartTrackingTouch(s: SeekBar) { dragging = true }
                override fun onStopTrackingTouch(s: SeekBar) { dragging = false; cmd("seek", s.progress.toDouble()) }
            })
        }
        col.addView(seek)
        position = Hu.text(a, "", 16f, Hu.mid, numbers = true).apply { gravity = Gravity.END }
        col.addView(position)
        tick()

        col.addView(LinearLayout(a).apply {                       // the controls, as on the HU
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, dp(14f), 0, dp(14f))
            fun gap() = View(a).apply { layoutParams = LinearLayout.LayoutParams(dp(14f), 1) }
            addView(Hu.roundButton(a, R.drawable.hu_shuffle, 48f, m.shuffle, ok) { cmd("shuffle", !m.shuffle) }); addView(gap())
            addView(Hu.roundButton(a, R.drawable.hu_prev, 56f, enabled = ok) { cmd("previous") }); addView(gap())
            val playing = m.status == "playing"
            addView(Hu.roundButton(a, if (playing) R.drawable.hu_pause else R.drawable.hu_play, 72f, true, ok) {
                cmd(if (playing) "pause" else "play")
            }); addView(gap())
            addView(Hu.roundButton(a, R.drawable.hu_next, 56f, enabled = ok) { cmd("next") }); addView(gap())
            addView(Hu.roundButton(a, R.drawable.hu_repeat, 48f, m.repeat, ok) { cmd("repeat", !m.repeat) })
        })

        val vol = m.volume
        val max = m.volumeMax
        if (vol != null && max != null) col.addView(LinearLayout(a).apply {     // the HU's master volume
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(6f), 0, dp(6f))
            addView(Hu.roundButton(a, if (m.muted) R.drawable.hu_mute else R.drawable.hu_speaker, 48f, m.muted, ok) {
                cmd("mute", !m.muted)
            })
            addView(Hu.text(a, a.getString(R.string.remote_volume), 16f).apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(16f) }
            })
            addView(Hu.roundButton(a, R.drawable.hu_minus, 48f, enabled = ok && vol > 0) { cmd("volume", vol - 1) })
            addView(Hu.text(a, if (m.muted) "–" else "$vol", 28f, numbers = true).apply {
                gravity = Gravity.CENTER
                layoutParams = LinearLayout.LayoutParams(dp(64f), ViewGroup.LayoutParams.WRAP_CONTENT)
            })
            addView(Hu.roundButton(a, R.drawable.hu_plus, 48f, enabled = ok && vol < max) { cmd("volume", vol + 1) })
        })

        col.addView(Hu.lineButton(a, a.getString(R.string.remote_browse), R.drawable.hu_list) {
            browsing = true; stack.clear(); open("")
        }.apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(14f) }
        })

        if (m.upNext.isNotEmpty()) {
            col.addView(Hu.text(a, a.getString(R.string.remote_up_next) + if (m.queue.isNotEmpty()) "  ·  ${m.queue}" else "",
                18f, strong = true).apply { setPadding(0, dp(24f), 0, dp(6f)) })
            for ((title, artist) in m.upNext) col.addView(LinearLayout(a).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, dp(6f), 0, dp(6f))
                addView(Hu.text(a, title, 16f).apply { maxLines = 1 })
                addView(Hu.text(a, artist, 13f, Hu.mid).apply { maxLines = 1 })
                addView(Hu.line(a))
            })
        }
    }

    // ---- browsing the HU's library ----------------------------------------------------
    private fun open(p: String) {
        path = p
        entries.clear(); listTitle = ""; total = 0
        request(0)
        show()
    }

    private fun request(offset: Int) {
        waiting = nextId++
        send(Protocol.browse(waiting, path, offset, 20))
    }

    private fun take(r: BrowseResult) {
        shownBrowse = r
        if (r.path != path) return
        listTitle = r.title
        total = r.total
        if (r.offset == entries.size) entries += r.entries
    }

    private fun browse(col: LinearLayout, m: MediaState) {
        col.addView(LinearLayout(a).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(Hu.roundButton(a, R.drawable.hu_back, 44f) {
                if (stack.isEmpty()) { browsing = false; show() } else open(stack.removeLast())
            })
            addView(Hu.text(a, listTitle.ifEmpty { m.source }, 20f).apply { setPadding(dp(16f), 0, 0, 0); maxLines = 1 })
        })
        when {
            total < 0 -> col.addView(Hu.text(a, a.getString(R.string.remote_list_gone), 15f, Hu.mid).apply { setPadding(0, dp(16f), 0, 0) })
            entries.isEmpty() -> col.addView(Hu.text(a, a.getString(R.string.remote_loading), 15f, Hu.mid).apply { setPadding(0, dp(16f), 0, 0) })
        }
        for (e in entries) col.addView(LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            addView(LinearLayout(a).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                minimumHeight = dp(56f)
                addView(Hu.icon(a, when (e.kind) {
                    "menu" -> R.drawable.hu_list; "folder" -> R.drawable.hu_folder; "artist" -> R.drawable.hu_person
                    "album" -> R.drawable.hu_disc; else -> R.drawable.hu_music
                }, 24f, Hu.mid))
                addView(LinearLayout(a).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(16f), 0, 0, 0)
                    addView(Hu.text(a, e.title, 16f).apply { maxLines = 1 })
                    if (e.subtitle.isNotEmpty()) addView(Hu.text(a, e.subtitle, 13f, Hu.mid).apply { maxLines = 1 })
                })
            })
            addView(Hu.line(a))
            isClickable = true
            setOnClickListener {
                if (e.kind == "track") {
                    if (m.allowed) send(Protocol.mediaCmd("play_from", path = path, index = e.index))
                    browsing = false; show()
                } else {
                    stack.addLast(path); open(e.id)
                }
            }
        })
        if (total > entries.size && entries.isNotEmpty()) col.addView(Hu.lineButton(a, a.getString(R.string.remote_more)) {
            request(entries.size)
        }.apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(12f) }
        })
    }

    private fun clock(s: Double): String {
        val t = s.toInt().coerceAtLeast(0)
        return "%d:%02d".format(t / 60, t % 60)
    }
}
