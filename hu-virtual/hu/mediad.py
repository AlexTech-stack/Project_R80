#!/usr/bin/env python3
"""hu-mediad: the Linux-side media service of the R80 headunit.

Plays local audio (the USB / SD-card source) with GStreamer and publishes the
playback state on D-Bus for the UI and the other services:

    bus name   de.r80.Media
    object     /de/r80/Media
    interface  de.r80.Media1
      properties  PlaybackStatus (s: playing|paused|stopped), Source (s),
                  Sources (as), TrackIndex (i), TrackCount (i),
                  Position (x, microseconds), Metadata (a{sv}),
                  Playlist (aa{sv}), Shuffle (b), RepeatAll (b),
                  CanGoNext (b), CanGoPrevious (b)
      methods     Play(), Pause(), PlayPause(), Next(), Previous(),
                  SetTrack(i), Seek(x offset_us), SetPosition(x pos_us),
                  SetPlaying(b), SetShuffle(b), SetRepeatAll(b),
                  SetSource(s)
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
import struct
import wave
from pathlib import Path

import dbus
import dbus.service
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

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


def make_demo(music_dir: Path, count: int = 4) -> list:
    """Write a few short WAV tones (stdlib only) so the UI has real audio."""
    tones = [("Neon Autobahn", "Night Drive", 220.0, 24),
             ("The Quattro Lines", "Red Horizon", 330.0, 20),
             ("Lumen Drift", "Tunnel Vision", 174.0, 28),
             ("Marta Kovac", "Coastline", 262.0, 18)]
    music_dir.mkdir(parents=True, exist_ok=True)
    made = []
    rate = 44100
    for artist, title, freq, secs in tones[:count]:
        f = music_dir / f"{artist} - {title}.wav"
        if not f.exists():
            with wave.open(str(f), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                frames = bytearray()
                for n in range(rate * secs):
                    # fade in / out so the tone does not click
                    edge = min(n, rate * secs - n, rate // 10) / (rate // 10)
                    amp = 0.25 * edge * 32767
                    frames += struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * n / rate)))
                w.writeframes(bytes(frames))
            log(f"demo tone: {f.name}")
        made.append(f)
    return made


class Media(dbus.service.Object):
    def __init__(self, bus, music_dir: Path, sink: str | None = None):
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
        if sink:
            element = Gst.ElementFactory.make(sink, None)
            if element is not None and element.find_property("sync") is not None:
                element.set_property("sync", True)   # keep fakesink real-time for headless tests
            self.player.set_property("audio-sink", element)
        bus_ = self.player.get_bus()
        bus_.add_signal_watch()
        bus_.connect("message", self.on_bus)

        GLib.timeout_add(100, self.flush)
        GLib.timeout_add(300, self.poll_position)
        self.refresh_props()

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
    def load(self, start: bool):
        if not self.tracks:
            self.stop()
            return
        self.index = self.index % len(self.tracks)
        t = self.tracks[self.index]
        self.uri = Path(t["path"]).as_uri()
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", self.uri)
        self.position = 0
        self.status = "playing" if start else "paused"
        self.player.set_state(Gst.State.PLAYING if start else Gst.State.PAUSED)
        self.refresh_props()

    def stop(self):
        self.player.set_state(Gst.State.NULL)
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
            self.advance(1)
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            log(f"playback error: {err.message if err else '?'} ({dbg or ''})")
            self.stop()
        elif t == Gst.MessageType.STATE_CHANGED and msg.src == self.player:
            ok, state, _pending = self.player.get_state(0)
            if ok:
                self.status = {Gst.State.PLAYING: "playing", Gst.State.PAUSED: "paused"}.get(state, "stopped")
                self.dirty.update(("PlaybackStatus",))
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
        if self.status == "playing":
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

    def advance(self, step: int):
        if not self.tracks:
            return
        n = len(self.tracks)
        if self.shuffle and n > 1:
            if step > 0:
                self.history.append(self.index)
                self.index = random.choice([i for i in range(n) if i != self.index])
            elif self.history:
                self.index = self.history.pop()
            self.load(True)
            return
        last = n - 1
        nxt = self.index + step
        if nxt > last:
            if not self.repeat_all:
                self.stop()
                return
            nxt = 0
        elif nxt < 0:
            nxt = last if self.repeat_all else 0
        self.index = nxt
        self.load(True)

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
        else:
            self.player.set_state(Gst.State.PLAYING)

    @dbus.service.method(IFACE)
    def Pause(self):
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
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                max(0, position_us) * 1000)
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
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()

    music_dir = Path(a.music_dir).expanduser()
    if a.demo and not (music_dir.is_dir() and any(p.suffix.lower() in AUDIO_EXT for p in music_dir.rglob("*"))):
        make_demo(music_dir)

    Gst.init(None)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    media = Media(bus, music_dir, a.sink)
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus, "
        f"{len(media.tracks)} track(s) in {music_dir}")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
