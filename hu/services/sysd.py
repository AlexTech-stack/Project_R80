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
                  Log (a{sv}): Settings -> System -> Diagnostics, from the HU's DLT daemon (dltclient.py,
                               diagnostics.py): connected (b), apps (aa{sv}: id, description, level,
                               running, errors, warnings; in [diagnostics] apps order), entries (aa{sv}:
                               time, app, context, level, text; the newest first, at most [diagnostics] keep)
                  Export (a{sv}): the last ExportLog: state (idle|writing|done|failed), message, dir
                  Update (a{sv}): software updates (D12, update.py): version (running), previous, pending
                                  (installed, starts next), trial (b: the running one is not confirmed yet),
                                  state (idle|checking|unpacking|ready|failed), message, source (phone|usb|
                                  file|rollback), found (a newer version on a USB stick), can_restart (b:
                                  pending, a restart command and the car stands still), can_rollback (b)
                  Shutdown (a{sv}): state (idle|saving|acked|cancelled), savers (as), waiting (as),
                                    last_saved (as), last_timed_out (as), last_ms (u), last_cancelled (b)
      methods     Set(s name, v value)   checked against system.ini; errors:
                                         de.r80.System1.Error.UnknownSetting / InvalidValue
                  Reset(s name), ResetAll()
                  SetLogLevel(s app, s level)  default | off | fatal | error | warning | info | debug |
                                         verbose, for every context of the DLT application (kept by
                                         the daemon); errors InvalidValue / UnknownApp / NotConnected
                  ClearLog()             the page's counters and list back to zero
                  ExportLog()            the DLT files (--log-dir) and a summary.txt onto a USB stick,
                                         into R80-logs/<date_time>/ (hu-mediad lends the stick out
                                         writable); error Busy while one runs
                  InstallFile(s path, s source)  check and install an update file (async: Update);
                                         errors NotFound, Busy
                  InstallFound()         the one on a USB stick (Update.found)
                  RestartNow()           start the installed update now (errors NotFound, NotAllowed:
                                         moving, or no --restart-command)
                  Rollback()             the previous release starts next
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
import shutil
import socket
import subprocess
import threading
import sys
import time
from pathlib import Path

import dlt
import dltclient as dc
from diagnostics import Diagnostics
import update

DEFAULT_CONFIG = Path(__file__).resolve().parent / "system.ini"
SYSTEM_CONFIG = Path("/etc/r80/system.ini")
TYPES = ("bool", "number", "choice")


log = dlt.context("MAIN", "System service")


class ConfigError(ValueError):
    pass


class SettingError(ValueError):
    """A value or a name that does not fit system.ini. `unknown` tells which."""

    def __init__(self, msg: str, unknown: bool = False):
        super().__init__(msg)
        self.unknown = unknown


def load_config(extra: str | None = None) -> dict:
    """{"settings": {name: {"type", "default", "min", "max" | "choices"}},
        "shutdown": {"save_timeout_s", "after_ack"}, "brightness": {...}, "info": {...},
        "diagnostics": {"keep", "apps"}, "update": {"health_s", "health_needs_ui", "max_starts",
        "allow_dev_key", "standstill_kmh"}}, checked."""
    cp = configparser.ConfigParser()
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else []) if f.is_file()])
    settings = {}
    shutdown = {}
    brightness = {}
    info = {}
    diag = {}
    upd = {}
    for section in cp.sections():
        if section == "update":
            keys = {"health_s": (10, 600), "max_starts": (1, 10), "standstill_kmh": (0, 10)}
            unknown = set(cp.options(section)) - set(keys) - {"health_needs_ui", "allow_dev_key"}
            if unknown:
                raise ConfigError(f"[update] unknown key(s): {', '.join(sorted(unknown))}")
            try:
                for k, (lo, hi) in keys.items():
                    upd[k] = float(cp.get(section, k))
                    if not lo <= upd[k] <= hi:
                        raise ValueError(f"{k} = {upd[k]:g} is outside {lo}..{hi}")
                upd["max_starts"] = int(upd["max_starts"])
                upd["health_needs_ui"] = cp.getboolean(section, "health_needs_ui")
                upd["allow_dev_key"] = cp.getboolean(section, "allow_dev_key")
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[update] {e}") from None
            continue
        if section == "diagnostics":
            unknown = set(cp.options(section)) - {"keep", "apps"}
            if unknown:
                raise ConfigError(f"[diagnostics] unknown key(s): {', '.join(sorted(unknown))}")
            try:
                diag["keep"] = int(cp.get(section, "keep"))
                diag["apps"] = [x.strip() for x in cp.get(section, "apps").split(",") if x.strip()]
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[diagnostics] {e}") from None
            if not 1 <= diag["keep"] <= 1000:
                raise ConfigError(f"[diagnostics] keep = {diag['keep']} is outside 1..1000")
            continue
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
    if not diag:
        raise ConfigError("[diagnostics] is missing")
    if not upd:
        raise ConfigError("[update] is missing")
    for need, t in (("brightness", "number"), ("night_dimming", "bool")):
        if settings.get(need, {}).get("type") != t:
            raise ConfigError(f"[setting {need}] ({t}) is needed for the display brightness")
    return {"settings": settings, "shutdown": shutdown, "brightness": brightness, "info": info, "diagnostics": diag,
            "update": upd}


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
                log.warning(f"ignoring saved setting {n!r}: not in system.ini")
                continue
            try:
                self.values[n] = check(n, schema[n], v)
            except SettingError as e:
                log.warning(f"saved setting ignored, back to default: {e}")

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
    info["version"] = read(repo / "VERSION", "unknown")          # an installed release (update.py)
    try:
        if info["version"] == "unknown":
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


