#!/usr/bin/env python3
"""hu-assistd: the voice assistant of the R80 headunit. The driver asks, the HU answers.

    bus name   de.r80.Assistant
    object     /de/r80/Assistant
    interface  de.r80.Assistant1
      properties  Available (b: the speech engines are loaded), Enabled (b: the setting "assistant"),
                  Mode (s: idle|command|conversation), State (s: idle|greeting|listening|thinking|speaking),
                  Heard (s: what the driver said last), Answer (s: the last answer), Turns (u: answers in
                  this session), Sessions (u: started since assistd started), Notice (s: why the last
                  start was refused or the session stopped; "" if not), Engines (a{ss}), Timing (a{sd})
      methods     Command(), Conversation(), Stop()
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Two modes, each on its own button (hu-vehicled's Input "button:VOICE" and "button:TALK"; the
methods do the same, for the UI):
- Command: "I'm here", it listens until the driver stops talking, answers, and ends. Pressed
  again while it runs: it stops.
- Conversation: "I'm here", then back and forth (listen, answer, listen, ...) until the button
  is pressed again ("Okay") or nobody talks for conversation_idle_s.

The speech (hu/services/speech.py) runs on the HU: Moonshine tiny hears, a Piper voice speaks,
both through sherpa-onnx, loaded once at start. The answers come from the LLM; until the companion
app brings it, the echo backend repeats what it heard (assistant.ini [llm]).

Sound: the voice is the audio source "voice" (its volume in hu-audiod). While the assistant
listens, audiod turns the music down to listen_duck_level, while it speaks to duck_level
(SetVoice). A call (ringing or active), a warning (severity "warning", hu-warnd), the HU going off
or the setting going off stop the assistant at once.

Logging (D14): states, durations and counts only. What the driver said and the answers are on
D-Bus for the UI and never in the log.

Numbers come from hu/assistant.ini (then /etc/r80/assistant.ini, then --config).
"""
from __future__ import annotations

import argparse
import configparser
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

import dbus
import dbus.service
import gi
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

import dlt  # noqa: E402
import speech  # noqa: E402

BUS_NAME, OBJ_PATH, IFACE = "de.r80.Assistant", "/de/r80/Assistant", "de.r80.Assistant1"
PROPS = "org.freedesktop.DBus.Properties"
VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")
AUDIO = ("de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1")
WARNINGS = ("de.r80.Warnings", "/de/r80/Warnings", "de.r80.Warnings1")
SYSTEM = ("de.r80.System", "/de/r80/System", "de.r80.System1")
DEFAULT_CONFIG = Path(__file__).resolve().parent / "assistant.ini"
SYSTEM_CONFIG = Path("/etc/r80/assistant.ini")
SETTING = "assistant"

log = dlt.context("MAIN", "Voice assistant")
log_speech = dlt.context("SPCH", "Speech engines")


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> dict:
    cp = configparser.ConfigParser(interpolation=None)
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else []) if f.is_file()])
    used = {"speech": {"recognizer", "voice", "model_dir", "recognizer_model", "voice_model", "threads", "mic"},
            "listen": {"speech_level_db", "end_silence_ms", "max_speech_s", "no_speech_s", "conversation_idle_s"},
            "talk": {"greeting", "not_heard", "conversation_end", "speed"},
            "llm": {"backend", "think_s"}}
    for section in cp.sections():
        if section not in used:
            raise ConfigError(f"unknown section [{section}]")
        unknown = set(cp.options(section)) - used[section]
        if unknown:
            raise ConfigError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")

    def get(section, key):
        try:
            return cp.get(section, key).strip()
        except configparser.Error as e:
            raise ConfigError(f"[{section}] {key}: {e}") from None

    def num(section, key, conv, lo, hi):
        try:
            v = conv(get(section, key))
        except ValueError as e:
            raise ConfigError(f"[{section}] {key}: {e}") from None
        if not lo <= v <= hi:
            raise ConfigError(f"[{section}] {key} = {v} is outside {lo}..{hi}")
        return v

    def choice(section, key, options):
        v = get(section, key)
        if v not in options:
            raise ConfigError(f"[{section}] {key} = {v!r}, expected one of {', '.join(options)}")
        return v

    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return {
        "recognizer": choice("speech", "recognizer", ("moonshine", "transcript")),
        "voice": choice("speech", "voice", ("piper", "silent")),
        "model_dir": Path(get("speech", "model_dir") or data / "r80" / "speech"),
        "recognizer_model": get("speech", "recognizer_model"),
        "voice_model": get("speech", "voice_model"),
        "threads": num("speech", "threads", int, 1, 8),
        "mic": get("speech", "mic"),
        "speech_level_db": num("listen", "speech_level_db", float, -90.0, 0.0),
        "end_silence_ms": num("listen", "end_silence_ms", int, 200, 5000),
        "max_speech_s": num("listen", "max_speech_s", float, 1.0, 60.0),
        "no_speech_s": num("listen", "no_speech_s", float, 1.0, 60.0),
        "conversation_idle_s": num("listen", "conversation_idle_s", float, 5.0, 600.0),
        "greeting": get("talk", "greeting"),
        "not_heard": get("talk", "not_heard"),
        "conversation_end": get("talk", "conversation_end"),
        "speed": num("talk", "speed", float, 0.5, 2.0),
        "backend": choice("llm", "backend", ("echo",)),
        "think_s": num("llm", "think_s", float, 0.0, 10.0),
    }


