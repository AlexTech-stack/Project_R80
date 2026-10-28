#!/usr/bin/env python3
"""hu-audiod: the audio service of the R80 headunit. It alone owns volume and mute.

    bus name   de.r80.Audio
    object     /de/r80/Audio
    interface  de.r80.Audio1
      properties  Max (i), Master (i), Muted (b), StartupCap (i),
                  Volumes (a{si}: source -> 0..Max), Gains (a{sd}: source -> 0.0..1.0),
                  Tone (a{sv}: bass, treble (dB), balance (-1..1), loudness; kept until a DSP applies them),
                  NavPrompt (b), CallState (s: idle|ringing|active), Duck (d: 1.0 = none),
                  Chime (b), WarningChimeGain (d), Voice (s: idle|listen|speak)
      methods     SetMaster(i), Step(i delta), SetMuted(b), ToggleMute(),
                  SetVolume(s source, i value), SetNavPrompt(b), SetCallState(s), SetChime(b),
                  SetVoice(s), SetTone(s name, v value)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Sources: media, navigation, phone, radio, chime, voice. For each source audiod computes the level
it should play at (Gains) and the source applies it to its own player: mediad gets it
through de.r80.Media1.SetGain, phoned (the call's sound) through de.r80.Phone1.SetGain,
times call_boost_db (speech arrives far quieter than music).
Navigation and radio have no service yet; their gains are already published for when
they do.

    gain = ((Master / Max) * (Volumes[source] / Max)) ** curve      (0 while muted)

Rules between sources ([focus] in audio.ini, decision D9):
- While a navigation prompt plays (SetNavPrompt), media and radio fade to duck_level.
- During a call (SetCallState; from "ringing" or only "active", see call_starts_on)
  mediad is paused if it was playing and resumed afterwards, and radio is at gain 0.
- Mute silences everything except the phone during a call (mute_spares_call).
- When hu-vehicled's Power goes "off" (after the shutdown save) mediad is paused if it
  was playing, and plays again when the power is back (pause_media_when_off).
- While a chime plays (SetChime, from hu-warnd), media and radio duck as for a prompt.
- The voice assistant (hu-assistd, SetVoice): while it speaks, media and radio duck as for a
  prompt; while it listens they go down to listen_duck_level (the microphone hears the music).
- The information chime is a normal source ("chime"); the warning chime (D10: the driver
  has to act within seconds) plays at WarningChimeGain: the chime volume ignoring mute,
  but never below warning_chime_min_gain.
The navigation and phone services do not exist yet; until then tests and the UI's
simulated call report prompts and calls.

The MCU's VOL_UP / VOL_DOWN / MUTE buttons (de.r80.Vehicle1.Input) go straight to
audiod, so volume keeps working without the UI; they are ignored while the HU is off.

Numbers come from hu/audio.ini (then /etc/r80/audio.ini, then --config, each overriding
the one before). The master and source volumes are state, not config: they are saved
to --state (default $XDG_STATE_HOME/r80/audio.json) and the master volume is capped at
StartupCap when audiod starts. Mute is not remembered.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import sys
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

import dlt
from saver import register_saver

BUS_NAME = "de.r80.Audio"
OBJ_PATH = "/de/r80/Audio"
IFACE = "de.r80.Audio1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
SOURCES = ("media", "navigation", "phone", "radio", "chime", "voice")
VOICE_STATES = ("idle", "listen", "speak")
VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")
MEDIA = ("de.r80.Media", "/de/r80/Media", "de.r80.Media1")
PHONE = ("de.r80.Phone", "/de/r80/Phone", "de.r80.Phone1")
DEFAULT_CONFIG = Path(__file__).resolve().parent / "audio.ini"
SYSTEM_CONFIG = Path("/etc/r80/audio.ini")


log = dlt.context("MAIN", "Audio service")


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> dict:
    """Read the config files in order and return checked values."""
    cp = configparser.ConfigParser()
    files = [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else [])
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in files if f.is_file()])
    used = {"volume": {"max", "startup_cap", "default_master", "curve", "change_fade_ms", "call_boost_db"}
            | {f"default_{s}" for s in SOURCES},
            "focus": {"duck_level", "listen_duck_level", "duck_fade_ms", "call_starts_on", "resume_media_after_call", "pause_media_when_off",
                      "call_mutes_radio", "mute_spares_call", "warning_chime_min_gain"},
            "tone": {"tone_range_db", "default_bass", "default_treble", "default_balance", "default_loudness"}}

    def get(section, key, conv):
        try:
            return conv(cp.get(section, key))
        except (configparser.Error, ValueError) as e:
            raise ConfigError(f"[{section}] {key}: {e}") from None

    def num(section, key, conv, lo, hi):
        v = get(section, key, conv)
        if not lo <= v <= hi:
            raise ConfigError(f"[{section}] {key} = {v} is outside {lo}..{hi}")
        return v

    def flag(section, key):
        try:
            return cp.getboolean(section, key)
        except (configparser.Error, ValueError) as e:
            raise ConfigError(f"[{section}] {key}: {e}") from None

    def choice(section, key, options):
        v = get(section, key, str).strip()
        if v not in options:
            raise ConfigError(f"[{section}] {key} = {v!r}, expected one of {', '.join(options)}")
        return v

    vmax = num("volume", "max", int, 1, 1000)
    cfg = {
        "max": vmax,
        "startup_cap": num("volume", "startup_cap", int, 0, vmax),
        "default_master": num("volume", "default_master", int, 0, vmax),
        "curve": num("volume", "curve", float, 0.1, 10.0),
        "change_fade_ms": num("volume", "change_fade_ms", int, 0, 1000),
        "call_boost_db": num("volume", "call_boost_db", float, 0.0, 18.0),
        "default_volumes": {s: num("volume", f"default_{s}", int, 0, vmax) for s in SOURCES},
        "duck_level": num("focus", "duck_level", float, 0.0, 1.0),
        "listen_duck_level": num("focus", "listen_duck_level", float, 0.0, 1.0),
        "warning_chime_min_gain": num("focus", "warning_chime_min_gain", float, 0.0, 1.0),
        "duck_fade_ms": num("focus", "duck_fade_ms", int, 0, 5000),
        "call_starts_on": choice("focus", "call_starts_on", ("ring", "answer")),
        "resume_media_after_call": flag("focus", "resume_media_after_call"),
        "pause_media_when_off": flag("focus", "pause_media_when_off"),
        "call_mutes_radio": flag("focus", "call_mutes_radio"),
        "mute_spares_call": flag("focus", "mute_spares_call"),
    }
    rng = num("tone", "tone_range_db", int, 1, 24)
    cfg["tone_range_db"] = rng
    cfg["default_tone"] = {"bass": num("tone", "default_bass", int, -rng, rng),
                           "treble": num("tone", "default_treble", int, -rng, rng),
                           "balance": num("tone", "default_balance", float, -1.0, 1.0),
                           "loudness": flag("tone", "default_loudness")}
    for section in cp.sections():
        if section not in used:
            raise ConfigError(f"unknown section [{section}]")
        unknown = set(cp.options(section)) - used[section]
        if unknown:
            raise ConfigError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")
    return cfg


def startup_state(cfg: dict, saved: dict | None) -> tuple[int, dict]:
    """Master and source volumes to start with: the saved ones (defaults where missing or
    invalid), the master capped at startup_cap."""
    saved = saved if isinstance(saved, dict) else {}
    vmax = cfg["max"]

    def ok(v):
        return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= vmax

    master = saved.get("master")
    master = master if ok(master) else cfg["default_master"]
    vols = saved.get("volumes") if isinstance(saved.get("volumes"), dict) else {}
    volumes = {s: vols[s] if ok(vols.get(s)) else cfg["default_volumes"][s] for s in SOURCES}
    return min(master, cfg["startup_cap"]), volumes


TONES = ("bass", "treble", "balance", "loudness")


def check_tone(cfg: dict, name: str, value):
    """value as the tone control's type, or ValueError (KeyError for an unknown name)."""
    if name not in TONES:
        raise KeyError(f"no tone control {name!r}; known: {', '.join(TONES)}")
    if name == "loudness":
        if not isinstance(value, bool):
            raise ValueError(f"loudness takes true or false, not {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} takes a number, not {value!r}")
    if name == "balance":
        if not -1.0 <= value <= 1.0:
            raise ValueError(f"balance = {value} is outside -1..1")
        return round(float(value), 3)
    r = cfg["tone_range_db"]
    if value != int(value) or not -r <= value <= r:
        raise ValueError(f"{name} = {value} is not a whole dB step in -{r}..{r}")
    return int(value)


