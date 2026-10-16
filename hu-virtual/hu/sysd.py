#!/usr/bin/env python3
"""hu-sysd: the system and settings service of the R80 headunit (decision D12).

Keeps the user's settings (described in system.ini: type, allowed values, default) and
saves them as state, so they survive a restart.

    bus name   de.r80.System
    object     /de/r80/System
    interface  de.r80.System1
      properties  Settings (a{sv}): every setting's current value (bool b, number d, choice s)
                  Schema (a{sv}): per setting {type, default, min, max | choices}
                  DisplayBrightness (d): what the display shows, 0..1 (D12: by day the user's
                                    brightness; at night the car's dimmer shifted by it)
                  Info (a{sv}): Settings -> System, refreshed every [info] refresh_s: version, os,
                                kernel, host, uptime_s, cpu_temp_c, load, mem_total_mb, mem_available_mb,
                                disk_free_mb, services_up / services_missing (as, of [info] services),
                                bt_name, bt_address, bt_powered (BlueZ adapter; bt_name "" = none)
                  Shutdown (a{sv}): state (idle|saving|acked|cancelled), savers (as), waiting (as),
                                    last_saved (as), last_timed_out (as), last_ms (u), last_cancelled (b)
      methods     Set(s name, v value)   checked against system.ini; errors:
                                         de.r80.System1.Error.UnknownSetting / InvalidValue
                  Reset(s name), ResetAll()
                  RegisterSaver(s name)  a service that has to save before a shutdown
                  Saved(s name)          ... has saved after PrepareForShutdown
      signals     PrepareForShutdown()
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

The values are saved to --state (default $XDG_STATE_HOME/r80/settings.json) half a
second after a change (one write for a dragged slider). A saved value that no longer fits system.ini (renamed, out of range after an
update) falls back to its default. 
Shutdown (D12): when hu-vehicled reports Power = shutdown (the MCU announced off), sysd
sends PrepareForShutdown; every registered saver (hu/saver.py: audiod, tripd) saves and
answers Saved. sysd waits for all of them, at most [shutdown] save_timeout_s, saves its own
settings, syncs the file systems and lets vehicled acknowledge to the MCU
(de.r80.Vehicle1.ShutdownReady). With after_ack = poweroff (target) Linux then powers off.
If the ignition comes back before that, nothing is acknowledged. A saver whose process
ends is not waited for. The logic (Settings, Shutdown) has no D-Bus, so tests can use it.
"""
from __future__ import annotations

import argparse
import configparser
import json
import math
import os
import subprocess
import sys
import time
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
    """{"settings": {name: {"type", "default", "min", "max" | "choices"}},
        "shutdown": {"save_timeout_s", "after_ack"}}, checked."""
    cp = configparser.ConfigParser()
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else []) if f.is_file()])
    settings = {}
    shutdown = {}
    brightness = {}
    info = {}
    for section in cp.sections():
        if section == "info":
            unknown = set(cp.options(section)) - {"refresh_s", "services"}
            if unknown:
                raise ConfigError(f"[info] unknown key(s): {', '.join(sorted(unknown))}")
            try:
                info["refresh_s"] = float(cp.get(section, "refresh_s"))
                info["services"] = [x.strip() for x in cp.get(section, "services").split(",") if x.strip()]
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[info] {e}") from None
            if not 1 <= info["refresh_s"] <= 600:
                raise ConfigError(f"[info] refresh_s = {info['refresh_s']} is outside 1..600")
            continue
        if section == "brightness":
            unknown = set(cp.options(section)) - {"night_min", "night_max", "floor"}
            if unknown:
                raise ConfigError(f"[brightness] unknown key(s): {', '.join(sorted(unknown))}")
            try:
                brightness = {k: float(cp.get(section, k)) for k in ("night_min", "night_max", "floor")}
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[brightness] {e}") from None
            if not 0 < brightness["floor"] <= brightness["night_min"] < brightness["night_max"] <= 1:
                raise ConfigError("[brightness] needs 0 < floor <= night_min < night_max <= 1")
            continue
        if section == "shutdown":
            unknown = set(cp.options(section)) - {"save_timeout_s", "after_ack"}
            if unknown:
                raise ConfigError(f"[shutdown] unknown key(s): {', '.join(sorted(unknown))}")
            try:
                shutdown["save_timeout_s"] = float(cp.get(section, "save_timeout_s"))
                shutdown["after_ack"] = cp.get(section, "after_ack").strip()
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[shutdown] {e}") from None
            if not 0.1 <= shutdown["save_timeout_s"] <= 9:
                raise ConfigError(f"[shutdown] save_timeout_s = {shutdown['save_timeout_s']} is outside 0.1..9 "
                                  "(the MCU cuts the power after 10 s)")
            if shutdown["after_ack"] not in ("none", "poweroff"):
                raise ConfigError(f"[shutdown] after_ack = {shutdown['after_ack']!r}, expected none or poweroff")
            continue
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
    if not shutdown:
        raise ConfigError("[shutdown] is missing")
    if not brightness:
        raise ConfigError("[brightness] is missing")
    if not info:
        raise ConfigError("[info] is missing")
    for need, t in (("brightness", "number"), ("night_dimming", "bool")):
        if settings.get(need, {}).get("type") != t:
            raise ConfigError(f"[setting {need}] ({t}) is needed for the display brightness")
    return {"settings": settings, "shutdown": shutdown, "brightness": brightness, "info": info}


