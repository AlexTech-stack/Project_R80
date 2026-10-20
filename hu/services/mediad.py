#!/usr/bin/env python3
"""hu-mediad: the Linux-side media service of the R80 headunit.

Plays local audio with GStreamer and publishes the playback state on D-Bus for the
UI and the other services. Sources: "Library" (the HU's own music folder, --music-dir)
and every USB stick udisks2 reports (hu/removable.py, --usb), named after its label or
"USB" (a second one "USB 2", ...).

    bus name   de.r80.Media
    object     /de/r80/Media
    interface  de.r80.Media1
      properties  PlaybackStatus (s: playing|paused|stopped), Source (s), Gain (d),
                  Sources (as), TrackIndex (i), TrackCount (i: the queue),
                  QueueTitle (s), Queue (s: its browse path), UpNext (aa{sv}: the next
                  up to 5 tracks in play order), SourceTrackCount (i), Scanned (i),
                  Position (x, microseconds), Metadata (a{sv}),
                  Shuffle (b), RepeatAll (b), CanGoNext (b), CanGoPrevious (b)
      methods     Play(), Pause(), PlayPause(), Next(), Previous(),
                  SetTrack(i), Seek(x offset_us), SetPosition(x pos_us),
                  SetPlaying(b), SetShuffle(b), SetRepeatAll(b),
                  SetSource(s, one of Sources; else de.r80.Media1.Error.UnknownSource),
                  SetGain(d gain 0.0..1.0, u fade_ms; set by hu-audiod),
                  GetQueue(i offset, i count) -> aa{sv},
                  Browse(s path, i offset, i count) -> (s title, i total, aa{sv} entries),
                  PlayFrom(s path, i index): that list's tracks become the queue
                  (errors: de.r80.Media1.Error.NotFound)
      signal      Seeked(x position)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

What plays is a queue: a list of the browse tree (hu/browse.py: folders, artists,
albums, all tracks); TrackIndex and TrackCount are about the queue, which a source
starts with as "All tracks". Shuffle plays the queue in a shuffled order, which UpNext
follows. Metadata, each UpNext / GetQueue entry: title, artist, album, trackNumber,
duration (s) and cover (a file path, or ""); Metadata and browse tracks also their
path (to mark what plays), a queue entry its index. They come from the files' tags, read in the
background by prerolling each file once (core GStreamer, no extra package); until
a file is read, and for what its tags lack, the file name (`Artist - Title.ext`)
and its folder (album) stand in. The cover is the picture embedded in the file,
else cover/folder/front.jpg|png next to it. What was read is cached in --cache-dir
(the HU's own storage, never the medium), keyed by path, size and mtime; Scanned
counts the tracks read so far. Bluetooth A2DP and MPRIS are not wired up yet;
this is the local-file path from architecture v0.3 section 4.

A stick plugged in while running becomes the source at once and plays (one udisks2
already lists when mediad starts does not: resume decides); when the playing stick is pulled,
the Library takes over (paused). Resume: per source (the Library, each stick by its
filesystem UUID) the track and position are kept, and with the active source and
whether it played saved to --state on a source change, before a shutdown (as a
saver of hu-sysd, D12) and on SIGTERM. At start the last source carries on where it was; if that
was a stick, mediad waits up to --resume-wait s for it to appear.

Runs unchanged on the bench (--usb system) and in the virtual environment (session
bus; --usb session is the BoAt tests' udisks2 stand-in).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

import dbus
import dbus.service
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import GLib, Gst, GstController  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browse import browse, tracks_of  # noqa: E402
from removable import RemovableMedia  # noqa: E402
from saver import register_saver  # noqa: E402

BUS_NAME = "de.r80.Media"
OBJ_PATH = "/de/r80/Media"
IFACE = "de.r80.Media1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
AUDIO_EXT = {".mp3", ".ogg", ".oga", ".flac", ".wav", ".m4a", ".aac", ".opus", ".wma"}
LIBRARY = "Library"
FOLDER_COVERS = ("cover", "folder", "front", "album")
COVER_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/gif": "gif", "image/bmp": "bmp"}
INT32_PROPS = {"TrackIndex", "TrackCount", "Scanned", "SourceTrackCount"}
UP_NEXT = 5
TRACK_KEYS = ("title", "artist", "album", "trackNumber", "duration", "cover")


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


def folder_cover(folder: Path) -> str:
    """cover.jpg, folder.png, ... next to the tracks (any case), or ""."""
    try:
        for p in sorted(folder.iterdir()):
            if p.stem.lower() in FOLDER_COVERS and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                return str(p)
    except OSError:
        pass
    return ""


class Scanner:
    """Reads the tags of one file after the other in the background and caches them.

    One reused playbin with fake sinks prerolls each file (PAUSED): the tags arrive as
    TAG messages, the duration once it is prerolled. Images go to cache_dir/covers,
    named by their hash, so an album's tracks share one file.
    """
    TIMEOUT_MS = 5000

    def __init__(self, cache_dir: Path, on_track):
        self.dir = cache_dir
        self.covers = cache_dir / "covers"
        self.covers.mkdir(parents=True, exist_ok=True)
        self.file = cache_dir / "library.json"
        try:
            self.cache = json.loads(self.file.read_text())
        except (OSError, ValueError):
            self.cache = {}
        self.on_track = on_track       # called with the track dict once it is read
        self.root, self.medium = "\0", ""   # the source being read (start)
        self.queue = []
        self.current = None
        self.tags = None
        self.timer = None
        self.dirty = False
        self.pipe = Gst.ElementFactory.make("playbin", "scanner")
        self.pipe.set_property("flags", 0x2)                       # audio only
        self.pipe.set_property("audio-sink", Gst.ElementFactory.make("fakesink", None))
        self.pipe.set_property("video-sink", Gst.ElementFactory.make("fakesink", None))
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus)
        GLib.timeout_add_seconds(5, self.save)

    @staticmethod
    def key(path: str) -> str | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        return f"{st.st_size}:{int(st.st_mtime)}"

    def ckey(self, path: str) -> str:
        """The cache's name for a track: its medium and its path on it, so a stick
        mounted somewhere else next time is not read again."""
        return self.medium + ":" + path[len(self.root):] if path.startswith(self.root) else path

    def cover_in(self, cover: str) -> str:
        return "@/" + cover[len(self.root):] if cover.startswith(self.root) else cover   # a folder cover: relative

    def cover_out(self, cover: str) -> str:
        return self.root + cover[2:] if cover.startswith("@/") else cover

    def cached(self, track: dict) -> bool:
        """Fill the track from the cache; False if it has to be read."""
        hit = self.cache.get(self.ckey(track["path"]))
        if not hit or hit.get("key") != self.key(track["path"]):
            return False
        cover = self.cover_out(hit["cover"])
        if cover and not os.path.exists(cover):
            return False
        track.update({k: hit[k] for k in TRACK_KEYS}, cover=cover)
        track["scanned"] = True
        return True

    def start(self, tracks: list, first: int = 0, root: Path | None = None, medium: str = "") -> None:
        """Read every track not in the cache, beginning with tracks[first]; root and
        medium: the source's folder and key (library, usb:<UUID>)."""
        self.stop()
        self.root = (str(root).rstrip("/") + "/") if root else "\0"
        self.medium = medium
        order = tracks[first:] + tracks[:first]
        self.queue = [t for t in order if not self.cached(t)]
        self.started, self.count = time.monotonic(), len(self.queue)
        if self.queue:
            log(f"reading tags of {len(self.queue)} track(s)")
        self.next()

    def stop(self) -> None:
        self.queue = []
        self.current = None
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.pipe.set_state(Gst.State.NULL)

    def next(self) -> bool:
        self.pipe.set_state(Gst.State.NULL)
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if not self.queue:
            if self.count:
                log(f"read the tags of {self.count} track(s) in {time.monotonic() - self.started:.1f} s")
                self.count = 0
            self.current = None
            self.save()
            return False
        self.current = self.queue.pop(0)
        self.tags = Gst.TagList.new_empty()
        self.pipe.set_property("uri", Path(self.current["path"]).as_uri())
        self.pipe.set_state(Gst.State.PAUSED)
        self.timer = GLib.timeout_add(self.TIMEOUT_MS, self.give_up)
        return False

    def give_up(self) -> bool:
        self.timer = None
        if self.current:
            log(f"no tags from {self.current['path']} within {self.TIMEOUT_MS} ms")
            self.done()
        return False

    def on_bus(self, _bus, msg):
        if not self.current:
            return True
        t = msg.type
        if t == Gst.MessageType.TAG:
            self.tags = self.tags.merge(msg.parse_tag(), Gst.TagMergeMode.KEEP)
        elif t == Gst.MessageType.ASYNC_DONE:
            self.done()
        elif t == Gst.MessageType.ERROR:
            err, _dbg = msg.parse_error()
            log(f"cannot read {self.current['path']}: {err.message if err else '?'}")
            self.done()
        return True

    def done(self) -> None:
        t, tags = self.current, self.tags
        ok, dur = self.pipe.query_duration(Gst.Format.TIME)

        def text(name):
            found, v = tags.get_string(name)
            return v.strip() if found and v else ""

        t["title"] = text("title") or t["title"]
        t["artist"] = text("artist") or text("album-artist") or t["artist"]
        t["album"] = text("album") or t["album"]
        found, n = tags.get_uint("track-number")
        t["trackNumber"] = int(n) if found else 0
        if ok and dur > 0:
            t["duration"] = int(round(dur / 1_000_000_000))
        else:
            # MP3 without a Xing/VBRI header: no duration before it plays; estimate it
            # from the size and the bitrate (exact for CBR, the player corrects it later)
            for name in ("bitrate", "nominal-bitrate"):
                found, rate = tags.get_uint(name)
                ok, size = self.pipe.query_duration(Gst.Format.BYTES)
                if found and rate and ok and size > 0:
                    t["duration"] = int(round(size * 8 / rate))
                    break
        t["cover"] = self.save_image(tags) or folder_cover(Path(t["path"]).parent)
        t["scanned"] = True
        self.cache[self.ckey(t["path"])] = {"key": self.key(t["path"]), **{k: t[k] for k in TRACK_KEYS},
                                            "cover": self.cover_in(t["cover"])}
        self.dirty = True
        self.current = None
        self.on_track(t)
        GLib.idle_add(self.next)

    def save_image(self, tags) -> str:
        """The embedded picture (front cover first) as a file in the cache, or ""."""
        best = None
        for i in range(tags.get_tag_size("image")):
            found, sample = tags.get_sample_index("image", i)
            if not found:
                continue
            info = sample.get_info()
            kind = info.get_value("image-type") if info and info.has_field("image-type") else None
            front = kind is not None and int(kind) == 1              # GST_TAG_IMAGE_TYPE_FRONT_COVER
            if best is None or front:
                best = sample
            if front:
                break
        if best is None:
            return ""
        buf = best.get_buffer()
        found, mapped = buf.map(Gst.MapFlags.READ)
        if not found:
            return ""
        data = bytes(mapped.data)
        buf.unmap(mapped)
        caps = best.get_caps()
        mime = caps.get_structure(0).get_name() if caps and caps.get_size() else ""
        ext = COVER_EXT.get(mime, "img")
        f = self.covers / f"{hashlib.sha1(data).hexdigest()[:16]}.{ext}"
        if not f.exists():
            f.write_bytes(data)
        return str(f)

    def save(self) -> bool:
        if self.dirty:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache))
            tmp.replace(self.file)
            self.dirty = False
        return True


