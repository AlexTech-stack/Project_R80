#!/usr/bin/env python3
"""hu-sysd: the system and settings service of the R80 headunit (decision D12).

Keeps the user's settings (described in system.ini: type, allowed values, default) and
saves them as state, so they survive a restart.

    bus name   de.r80.System
    object     /de/r80/System
    interface  de.r80.System1
      properties  Settings (a{sv}): every setting's current value (bool b, number d, choice s)
                  Schema (a{sv}): per setting {type, default, min, max | choices}
      methods     Set(s name, v value)   checked against system.ini; errors:
                                         de.r80.System1.Error.UnknownSetting / InvalidValue
                  Reset(s name), ResetAll()
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

The values are saved to --state (default $XDG_STATE_HOME/r80/settings.json) on every
change. A saved value that no longer fits system.ini (renamed, out of range after an
update) falls back to its default. The logic (Settings) has no D-Bus, so tests can use it.
"""
from __future__ import annotations

import argparse
import configparser
import json
import math
import os
import sys
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent / "system.ini"
SYSTEM_CONFIG = Path("/etc/r80/system.ini")
TYPES = ("bool", "number", "choice")


def log(*a):
    print("[sysd]", *a, flush=True)


class ConfigError(ValueError):
    pass


class SettingError(ValueError):
    """A value or a name that does not fit system.ini. `unknown` tells which."""

    def __init__(self, msg: str, unknown: bool = False):
        super().__init__(msg)
        self.unknown = unknown


def load_config(extra: str | None = None) -> dict:
    """{"settings": {name: {"type", "default", "min", "max" | "choices"}}}, checked."""
    cp = configparser.ConfigParser()
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else []) if f.is_file()])
    settings = {}
    for section in cp.sections():
        kind, _, name = section.partition(" ")
        if kind != "setting" or not name.strip():
            raise ConfigError(f"unknown section [{section}]")
        name = name.strip()
        o = dict(cp.items(section))
        t = o.get("type", "")
        if t not in TYPES:
            raise ConfigError(f"[{section}] type = {t!r}, expected one of {', '.join(TYPES)}")
        allowed = {"type", "default"} | ({"min", "max"} if t == "number" else {"choices"} if t == "choice" else set())
        unknown = set(o) - allowed
        if unknown:
            raise ConfigError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")
        s = {"type": t}
        try:
            if t == "number":
                s["min"], s["max"] = float(o["min"]), float(o["max"])
                if not s["min"] < s["max"]:
                    raise ValueError("min must be below max")
            elif t == "choice":
                s["choices"] = [c.strip() for c in o["choices"].split(",") if c.strip()]
                if len(s["choices"]) < 2:
                    raise ValueError("a choice needs at least two choices")
            raw = o["default"]
            s["default"] = (cp.getboolean(section, "default") if t == "bool"
                            else float(raw) if t == "number" else raw.strip())
            check(name, s, s["default"])
        except KeyError as e:
            raise ConfigError(f"[{section}] {e.args[0]} is missing") from None
        except (ValueError, SettingError) as e:
            raise ConfigError(f"[{section}] {e}") from None
        settings[name] = s
    if not settings:
        raise ConfigError("no [setting ...] sections")
    return {"settings": settings}


def check(name: str, s: dict, value):
    """value as the setting's type, or SettingError."""
    t = s["type"]
    if t == "bool":
        if not isinstance(value, bool):
            raise SettingError(f"{name} takes true or false, not {value!r}")
        return value
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SettingError(f"{name} takes a number, not {value!r}")
        if not s["min"] <= value <= s["max"]:
            raise SettingError(f"{name} = {value} is outside {s['min']:g}..{s['max']:g}")
        return float(value)
    if not isinstance(value, str) or value not in s["choices"]:
        raise SettingError(f"{name} takes one of {', '.join(s['choices'])}, not {value!r}")
    return value


