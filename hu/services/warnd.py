#!/usr/bin/env python3
"""hu-warnd: vehicle warnings of the R80 headunit (decision D10).

Watches the signals hu-vehicled publishes and raises warnings by the rules in
hu/warnings.ini (then /etc/r80/warnings.ini, then --config):

    bus name   de.r80.Warnings
    object     /de/r80/Warnings
    interface  de.r80.Warnings1
      properties  Active (aa{sv}): one dict per active warning, most severe first:
                  id (s), severity (s: notice|information|warning), text (s), value (d),
                  since (d: seconds the warning is active), acknowledged (b)
                  LastChime (s: information|warning|""), LastChimeGain (d), ChimeCount (u)
      methods     Acknowledge(s id), AcknowledgeAll()
      signal      Raised(s id, s severity, s text)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Severity says how soon the driver has to act (Alex, D10):
  warning      within seconds (tyre pressure falling fast, oil pressure gone)
  information  within minutes or hours; the car can still reach a workshop or fuel
  notice       not dangerous, some time soon (service due)

Rule kinds: threshold with hysteresis (optionally a band, at_least), drop rate (bar/s
over a window; a fast tyre pressure drop is urgent even while the value is still fine),
difference between two signals, and missing data (hu-vehicled StaleSignals). A rule
can require the engine to run. Texts get {value}, {value_abs} and {label}.
Warnings are only evaluated while the HU is on; an acknowledged warning stays in the
list but does not pop up again until it has cleared.

Chimes: a newly raised "information" plays the information chime, a "warning" the
warning chime (a notice is silent; several at once play only the most urgent one). Both
are generated in code at start (no sound files). warnd plays them at the level hu-audiod
publishes (Gains["chime"], or WarningChimeGain, which ignores mute) and tells audiod
(SetChime) so the music ducks meanwhile.

The rule logic (Engine) has no D-Bus, so tests can drive it with their own clock.
"""
from __future__ import annotations

import argparse
import bisect
import configparser
import math
import os
import sys
import time
import wave
from array import array
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent / "warnings.ini"
SYSTEM_CONFIG = Path("/etc/r80/warnings.ini")
SEVERITIES = ("notice", "information", "warning")       # least to most urgent
RULE_KEYS = {"signal", "signals", "labels", "below", "at_least", "above", "clear_above", "clear_below",
             "drop_rate", "window_s", "hold_s", "diff_above", "diff_clear", "stale",
             "for_s", "when", "severity", "text"}