class Media(dbus.service.Object):
    def __init__(self, bus, music_dir: Path, cache_dir: Path, state: Path, sink: str | None = None,
                 buffer_ms: int = 60, usb_bus=None, resume_wait: float = 15.0):
        super().__init__(bus, OBJ_PATH)
        self.sources = {LIBRARY: {"key": "library", "dir": music_dir}}   # name -> key, folder
        self.source = LIBRARY
        self.dir = music_dir
        self.library = self.scan()     # every track of the source
        self.tracks = self.library     # the queue: what plays, in its order
        self.queue_path, self.queue_title = "tracks", "All tracks"
        self.order = None              # with shuffle: the play order (queue positions) ...
        self.opos = 0                  # ... and where in it we are
        self.list_changed = False      # tags read since the last UpNext update
        self.index = 0
        self.state_file = state
        self.resume = {}               # source key -> {"path", "position" (us)}
        self.shuffle = False
        self.repeat_all = True
        self.status = "stopped"
        self.position = 0          # microseconds
        self.uri = ""
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
        self.deferred_seek = None    # ns: a seek asked for before the new track prerolled
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
        GLib.timeout_add(1000, self.publish_scanned)
        self.scanner = Scanner(cache_dir, self.on_scanned)
        self.awaited = None            # (key, play): the stick the last session ended on
        self.restore(resume_wait)
        register_saver(bus, "mediad", self.save_state, log)
        if usb_bus is not None:
            self.usb = RemovableMedia(usb_bus, self.on_medium_added, self.on_medium_removed, log)
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
        return [dict(path=str(p), duration=0, trackNumber=0, cover="", scanned=False, **parse_name(p)) for p in files]

    # ---- sources and resume -------------------------------------------------
    def key(self) -> str:
        return self.sources[self.source]["key"]

    def remember(self):
        """Note where the active source is, for when it comes back."""
        if self.tracks:
            if self.deferred_seek is not None or self.pending:
                pos = self.position            # a seek not done yet: where it is going
            else:
                pos = self.current_time() if self.status == "playing" else self.position
            self.resume[self.key()] = {"path": self.rel(self.tracks[self.index]["path"]), "position": int(pos),
                                       "queue": self.queue_path}

    def rel(self, path: str) -> str:
        """A track's path inside its source (a stick may be mounted elsewhere next time)."""
        root = str(self.dir).rstrip("/") + "/"
        return path[len(root):] if path.startswith(root) else path

    def use_source(self, name: str, play: bool):
        """Switch to a source and carry on where it was (track and position)."""
        if name in self.sources and name != self.source:
            self.remember()
        self.stop()
        self.source = name
        self.dir = self.sources[name]["dir"]
        self.library = self.scan()
        r = self.resume.get(self.key(), {})
        self.set_queue("tracks", "All tracks", self.library)
        try:                                       # the list it played, if it is still there
            title, queue = tracks_of(self.library, self.dir, self.source, r.get("queue", "tracks"))
            if any(self.rel(t["path"]) == r.get("path") for t in queue):
                self.set_queue(r["queue"], title, queue)
        except KeyError:
            pass
        paths = [self.rel(t["path"]) for t in self.tracks]
        self.index = paths.index(r["path"]) if r.get("path") in paths else 0
        if self.shuffle:
            self.shuffle_from(self.index)
        self.scanner.start(self.library, self.library.index(self.tracks[self.index]) if self.tracks else 0,
                           self.dir, self.key())
        if self.tracks:
            self.load(play)
            if r.get("path") in paths and r.get("position", 0) > 0:
                self.seek_abs(int(r["position"]))
        self.refresh_props()
        self.save_state()
        log(f"source {name}: {len(self.library)} track(s) in {self.dir}, queue {self.queue_path!r}, track {self.index}")

    # ---- the queue -----------------------------------------------------------
    def set_queue(self, path: str, title: str, tracks: list):
        self.queue_path, self.queue_title, self.tracks = path, title, tracks
        self.order, self.opos = None, 0

    def shuffle_from(self, index: int):
        """A new shuffled play order that starts with the queue position index."""
        rest = [i for i in range(len(self.tracks)) if i != index]
        random.shuffle(rest)
        self.order, self.opos = [index] + rest, 0

    def play_order(self) -> list:
        return self.order if self.order is not None else list(range(len(self.tracks)))

    def up_next(self) -> list:
        order, n = self.play_order(), len(self.tracks)
        pos = self.opos if self.order is not None else self.index
        out = []
        for k in range(1, min(UP_NEXT, n - 1) + 1):
            if pos + k >= n and not self.repeat_all:
                break
            i = order[(pos + k) % n]
            out.append({**{key: self.tracks[i][key] for key in TRACK_KEYS}, "index": i})
        return out

    def entry(self, e: dict) -> dict:
        """A browse entry for D-Bus (without the track object)."""
        return {k: v for k, v in e.items() if k != "track"}

    def restore(self, resume_wait: float):
        try:
            st = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            st = {}
        self.resume = st.get("resume", {})
        last, play = st.get("source", "library"), bool(st.get("playing", False))
        if last.startswith("usb:"):
            # The stick shows up a moment after start, if it is still plugged in.
            self.awaited = (last, play)
            self.use_source(LIBRARY, False)
            GLib.timeout_add(int(resume_wait * 1000), self.stop_waiting)
        else:
            self.use_source(LIBRARY, play)

    def stop_waiting(self):
        if self.awaited:
            _key, play = self.awaited
            self.awaited = None
            log("the last stick did not come back: staying on the Library")
            if play and self.tracks:
                self.Play()
        return False

    def save_state(self):
        self.remember()
        st = {"source": self.key(), "playing": self.status == "playing", "resume": self.resume}
        if self.awaited:                       # still waiting at start for the last session's stick
            st["source"], st["playing"] = self.awaited
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(st))
            tmp.replace(self.state_file)
        except OSError as e:
            log(f"cannot save {self.state_file}: {e}")

    def on_medium_added(self, key: str, label: str, mount: str, initial: bool):
        same = next((n for n, s in self.sources.items() if s["key"] == key), None)
        if same is not None:                                 # the same medium, now mounted elsewhere
            if same == self.source:
                self.remember()                              # while its paths are still the old ones
            self.sources[same]["dir"] = Path(mount)
            if same == self.source:
                playing, self.source = self.status == "playing", LIBRARY   # use_source must not remember again
                self.use_source(same, playing)
            return
        base = label or "USB"
        name, n = base, 2
        while name in self.sources:
            name, n = f"{base} {n}", n + 1
        self.sources[name] = {"key": key, "dir": Path(mount)}
        if self.awaited and self.awaited[0] == key:          # the stick the last session ended on
            _key, play = self.awaited
            self.awaited = None
            self.use_source(name, play)
        elif not initial:                                    # plugged in now: play it
            self.awaited = None
            self.use_source(name, True)
        else:                                                # already in at start: resume decides
            self.refresh_props()

    def on_medium_removed(self, key: str):
        name = next((n for n, s in self.sources.items() if s["key"] == key), None)
        if name is None:
            return
        if name == self.source:
            self.remember()                                  # where it was, for when it is back
            del self.sources[name]
            self.source = LIBRARY                            # use_source must not remember the stick again
            self.use_source(LIBRARY, False)
        else:
            del self.sources[name]
            self.refresh_props()

    def metadata(self):
        if not self.tracks:
            return {"title": "", "artist": "", "album": "", "trackNumber": 0, "duration": 0, "cover": "", "path": ""}
        t = self.tracks[self.index]
        return {**{k: t[k] for k in TRACK_KEYS}, "path": t["path"]}

    def on_scanned(self, track):
        self.list_changed = True
        if self.tracks and track is self.tracks[self.index]:
            self.set("Metadata", self.metadata())      # the playing track at once

    def publish_scanned(self):
        # At most once a second, not for every file read.
        if self.list_changed:
            self.list_changed = False
            self.refresh_props()
        return True

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
            self.deferred_seek = None            # the new track starts at 0
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
            if self.pending:
                # A fade-out is running for what the driver asked last (e.g. Pause right
                # after Play): a late "now PLAYING" from before must not overwrite that.
                return True
            _old, state, pending = msg.parse_state_changed()
            # Only the state the player settles in; the PAUSED step on the way to PLAYING
            # (every track change) would make the UI's play button flicker.
            if pending == Gst.State.VOID_PENDING:
                self.status = {Gst.State.PLAYING: "playing", Gst.State.PAUSED: "paused"}.get(state, "stopped")
                self.set("PlaybackStatus", self.status)
        elif t == Gst.MessageType.DURATION_CHANGED:
            self.learn_duration()
        elif t == Gst.MessageType.ASYNC_DONE and self.deferred_seek is not None:
            ns, self.deferred_seek = self.deferred_seek, None
            self.do_seek(ns)
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
        self.set("Sources", list(self.sources))
        self.set("TrackIndex", self.index)
        self.set("TrackCount", len(self.tracks))
        self.set("Position", self.position)
        self.set("Metadata", self.metadata())
        self.set("UpNext", self.up_next())
        self.set("QueueTitle", self.queue_title)
        self.set("Queue", self.queue_path)
        self.set("SourceTrackCount", len(self.library))
        self.set("Scanned", sum(1 for t in self.library if t["scanned"]))
        self.set("Shuffle", self.shuffle)
        self.set("RepeatAll", self.repeat_all)
        pos = self.opos if self.order is not None else self.index
        self.set("CanGoNext", bool(self.tracks) and (pos < len(self.tracks) - 1 or self.repeat_all))
        self.set("CanGoPrevious", bool(self.tracks) and (pos > 0 or self.repeat_all))
        self.set("Gain", self.gain)

    def advance(self, step: int, natural: bool = False):
        if not self.tracks:
            return
        n = len(self.tracks)
        last = n - 1
        nxt = (self.opos if self.order is not None else self.index) + step
        if nxt > last:
            if not self.repeat_all:
                self.stop(fade=not natural)
                return
            nxt = 0
        elif nxt < 0:
            nxt = last if self.repeat_all else 0
        if self.order is not None:
            self.opos, self.index = nxt, self.order[nxt]
        else:
            self.index = nxt
        self.load(True, fade_out=not natural)

    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def prop(self, name):
        """A property as the D-Bus type the interface documents."""
        v = self.props[name]
        if name in INT32_PROPS:
            return dbus.Int32(v)
        if name == "UpNext":
            return dbus.Array([variant(x) for x in v], signature="a{sv}")
        if name == "Sources":
            return dbus.Array([dbus.String(x) for x in v], signature="s")
        return variant(v)

    def flush(self):
        if self.dirty:
            changed = {k: self.prop(k) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"),
                                   dbus.Array([], signature="s"))
        return True

    # ---- D-Bus properties ------------------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.prop(name)

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: self.prop(k) for k in self.props}, signature="sv")

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
        self.index = max(0, min(int(index), len(self.tracks) - 1))
        if self.shuffle:
            self.shuffle_from(self.index)
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
            # Right after a track switch the pipeline is still on its way to PLAYING and
            # drops a seek; keep it for when the track has prerolled (ASYNC_DONE).
            _ret, state, pending = self.player.get_state(0)
            if pending != Gst.State.VOID_PENDING or state < Gst.State.PAUSED or not self.do_seek(position_us * 1000):
                self.deferred_seek = max(0, position_us) * 1000
        self.fade_out_then(seek)
        self.position = max(0, position_us)
        self.set("Position", self.position)
        self.Seeked(self.position)

    def do_seek(self, ns: int) -> bool:
        return self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, max(0, ns))

    @dbus.service.method(IFACE, in_signature="b")
    def SetShuffle(self, on):
        self.shuffle = bool(on)
        if self.shuffle and self.tracks:
            self.shuffle_from(self.index)
        elif not self.shuffle:
            self.order, self.opos = None, 0
        self.refresh_props()

    @dbus.service.method(IFACE, in_signature="ii", out_signature="aa{sv}")
    def GetQueue(self, offset, count):
        offset, count = max(0, int(offset)), max(0, int(count))
        return dbus.Array([variant({**{k: t[k] for k in TRACK_KEYS}, "index": offset + i})
                           for i, t in enumerate(self.tracks[offset:offset + count])], signature="a{sv}")

    def not_found(self, path):
        return dbus.exceptions.DBusException(f"no list {str(path)!r} on {self.source}",
                                             name="de.r80.Media1.Error.NotFound")

    @dbus.service.method(IFACE, in_signature="sii", out_signature="siaa{sv}")
    def Browse(self, path, offset, count):
        try:
            title, entries = browse(self.library, self.dir, self.source, str(path))
        except KeyError:
            raise self.not_found(path) from None
        offset, count = max(0, int(offset)), max(0, int(count))
        page = [variant(self.entry(e)) for e in entries[offset:offset + count]]
        return title, dbus.Int32(len(entries)), dbus.Array(page, signature="a{sv}")

    @dbus.service.method(IFACE, in_signature="si")
    def PlayFrom(self, path, index):
        try:
            title, queue = tracks_of(self.library, self.dir, self.source, str(path))
        except KeyError:
            raise self.not_found(path) from None
        if not queue:
            raise self.not_found(path)
        self.set_queue(str(path), title, queue)
        self.index = max(0, min(int(index), len(queue) - 1))
        if self.shuffle:
            self.shuffle_from(self.index)
        self.load(True)
        self.save_state()

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
        # Local files only: the Library and the sticks; Bluetooth A2DP comes later.
        source = str(source)
        if source not in self.sources:
            raise dbus.exceptions.DBusException(f"unknown source {source!r} (one of {', '.join(self.sources)})",
                                                name="de.r80.Media1.Error.UnknownSource")
        if source != self.source:
            self.awaited = None
            self.use_source(source, self.status == "playing")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--music-dir", default=os.environ.get("XDG_MUSIC_DIR", str(Path.home() / "Music")),
                    help="the Library: the HU's own music folder (default ~/Music)")
    ap.add_argument("--sink", default=None, help="force a GStreamer audio sink (e.g. fakesink, for headless runs)")
    ap.add_argument("--buffer-ms", type=int, default=60,
                    help="audio sink buffer; smaller makes volume changes audible sooner (default 60)")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    ap.add_argument("--cache-dir", default=str(Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "r80" / "media"),
                    help="where the tags read and the covers are kept (default ~/.cache/r80/media)")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "media.json"),
                    help="where the source and resume points are saved (default ~/.local/state/r80/media.json)")
    ap.add_argument("--usb", choices=("system", "session"), metavar="BUS",
                    help="USB sticks through udisks2 on this bus (system on the target; session: the tests' stand-in)")
    ap.add_argument("--resume-wait", type=float, default=15.0,
                    help="how long to wait at start for the stick the last session played (s, default 15)")
    a = ap.parse_args()

    music_dir = Path(a.music_dir).expanduser()

    Gst.init(None)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    usb_bus = None if not a.usb else dbus.SystemBus() if a.usb == "system" else dbus.SessionBus()
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus, Library {music_dir}"
        + (f", USB sticks via udisks2 on the {a.usb} bus" if a.usb else ""))
    media = Media(bus, music_dir, Path(a.cache_dir).expanduser(), Path(a.state).expanduser(), a.sink, a.buffer_ms,
                  usb_bus, a.resume_wait)
    loop = GLib.MainLoop()

    def terminate(*_):
        # Stopped by systemd (restart, poweroff): keep the resume point. systemd ends the
        # session bus at the same moment, so losing it must not end mediad before this.
        media.save_state()
        media.scanner.stop()
        media.player.set_state(Gst.State.NULL)     # a running pipeline would block the exit
        loop.quit()
        return False
    for b in {bus, usb_bus} - {None}:
        b.set_exit_on_disconnect(False)
    bus.add_signal_receiver(terminate, "Disconnected", "org.freedesktop.DBus.Local")
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add             # GLib 2.80 and newer
    except (ImportError, ValueError, AttributeError):  # e.g. Debian 13 (the Pi): only the old name
        signal_add = GLib.unix_signal_add
    signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, terminate)
    loop.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