def display_brightness(cfg: dict, values: dict, night: bool, dim_level: float) -> float:
    """What the display shows (0..1), D12: by day the user's brightness; at night the car's
    dimmer is the base and the user's setting shifts it (relative to the setting's default)."""
    user = values["brightness"]
    if not (night and values["night_dimming"]):
        return round(user, 3)
    b = cfg["brightness"]
    base = b["night_min"] + (b["night_max"] - b["night_min"]) * max(0.0, min(100.0, dim_level)) / 100
    shifted = base * user / cfg["settings"]["brightness"]["default"]
    return round(max(b["floor"], min(1.0, shifted)), 3)


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


def system_info(repo: Path) -> dict:
    """Settings -> System: facts about this computer from standard Linux sources (no
    hardware-specific tools). Missing values are -1 / "unknown"."""
    def read(p, default=""):
        try:
            return Path(p).read_text().strip()
        except OSError:
            return default

    info = {"version": "unknown", "os": "unknown", "kernel": os.uname().release, "host": os.uname().nodename,
            "uptime_s": -1, "cpu_temp_c": -1.0, "load": -1.0, "mem_total_mb": -1, "mem_available_mb": -1,
            "disk_free_mb": -1}
    try:
        info["version"] = subprocess.run(["git", "-C", str(repo), "describe", "--always", "--dirty"],
                                         capture_output=True, text=True, timeout=3).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    if info["version"] == "unknown":           # no git program (e.g. a minimal image): read the commit
        head = read(repo / ".git" / "HEAD")
        ref = head[5:] if head.startswith("ref: ") else ""
        sha = read(repo / ".git" / ref) if ref else head
        if not sha and ref:
            sha = next((ln.split()[0] for ln in read(repo / ".git" / "packed-refs").splitlines()
                        if ln.endswith(" " + ref)), "")
        if sha:
            info["version"] = sha[:7]
    for line in read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            info["os"] = line.split("=", 1)[1].strip('"')
    up = read("/proc/uptime").split()
    if up:
        info["uptime_s"] = int(float(up[0]))
    zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*"))
    cpu = [z for z in zones if any(k in read(z / "type").lower() for k in ("cpu", "x86_pkg", "soc"))] or zones[:1]
    if cpu:
        info["cpu_temp_c"] = round(int(read(cpu[0] / "temp", "0")) / 1000, 1)
    load = read("/proc/loadavg").split()
    if load:
        info["load"] = float(load[0])
    mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in read("/proc/meminfo").splitlines() if ln.split()[1:2]}
    if "MemTotal" in mem:
        info["mem_total_mb"] = mem["MemTotal"] // 1024
        info["mem_available_mb"] = mem.get("MemAvailable", 0) // 1024
    try:
        st = os.statvfs(str(repo))
        info["disk_free_mb"] = st.f_bavail * st.f_frsize // (1024 * 1024)
    except OSError:
        pass
    return info