class Worker:
    """One thread for the speech engines (loading, hearing, speaking take seconds on the Pi); the
    results come back on the GLib main loop."""

    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self.run, name="speech", daemon=True).start()

    def run(self):
        while True:
            job, done = self.q.get()
            try:
                result, err = job(), None
            except Exception as e:                       # noqa: BLE001 (reported, the service goes on)
                result, err = None, e
            if done:
                GLib.idle_add(lambda r=result, e=err: (done(r, e), False)[1])

    def submit(self, job, done=None):
        self.q.put((job, done))


class Mic:
    """The microphone through GStreamer, 16 kHz mono, only while listening."""

    def __init__(self, source: str):
        self.desc = (f"{source} ! audioconvert ! audioresample ! "
                     f"audio/x-raw,format=S16LE,rate={speech.RATE},channels=1 ! "
                     "appsink name=out emit-signals=true sync=false max-buffers=100 drop=true")
        self.pipe = None
        self.lock = threading.Lock()
        self.ep = None
        self.done = None

    def listen(self, ep: speech.Endpointer, done):
        """done(Utterance or None) on the main loop: what was said, or None for nothing."""
        self.stop()
        self.ep, self.done = ep, done
        try:
            self.pipe = Gst.parse_launch(self.desc)
        except GLib.Error as e:
            log.error(f"microphone: {e.message}")
            GLib.idle_add(lambda: (done(None), False)[1])
            return
        self.pipe.get_by_name("out").connect("new-sample", self.on_sample)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self.on_error)
        self.pipe.set_state(Gst.State.PLAYING)

    def on_sample(self, sink):
        s = sink.emit("pull-sample")
        buf = s.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        frame = bytes(info.data)
        buf.unmap(info)
        with self.lock:
            if not self.ep:
                return Gst.FlowReturn.OK
            r = self.ep.feed(frame)
            if r in ("done", "nothing"):
                utt = self.ep.utterance() if r == "done" else None
                self.ep, done = None, self.done
                GLib.idle_add(lambda: (self.finish(done, utt), False)[1])
        return Gst.FlowReturn.OK

    def finish(self, done, utt):
        self.stop()
        done(utt)

    def on_error(self, _bus, msg):
        log.error(f"microphone: {msg.parse_error()[0].message}")
        with self.lock:
            done, self.ep = self.done, None
        self.stop()
        if done:
            done(None)

    def stop(self):
        with self.lock:
            self.ep = None
        if self.pipe:
            self.pipe.set_state(Gst.State.NULL)
            self.pipe.get_bus().remove_signal_watch()
            self.pipe = None


