#!/usr/bin/env python3
"""hu-audiod: the audio service of the R80 headunit. It alone owns volume and mute.

    bus name   de.r80.Audio
    object     /de/r80/Audio
    interface  de.r80.Audio1
      properties  Max (i), Master (i), Muted (b), StartupCap (i),
                  Volumes (a{si}: source -> 0..Max), Gains (a{sd}: source -> 0.0..1.0)
      methods     SetMaster(i), Step(i delta), SetMuted(b), ToggleMute(),
                  SetVolume(s source, i value)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Sources: media, navigation, phone, radio. For each source audiod computes the level
it should play at (Gains) and the source applies it to its own player: mediad gets it
through de.r80.Media1.SetGain. Navigation, phone and radio have no service yet; their
gains are already published for when they do.

    gain = ((Master / Max) * (Volumes[source] / Max)) ** curve      (0 while muted)

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

BUS_NAME = "de.r80.Audio"
OBJ_PATH = "/de/r80/Audio"
IFACE = "de.r80.Audio1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
SOURCES = ("media", "navigation", "phone", "radio")
VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")
MEDIA = ("de.r80.Media", "/de/r80/Media", "de.r80.Media1")
DEFAULT_CONFIG = Path(__file__).resolve().parent / "audio.ini"
SYSTEM_CONFIG = Path("/etc/r80/audio.ini")


def log(*a):
    print("[audiod]", *a, flush=True)


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> dict:
    """Read the config files in order and return checked numbers."""
    cp = configparser.ConfigParser()
    files = [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else [])
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in files if f.is_file()])

    def num(key, conv, lo, hi):
        try:
            v = conv(cp.get("volume", key))
        except (configparser.Error, ValueError) as e:
            raise ConfigError(f"[volume] {key}: {e}") from None
        if not lo <= v <= hi:
            raise ConfigError(f"[volume] {key} = {v} is outside {lo}..{hi}")
        return v

    vmax = num("max", int, 1, 1000)
    cfg = {
        "max": vmax,
        "startup_cap": num("startup_cap", int, 0, vmax),
        "default_master": num("default_master", int, 0, vmax),
        "curve": num("curve", float, 0.1, 10.0),
        "default_volumes": {s: num(f"default_{s}", int, 0, vmax) for s in SOURCES},
    }
    unknown = set(cp.options("volume")) - {"max", "startup_cap", "default_master", "curve"} \
        - {f"default_{s}" for s in SOURCES}
    if unknown:
        raise ConfigError(f"[volume] unknown key(s): {', '.join(sorted(unknown))}")
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


def gain(cfg: dict, master: int, volume: int, muted: bool) -> float:
    if muted:
        return 0.0
    level = (master / cfg["max"]) * (volume / cfg["max"])
    return round(level ** cfg["curve"], 6)


def read_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"ignoring unreadable state {path}: {e}")
        return None


def write_state(path: Path, master: int, volumes: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"master": master, "volumes": volumes}, indent=1) + "\n")
    os.replace(tmp, path)


class Audio(dbus.service.Object):
    def __init__(self, bus, cfg: dict, state_path: Path):
        super().__init__(bus, OBJ_PATH)
        self.bus, self.cfg, self.state_path = bus, cfg, state_path
        saved = read_state(state_path)
        self.master, self.volumes = startup_state(cfg, saved)
        self.muted = False
        self.props = {}
        self.dirty = set()
        self.save_pending = False
        self.media_gain = None          # last gain sent to mediad
        self.refresh()
        log(f"master {self.master}/{cfg['max']} (saved {saved.get('master') if isinstance(saved, dict) else None}, "
            f"cap {cfg['startup_cap']}), volumes {self.volumes}, state {state_path}")

        bus.add_signal_receiver(self.on_input, "Input", VEHICLE[2], None, VEHICLE[1])
        bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus")
        GLib.timeout_add(100, self.flush)
        GLib.idle_add(self.push_media)

    # ---- state -------------------------------------------------------------
    def gains(self) -> dict:
        return {s: gain(self.cfg, self.master, self.volumes[s], self.muted) for s in SOURCES}

    def refresh(self):
        self.set("Max", self.cfg["max"])
        self.set("StartupCap", self.cfg["startup_cap"])
        self.set("Master", self.master)
        self.set("Muted", self.muted)
        self.set("Volumes", dict(self.volumes))
        self.set("Gains", self.gains())
        self.push_media()

    def changed_volume(self):
        self.refresh()
        if not self.save_pending:
            self.save_pending = True
            GLib.timeout_add(500, self.save)

    def save(self):
        self.save_pending = False
        try:
            write_state(self.state_path, self.master, self.volumes)
        except OSError as e:
            log(f"could not save {self.state_path}: {e}")
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
        if name == "Gains":
            return dbus.Dictionary({k: dbus.Double(x) for k, x in v.items()}, signature="sd")
        if isinstance(v, bool):
            return dbus.Boolean(v)
        return dbus.Int32(v)

    # ---- sources -----------------------------------------------------------
    def push_media(self):
        g = self.gains()["media"]
        if g == self.media_gain:
            return False

        def done(*_):
            self.media_gain = g           # only what mediad confirmed counts as sent
        self.bus.call_async(MEDIA[0], MEDIA[1], MEDIA[2], "SetGain", "d", (g,),
                            done, lambda e: None, timeout=1.0)
        return False

    def on_owner(self, name, _old, new):
        if name == MEDIA[0] and new:
            self.media_gain = None       # a (re)started mediad needs its gain
            self.push_media()

    # ---- vehicle -----------------------------------------------------------
    def on_input(self, kind, _value):
        kind = str(kind)
        if kind not in ("button:VOL_UP", "button:VOL_DOWN", "button:MUTE"):
            return
        # Ask hu-vehicled for the power state now instead of tracking its PropertiesChanged:
        # those are batched, key events are not, so a key pressed right after power-on would
        # otherwise reach audiod before the news that the HU is on, and get lost.
        self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS_IFACE, "Get", "ss", (VEHICLE[2], "Power"),
                            lambda power: self.on_key(kind, str(power)),
                            lambda e: log(f"ignoring {kind}: no power state from hu-vehicled ({e})"),
                            timeout=1.0)

    def on_key(self, kind, power):
        if power in ("off", "shutdown"):
            log(f"ignoring {kind}: HU power is {power}")
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

    @dbus.service.method(IFACE, in_signature="si")
    def SetVolume(self, source, value):
        source = str(source)
        if source not in SOURCES:
            raise dbus.exceptions.DBusException(f"unknown source {source!r}; known: {', '.join(SOURCES)}",
                                                name="de.r80.Audio1.Error.UnknownSource")
        self.volumes[source] = self._clamp(value)
        self.changed_volume()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/audio.ini and /etc/r80/audio.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "audio.json"), help="where the volumes are saved")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[audiod] bad config: {e}")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Audio(bus, cfg, Path(a.state))
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