def log(*a):
    print("[warnd]", *a, flush=True)


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> tuple[dict, list]:
    """Read the config files in order; return (general settings, list of rules)."""
    cp = configparser.ConfigParser(interpolation=None)
    files = [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else [])
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in files if f.is_file()])
    if not cp.has_section("general"):
        raise ConfigError("missing [general]")

    def num(section, key, default=None, lo=0.0):
        if not cp.has_option(section, key):
            if default is None:
                raise ConfigError(f"[{section}] {key} missing")
            return default
        try:
            v = float(cp.get(section, key))
        except ValueError as e:
            raise ConfigError(f"[{section}] {key}: {e}") from None
        if v < lo:
            raise ConfigError(f"[{section}] {key} = {v} is below {lo}")
        return v

    unknown = set(cp.options("general")) - {"active_power", "engine_running_rpm"}
    if unknown:
        raise ConfigError(f"[general] unknown key(s): {', '.join(sorted(unknown))}")
    general = {
        "active_power": [p.strip() for p in cp.get("general", "active_power", fallback="on").split(",") if p.strip()],
        "engine_running_rpm": num("general", "engine_running_rpm", 400),
    }

    rules, stale_sections = [], []
    for s in cp.sections():
        if s == "general":
            continue
        sec = cp[s]
        unknown = set(sec.keys()) - RULE_KEYS
        if unknown:
            raise ConfigError(f"[{s}] unknown key(s): {', '.join(sorted(unknown))}")
        severity = sec.get("severity", "")
        if severity not in SEVERITIES:
            raise ConfigError(f"[{s}] severity = {severity!r}, expected one of {', '.join(SEVERITIES)}")
        when = sec.get("when", "").strip()
        if when not in ("", "engine_running"):
            raise ConfigError(f"[{s}] when = {when!r}, expected engine_running or nothing")
        if "text" not in sec:
            raise ConfigError(f"[{s}] text missing")
        signals = [x.strip() for x in sec.get("signals", sec.get("signal", "")).split(",") if x.strip()]
        if not signals:
            raise ConfigError(f"[{s}] signal or signals missing")
        labels = [x.strip() for x in sec.get("labels", "").split(",") if x.strip()]
        if labels and len(labels) != len(signals):
            raise ConfigError(f"[{s}] {len(labels)} labels for {len(signals)} signals")
        base = {"section": s, "severity": severity, "text": sec["text"], "for_s": num(s, "for_s", 0.0),
                "engine": when == "engine_running"}
        kinds = [k for k in ("below", "above", "drop_rate", "diff_above", "stale") if k in sec]
        if len(kinds) != 1:
            raise ConfigError(f"[{s}] needs exactly one of below, above, drop_rate, diff_above, stale")
        kind = kinds[0]
        if "at_least" in sec and kind != "below":
            raise ConfigError(f"[{s}] at_least only goes with below")
        if kind == "stale":
            if sec.get("stale").strip().lower() not in ("yes", "true", "1"):
                raise ConfigError(f"[{s}] stale must be yes")
            stale_sections.append((base, signals))
            continue
        if kind == "diff_above":
            if len(signals) != 2:
                raise ConfigError(f"[{s}] diff_above needs exactly two signals")
            d = num(s, "diff_above")
            rules.append(dict(base, id=s, kind="diff", signals=signals, label=", ".join(labels or signals),
                              raise_=d, clear=num(s, "diff_clear", d)))
            continue
        for i, sig in enumerate(signals):
            r = dict(base, id=s if len(signals) == 1 else f"{s}.{sig}", signals=[sig],
                     label=labels[i] if labels else sig)
            if kind == "below":
                b = num(s, "below", lo=-1e9)
                r.update(kind="below", raise_=b, clear=num(s, "clear_above", b, lo=-1e9),
                         floor=num(s, "at_least", -1e18, lo=-1e18))
                if r["clear"] < b:
                    raise ConfigError(f"[{s}] clear_above must not be below 'below'")
                if r["floor"] >= b:
                    raise ConfigError(f"[{s}] at_least must be below 'below'")
            elif kind == "above":
                a = num(s, "above", lo=-1e9)
                r.update(kind="above", raise_=a, clear=num(s, "clear_below", a, lo=-1e9))
                if r["clear"] > a:
                    raise ConfigError(f"[{s}] clear_below must not be above 'above'")
            else:
                r.update(kind="rate", raise_=num(s, "drop_rate"), window=num(s, "window_s", 2.0),
                         hold=num(s, "hold_s", 10.0))
                if r["window"] <= 0:
                    raise ConfigError(f"[{s}] window_s must be above 0")
            rules.append(r)

    used = sorted({sig for r in rules for sig in r["signals"]}
                  | ({"EngineSpeed"} if any(r["engine"] for r in rules) else set()))
    for base, signals in stale_sections:
        for sig in (used if signals == ["*"] else signals):
            rules.append(dict(base, id=f"{base['section']}.{sig}", kind="stale", signals=[sig], label=sig))
    for r in rules:                                          # the text must format
        try:
            r["text"].format(value=0.0, value_abs=0.0, label="x")
        except (KeyError, ValueError, IndexError) as e:
            raise ConfigError(f"[{r['section']}] text: {e}") from None
    ids = [r["id"] for r in rules]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate warning ids")
    return general, rules


CHIME_RATE = 44100


def _tone(notes, rate=CHIME_RATE):
    """notes: (start s, freq Hz, length s, level 0..1). Bell-like: 5 ms attack, exponential
    decay, a quiet octave on top; every note ends at zero so nothing clicks."""
    end = max(s + d for s, _f, d, _l in notes)
    out = [0.0] * int(end * rate + 1)
    for start, freq, dur, level in notes:
        n0, n = int(start * rate), int(dur * rate)
        attack, release = int(0.005 * rate), int(0.02 * rate)
        for i in range(n):
            env = min(1.0, i / attack, (n - i) / release) * math.exp(-3.0 * i / n)
            ph = 2 * math.pi * freq * i / rate
            out[n0 + i] += level * env * (0.8 * math.sin(ph) + 0.2 * math.sin(2 * ph))
    return array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in out))


