#!/usr/bin/env python3
"""hu-mediad: the Linux-side media service of the R80 headunit.

Plays local audio (the USB / SD-card source) with GStreamer and publishes the
playback state on D-Bus for the UI and the other services:

    bus name   de.r80.Media
    object     /de/r80/Media
    interface  de.r80.Media1
      properties  PlaybackStatus (s: playing|paused|stopped), Source (s), Gain (d),
                  Sources (as), TrackIndex (i), TrackCount (i),
                  Position (x, microseconds), Metadata (a{sv}),
                  Playlist (aa{sv}), Shuffle (b), RepeatAll (b),
                  CanGoNext (b), CanGoPrevious (b)
      methods     Play(), Pause(), PlayPause(), Next(), Previous(),
                  SetTrack(i), Seek(x offset_us), SetPosition(x pos_us),
                  SetPlaying(b), SetShuffle(b), SetRepeatAll(b),
                  SetSource(s), SetGain(d gain 0.0..1.0, u fade_ms; set by hu-audiod)
      signal      Seeked(x position)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Metadata comes from the file name (`Artist - Title.ext`, album = folder) and
the duration is learned once GStreamer has prerolled the track. Bluetooth A2DP
and MPRIS are not wired up yet; this is the local-file path from architecture
v0.3 section 4.

Runs unchanged on the bench (--system --music-dir /media/usb) and in the virtual
environment (session bus, --demo tones when there is no music yet).
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import wave
from array import array
from pathlib import Path

import dbus
import dbus.service
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import GLib, Gst, GstController  # noqa: E402

BUS_NAME = "de.r80.Media"
OBJ_PATH = "/de/r80/Media"
IFACE = "de.r80.Media1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
AUDIO_EXT = {".mp3", ".ogg", ".oga", ".flac", ".wav", ".m4a", ".aac", ".opus", ".wma"}
SOURCES = ["USB", "SD card"]


def log(*a):
    print("[mediad]", *a, flush=True)


def variant(v):
    if isinstance(v, bool):
        return dbus.Boolean(v)
    if isinstance(v, str):
        return dbus.String(v)
    if isinstance(v, int):
        return dbus.Int64(v)
    if isinstance(v, float):
        return dbus.Double(v)
    if isinstance(v, dict):
        return dbus.Dictionary({k: variant(x) for k, x in v.items()}, signature="sv")
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return dbus.Array([variant(x) for x in v], signature="a{sv}")
        if v and isinstance(v[0], str):
            return dbus.Array([dbus.String(x) for x in v], signature="s")
        return dbus.Array([variant(x) for x in v], signature="v")
    raise TypeError(type(v))


def parse_name(path: Path) -> dict:
    """Title / artist / album from the file name and its folder."""
    stem = path.stem.replace("_", " ").strip()
    artist, title = "", stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        artist, title = artist.strip(), title.strip()
    return {"title": title or path.stem, "artist": artist, "album": path.parent.name}


def _wav_rate_is(path: Path, rate: int) -> bool:
    try:
        with wave.open(str(path)) as w:
            return w.getframerate() == rate
    except (OSError, wave.Error, EOFError):
        return False


DEMO_TONES = [("Neon Autobahn", "Night Drive", 225, 24),
              ("The Quattro Lines", "Red Horizon", 315, 20),
              ("Lumen Drift", "Tunnel Vision", 175, 28),
              ("Marta Kovac", "Coastline", 245, 18)]


def only_demo_tones(music_dir: Path) -> bool:
    """True if the folder has no audio, or only (possibly older) demo tones of ours."""
    names = {f"{a} - {t}.wav" for a, t, _f, _s in DEMO_TONES}
    audio = [p for p in music_dir.rglob("*") if p.suffix.lower() in AUDIO_EXT] if music_dir.is_dir() else []
    return all(p.name in names and p.parent == music_dir for p in audio)


def make_demo(music_dir: Path, count: int = 4) -> list:
    """Write a few short WAV tones (stdlib only) so the UI has real audio.

    Fast on purpose, also on a Pi 3B or under QEMU: each frequency divides the sample
    rate, so one period is computed and repeated as bytes; only the fades are per sample.
    44.1 kHz rather than less: wavparse hands out 4 KB chunks, which at 8 kHz were 256 ms
    long and made every volume change late by up to that much.
    """
    tones = DEMO_TONES
    music_dir.mkdir(parents=True, exist_ok=True)
    made = []
    rate = 44100
    edge = rate // 10                # 0.1 s fade in / out so the tone does not click
    for artist, title, freq, secs in tones[:count]:
        f = music_dir / f"{artist} - {title}.wav"
        if not f.exists() or not _wav_rate_is(f, rate):     # also replaces older 8 kHz tones
            period = rate // freq
            one = array("h", (int(0.25 * 32767 * math.sin(2 * math.pi * k / period)) for k in range(period)))
            total = rate * secs
            samples = array("h")
            samples.frombytes((one.tobytes() * (total // period + 1))[:total * 2])
            for n in range(edge):
                samples[n] = int(samples[n] * n / edge)
                samples[total - 1 - n] = int(samples[total - 1 - n] * (n + 1) / edge)
            if sys.byteorder == "big":
                samples.byteswap()   # WAV is little-endian
            with wave.open(str(f), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(samples.tobytes())
            log(f"demo tone: {f.name}")
        made.append(f)
    return made


class Media(dbus.service.Object):
    def __init__(self, bus, music_dir: Path, sink: str | None = None, buffer_ms: int = 60):
        super().__init__(bus, OBJ_PATH)
        self.dir = music_dir
        self.tracks = self.scan()
        self.index = 0
        self.source = SOURCES[0]
        self.shuffle = False
        self.repeat_all = True
        self.status = "stopped"
        self.position = 0          # microseconds
        self.uri = ""
        self.history = []
        self.props = {}
        self.dirty = set()

        self.player = Gst.ElementFactory.make("playbin", "player")
        if self.player is None:
            raise RuntimeError("GStreamer playbin not available")
        # Playback level from hu-audiod, applied by a volume element right in front of the
        # audio sink: in playbin's audio-filter slot it ran ~1.3 s ahead of what was heard.
        # Not playbin's own volume either: that becomes the PipeWire stream volume, which
        # WirePlumber saves per application and restores for every python3 program.
        self.gain = 1.0
        self.fade_ms = 50            # ramp length, from the last SetGain (audio.ini change_fade_ms)
        self.buffer_ms = buffer_ms
        self.silenced = False        # faded out for a pause or a track change / seek
        self.fade_in_next = False    # the next new segment starts at 0 and ramps up
        self.pending = None          # timer of a fade-out in progress ...
        self.pending_actions = []    # ... and what runs once it has been heard
        self.player.set_property("audio-sink", self.make_output(sink, buffer_ms))
        # Every change is a short linear ramp, interpolated per sample, so it does not click.
        self.ramp = GstController.InterpolationControlSource()
        self.ramp.set_property("mode", GstController.InterpolationMode.LINEAR)
        self.gain_el.add_control_binding(GstController.DirectControlBinding.new_absolute(self.gain_el, "volume", self.ramp))
        self.ramp.set(0, 1.0)
        self.ramp_pts = None         # ((t0, level), (t1, level)) of the ramp now in the controller
        self.segment = None          # of the stream entering the gain element
        self.next_time = None        # stream time of the next audio it will process
        pad = self.gain_el.get_static_pad("sink")
        pad.add_probe(Gst.PadProbeType.BUFFER | Gst.PadProbeType.EVENT_DOWNSTREAM, self.on_gain_pad)
        bus_ = self.player.get_bus()
        bus_.add_signal_watch()
        bus_.connect("message", self.on_bus)

        GLib.timeout_add(100, self.flush)
        GLib.timeout_add(300, self.poll_position)
        self.refresh_props()

    # ---- output and gain --------------------------------------------------
    def make_output(self, sink: str | None, buffer_ms: int):
        out = Gst.Bin.new("output")
        self.gain_el = Gst.ElementFactory.make("volume", "gain")
        conv = Gst.ElementFactory.make("audioconvert", None)
        res = Gst.ElementFactory.make("audioresample", None)
        snk = Gst.ElementFactory.make(sink or "autoaudiosink", "sink")
        if snk is None:
            raise RuntimeError(f"GStreamer element {sink!r} not available")
        if snk.find_property("sync") is not None and sink:
            snk.set_property("sync", True)   # keep fakesink real-time for headless tests

        def small_buffer(_bin, _sub, el):
            # autoaudiosink picks its real sink only when it starts; shrink that one's buffer
            if el.find_property("buffer-time") is not None and el.find_property("latency-time") is not None:
                el.set_property("buffer-time", buffer_ms * 1000)
                el.set_property("latency-time", min(10, buffer_ms) * 1000)
        out.connect("deep-element-added", small_buffer)
        for e in (self.gain_el, conv, res, snk):
            out.add(e)
        self.gain_el.link(conv)
        conv.link(res)
        res.link(snk)
        out.add_pad(Gst.GhostPad.new("sink", self.gain_el.get_static_pad("sink")))
        return out

    def on_gain_pad(self, _pad, info):
        if info.type & Gst.PadProbeType.BUFFER:
            b = info.get_buffer()
            if b and self.segment and b.pts != Gst.CLOCK_TIME_NONE:
                end = b.pts + (b.duration if b.duration != Gst.CLOCK_TIME_NONE else 0)
                self.next_time = self.segment.to_stream_time(Gst.Format.TIME, end)
        else:
            ev = info.get_event()
            if ev and ev.type == Gst.EventType.SEGMENT:
                self.segment = ev.parse_segment()
                # new track or seek: stream times start over
                if self.fade_in_next:
                    self.fade_in_next = False
                    self.silenced = False
                    start = self.segment.time
                    self.set_ramp((start, 0.0), (start + self.fade_ms * Gst.MSECOND, self.gain))
                else:
                    self.hold_gain()
        return Gst.PadProbeReturn.OK

    def hold_gain(self):
        """Forget any ramp and play at the current target (0 while silenced) from now on."""
        self.ramp.unset_all()
        self.ramp.set(0, 0.0 if self.silenced else self.gain)
        self.ramp_pts = None
        self.next_time = None

    def set_ramp(self, a, b):
        self.ramp.unset_all()
        self.ramp.set(*a)
        self.ramp.set(*b)
        self.ramp_pts = (a, b)

    def level_at(self, t: int) -> float:
        """Gain the ramp gives at stream time t. Kept here: ControlSource.get_value() cannot
        be called from Python (PyGObject: "Interface type 2 should have is_pointer set")."""
        if not self.ramp_pts:
            return 0.0 if self.silenced else self.gain
        (t0, v0), (t1, v1) = self.ramp_pts
        if t <= t0:
            return v0
        if t >= t1:
            return v1
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    def ramp_level(self, level: float, fade_ms: int, start: float | None = None):
        """Ramp from the level now reaching the gain element (or `start`) to `level` over
        fade_ms. It starts at the next audio the element processes: what it already passed
        cannot change."""
        t0 = self.next_time
        if t0 is None or t0 == Gst.CLOCK_TIME_NONE or fade_ms <= 0:
            self.ramp.unset_all()
            self.ramp.set(0, level)
            self.ramp_pts = None
            return
        now = self.level_at(t0) if start is None else start
        self.set_ramp((t0, now), (t0 + fade_ms * Gst.MSECOND, level))

    def ramp_to(self, gain: float, fade_ms: int):
        """New target from hu-audiod. While silenced it only takes effect on the fade-in."""
        self.gain = gain
        if fade_ms > 0:
            self.fade_ms = fade_ms
        if not self.silenced:
            self.ramp_level(gain, fade_ms)

    # ---- transitions without clicks ----------------------------------------
    def fade_out_then(self, action):
        """Fade to silence, and run `action` once that silence is what is being heard
        (fade + sink buffer + a chunk). Stopping, switching or seeking mid-waveform clicks."""
        if self.pending:                         # already fading out: just queue it
            self.pending_actions.append(action)
            return
        if self.status != "playing" or self.next_time is None:
            action()                             # nothing audible to fade
            return
        self.silenced = True
        self.ramp_level(0.0, self.fade_ms)
        self.pending_actions = [action]
        self.pending = GLib.timeout_add(self.fade_ms + self.buffer_ms + 50, self.run_pending)

    def run_pending(self):
        self.pending = None
        actions, self.pending_actions = self.pending_actions, []
        for a in actions:
            a()
        return False

    def fade_in_from_silence(self):
        """Resume: what the element already passed is silent; ramp up from the next audio."""
        self.silenced = False
        self.ramp_level(self.gain, self.fade_ms, start=0.0)

    # ---- playlist --------------------------------------------------------
    def scan(self) -> list:
        if not self.dir.is_dir():
            return []
        files = sorted((p for p in self.dir.rglob("*") if p.suffix.lower() in AUDIO_EXT),
                       key=lambda p: str(p).lower())
        return [dict(path=str(p), duration=0, **parse_name(p)) for p in files]

    def metadata(self):
        if not self.tracks:
            return {"title": "", "artist": "", "album": "", "duration": 0}
        t = self.tracks[self.index]
        return {k: t[k] for k in ("title", "artist", "album", "duration")}

    # ---- GStreamer -------------------------------------------------------
    def load(self, start: bool, fade_out: bool = True):
        """Switch to self.index. The new title shows at once; the pipeline switches after
        a fade-out (not at the natural end of a track) and the new track fades in."""
        if not self.tracks:
            self.stop()
            return
        self.index = self.index % len(self.tracks)
        uri = Path(self.tracks[self.index]["path"]).as_uri()
        was_playing = self.status == "playing"
        self.position = 0
        self.refresh_props()

        def switch():
            self.uri = uri
            self.fade_in_next = True
            self.player.set_state(Gst.State.NULL)
            self.player.set_property("uri", uri)
            self.status = "playing" if start else "paused"
            self.player.set_state(Gst.State.PLAYING if start else Gst.State.PAUSED)
            self.refresh_props()
        if (fade_out and was_playing) or self.pending:
            self.fade_out_then(switch)           # queues behind a pending fade-out or stop
        else:
            switch()

    def stop(self, fade: bool = False):
        """Stop. It wins over a queued track switch (else that would start playing again);
        when stopping mid-track (fade=True) it fades out first."""
        was_playing = self.status == "playing"
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending, self.pending_actions = None, []
            fade = False                         # already faded out for the switch

        def now():
            self.player.set_state(Gst.State.NULL)
            self.silenced = False
            self.fade_in_next = False
        if fade and was_playing:
            self.fade_out_then(now)              # needs status "playing" to fade
        else:
            now()
        self.uri = ""
        self.status = "stopped"
        self.position = 0
        self.refresh_props()

    def current_time(self) -> int:
        """Playback position in microseconds."""
        ok, pos = self.player.query_position(Gst.Format.TIME)
        return int(pos // 1000) if ok and pos > 0 else 0

    def duration(self) -> int:
        """Track duration in seconds."""
        ok, dur = self.player.query_duration(Gst.Format.TIME)
        return int(dur // 1_000_000_000) if ok and dur > 0 else 0

    def on_bus(self, _bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            self.advance(1, natural=True)
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            log(f"playback error: {err.message if err else '?'} ({dbg or ''})")
            self.stop()
        elif t == Gst.MessageType.STATE_CHANGED and msg.src == self.player:
            _old, state, pending = msg.parse_state_changed()
            # Only the state the player settles in; the PAUSED step on the way to PLAYING
            # (every track change) would make the UI's play button flicker.
            if pending == Gst.State.VOID_PENDING:
                self.status = {Gst.State.PLAYING: "playing", Gst.State.PAUSED: "paused"}.get(state, "stopped")
                self.set("PlaybackStatus", self.status)
        elif t == Gst.MessageType.DURATION_CHANGED:
            self.learn_duration()
        return True

    def learn_duration(self):
        if not self.tracks:
            return
        dur = self.duration()
        if dur and dur != self.tracks[self.index]["duration"]:
            self.tracks[self.index]["duration"] = dur
            self.refresh_props()

    def poll_position(self):
        if self.status == "playing" and not self.pending:     # not while switching away
            self.position = self.current_time()
            self.set("Position", self.position)
            if self.tracks and not self.tracks[self.index]["duration"]:
                self.learn_duration()
        return True

    # ---- helpers ---------------------------------------------------------
    def refresh_props(self):
        self.set("PlaybackStatus", self.status)
        self.set("Source", self.source)
        self.set("Sources", list(SOURCES))
        self.set("TrackIndex", self.index)
        self.set("TrackCount", len(self.tracks))
        self.set("Position", self.position)
        self.set("Metadata", self.metadata())
        self.set("Playlist", [{k: t[k] for k in ("title", "artist", "album", "duration")} for t in self.tracks])
        self.set("Shuffle", self.shuffle)
        self.set("RepeatAll", self.repeat_all)
        self.set("CanGoNext", bool(self.tracks) and (self.index < len(self.tracks) - 1 or self.repeat_all))
        self.set("CanGoPrevious", bool(self.tracks) and (self.index > 0 or self.repeat_all))
        self.set("Gain", self.gain)

    def advance(self, step: int, natural: bool = False):
        if not self.tracks:
            return
        n = len(self.tracks)
        if self.shuffle and n > 1:
            if step > 0:
                self.history.append(self.index)
                self.index = random.choice([i for i in range(n) if i != self.index])
            elif self.history:
                self.index = self.history.pop()
            self.load(True, fade_out=not natural)
            return
        last = n - 1
        nxt = self.index + step
        if nxt > last:
            if not self.repeat_all:
                self.stop(fade=not natural)
                return
            nxt = 0
        elif nxt < 0:
            nxt = last if self.repeat_all else 0
        self.index = nxt
        self.load(True, fade_out=not natural)

    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def flush(self):
        if self.dirty:
            changed = {k: variant(self.props[k]) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"),
                                   dbus.Array([], signature="s"))
        return True

    # ---- D-Bus properties ------------------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return variant(self.props[name])

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: variant(v) for k, v in self.props.items()}, signature="sv")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    @dbus.service.signal(IFACE, signature="x")
    def Seeked(self, position):
        pass

    # ---- D-Bus methods ---------------------------------------------------
    @dbus.service.method(IFACE)
    def Play(self):
        if not self.uri:
            self.load(True)
            return
        if self.pending and self.pending_actions == [self.pause_now]:
            GLib.source_remove(self.pending)     # pause not reached the speaker yet: undo it
            self.pending, self.pending_actions = None, []
        self.status = "playing"
        self.set("PlaybackStatus", "playing")
        self.fade_in_from_silence()
        self.player.set_state(Gst.State.PLAYING)

    @dbus.service.method(IFACE)
    def Pause(self):
        if self.status != "playing":
            return
        self.fade_out_then(self.pause_now)       # needs status "playing" to fade at all
        self.status = "paused"                   # shown at once; heard after the fade-out
        self.set("PlaybackStatus", "paused")

    def pause_now(self):
        self.silenced = True
        self.player.set_state(Gst.State.PAUSED)

    @dbus.service.method(IFACE)
    def PlayPause(self):
        self.SetPlaying(self.status != "playing")

    @dbus.service.method(IFACE, in_signature="b")
    def SetPlaying(self, playing):
        if playing:
            self.Play()
        else:
            self.Pause()

    @dbus.service.method(IFACE)
    def Next(self):
        self.advance(1)

    @dbus.service.method(IFACE)
    def Previous(self):
        if self.position > 3_000_000:
            self.SetPosition(0)
        else:
            self.advance(-1)

    @dbus.service.method(IFACE, in_signature="i")
    def SetTrack(self, index):
        if not self.tracks:
            return
        self.history.clear()
        self.index = max(0, min(int(index), len(self.tracks) - 1))
        self.load(True)

    @dbus.service.method(IFACE, in_signature="x")
    def Seek(self, offset):
        self.seek_abs(self.current_time() + int(offset))

    @dbus.service.method(IFACE, in_signature="x")
    def SetPosition(self, position):
        self.seek_abs(max(0, int(position)))

    def seek_abs(self, position_us: int):
        if not self.uri:
            return

        def seek():
            self.fade_in_next = self.status == "playing"
            self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                    max(0, position_us) * 1000)
        self.fade_out_then(seek)
        self.position = max(0, position_us)
        self.set("Position", self.position)
        self.Seeked(self.position)

    @dbus.service.method(IFACE, in_signature="b")
    def SetShuffle(self, on):
        self.shuffle = bool(on)
        self.refresh_props()

    @dbus.service.method(IFACE, in_signature="b")
    def SetRepeatAll(self, on):
        self.repeat_all = bool(on)
        self.refresh_props()

    @dbus.service.method(IFACE, in_signature="du")
    def SetGain(self, gain, fade_ms):
        self.ramp_to(max(0.0, min(float(gain), 1.0)), int(fade_ms))
        self.set("Gain", self.gain)

    @dbus.service.method(IFACE, in_signature="s")
    def SetSource(self, source):
        # Only local files are wired up; Bluetooth A2DP comes later.
        self.source = str(source)
        self.refresh_props()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--music-dir", default=os.environ.get("XDG_MUSIC_DIR", str(Path.home() / "Music")),
                    help="folder to scan for audio files (USB / SD card)")
    ap.add_argument("--demo", action="store_true",
                    help="if the music dir has no audio, write a few short WAV tones into it")
    ap.add_argument("--sink", default=None, help="force a GStreamer audio sink (e.g. fakesink, for headless runs)")
    ap.add_argument("--buffer-ms", type=int, default=60,
                    help="audio sink buffer; smaller makes volume changes audible sooner (default 60)")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()

    music_dir = Path(a.music_dir).expanduser()
    if a.demo and only_demo_tones(music_dir):     # never touches a folder with real music
        make_demo(music_dir)                      # writes missing or outdated demo tones

    Gst.init(None)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    media = Media(bus, music_dir, a.sink, a.buffer_ms)
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus, "
        f"{len(media.tracks)} track(s) in {music_dir}")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