class MicFiles:
    """Tests and the virtual HU: recorded speech instead of the microphone. At each listen the oldest
    *.wav in the folder is what the driver says (its text in <name>.txt for the transcript
    recognizer); it takes as long as the recording, then moves to heard/. No file: nothing was said
    (after no_speech_s)."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.timer = None
        folder.mkdir(parents=True, exist_ok=True)

    def listen(self, ep: speech.Endpointer, done):
        self.stop()
        files = sorted(self.folder.glob("*.wav"), key=lambda f: (f.stat().st_mtime, f.name))
        if not files:
            self.timer = GLib.timeout_add(int(ep.no_speech * 1000), lambda: self.fire(done, None))
            return
        f = files[0]
        try:
            utt = speech.read_wav(f)
        except (OSError, ValueError, EOFError) as e:
            log.error(f"recorded speech {f.name}: {e}")
            utt = None
        heard = self.folder / "heard"
        heard.mkdir(exist_ok=True)
        for g in (f, f.with_suffix(".txt")):
            if g.exists():
                shutil.move(str(g), str(heard / g.name))
        wait = utt.seconds + ep.end_silence if utt else ep.no_speech
        self.timer = GLib.timeout_add(int(wait * 1000), lambda: self.fire(done, utt))

    def fire(self, done, utt):
        self.timer = None
        done(utt)
        return False

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None


class Player:
    """The voice through GStreamer: PCM pushed phrase by phrase (the next is made while one plays)."""

    def __init__(self, rate: int, sink: str | None):
        self.rate = rate
        self.pipe = Gst.Pipeline.new("voice")
        self.src = Gst.ElementFactory.make("appsrc", None)
        self.src.set_property("caps", Gst.Caps.from_string(
            f"audio/x-raw,format=S16LE,rate={rate},channels=1,layout=interleaved"))
        self.src.set_property("format", Gst.Format.TIME)
        self.gain = Gst.ElementFactory.make("volume", None)
        conv, res = Gst.ElementFactory.make("audioconvert", None), Gst.ElementFactory.make("audioresample", None)
        snk = Gst.ElementFactory.make(sink or "autoaudiosink", None)
        if sink and snk.find_property("sync") is not None:
            snk.set_property("sync", True)                  # a fake sink takes as long as the sound would
        for e in (self.src, self.gain, conv, res, snk):
            self.pipe.add(e)
        self.src.link(self.gain)
        self.gain.link(conv)
        conv.link(res)
        res.link(snk)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", lambda *_: self.finished())
        bus.connect("message::error", lambda _b, m: (log.error(f"voice: {m.parse_error()[0].message}"), self.finished()))
        self.done = None
        self.pts = 0

    def set_gain(self, g: float):
        self.gain.set_property("volume", g)

    def start(self, done):
        self.stop()
        self.done, self.pts = done, 0
        self.pipe.set_state(Gst.State.PLAYING)

    def push(self, pcm: bytes):
        """From the speech worker: one phrase."""
        buf = Gst.Buffer.new_wrapped(pcm)
        dur = Gst.util_uint64_scale(len(pcm) // 2, Gst.SECOND, self.rate)
        buf.pts, buf.duration = self.pts, dur
        self.pts += dur
        self.src.emit("push-buffer", buf)

    def end(self):
        self.src.emit("end-of-stream")

    def finished(self):
        done, self.done = self.done, None
        self.pipe.set_state(Gst.State.NULL)
        if done:
            done()

    def stop(self):
        self.done = None
        self.pipe.set_state(Gst.State.NULL)


class EchoBrain:
    """Until the companion app brings the LLM: repeats what it heard."""
    name = "echo"

    def __init__(self, think_s: float):
        self.think_s = think_s

    def ask(self, history: list, done):
        last = history[-1]["content"]
        GLib.timeout_add(int(self.think_s * 1000), lambda: (done(f"You said: {last}"), False)[1])


class Assistant(dbus.service.Object):
    def __init__(self, bus, cfg: dict, sink: str | None, mic_files: Path | None):
        super().__init__(bus, OBJ_PATH)
        self.bus, self.cfg, self.sink = bus, cfg, sink
        self.worker = Worker()
        self.mic = MicFiles(mic_files) if mic_files else Mic(cfg["mic"])
        self.brain = EchoBrain(cfg["think_s"])
        self.rec = self.voice = self.player = None
        self.cache = {}                  # the fixed phrases, made once
        self.session = 0                 # a stale callback carries an older number
        self.history = []
        self.power = None
        self.call = "idle"
        self.gain = 1.0
        self.last_talk = 0.0
        self.t = {}
        self.props = {"Available": False, "Enabled": True, "Mode": "idle", "State": "idle", "Heard": "",
                      "Answer": "", "Turns": 0, "Sessions": 0, "Notice": "",
                      "Engines": {"recognizer": cfg["recognizer"], "voice": cfg["voice"], "llm": self.brain.name,
                                  "microphone": "recorded speech" if mic_files else cfg["mic"]},
                      "Timing": {}}
        self.dirty = set()
        bus.add_signal_receiver(self.on_input, "Input", VEHICLE[2], None, VEHICLE[1])
        bus.add_signal_receiver(self.on_props, "PropertiesChanged", PROPS, None, None, path_keyword="path")
        bus.add_signal_receiver(self.on_raised, "Raised", WARNINGS[2], None, WARNINGS[1])
        bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus")
        GLib.idle_add(self.read_all)
        GLib.timeout_add(100, self.flush)
        self.load()

    # ---- engines ---------------------------------------------------------------------------
    def load(self):
        c = self.cfg
        t0 = time.monotonic()

        def job():
            rec, voice = speech.load(c["recognizer"], c["voice"], c["model_dir"], c["recognizer_model"],
                                     c["voice_model"], c["threads"])
            cache = {p: voice.say(p, c["speed"]) for p in (c["greeting"], c["not_heard"], c["conversation_end"]) if p}
            return rec, voice, cache

        def done(r, err):
            if err:
                log_speech.error(f"speech engines not loaded ({c['recognizer']}, {c['voice']}): {err}")
                self.set("Notice", f"speech not available: {err}")
                return
            self.rec, self.voice, self.cache = r
            self.player = Player(self.voice.rate, self.sink)
            self.player.set_gain(self.gain)
            self.set("Available", True)
            log_speech.info(f"speech engines loaded in {time.monotonic() - t0:.1f} s: {c['recognizer']}, "
                            f"{c['voice']} ({self.voice.rate} Hz)")
        self.worker.submit(job, done)

    # ---- the other services ----------------------------------------------------------------
    def read_all(self):
        for svc, path, iface in (VEHICLE, AUDIO, SYSTEM):
            self.bus.call_async(svc, path, PROPS, "GetAll", "s", (iface,),
                                lambda p, i=iface: self.on_props(i, p, [], None), lambda e: None, timeout=1.0)
        return False

    def on_owner(self, name, _old, new):
        if new and name in (VEHICLE[0], AUDIO[0], SYSTEM[0]):
            self.read_all()

    def on_props(self, iface, changed, _inv, path=None):
        iface = str(iface)
        if iface == VEHICLE[2] and "Power" in changed:
            self.power = str(changed["Power"])
            if self.power in ("off", "shutdown"):
                self.stop("the HU went off")
        elif iface == AUDIO[2]:
            if "CallState" in changed:
                self.call = str(changed["CallState"])
                if self.call != "idle":
                    self.stop("a call")
            if "Gains" in changed and "voice" in changed["Gains"]:
                self.gain = float(changed["Gains"]["voice"])
                if self.player:
                    self.player.set_gain(self.gain)
        elif iface == SYSTEM[2] and "Settings" in changed:
            on = bool(changed["Settings"].get(SETTING, True))
            self.set("Enabled", on)
            if not on:
                self.stop("switched off")

    def on_raised(self, _rid, severity, _text):
        if str(severity) == "warning":
            self.stop("a warning")

    def on_input(self, kind, _value):
        kind = str(kind)
        if kind not in ("button:VOICE", "button:TALK"):
            return
        # the power state now, as hu-audiod does: a key right after power-on beats the batched news
        self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS, "Get", "ss", (VEHICLE[2], "Power"),
                            lambda p: self.on_key(kind, str(p)),
                            lambda e: log.warning(f"ignoring {kind}: no power state from hu-vehicled ({e})"),
                            timeout=1.0)

    def on_key(self, kind, power):
        self.power = power
        if kind == "button:VOICE":
            self.Command()
        else:
            self.Conversation()

    def voice_state(self, state):
        self.bus.call_async(AUDIO[0], AUDIO[1], AUDIO[2], "SetVoice", "s", (state,),
                            lambda *_: None, lambda e: None, timeout=1.0)

    # ---- the session -----------------------------------------------------------------------
    def refuse(self, why) -> bool:
        if not self.props["Enabled"]:
            why = "switched off"
        elif not self.props["Available"]:
            why = "speech not available" if self.props["Notice"].startswith("speech not") else "still loading"
        elif self.power in ("off", "shutdown"):
            why = "the HU is off"
        elif self.call != "idle":
            why = "a call"
        if why:
            log.info(f"not starting: {why}")
            self.set("Notice", why if why != "speech not available" else self.props["Notice"])
        return bool(why)

    def begin(self, mode):
        if self.refuse(""):
            return
        self.session += 1
        self.history = []
        self.last_talk = time.monotonic()
        self.set("Mode", mode)
        self.set("Heard", "")
        self.set("Answer", "")
        self.set("Turns", 0)
        self.set("Notice", "")
        self.set("Sessions", self.props["Sessions"] + 1)
        log.info(f"{mode} mode")
        self.say(self.cfg["greeting"], "greeting", self.listen)

    def end(self, why=""):
        if self.props["Mode"] == "idle":
            return
        self.session += 1
        self.mic.stop()
        if self.player:
            self.player.stop()
        log.info(f"{self.props['Mode']} mode ended after {self.props['Turns']} answer(s)" + (f": {why}" if why else ""))
        self.history = []                 # a conversation's summary (its memory) comes later
        self.set("Mode", "idle")
        self.set("State", "idle")
        if why:
            self.set("Notice", why)
        self.voice_state("idle")

    def stop(self, why):
        if self.props["Mode"] != "idle":
            self.end(why)

    def listen(self):
        s = self.session
        self.set("State", "listening")
        self.voice_state("listen")
        c = self.cfg
        no_speech = c["no_speech_s"]
        if self.props["Mode"] == "conversation":     # waits for the driver; ends by itself only after the idle time
            no_speech = max(1.0, min(c["no_speech_s"], c["conversation_idle_s"] - (time.monotonic() - self.last_talk)))
        ep = speech.Endpointer(speech.RATE, c["speech_level_db"], c["end_silence_ms"], c["max_speech_s"], no_speech)
        self.t["listen"] = time.monotonic()
        self.mic.listen(ep, lambda utt: s == self.session and self.heard(utt))

    def heard(self, utt):
        if utt is None:
            return self.nothing()
        s = self.session
        self.set("State", "thinking")
        self.voice_state("speak")
        self.t["speech_s"] = utt.seconds
        t0 = time.monotonic()

        def done(text, err):
            if s != self.session:
                return
            if err:
                log_speech.error(f"recognizer failed: {err}")
            self.t["recognise_s"] = time.monotonic() - t0
            if not text:
                return self.nothing()
            self.last_talk = time.monotonic()
            self.set("Heard", text)
            log.info(f"heard {utt.seconds:.1f} s of speech, {len(text.split())} words, recognised in "
                     f"{self.t['recognise_s']:.2f} s")
            self.history.append({"role": "user", "content": text})
            t1 = time.monotonic()
            self.brain.ask(list(self.history), lambda answer: s == self.session and self.answer(answer, t1))
        self.worker.submit(lambda: self.rec.recognize(utt), done)

    def nothing(self):
        if self.props["Mode"] == "command":
            log.info("nothing heard")
            self.say(self.cfg["not_heard"], "speaking", lambda: self.end())
        elif time.monotonic() - self.last_talk >= self.cfg["conversation_idle_s"]:
            self.say(self.cfg["conversation_end"], "speaking", lambda: self.end("nobody talked"))
        else:
            self.listen()

    def answer(self, text, t1):
        self.t["think_s"] = time.monotonic() - t1
        self.history.append({"role": "assistant", "content": text})
        self.set("Answer", text)
        self.set("Turns", self.props["Turns"] + 1)
        then = self.end if self.props["Mode"] == "command" else self.listen
        self.say(text, "speaking", then)

    def say(self, text, state, then):
        """Speak text (cut into phrases), then call then() unless the session moved on."""
        s = self.session
        self.set("State", state)
        self.voice_state("speak")
        if not text:
            GLib.idle_add(lambda: (s == self.session and then(), False)[1])
            return
        t0 = time.monotonic()
        first = []

        def finished():
            if s != self.session:
                return
            if state == "speaking":
                self.publish_timing(first[0] - t0 if first else None)
            then()
        self.player.start(finished)
        parts = [text] if text in self.cache else speech.phrases(text)

        def job():
            for p in parts:
                if s != self.session:
                    return
                pcm = self.cache.get(p) or self.voice.say(p, self.cfg["speed"])
                if s != self.session:
                    return
                if not first:
                    first.append(time.monotonic())
                self.player.push(pcm)
            self.player.end()

        def done(_r, err):
            if err and s == self.session:
                log_speech.error(f"voice failed: {err}")
                self.player.finished()
        self.worker.submit(job, done)

    def publish_timing(self, first_sound):
        t = {k: round(v, 3) for k, v in self.t.items() if k.endswith("_s")}
        if first_sound is not None:
            t["first_sound_s"] = round(first_sound, 3)
        self.set("Timing", t)
        log.info("timing: " + ", ".join(f"{k} {v:.2f}" for k, v in t.items()))

    # ---- properties --------------------------------------------------------------------------
    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def variant(self, name):
        v = self.props[name]
        if name == "Engines":
            return dbus.Dictionary({k: dbus.String(x) for k, x in v.items()}, signature="ss")
        if name == "Timing":
            return dbus.Dictionary({k: dbus.Double(x) for k, x in v.items()}, signature="sd")
        if isinstance(v, bool):
            return dbus.Boolean(v)
        if isinstance(v, int):
            return dbus.UInt32(v)
        return dbus.String(v)

    def flush(self):
        if self.dirty:
            changed = {k: self.variant(k) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))
        return True

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        if name not in self.props:
            raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")
        return self.variant(name)

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: self.variant(k) for k in self.props}, signature="sv")

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    # ---- methods -------------------------------------------------------------------------------
    @dbus.service.method(IFACE)
    def Command(self):
        """Command mode; while the assistant runs (either mode): stop it."""
        if self.props["Mode"] != "idle":
            self.end()
        else:
            self.begin("command")

    @dbus.service.method(IFACE)
    def Conversation(self):
        """Conversation mode; pressed again: "Okay" and end. From command mode: a conversation instead."""
        mode = self.props["Mode"]
        if mode == "conversation":
            self.session += 1
            self.mic.stop()
            self.say(self.cfg["conversation_end"], "speaking", lambda: self.end())
        else:
            if mode == "command":
                self.end()
            self.begin("conversation")

    @dbus.service.method(IFACE)
    def Stop(self):
        self.end()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/assistant.ini and /etc/r80/assistant.ini")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    ap.add_argument("--sink", default=None, help="GStreamer audio sink for the voice (e.g. fakesink for tests)")
    ap.add_argument("--mic-files", help="recorded speech instead of the microphone: a folder of WAVs (tests)")
    ap.add_argument("--recognizer", choices=("moonshine", "transcript"), help="instead of assistant.ini's")
    ap.add_argument("--voice", choices=("piper", "silent"), help="instead of assistant.ini's")
    ap.add_argument("--check", action="store_true", help="only check the config")
    a = ap.parse_args()
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[assistd] bad config: {e}")
    cfg["recognizer"] = a.recognizer or cfg["recognizer"]
    cfg["voice"] = a.voice or cfg["voice"]
    if a.check:
        print(cfg)
        return
    dlt.app("AST", "Voice assistant", "assistd")
    Gst.init(None)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Assistant(bus, cfg, a.sink, Path(a.mic_files) if a.mic_files else None)
    log.info(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