def make_chimes(folder: Path) -> dict:
    """Write the two chimes as WAV files; return {"information": path, "warning": path}."""
    folder.mkdir(parents=True, exist_ok=True)
    chimes = {
        # soft, falling two-note bell
        "information": _tone([(0.0, 880.0, 0.35, 0.35), (0.22, 660.0, 0.55, 0.35)]),
        # urgent: two groups of three short high beeps
        "warning": _tone([(g * 0.75 + k * 0.17, 1320.0, 0.12, 0.45) for g in range(2) for k in range(3)]),
    }
    paths = {}
    for kind, samples in chimes.items():
        if sys.byteorder == "big":
            samples.byteswap()
        path = folder / f"chime-{kind}.wav"
        with wave.open(str(path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(CHIME_RATE)
            w.writeframes(samples.tobytes())
        paths[kind] = path
    return paths


def chime_for(severities) -> str:
    """The one chime to play for warnings raised together: the most urgent, none for notices."""
    if "warning" in severities:
        return "warning"
    if "information" in severities:
        return "information"
    return ""


class Engine:
    """The rules, fed with timestamped signal values. No D-Bus, no clock of its own."""

    def __init__(self, general: dict, rules: list):
        self.general, self.rules = general, rules
        self.history = {}           # signal -> ([times], [values]), step function
        self.keep = max([r.get("window", 0) for r in rules] + [1.0]) + 1.0
        self.stale = set()
        self.power = "off"
        self.state = {r["id"]: {"pending": None, "last_true": None} for r in rules}
        self.active = {}            # id -> {"severity", "text", "value", "raised", "acknowledged"}

    # ---- input ----
    def feed(self, now: float, name: str, value) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        ts, vs = self.history.setdefault(name, ([], []))
        ts.append(now)
        vs.append(float(value))
        while len(ts) > 2 and ts[1] < now - self.keep:       # keep one sample before the window
            ts.pop(0)
            vs.pop(0)

    def value_at(self, name: str, t: float):
        ts, vs = self.history.get(name, ([], []))
        i = bisect.bisect_right(ts, t) - 1
        return vs[i] if i >= 0 else None

    # ---- evaluation ----
    def condition(self, r: dict, now: float):
        """(raise?, clear?, value) of one rule now."""
        if r["kind"] == "stale":
            missing = r["signals"][0] in self.stale
            return missing, not missing, None
        if any(sig in self.stale for sig in r["signals"]):
            return False, True, None                          # old data: sensor_missing reports it
        if r["engine"]:
            rpm = self.value_at("EngineSpeed", now)
            if rpm is None or rpm <= self.general["engine_running_rpm"]:
                return False, True, None
        if r["kind"] == "diff":
            a, b = (self.value_at(sig, now) for sig in r["signals"])
            if a is None or b is None:
                return False, True, None
            d = abs(a - b)
            return d > r["raise_"], d <= r["clear"], d
        v = self.value_at(r["signals"][0], now)
        if v is None:
            return False, True, None
        if r["kind"] == "below":                               # at_least: a band, e.g. 0..1000 km
            return r["floor"] <= v < r["raise_"], v >= r["clear"] or v < r["floor"], v
        if r["kind"] == "above":
            return v > r["raise_"], v <= r["clear"], v
        # rate: drop per second over the window; the value holds until the next sample
        ts = self.history[r["signals"][0]][0]
        if not ts or ts[0] > now - r["window"]:
            return False, False, None                         # not enough history yet
        then = self.value_at(r["signals"][0], now - r["window"])
        rate = (then - v) / r["window"]
        st = self.state[r["id"]]
        if rate >= r["raise_"]:
            st["last_true"] = now
        held = st["last_true"] is not None and now - st["last_true"] < r["hold"]
        return rate >= r["raise_"], not held, rate

    def evaluate(self, now: float) -> tuple[list, list]:
        """Update the active warnings; return (raised ids, cleared ids)."""
        raised, cleared = [], []
        if self.power not in self.general["active_power"]:
            cleared = list(self.active)
            self.active.clear()
            for st in self.state.values():
                st["pending"] = None
                st["last_true"] = None
            return raised, cleared
        for r in self.rules:
            rid, st = r["id"], self.state[r["id"]]
            up, down, value = self.condition(r, now)
            if rid in self.active:
                if down:
                    del self.active[rid]
                    cleared.append(rid)
                elif value is not None:
                    self.active[rid]["value"] = value
                    self.active[rid]["text"] = r["text"].format(value=value, value_abs=abs(value), label=r["label"])
                continue
            if not up:
                st["pending"] = None
                continue
            if st["pending"] is None:
                st["pending"] = now
            if now - st["pending"] >= r["for_s"]:
                st["pending"] = None
                self.active[rid] = {"severity": r["severity"], "value": value if value is not None else 0.0,
                                    "text": r["text"].format(value=value if value is not None else 0.0,
                                                             value_abs=abs(value) if value is not None else 0.0,
                                                             label=r["label"]),
                                    "raised": now, "acknowledged": False}
                raised.append(rid)
        return raised, cleared

    def acknowledge(self, rid: str) -> bool:
        if rid in self.active:
            self.active[rid]["acknowledged"] = True
            return True
        return False

    def listing(self, now: float) -> list:
        order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
        items = sorted(self.active.items(), key=lambda kv: (order[kv[1]["severity"]], kv[1]["raised"]))
        return [{"id": rid, "severity": w["severity"], "text": w["text"], "value": float(w["value"]),
                 "since": round(now - w["raised"], 1), "acknowledged": w["acknowledged"]} for rid, w in items]


def run_service(general: dict, rules: list, system: bool, sink: str | None, chime_dir: Path):
    import dbus
    import dbus.service
    import gi
    from dbus.mainloop.glib import DBusGMainLoop
    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst
    Gst.init(None)
    AUDIO = ("de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1")
    chime_files = make_chimes(chime_dir)

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.Warnings", "/de/r80/Warnings", "de.r80.Warnings1"
    PROPS = "org.freedesktop.DBus.Properties"
    VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")

    class Warnings(dbus.service.Object):
        def __init__(self, bus):
            super().__init__(bus, OBJ_PATH)
            self.bus = bus
            self.engine = Engine(general, rules)
            self.published = None
            self.chime = {"last": "", "gain": 0.0, "count": 0, "playing": ""}
            self.levels = {"information": 0.5, "warning": 1.0}      # until hu-audiod says otherwise
            self.player = self.make_player()
            bus.add_signal_receiver(self.on_audio, "PropertiesChanged", PROPS, None, AUDIO[1])
            bus.add_signal_receiver(self.on_vehicle, "PropertiesChanged", PROPS, None, VEHICLE[1])
            bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                    "org.freedesktop.DBus", "/org/freedesktop/DBus")
            GLib.idle_add(self.read_all)
            GLib.timeout_add(100, self.tick)

        # ---- chimes ----
        def make_player(self):
            player = Gst.ElementFactory.make("playbin", "chime")
            out = Gst.Bin.new("chime-out")
            self.gain_el = Gst.ElementFactory.make("volume", None)
            conv, res = Gst.ElementFactory.make("audioconvert", None), Gst.ElementFactory.make("audioresample", None)
            snk = Gst.ElementFactory.make(sink or "autoaudiosink", None)
            if sink and snk.find_property("sync") is not None:
                snk.set_property("sync", True)
            for e in (self.gain_el, conv, res, snk):
                out.add(e)
            self.gain_el.link(conv)
            conv.link(res)
            res.link(snk)
            out.add_pad(Gst.GhostPad.new("sink", self.gain_el.get_static_pad("sink")))
            player.set_property("audio-sink", out)
            pbus = player.get_bus()
            pbus.add_signal_watch()
            pbus.connect("message::eos", lambda *_: self.chime_done())
            pbus.connect("message::error", lambda _b, m: (log(f"chime error: {m.parse_error()[0].message}"), self.chime_done()))
            return player

        def play_chime(self, kind):
            if not kind:
                return
            if self.chime["playing"] and SEVERITIES.index(kind) <= SEVERITIES.index(self.chime["playing"]):
                return                                   # one at a time; only a more urgent one interrupts
            gain = self.levels[kind]
            self.player.set_state(Gst.State.NULL)
            self.gain_el.set_property("volume", gain)
            self.player.set_property("uri", chime_files[kind].as_uri())
            self.chime.update(last=kind, gain=gain, count=self.chime["count"] + 1, playing=kind)
            self.audio_call("SetChime", "b", (True,))   # duck the music meanwhile
            self.player.set_state(Gst.State.PLAYING)
            log(f"chime {kind} at gain {gain:.2f}")
            self.publish_chime()

        def chime_done(self):
            self.player.set_state(Gst.State.NULL)
            self.chime["playing"] = ""
            self.audio_call("SetChime", "b", (False,))

        def audio_call(self, method, sig, args):
            self.bus.call_async(AUDIO[0], AUDIO[1], AUDIO[2], method, sig, args,
                                lambda *_: None, lambda e: None, timeout=1.0)

        def on_audio(self, iface, changed, _inv):
            if iface != AUDIO[2]:
                return
            if "Gains" in changed and "chime" in changed["Gains"]:
                self.levels["information"] = float(changed["Gains"]["chime"])
            if "WarningChimeGain" in changed:
                self.levels["warning"] = float(changed["WarningChimeGain"])

        def chime_props(self):
            return {"LastChime": dbus.String(self.chime["last"]), "LastChimeGain": dbus.Double(self.chime["gain"]),
                    "ChimeCount": dbus.UInt32(self.chime["count"])}

        def publish_chime(self):
            self.PropertiesChanged(IFACE, dbus.Dictionary(self.chime_props(), signature="sv"),
                                   dbus.Array([], signature="s"))

        # ---- vehicle and rules ----
        def read_all(self):
            self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS, "GetAll", "s", (VEHICLE[2],),
                                lambda props: self.on_vehicle(VEHICLE[2], props, []), lambda e: None, timeout=1.0)
            self.bus.call_async(AUDIO[0], AUDIO[1], PROPS, "GetAll", "s", (AUDIO[2],),
                                lambda props: self.on_audio(AUDIO[2], props, []), lambda e: None, timeout=1.0)
            return False

        def on_owner(self, name, _old, new):
            if name in (VEHICLE[0], AUDIO[0]) and new:
                self.read_all()

        def on_vehicle(self, iface, changed, _inv):
            if iface != VEHICLE[2]:
                return
            now = time.monotonic()
            for k, v in changed.items():
                k = str(k)
                if k == "Power":
                    self.engine.power = str(v)
                elif k == "StaleSignals":
                    self.engine.stale = {str(x) for x in v}
                elif isinstance(v, (dbus.Double, dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32,
                                    dbus.UInt64, dbus.Byte)):
                    self.engine.feed(now, k, float(v))

        def tick(self):
            now = time.monotonic()
            raised, cleared = self.engine.evaluate(now)
            for rid in raised:
                w = self.engine.active[rid]
                log(f"raised {rid} ({w['severity']}): {w['text']}")
                self.Raised(rid, w["severity"], w["text"])
            self.play_chime(chime_for([self.engine.active[rid]["severity"] for rid in raised]))
            for rid in cleared:
                log(f"cleared {rid}")
            listing = self.engine.listing(now)
            # publish when the set, a text or the acknowledged flags change (not every 'since' tick)
            key = [(w["id"], w["text"], w["acknowledged"]) for w in listing]
            if key != self.published:
                self.published = key
                self.PropertiesChanged(IFACE, dbus.Dictionary({"Active": self.active_variant(listing)},
                                                              signature="sv"), dbus.Array([], signature="s"))
            return True

        def active_variant(self, listing):
            return dbus.Array([dbus.Dictionary({
                "id": dbus.String(w["id"]), "severity": dbus.String(w["severity"]),
                "text": dbus.String(w["text"]), "value": dbus.Double(w["value"]),
                "since": dbus.Double(w["since"]), "acknowledged": dbus.Boolean(w["acknowledged"]),
            }, signature="sv") for w in listing], signature="a{sv}")

        def all_props(self):
            return dict(self.chime_props(), Active=self.active_variant(self.engine.listing(time.monotonic())))

        @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, name):
            props = self.all_props()
            if name not in props:
                raise dbus.exceptions.DBusException(f"no property {name}",
                                                    name="org.freedesktop.DBus.Error.UnknownProperty")
            return props[name]

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary(self.all_props(), signature="sv")

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

        @dbus.service.signal(IFACE, signature="sss")
        def Raised(self, rid, severity, text):
            pass

        @dbus.service.method(IFACE, in_signature="s")
        def Acknowledge(self, rid):
            if not self.engine.acknowledge(str(rid)):
                raise dbus.exceptions.DBusException(f"no active warning {rid!r}",
                                                    name="de.r80.Warnings1.Error.NotActive")

        @dbus.service.method(IFACE)
        def AcknowledgeAll(self):
            for rid in list(self.engine.active):
                self.engine.acknowledge(rid)

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Warnings(bus)
    log(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, {len(rules)} rules")
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/warnings.ini and /etc/r80/warnings.ini")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    ap.add_argument("--check", action="store_true", help="only check the config and list the rules")
    ap.add_argument("--sink", default=None, help="GStreamer audio sink for the chimes (e.g. fakesink for tests)")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    ap.add_argument("--chime-dir", default=str(runtime / "r80-chimes"), help="where the generated chimes go")
    a = ap.parse_args()
    try:
        general, rules = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[warnd] bad config: {e}")
    if a.check:
        for r in rules:
            print(f"{r['id']:34} {r['kind']:6} {r['severity']:8} {', '.join(r['signals'])}")
        return
    run_service(general, rules, a.system, a.sink, Path(a.chime_dir))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