def export_logs(src: Path, dest_root: Path, summary: str, now: float | None = None) -> dict:
    """Copy the DLT files (src/*.dlt, oldest first) and summary.txt into
    dest_root/R80-logs/<date_time>/. {"dir", "files", "bytes"}; OSError when it does not fit
    or a write fails (then the half-written folder is removed)."""
    files = sorted(src.glob("*.dlt"), key=lambda f: f.stat().st_mtime) if src.is_dir() else []
    need = sum(f.stat().st_size for f in files) + len(summary.encode()) + 65536
    free = shutil.disk_usage(dest_root).free
    if free < need:
        raise OSError(f"not enough space on the stick ({free // 1_000_000} MB free, {need // 1_000_000 + 1} MB needed)")
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now))
    dest = dest_root / "R80-logs" / stamp
    try:
        dest.mkdir(parents=True)
        for f in files:
            shutil.copyfile(f, dest / f.name)
        (dest / "summary.txt").write_text(summary, encoding="utf-8")
        os.sync()
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return {"dir": f"R80-logs/{stamp}", "files": len(files), "bytes": need - 65536}


def log_summary(info: dict, apps: list, entries, now: float | None = None) -> str:
    """summary.txt next to the exported DLT files: what was where, the counts, the last entries."""
    lines = ["R80 headunit: log export", f"exported   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}"]
    for k in ("version", "os", "kernel", "uptime_s", "mem_total_mb", "mem_available_mb", "disk_free_mb"):
        if k in info:
            lines.append(f"{k:<10} {info[k]}")
    lines += ["", "The log: *.dlt (DLT protocol version 1, ECU R80), opens in DLT Viewer.", "",
              "service                   level     errors  warnings  running"]
    for a in apps:
        lines.append(f"{a['id']:<4} {a['description'][:20]:<20} {a['level']:<9} {a['errors']:>6}  {a['warnings']:>8}  "
                     f"{'yes' if a['running'] else 'no'}")
    lines += ["", "the last warnings and errors, newest first:"]
    for e in entries:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["time"]))
        lines.append(f"{stamp}  {e['level']:<7} {e['app']:<4} {e['context']:<4} {e['text']}")
    return "\n".join(lines) + "\n"