def startup_tone(cfg: dict, saved: dict | None) -> dict:
    """The saved tone controls; defaults where missing or no longer valid."""
    t = saved.get("tone") if isinstance(saved, dict) and isinstance(saved.get("tone"), dict) else {}
    out = {}
    for n in TONES:
        try:
            out[n] = check_tone(cfg, n, t[n]) if n in t else cfg["default_tone"][n]
        except ValueError:
            out[n] = cfg["default_tone"][n]
    return out


def gain(cfg: dict, master: int, volume: int, muted: bool) -> float:
    if muted:
        return 0.0
    level = (master / cfg["max"]) * (volume / cfg["max"])
    return round(level ** cfg["curve"], 6)


def in_call(cfg: dict, call_state: str) -> bool:
    return call_state == "active" or (call_state == "ringing" and cfg["call_starts_on"] == "ring")


def gains_for(cfg: dict, master: int, volumes: dict, muted: bool, duck: float, call_state: str) -> dict:
    """Every source's gain under the D9 rules: volumes, mute (sparing the phone during a
    call), ducking of media and radio, radio silent during a call."""
    call = in_call(cfg, call_state)
    out = {}
    for s in SOURCES:
        g = gain(cfg, master, volumes[s], muted and not (s == "phone" and call and cfg["mute_spares_call"]))
        if s in ("media", "radio"):
            g *= duck
        if s == "radio" and call and cfg["call_mutes_radio"]:
            g = 0.0
        out[s] = round(g, 6)
    return out