class Shutdown:
    """Who has to save before the HU may acknowledge the shutdown, and whether they did.
    Feed it the monotonic time; check() says when to acknowledge. No D-Bus, no clock."""

    def __init__(self, timeout_s: float):
        self.timeout_s = timeout_s
        self.savers: dict[str, str] = {}     # name -> D-Bus sender
        self.state = "idle"                  # idle | saving | acked | cancelled
        self.waiting: set[str] = set()
        self.saved: list[str] = []
        self.started = 0.0
        self.last: dict = {}

    def register(self, name: str, sender: str = ""):
        self.savers[name] = sender

    def gone(self, sender: str):
        """A saver's process ended: nobody left to wait for under that name."""
        for n in [n for n, s in self.savers.items() if s and s == sender]:
            del self.savers[n]
            self.waiting.discard(n)

    def start(self, now: float) -> list[str]:
        self.state, self.started = "saving", now
        self.waiting, self.saved = set(self.savers), []
        return sorted(self.waiting)

    def done(self, name: str):
        if self.state == "saving" and name in self.waiting:
            self.waiting.discard(name)
            self.saved.append(name)

    def check(self, now: float) -> bool:
        """True once: everybody saved, or the time is up. Then the caller acknowledges."""
        if self.state != "saving":
            return False
        if self.waiting and now - self.started < self.timeout_s:
            return False
        self.state = "acked"
        self.last = {"saved": sorted(self.saved), "timed_out": sorted(self.waiting),
                     "ms": int((now - self.started) * 1000)}
        return True

    def cancel(self, now: float | None = None):
        """The ignition came back before the acknowledgement: keep running."""
        if self.state == "saving":
            self.state = "cancelled"
            self.last = {"saved": sorted(self.saved), "timed_out": [], "cancelled": True,
                         "ms": int(((now if now is not None else self.started) - self.started) * 1000)}
            self.waiting = set()


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
    VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")

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
            self.bus = bus
            self.settings = Settings(cfg["settings"], read_state(state_path))
            self.save_pending = False
            self.shutdown = Shutdown(cfg["shutdown"]["save_timeout_s"])
            self.night, self.dim_level = False, 100.0
            self.display = display_brightness(cfg, self.settings.values, self.night, self.dim_level)
            bus.add_signal_receiver(self.on_vehicle, "PropertiesChanged", PROPS, None, VEHICLE[1])
            GLib.idle_add(self.read_vehicle)
            self.repo = Path(__file__).resolve().parents[2]
            self.sys_bus = None
            self.info = {}
            self.refresh_info()
            GLib.timeout_add(int(cfg["info"]["refresh_s"] * 1000), self.refresh_info)
            bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                    "org.freedesktop.DBus", "/org/freedesktop/DBus")

        # ---- shutdown (D12) -------------------------------------------------------
        # ---- system information (Settings -> System) ------------------------------
        def bluetooth(self) -> dict:
            try:
                if self.sys_bus is None:
                    self.sys_bus = dbus.SystemBus()
                objs = self.sys_bus.get_object("org.bluez", "/").GetManagedObjects(
                    dbus_interface="org.freedesktop.DBus.ObjectManager", timeout=1.0)
                for _path, ifaces in sorted(objs.items()):
                    a = ifaces.get("org.bluez.Adapter1")
                    if a:
                        return {"bt_name": str(a.get("Alias", a.get("Name", ""))), "bt_address": str(a.get("Address", "")),
                                "bt_powered": bool(a.get("Powered", False))}
            except dbus.DBusException:
                pass
            return {"bt_name": "", "bt_address": "", "bt_powered": False}

        def refresh_info(self):
            info = system_info(self.repo)
            names = cfg["info"]["services"]
            up = [n for n in names if n == BUS_NAME or self.bus.name_has_owner(n)]
            info.update(services_up=up, services_missing=[n for n in names if n not in up], **self.bluetooth())
            if info != self.info:
                self.info = info
                self.PropertiesChanged(IFACE, dbus.Dictionary({"Info": self.info_v()}, signature="sv"),
                                       dbus.Array([], signature="s"))
            return True

        def info_v(self):
            out = {}
            for k, v in self.info.items():
                out[k] = (dbus.Array(v, signature="s") if isinstance(v, list) else dbus.Boolean(v) if isinstance(v, bool)
                          else dbus.Double(v) if isinstance(v, float) else dbus.Int64(v) if isinstance(v, int)
                          else dbus.String(v))
            return dbus.Dictionary(out, signature="sv")

        # ---- display brightness (D12) ------------------------------------------
        def read_vehicle(self):
            self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS, "GetAll", "s", (VEHICLE[2],),
                                lambda props: self.on_vehicle(VEHICLE[2], props, []), lambda e: None, timeout=1.0)
            return False

        def update_display(self):
            d = display_brightness(cfg, self.settings.values, self.night, self.dim_level)
            if d != self.display:
                self.display = d
                self.PropertiesChanged(IFACE, dbus.Dictionary({"DisplayBrightness": dbus.Double(d)}, signature="sv"),
                                       dbus.Array([], signature="s"))

        def on_owner(self, name, _old, new):
            if name == VEHICLE[0] and new:
                self.read_vehicle()
            if not new and name.startswith(":"):
                before = set(self.shutdown.savers)
                self.shutdown.gone(name)
                for n in sorted(before - set(self.shutdown.savers)):
                    log(f"saver {n} is gone")
                if before != set(self.shutdown.savers):
                    self.publish_shutdown()

        def on_vehicle(self, iface, changed, _inv):
            if iface != VEHICLE[2]:
                return
            if "Night" in changed or "DimLevel" in changed:
                self.night = bool(changed.get("Night", self.night))
                self.dim_level = float(changed.get("DimLevel", self.dim_level))
                self.update_display()
            if "Power" not in changed:
                return
            power = str(changed["Power"])
            if power == "shutdown" and self.shutdown.state != "saving":
                waiting = self.shutdown.start(time.monotonic())
                log(f"shutdown: asking {', '.join(waiting) or 'nobody'} to save "
                    f"(at most {cfg['shutdown']['save_timeout_s']:g} s)")
                if self.save_pending:
                    self.save()
                self.PrepareForShutdown()
                self.publish_shutdown()
                GLib.timeout_add(50, self.shutdown_tick)
            elif power in ("on", "acc", "crank", "standby"):
                if self.shutdown.state == "saving":
                    log("shutdown cancelled: power is back")
                    self.shutdown.cancel(time.monotonic())
                elif self.shutdown.state != "idle":
                    self.shutdown.state = "idle"
                self.publish_shutdown()

        def shutdown_tick(self):
            if not self.shutdown.check(time.monotonic()):
                return self.shutdown.state == "saving"
            last = self.shutdown.last
            if self.save_pending:
                self.save()
            os.sync()
            log(f"shutdown: saved {', '.join(last['saved']) or 'nothing'}"
                + (f", no answer from {', '.join(last['timed_out'])}" if last["timed_out"] else "")
                + f" after {last['ms']} ms; acknowledging to the MCU")
            self.bus.call_async(VEHICLE[0], VEHICLE[1], VEHICLE[2], "ShutdownReady", "", (),
                                lambda *_: None, lambda e: log(f"vehicled refused the acknowledgement: {e}"), timeout=2.0)
            self.publish_shutdown()
            if cfg["shutdown"]["after_ack"] == "poweroff":
                log("powering off")
                subprocess.Popen(["systemctl", "poweroff"])
            return False

        def shutdown_v(self):
            sd = self.shutdown
            return dbus.Dictionary({
                "state": dbus.String(sd.state),
                "savers": dbus.Array(sorted(sd.savers), signature="s"),
                "waiting": dbus.Array(sorted(sd.waiting), signature="s"),
                "last_saved": dbus.Array(sd.last.get("saved", []), signature="s"),
                "last_timed_out": dbus.Array(sd.last.get("timed_out", []), signature="s"),
                "last_ms": dbus.UInt32(sd.last.get("ms", 0)),
                "last_cancelled": dbus.Boolean(sd.last.get("cancelled", False))}, signature="sv")

        def publish_shutdown(self):
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Shutdown": self.shutdown_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))

        @dbus.service.method(IFACE, in_signature="s", sender_keyword="sender")
        def RegisterSaver(self, name, sender=None):
            self.shutdown.register(str(name), str(sender or ""))
            log(f"saver registered: {name}")
            self.publish_shutdown()

        @dbus.service.method(IFACE, in_signature="s")
        def Saved(self, name):
            self.shutdown.done(str(name))
            self.publish_shutdown()

        @dbus.service.signal(IFACE)
        def PrepareForShutdown(self):
            pass

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

        def save(self):
            self.save_pending = False
            try:
                write_state(state_path, self.settings.values)
            except OSError as e:
                log(f"could not save {state_path}: {e}")
            return False

        def changed(self):
            # saved half a second later: a dragged slider sends many values, the SD card gets one write
            if not self.save_pending:
                self.save_pending = True
                GLib.timeout_add(500, self.save)
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Settings": self.settings_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))
            self.update_display()

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
            if name == "Shutdown":
                return self.shutdown_v()
            if name == "DisplayBrightness":
                return dbus.Double(self.display)
            if name == "Info":
                return self.info_v()
            raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary({"Settings": self.settings_v(), "Schema": self.schema_v(),
                                    "Shutdown": self.shutdown_v(), "DisplayBrightness": dbus.Double(self.display),
                                    "Info": self.info_v()},
                                   signature="sv")

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