def read_state(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning(f"ignoring unreadable state {path}: {e}")
        return None


def write_state(path: Path, values: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def update_view(running: str, rel: "update.Releases", u: dict, can_restart: bool) -> dict:
    """The Update property: what Settings -> System -> Software update shows."""
    return {"version": running, "previous": rel.version("previous"), "pending": rel.version("pending"),
            "trial": rel.on_trial() == running and bool(running), "state": u["state"], "message": u["message"],
            "source": u["source"], "found": u["found"], "can_restart": can_restart,
            "can_rollback": bool(rel.version("previous")) and not rel.version("pending")}


def run_service(cfg: dict, state_path: Path, system: bool, log_dir: Path, upd_opts: dict):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.System", "/de/r80/System", "de.r80.System1"
    PROPS = "org.freedesktop.DBus.Properties"
    VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")
    MEDIA = ("de.r80.Media", "/de/r80/Media", "de.r80.Media1")

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
            self.diag = Diagnostics(cfg["diagnostics"]["apps"], cfg["diagnostics"]["keep"])
            self.dlt_sock, self.dlt_parser, self.log_pending = None, None, False
            self.dlt_connect()
            self.export = {"state": "idle", "message": "", "dir": ""}
            # ---- software updates (D12)
            self.releases = update.Releases(upd_opts["releases"], cfg["update"]["max_starts"])
            self.upd = {"state": "idle", "message": "", "source": "", "found": ""}
            self.found_file = None                         # the newest update file on a stick
            self.mounts = []
            self.speed = None                              # km/h; None: not known
            self.running = self.info.get("version", "unknown")
            if self.releases.on_trial() == self.running:
                log.info(f"release {self.running} is on trial: healthy within {cfg['update']['health_s']:g} s?")
                self.trial_since = time.monotonic()
                GLib.timeout_add(1000, self.health_tick)
            bus.add_signal_receiver(self.on_media, "PropertiesChanged", PROPS, None, MEDIA[1])
            GLib.idle_add(self.read_media)

        # ---- diagnostics: the DLT daemon's warnings and errors (Settings -> System) ---
        def dlt_connect(self):
            port = int(os.environ.get("DLT_DAEMON_TCP_PORT", "3490"))
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            except OSError:
                GLib.timeout_add(2000, self.dlt_connect)
                return False
            s.setblocking(False)
            self.dlt_sock, self.dlt_parser = s, dc.Parser()
            GLib.io_add_watch(s.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.dlt_read)
            self.dlt_send(dc.get_log_info())
            self.publish_log()
            return False

        def dlt_send(self, data: bytes) -> bool:
            try:
                self.dlt_sock.sendall(data)
                return True
            except (OSError, AttributeError):
                return False

        def dlt_read(self, _fd, cond):
            data = b""
            try:
                data = self.dlt_sock.recv(65536)
            except BlockingIOError:
                return True
            except OSError:
                pass
            if not data or cond & (GLib.IO_HUP | GLib.IO_ERR):
                self.dlt_sock.close()
                self.dlt_sock = None
                self.publish_log()
                GLib.timeout_add(2000, self.dlt_connect)
                return False
            changed = False
            for m in self.dlt_parser.feed(data):
                changed |= self.diag.message(m)
            if changed:
                self.publish_log()
            return True

        def log_v(self):
            def var(v):
                return (dbus.Boolean(v) if isinstance(v, bool) else dbus.UInt32(v) if isinstance(v, int)
                        else dbus.Double(v) if isinstance(v, float) else dbus.String(v))
            return dbus.Dictionary({
                "connected": dbus.Boolean(self.dlt_sock is not None),
                "apps": dbus.Array([dbus.Dictionary({k: var(v) for k, v in a.items()}, signature="sv")
                                    for a in self.diag.apps()], signature="a{sv}"),
                "entries": dbus.Array([dbus.Dictionary({k: var(v) for k, v in e.items()}, signature="sv")
                                       for e in self.diag.entries], signature="a{sv}")}, signature="sv")

        def publish_log(self):
            # at most twice a second: a burst of warnings is one update for the UI
            if not self.log_pending:
                self.log_pending = True
                GLib.timeout_add(500, self.send_log)

        def send_log(self):
            self.log_pending = False
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Log": self.log_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))
            return False

        @dbus.service.method(IFACE, in_signature="ss")
        def SetLogLevel(self, app, level):
            app, level = str(app), str(level)
            if level != "default" and level not in dc.LEVELS:
                raise dbus.exceptions.DBusException(f"level {level!r}: default, {', '.join(dc.LEVELS)}",
                                                    name=IFACE + ".Error.InvalidValue")
            if not 1 <= len(app) <= 4:
                raise dbus.exceptions.DBusException(f"no application {app!r}", name=IFACE + ".Error.UnknownApp")
            n = -1 if level == "default" else dc.LEVELS.index(level)
            if not (self.dlt_send(dc.set_log_level(app, "", n)) and self.dlt_send(dc.store_configuration())
                    and self.dlt_send(dc.get_log_info())):
                raise dbus.exceptions.DBusException("no DLT daemon", name=IFACE + ".Error.NotConnected")
            log.info(f"log level of {app}: {level}")

        # ---- the log onto a USB stick: hu-mediad lends it out writable ----------
        @dbus.service.method(IFACE)
        def ExportLog(self):
            if self.export["state"] == "writing":
                raise dbus.exceptions.DBusException("an export is running", name=IFACE + ".Error.Busy")
            self.set_export("writing", "waiting for the USB stick")
            self.bus.call_async(MEDIA[0], MEDIA[1], MEDIA[2], "LendMedium", "s", ("",), self.export_to,
                                lambda e: self.set_export("failed", "no USB stick" if "NoMedium" in (e.get_dbus_name() or "")
                                                          else e.get_dbus_message() or "the media service did not answer"),
                                timeout=60.0)

        def export_to(self, key, mount):
            self.set_export("writing", "writing to the USB stick")
            summary = log_summary(self.info, self.diag.apps(), list(self.diag.entries))
            result = {}

            def work():                                    # copying megabytes: not on the main loop
                try:
                    result.update(export_logs(log_dir, Path(str(mount)), summary))
                except OSError as e:
                    result["error"] = str(e)
                GLib.idle_add(give_back)

            def give_back():
                def returned(*_):
                    if "error" in result:
                        log.warning(f"log export failed: {result['error']}")
                        self.set_export("failed", result["error"])
                    else:
                        mb = result["bytes"] / 1e6
                        files = f"{result['files']} log file" + ("" if result["files"] == 1 else "s")
                        log.info(f"log exported: {files}, {mb:.1f} MB to {result['dir']}")
                        self.set_export("done", f"{files}, {mb:.1f} MB in {result['dir']}",
                                        result["dir"])
                self.bus.call_async(MEDIA[0], MEDIA[1], MEDIA[2], "ReturnMedium", "s", (key,), returned, returned,
                                    timeout=60.0)
                return False
            threading.Thread(target=work, daemon=True).start()

        def set_export(self, state, message, path=""):
            self.export = {"state": state, "message": message, "dir": path}
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Export": self.export_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))

        def export_v(self):
            return dbus.Dictionary({k: dbus.String(v) for k, v in self.export.items()}, signature="sv")

        # ---- software updates (D12): from the phone (navd) or a USB stick -------
        def keys(self) -> list:
            ks = sorted((self.repo / "hu" / "update-keys").glob("*.pem"))
            if upd_opts["allow_dev_key"] or cfg["update"]["allow_dev_key"]:
                ks += sorted(Path(upd_opts["dev_keys"]).glob("*.pem"))
            return ks

        def can_restart(self) -> bool:
            return (bool(self.releases.version("pending")) and bool(upd_opts["restart_command"])
                    and self.speed is not None and self.speed < cfg["update"]["standstill_kmh"])

        def update_v(self):
            v = update_view(self.running, self.releases, self.upd, self.can_restart())
            return dbus.Dictionary({k: dbus.Boolean(x) if isinstance(x, bool) else dbus.String(x)
                                    for k, x in v.items()}, signature="sv")

        def publish_update(self):
            self.PropertiesChanged(IFACE, dbus.Dictionary({"Update": self.update_v()}, signature="sv"),
                                   dbus.Array([], signature="s"))

        def set_update(self, **kw):
            self.upd.update(kw)
            self.publish_update()

        def install(self, path: Path, source: str):
            if self.upd["state"] in ("checking", "unpacking"):
                raise dbus.exceptions.DBusException("an update is being installed", name=IFACE + ".Error.Busy")
            self.set_update(state="checking", message=f"checking {path.name}", source=source)
            origin = {"phone": "the phone", "usb": "a USB stick"}.get(source, "a file")
            log.info(f"update from {origin}: checking {path.name}")

            def progress(what):
                GLib.idle_add(lambda: self.set_update(state=what) and False)

            def work():
                try:
                    m = self.releases.install(path, self.keys(), self.running, progress)
                    GLib.idle_add(done, m["version"], None)
                except update.UpdateError as e:
                    GLib.idle_add(done, "", e)
                except OSError as e:
                    GLib.idle_add(done, "", update.UpdateError("io", str(e)))

            def done(version, err):
                if err is None:
                    log.info(f"update {version} installed from {origin}: starts with the next start")
                    self.set_update(state="ready", message=f"{version} starts with the next start of the HU")
                else:
                    log.warning(f"update from {origin} refused ({err.code}): {err}")
                    self.set_update(state="failed", message=str(err))
                self.scan_sticks()
                return False
            threading.Thread(target=work, daemon=True).start()

        @dbus.service.method(IFACE, in_signature="ss")
        def InstallFile(self, path, source):
            """An update file (navd: received from the phone; tests). source: phone | usb | file."""
            p = Path(str(path))
            if not p.is_file():
                raise dbus.exceptions.DBusException(f"no file {p}", name=IFACE + ".Error.NotFound")
            self.install(p, str(source) or "file")

        @dbus.service.method(IFACE)
        def InstallFound(self):
            """The update file found on a USB stick (Update.found)."""
            if self.found_file is None:
                raise dbus.exceptions.DBusException("no update on a USB stick", name=IFACE + ".Error.NotFound")
            self.install(self.found_file, "usb")

        @dbus.service.method(IFACE)
        def RestartNow(self):
            """Start the installed update now: only while the car stands still."""
            if not self.releases.version("pending"):
                raise dbus.exceptions.DBusException("no update waiting", name=IFACE + ".Error.NotFound")
            if not self.can_restart():
                why = ("this HU cannot restart itself" if not upd_opts["restart_command"]
                       else "only while the car stands still")
                raise dbus.exceptions.DBusException(why, name=IFACE + ".Error.NotAllowed")
            self.restart(f"restart for {self.releases.version('pending')}")

        @dbus.service.method(IFACE)
        def Rollback(self):
            """The previous release starts with the next start (or RestartNow)."""
            try:
                v = self.releases.rollback()
            except update.UpdateError as e:
                raise dbus.exceptions.DBusException(str(e), name=IFACE + ".Error.NotFound") from None
            log.info(f"back to {v} with the next start")
            self.set_update(state="ready", message=f"{v} starts with the next start of the HU", source="rollback")

        def restart(self, why: str):
            """Saves, then the restart command (the HU's unit; it ends this process too)."""
            log.info(f"{why}: {upd_opts['restart_command']}")
            if self.save_pending:
                self.save()
            os.sync()
            try:
                subprocess.Popen(upd_opts["restart_command"], shell=True, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                log.error(f"restart failed: {e}")

        def health_tick(self):
            names = cfg["info"]["services"]
            missing = [n for n in names if n != BUS_NAME and not self.bus.name_has_owner(n)]
            ui = not cfg["update"]["health_needs_ui"] or any(a["id"] == "HMI" and a["running"] for a in self.diag.apps())
            if not missing and ui:
                if self.releases.healthy(self.running):
                    log.info(f"release {self.running} is healthy: it stays")
                    self.publish_update()
                return False
            if time.monotonic() - self.trial_since < cfg["update"]["health_s"]:
                return True
            back = self.releases.give_up(self.running)
            what = ", ".join(missing + ([] if ui else ["the UI"]))
            log.error(f"release {self.running} is not healthy after {cfg['update']['health_s']:g} s "
                      f"(missing: {what}): back to {back or 'the checkout'}")
            self.set_update(state="failed", message=f"{self.running} did not start properly: back to {back or 'the previous one'}")
            if upd_opts["restart_command"]:
                self.restart("rollback")
            return False

        def read_media(self):
            self.bus.call_async(MEDIA[0], MEDIA[1], PROPS, "Get", "ss", (MEDIA[2], "Mounts"),
                                lambda v: self.on_media(MEDIA[2], {"Mounts": v}, []), lambda e: None, timeout=2.0)
            return False

        def on_media(self, iface, changed, _inv):
            if iface != MEDIA[2] or "Mounts" not in changed:
                return
            mounts = sorted(str(m.get("mount", "")) for m in changed["Mounts"])
            if mounts != self.mounts:
                self.mounts = mounts
                self.scan_sticks()

        def scan_sticks(self):
            """The newest update file on the sticks that this HU would take (checked in a thread)."""
            mounts = list(self.mounts)

            def work():
                best = None
                for m in mounts:
                    for f in sorted(Path(m, "R80-update").glob("*" + update.SUFFIX)) if m else []:
                        try:
                            v = update.verify(f, self.keys())["version"]
                        except (update.UpdateError, OSError) as e:
                            log.info(f"update file on the stick not usable: {f.name}: {e}")
                            continue
                        if (update.newer(v, self.running) and v != self.releases.version("pending")
                                and (best is None or update.newer(v, best[0]))):
                            best = (v, f)
                GLib.idle_add(found, best)

            def found(best):
                self.found_file = best[1] if best else None
                v = best[0] if best else ""
                if v != self.upd["found"]:
                    if v:
                        log.info(f"update {v} on a USB stick")
                    self.set_update(found=v)
                return False
            threading.Thread(target=work, daemon=True).start()

        @dbus.service.method(IFACE)
        def ClearLog(self):
            self.diag.clear()
            self.publish_log()

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
            if name == VEHICLE[0] and not new and self.speed is not None:
                self.speed = None
                self.publish_update()
            if name == MEDIA[0]:
                if new:
                    self.read_media()
                else:
                    self.on_media(MEDIA[2], {"Mounts": []}, [])
            if not new and name.startswith(":"):
                before = set(self.shutdown.savers)
                self.shutdown.gone(name)
                for n in sorted(before - set(self.shutdown.savers)):
                    log.warning(f"saver {n} is gone")
                if before != set(self.shutdown.savers):
                    self.publish_shutdown()

        def on_vehicle(self, iface, changed, _inv):
            if iface != VEHICLE[2]:
                return
            if "VehicleSpeed" in changed:
                v = float(changed["VehicleSpeed"])
                self.speed = None if math.isnan(v) else v
                self.publish_update()
            if "Night" in changed or "DimLevel" in changed:
                self.night = bool(changed.get("Night", self.night))
                self.dim_level = float(changed.get("DimLevel", self.dim_level))
                self.update_display()
            if "Power" not in changed:
                return
            power = str(changed["Power"])
            if power == "shutdown" and self.shutdown.state != "saving":
                waiting = self.shutdown.start(time.monotonic())
                log.info(f"shutdown: asking {', '.join(waiting) or 'nobody'} to save "
                         f"(at most {cfg['shutdown']['save_timeout_s']:g} s)")
                if self.save_pending:
                    self.save()
                self.PrepareForShutdown()
                self.publish_shutdown()
                GLib.timeout_add(50, self.shutdown_tick)
            elif power in ("on", "acc", "crank", "standby"):
                if self.shutdown.state == "saving":
                    log.info("shutdown cancelled: power is back")
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
            log.info(f"shutdown: saved {', '.join(last['saved']) or 'nothing'}"
                     + (f", no answer from {', '.join(last['timed_out'])}" if last["timed_out"] else "")
                     + f" after {last['ms']} ms; acknowledging to the MCU")
            self.bus.call_async(VEHICLE[0], VEHICLE[1], VEHICLE[2], "ShutdownReady", "", (),
                                lambda *_: None, lambda e: log.error(f"vehicled refused the acknowledgement: {e}"), timeout=2.0)
            self.publish_shutdown()
            if cfg["shutdown"]["after_ack"] == "poweroff":
                log.info("powering off")
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
            log.info(f"saver registered: {name}")
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
                log.error(f"could not save {state_path}: {e}")
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
                    log.info(f"{name} = {self.settings.values[str(name)]}")
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
                log.info("all settings back to their defaults")
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
            if name == "Log":
                return self.log_v()
            if name == "Export":
                return self.export_v()
            if name == "Update":
                return self.update_v()
            raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary({"Settings": self.settings_v(), "Schema": self.schema_v(),
                                    "Shutdown": self.shutdown_v(), "DisplayBrightness": dbus.Double(self.display),
                                    "Info": self.info_v(), "Log": self.log_v(),
                                    "Export": self.export_v(), "Update": self.update_v()},
                                   signature="sv")

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    System(bus)
    log.info(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, "
             f"{len(cfg['settings'])} settings, state {state_path}")
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/system.ini and /etc/r80/system.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "settings.json"), help="where the settings are saved")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    ap.add_argument("--log-dir", default=str(state_home / "r80" / "dlt" / "trace"),
                    help="the DLT daemon's files, what ExportLog copies (hu/services/dlt-daemon.sh STATE_DIR/trace)")
    ap.add_argument("--check", action="store_true", help="check the config, list the settings and exit")
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    ap.add_argument("--releases", default=str(data_home / "r80" / "releases"),
                    help="the HU's release folders (update.py; the target: /opt/r80/releases)")
    ap.add_argument("--dev-keys", default=str(config_home / "r80" / "update-keys"),
                    help="development keys (public *.pem), trusted only with --allow-dev-key or [update] allow_dev_key")
    ap.add_argument("--allow-dev-key", action="store_true", help="trust the development keys (the bench)")
    ap.add_argument("--restart-command", default="",
                    help="restarts the HU (its unit) for RestartNow and a rollback; empty: at the next start only")
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
    dlt.app("SYS", "System service", "sysd")
    run_service(cfg, Path(a.state), a.system, Path(a.log_dir).expanduser(),
                {"releases": Path(a.releases), "dev_keys": Path(a.dev_keys), "allow_dev_key": a.allow_dev_key,
                 "restart_command": a.restart_command})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