def warning_chime_gain(cfg: dict, master: int, volumes: dict) -> float:
    """The warning chime ignores mute and is never quieter than warning_chime_min_gain."""
    return round(max(gain(cfg, master, volumes["chime"], False), cfg["warning_chime_min_gain"]), 6)


def read_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning(f"ignoring unreadable state {path}: {e}")
        return None


def write_state(path: Path, master: int, volumes: dict, tone: dict | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    data = {"master": master, "volumes": volumes}
    if tone is not None:
        data["tone"] = tone
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    os.replace(tmp, path)


class Audio(dbus.service.Object):
    def __init__(self, bus, cfg: dict, state_path: Path):
        super().__init__(bus, OBJ_PATH)
        self.bus, self.cfg, self.state_path = bus, cfg, state_path
        saved = read_state(state_path)
        self.master, self.volumes = startup_state(cfg, saved)
        self.tone = startup_tone(cfg, saved)
        self.muted = False
        self.nav_prompt = False
        self.chime = False              # a chime is playing (hu-warnd)
        self.voice = "idle"             # the voice assistant listens or speaks (hu-assistd)
        self.call_state = "idle"
        self.duck = 1.0                 # current factor on media and radio, fades to its target
        self.duck_timer = None
        self.media_paused_by_call = False
        self.media_paused_by_power = False
        self.power = None
        self.props = {}
        self.dirty = set()
        self.save_pending = False
        self.media_gain = None          # last gain sent to mediad
        self.phone_gain = None          # ... and to phoned
        self.refresh()
        log.info(f"master {self.master}/{cfg['max']} (saved {saved.get('master') if isinstance(saved, dict) else None}, "
                 f"cap {cfg['startup_cap']}), volumes {self.volumes}, state {state_path}")

        bus.add_signal_receiver(self.on_input, "Input", VEHICLE[2], None, VEHICLE[1])
        bus.add_signal_receiver(self.on_vehicle_props, "PropertiesChanged", PROPS_IFACE, None, VEHICLE[1])
        bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus")
        GLib.timeout_add(100, self.flush)
        GLib.idle_add(self.push_media)
        GLib.idle_add(self.push_phone)
        register_saver(bus, "audiod", self.save)      # volumes and tone saved before a shutdown (D12)

    # ---- state -------------------------------------------------------------
    def gains(self) -> dict:
        return gains_for(self.cfg, self.master, self.volumes, self.muted, self.duck, self.call_state)

    def refresh(self):
        self.set("Max", self.cfg["max"])
        self.set("StartupCap", self.cfg["startup_cap"])
        self.set("Master", self.master)
        self.set("Muted", self.muted)
        self.set("Volumes", dict(self.volumes))
        self.set("Tone", dict(self.tone))
        self.set("Gains", self.gains())
        self.set("NavPrompt", self.nav_prompt)
        self.set("Chime", self.chime)
        self.set("Voice", self.voice)
        self.set("WarningChimeGain", warning_chime_gain(self.cfg, self.master, self.volumes))
        self.set("CallState", self.call_state)
        self.set("Duck", round(self.duck, 6))
        self.push_media()
        self.push_phone()

    def changed_volume(self):
        self.refresh()
        if not self.save_pending:
            self.save_pending = True
            GLib.timeout_add(500, self.save)

    def save(self):
        self.save_pending = False
        try:
            write_state(self.state_path, self.master, self.volumes, self.tone)
        except OSError as e:
            log.error(f"could not save {self.state_path}: {e}")
        return False

    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def flush(self):
        if self.dirty:
            changed = {k: self.variant(k) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))
        return True

    def variant(self, name):
        v = self.props[name]
        if name == "Volumes":
            return dbus.Dictionary({k: dbus.Int32(x) for k, x in v.items()}, signature="si")
        if name == "Tone":
            return dbus.Dictionary({k: dbus.Boolean(x) if isinstance(x, bool) else dbus.Double(x) if isinstance(x, float)
                                    else dbus.Int32(x) for k, x in v.items()}, signature="sv")
        if name == "Gains":
            return dbus.Dictionary({k: dbus.Double(x) for k, x in v.items()}, signature="sd")
        if isinstance(v, bool):
            return dbus.Boolean(v)
        if isinstance(v, str):
            return dbus.String(v)
        if isinstance(v, float):
            return dbus.Double(v)
        return dbus.Int32(v)

    # ---- sources -----------------------------------------------------------
    def push_media(self):
        g = self.gains()["media"]
        if g == self.media_gain:
            return False
        # Remember what was sent, not what was confirmed: a quick mute + unmute would
        # otherwise skip the unmute (same value as the last confirmed one). On an error
        # forget it, so the next change sends again.
        self.media_gain = g

        def failed(_e):
            if self.media_gain == g:
                self.media_gain = None
        self.bus.call_async(MEDIA[0], MEDIA[1], MEDIA[2], "SetGain", "du", (g, self.cfg["change_fade_ms"]),
                            lambda *_: None, failed, timeout=1.0)
        return False

    def push_phone(self):
        # the phone volume's gain, plus the call boost (speech is far quieter than music)
        g = round(self.gains()["phone"] * 10 ** (self.cfg["call_boost_db"] / 20), 6)
        if g == self.phone_gain:
            return False
        self.phone_gain = g                  # as push_media: what was sent, forgotten on an error

        def failed(_e):
            if self.phone_gain == g:
                self.phone_gain = None
        self.bus.call_async(PHONE[0], PHONE[1], PHONE[2], "SetGain", "du", (g, self.cfg["change_fade_ms"]),
                            lambda *_: None, failed, timeout=1.0)
        return False

    def on_owner(self, name, _old, new):
        if name == MEDIA[0] and new:
            self.media_gain = None       # a (re)started mediad needs its gain
            self.push_media()
        elif name == PHONE[0] and new:
            self.phone_gain = None
            self.push_phone()

    # ---- rules ---------------------------------------------------------------
    def start_duck_fade(self):
        target = 1.0
        if self.voice == "listen":
            target = self.cfg["listen_duck_level"]
        if self.nav_prompt or self.chime or self.voice == "speak":
            target = min(target, self.cfg["duck_level"])
        steps = max(1, self.cfg["duck_fade_ms"] // 50)
        delta = (target - self.duck) / steps
        if self.duck_timer:
            GLib.source_remove(self.duck_timer)
            self.duck_timer = None

        def step():
            nonlocal steps
            steps -= 1
            self.duck = target if steps <= 0 else self.duck + delta
            self.refresh()
            if steps <= 0:
                self.duck_timer = None
                return False
            return True
        if self.cfg["duck_fade_ms"] < 50:
            self.duck = target
            self.refresh()
        else:
            self.duck_timer = GLib.timeout_add(50, step)

    def media_call(self, method, signature="", args=(), reply=None):
        self.bus.call_async(MEDIA[0], MEDIA[1], MEDIA[2] if method != "Get" else PROPS_IFACE, method,
                            signature, args, reply or (lambda *_: None), lambda e: None, timeout=1.0)

    def call_started(self):
        def status(s):
            # still in the call, and media was playing: pause it and remember that
            if in_call(self.cfg, self.call_state) and str(s) == "playing":
                self.media_paused_by_call = True
                self.media_call("SetPlaying", "b", (False,))
        self.media_call("Get", "ss", (MEDIA[2], "PlaybackStatus"), status)

    def call_ended(self):
        if self.media_paused_by_call and self.cfg["resume_media_after_call"]:
            self.media_call("SetPlaying", "b", (True,))
        self.media_paused_by_call = False

    # ---- vehicle -----------------------------------------------------------
    def on_vehicle_props(self, iface, changed, _invalidated):
        if str(iface) != VEHICLE[2] or "Power" not in changed:
            return
        old, self.power = self.power, str(changed["Power"])
        if not self.cfg["pause_media_when_off"] or old is None or old == self.power:
            return                                  # the first value after (re)starting is no change
        if self.power == "off":
            def status(s):
                if self.power == "off" and str(s) == "playing":
                    self.media_paused_by_power = True
                    self.media_call("SetPlaying", "b", (False,))
            self.media_call("Get", "ss", (MEDIA[2], "PlaybackStatus"), status)
        elif self.power != "shutdown" and self.media_paused_by_power:
            self.media_paused_by_power = False
            if in_call(self.cfg, self.call_state):
                self.media_paused_by_call = True                 # resumed when the call ends
            else:
                self.media_call("SetPlaying", "b", (True,))

    def on_input(self, kind, _value):
        kind = str(kind)
        if kind not in ("button:VOL_UP", "button:VOL_DOWN", "button:MUTE"):
            return
        # Ask hu-vehicled for the power state now instead of tracking its PropertiesChanged:
        # those are batched, key events are not, so a key pressed right after power-on would
        # otherwise reach audiod before the news that the HU is on, and get lost.
        self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS_IFACE, "Get", "ss", (VEHICLE[2], "Power"),
                            lambda power: self.on_key(kind, str(power)),
                            lambda e: log.warning(f"ignoring {kind}: no power state from hu-vehicled ({e})"),
                            timeout=1.0)

    def on_key(self, kind, power):
        if power in ("off", "shutdown"):
            log.info(f"ignoring {kind}: HU power is {power}")
        elif kind == "button:VOL_UP":
            self.Step(1)
        elif kind == "button:VOL_DOWN":
            self.Step(-1)
        else:
            self.ToggleMute()

    # ---- D-Bus properties ----------------------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.variant(name)

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: self.variant(k) for k in self.props}, signature="sv")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    # ---- D-Bus methods ---------------------------------------------------------
    def _clamp(self, v):
        return max(0, min(int(v), self.cfg["max"]))

    @dbus.service.method(IFACE, in_signature="i")
    def SetMaster(self, value):
        self.master = self._clamp(value)
        self.changed_volume()

    @dbus.service.method(IFACE, in_signature="i")
    def Step(self, delta):
        self.SetMaster(self.master + int(delta))

    @dbus.service.method(IFACE, in_signature="b")
    def SetMuted(self, muted):
        self.muted = bool(muted)
        self.refresh()

    @dbus.service.method(IFACE)
    def ToggleMute(self):
        self.SetMuted(not self.muted)

    @dbus.service.method(IFACE, in_signature="b")
    def SetNavPrompt(self, active):
        active = bool(active)
        if active != self.nav_prompt:
            self.nav_prompt = active
            self.refresh()
            self.start_duck_fade()

    @dbus.service.method(IFACE, in_signature="b")
    def SetChime(self, active):
        active = bool(active)
        if active != self.chime:
            self.chime = active
            self.refresh()
            self.start_duck_fade()

    @dbus.service.method(IFACE, in_signature="s")
    def SetVoice(self, state):
        state = str(state)
        if state not in VOICE_STATES:
            raise dbus.exceptions.DBusException(f"unknown voice state {state!r}; known: {', '.join(VOICE_STATES)}",
                                                name="de.r80.Audio1.Error.UnknownVoiceState")
        if state != self.voice:
            self.voice = state
            self.refresh()
            self.start_duck_fade()

    @dbus.service.method(IFACE, in_signature="s")
    def SetCallState(self, state):
        state = str(state)
        if state not in ("idle", "ringing", "active"):
            raise dbus.exceptions.DBusException(f"unknown call state {state!r}; known: idle, ringing, active",
                                                name="de.r80.Audio1.Error.UnknownCallState")
        was = in_call(self.cfg, self.call_state)
        self.call_state = state
        now = in_call(self.cfg, state)
        self.refresh()
        if now and not was:
            self.call_started()
        elif was and not now:
            self.call_ended()

    @dbus.service.method(IFACE, in_signature="si")
    def SetVolume(self, source, value):
        source = str(source)
        if source not in SOURCES:
            raise dbus.exceptions.DBusException(f"unknown source {source!r}; known: {', '.join(SOURCES)}",
                                                name="de.r80.Audio1.Error.UnknownSource")
        self.volumes[source] = self._clamp(value)
        self.changed_volume()

    @dbus.service.method(IFACE, in_signature="sv")
    def SetTone(self, name, value):
        """Bass / treble (whole dB steps within tone_range_db), balance (-1..1), loudness (bool)."""
        v = value
        if isinstance(v, dbus.Boolean):
            v = bool(v)
        elif isinstance(v, (dbus.Double, dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.Byte)):
            v = float(v) if isinstance(v, dbus.Double) else int(v)
        try:
            self.tone[str(name)] = check_tone(self.cfg, str(name), v)
        except KeyError as e:
            raise dbus.exceptions.DBusException(e.args[0], name="de.r80.Audio1.Error.UnknownTone")
        except ValueError as e:
            raise dbus.exceptions.DBusException(str(e), name="de.r80.Audio1.Error.InvalidValue")
        self.changed_volume()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/audio.ini and /etc/r80/audio.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "audio.json"), help="where the volumes are saved")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()
    dlt.app("AUD", "Audio service", "audiod")
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[audiod] bad config: {e}")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Audio(bus, cfg, Path(a.state))
    log.info(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