class Settings:
    """The settings' values against their schema; saved values that no longer fit fall back."""

    def __init__(self, schema: dict, saved: dict | None = None):
        self.schema = schema
        self.values = {n: s["default"] for n, s in schema.items()}
        for n, v in (saved if isinstance(saved, dict) else {}).items():
            if n not in schema:
                log(f"ignoring saved setting {n!r}: not in system.ini")
                continue
            try:
                self.values[n] = check(n, schema[n], v)
            except SettingError as e:
                log(f"saved setting ignored, back to default: {e}")

    def set(self, name: str, value) -> bool:
        """True if the value changed."""
        if name not in self.schema:
            raise SettingError(f"no setting {name!r}; known: {', '.join(sorted(self.schema))}", unknown=True)
        v = check(name, self.schema[name], value)
        changed = v != self.values[name]
        self.values[name] = v
        return changed

    def reset(self, name: str) -> bool:
        if name not in self.schema:
            raise SettingError(f"no setting {name!r}", unknown=True)
        return self.set(name, self.schema[name]["default"])

    def reset_all(self) -> bool:
        return any([self.reset(n) for n in self.schema])


def read_state(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"ignoring unreadable state {path}: {e}")
        return None


def write_state(path: Path, values: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def run_service(cfg: dict, state_path: Path, system: bool):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.System", "/de/r80/System", "de.r80.System1"
    PROPS = "org.freedesktop.DBus.Properties"

    def plain(v):
        if isinstance(v, dbus.Boolean):
            return bool(v)
        if isinstance(v, (dbus.Double,)):
            return float(v)
        if isinstance(v, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
            return int(v)
        if isinstance(v, dbus.String):
            return str(v)
        return v

    def variant(v):
        return dbus.Boolean(v) if isinstance(v, bool) else dbus.Double(v) if isinstance(v, float) else dbus.String(v)

    class System(dbus.service.Object):
        def __init__(self, bus):
            super().__init__(bus, OBJ_PATH)
            self.settings = Settings(cfg["settings"], read_state(state_path))

        def settings_v(self):
            return dbus.Dictionary({n: variant(v) for n, v in self.settings.values.items()}, signature="sv")

        def schema_v(self):
            out = {}
            for n, s in cfg["settings"].items():
                d = {"type": dbus.String(s["type"]), "default": variant(s["default"])}
                if s["type"] == "number":
                    d["min"], d["max"] = dbus.Double(s["min"]), dbus.Double(s["max"])
                if s["type"] == "choice":
                    d["choices"] = dbus.Array(s["choices"], signature="s")
                out[n] = dbus.Dictionary(d, signature="sv")
            return dbus.Dictionary(out, signature="sv")

        def changed(self):
            try:
                write_state(state_path, self.settings.values)
            except OSError as e:
                log(f"could not save {state_path}: {e}")
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Settings": self.settings_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))

        def fail(self, e: SettingError):
            raise dbus.exceptions.DBusException(
                str(e), name=f"{IFACE}.Error." + ("UnknownSetting" if e.unknown else "InvalidValue"))

        @dbus.service.method(IFACE, in_signature="sv")
        def Set(self, name, value):
            try:
                if self.settings.set(str(name), plain(value)):
                    log(f"{name} = {self.settings.values[str(name)]}")
                    self.changed()
            except SettingError as e:
                self.fail(e)

        @dbus.service.method(IFACE, in_signature="s")
        def Reset(self, name):
            try:
                if self.settings.reset(str(name)):
                    self.changed()
            except SettingError as e:
                self.fail(e)

        @dbus.service.method(IFACE)
        def ResetAll(self):
            if self.settings.reset_all():
                log("all settings back to their defaults")
                self.changed()

        @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, name):
            if name == "Settings":
                return self.settings_v()
            if name == "Schema":
                return self.schema_v()
            raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary({"Settings": self.settings_v(), "Schema": self.schema_v()}, signature="sv")

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    System(bus)
    log(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, "
        f"{len(cfg['settings'])} settings, state {state_path}")
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/system.ini and /etc/r80/system.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "settings.json"), help="where the settings are saved")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    ap.add_argument("--check", action="store_true", help="check the config, list the settings and exit")
    a = ap.parse_args()
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[sysd] bad config: {e}")
    if a.check:
        for n, s in cfg["settings"].items():
            rng = f"{s['min']:g}..{s['max']:g}" if s["type"] == "number" else ", ".join(s.get("choices", [])) or "true/false"
            print(f"{n:16s} {s['type']:7s} {rng:45s} default {s['default']}")
        return
    run_service(cfg, Path(a.state), a.system)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
