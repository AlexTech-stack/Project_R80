#!/usr/bin/env python3
"""hu-tripd: the trip computer of the R80 headunit (decision D10).

Two trips from the signals hu-vehicled publishes:
  since start  starts over when the ignition was off longer than auto_reset_h (trip.ini)
  long-term    starts over only when the driver resets it

    bus name   de.r80.Trip
    object     /de/r80/Trip
    interface  de.r80.Trip1
      properties  SinceStart (a{sv}), LongTerm (a{sv}), each:
                    distance (d, km), time (u, s), avg_speed (d, km/h), max_speed (d, km/h),
                    avg_consumption (d, l/100 km: the car's own value, the same for both)
      methods     Reset(s which: since_start | long_term)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

Distance comes from odometer steps (not from integrating speed), driving time counts
while the HU is on (count_time_in). The trips are state, saved to --state (default
$XDG_STATE_HOME/r80/trip.json), including when the ignition went off, so the auto-reset
also works across a power cycle of the HU. The logic (Trips) has no D-Bus and no clock,
so tests can drive it with their own time.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent / "trip.ini"
SYSTEM_CONFIG = Path("/etc/r80/trip.ini")
WHICH = ("since_start", "long_term")


def log(*a):
    print("[tripd]", *a, flush=True)


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> dict:
    cp = configparser.ConfigParser()
    files = [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else [])
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in files if f.is_file()])
    keys = {"auto_reset_h", "count_time_in", "max_odometer_jump_km", "min_time_for_average_s"}
    for s in cp.sections():
        if s != "trip":
            raise ConfigError(f"unknown section [{s}]")
    unknown = set(cp.options("trip")) - keys if cp.has_section("trip") else set()
    if unknown:
        raise ConfigError(f"[trip] unknown key(s): {', '.join(sorted(unknown))}")

    def num(key, lo, hi):
        try:
            v = float(cp.get("trip", key))
        except (configparser.Error, ValueError) as e:
            raise ConfigError(f"[trip] {key}: {e}") from None
        if not lo <= v <= hi:
            raise ConfigError(f"[trip] {key} = {v} is outside {lo}..{hi}")
        return v
    states = [p.strip() for p in cp.get("trip", "count_time_in", fallback="").split(",") if p.strip()]
    if not states:
        raise ConfigError("[trip] count_time_in needs at least one power state")
    return {"auto_reset_h": num("auto_reset_h", 0, 24 * 365), "count_time_in": states,
            "max_jump_km": num("max_odometer_jump_km", 0.1, 1000),
            "min_avg_s": num("min_time_for_average_s", 0, 3600)}


def blank() -> dict:
    return {"distance": 0.0, "time": 0.0, "max_speed": 0.0}


class Trips:
    """The two trips. Feed it power, odometer and speed; call tick(dt) for driving time."""

    def __init__(self, cfg: dict, saved: dict | None = None):
        self.cfg = cfg
        saved = saved if isinstance(saved, dict) else {}
        self.trips = {}
        for w in WHICH:
            t = saved.get(w) if isinstance(saved.get(w), dict) else {}
            self.trips[w] = {k: float(t[k]) if isinstance(t.get(k), (int, float)) else v for k, v in blank().items()}
        self.last_odo = saved.get("last_odometer") if isinstance(saved.get("last_odometer"), (int, float)) else None
        self.off_since = saved.get("off_since") if isinstance(saved.get("off_since"), (int, float)) else None
        self.saved_at = saved.get("saved_at") if isinstance(saved.get("saved_at"), (int, float)) else None
        self.power = None
        self.avg_consumption = 0.0

    def counting(self) -> bool:
        return self.power in self.cfg["count_time_in"]

    def on_power(self, wall: float, power: str) -> bool:
        """New power state at wall-clock time `wall`; returns True if 'since start' was reset."""
        first = self.power is None
        was = self.counting()
        self.power = power
        if first and self.off_since is None:
            # Started without knowing when the ignition went off (e.g. the HU lost power
            # while driving): the last save is the latest moment it was still on.
            self.off_since = self.saved_at
        reset = False
        if self.counting() and not was:
            if self.off_since is not None and wall - self.off_since > self.cfg["auto_reset_h"] * 3600:
                self.reset("since_start")
                reset = True
            self.off_since = None
        elif not self.counting() and (was or self.off_since is None):
            self.off_since = wall
        return reset

    def on_odometer(self, km: float):
        if self.last_odo is not None:
            step = km - self.last_odo
            if 0 < step <= self.cfg["max_jump_km"]:
                for t in self.trips.values():
                    t["distance"] += step
        self.last_odo = km

    def on_speed(self, kmh: float):
        if self.counting():
            for t in self.trips.values():
                t["max_speed"] = max(t["max_speed"], kmh)

    def tick(self, dt: float):
        if self.counting():
            for t in self.trips.values():
                t["time"] += dt

    def reset(self, which: str):
        self.trips[which] = blank()

    def values(self, which: str) -> dict:
        t = self.trips[which]
        avg = t["distance"] / (t["time"] / 3600) if t["time"] >= max(self.cfg["min_avg_s"], 1) else 0.0
        return {"distance": round(t["distance"], 1), "time": int(t["time"]), "avg_speed": round(avg, 1),
                "max_speed": round(t["max_speed"], 1), "avg_consumption": round(self.avg_consumption, 1)}

    def state(self, wall: float) -> dict:
        return {"since_start": dict(self.trips["since_start"]), "long_term": dict(self.trips["long_term"]),
                "last_odometer": self.last_odo, "off_since": self.off_since, "saved_at": wall}


def read_state(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"ignoring unreadable state {path}: {e}")
        return None


def write_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    os.replace(tmp, path)


def run_service(cfg: dict, state_path: Path, system: bool):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    from saver import register_saver

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.Trip", "/de/r80/Trip", "de.r80.Trip1"
    PROPS = "org.freedesktop.DBus.Properties"
    VEHICLE = ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1")
    NAMES = {"since_start": "SinceStart", "long_term": "LongTerm"}

    class Trip(dbus.service.Object):
        def __init__(self, bus):
            super().__init__(bus, OBJ_PATH)
            self.bus = bus
            self.trips = Trips(cfg, read_state(state_path))
            self.published = {}
            self.last_tick = time.monotonic()
            self.last_save = 0.0
            bus.add_signal_receiver(self.on_vehicle, "PropertiesChanged", PROPS, None, VEHICLE[1])
            bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                    "org.freedesktop.DBus", "/org/freedesktop/DBus")
            GLib.idle_add(self.read_all)
            GLib.timeout_add(1000, self.tick)
            register_saver(bus, "tripd", self.save, log)   # trips saved before a shutdown (D12)

        def read_all(self):
            self.bus.call_async(VEHICLE[0], VEHICLE[1], PROPS, "GetAll", "s", (VEHICLE[2],),
                                lambda props: self.on_vehicle(VEHICLE[2], props, []), lambda e: None, timeout=1.0)
            return False

        def on_owner(self, name, _old, new):
            if name == VEHICLE[0] and new:
                self.read_all()

        def on_vehicle(self, iface, changed, _inv):
            if iface != VEHICLE[2]:
                return
            if "Power" in changed:
                if self.trips.on_power(time.time(), str(changed["Power"])):
                    log("ignition was off longer than auto_reset_h: 'since start' starts over")
                self.save()
            if "Odometer" in changed:
                self.trips.on_odometer(float(changed["Odometer"]))
            if "VehicleSpeed" in changed:
                self.trips.on_speed(float(changed["VehicleSpeed"]))
            if "AvgConsumption" in changed:
                self.trips.avg_consumption = float(changed["AvgConsumption"])

        def tick(self):
            now = time.monotonic()
            self.trips.tick(now - self.last_tick)
            self.last_tick = now
            self.publish()
            if now - self.last_save > 5:
                self.save()
            return True

        def save(self):
            self.last_save = time.monotonic()
            try:
                write_state(state_path, self.trips.state(time.time()))
            except OSError as e:
                log(f"could not save {state_path}: {e}")

        def variant(self, which):
            v = self.trips.values(which)
            return dbus.Dictionary({"distance": dbus.Double(v["distance"]), "time": dbus.UInt32(v["time"]),
                                    "avg_speed": dbus.Double(v["avg_speed"]), "max_speed": dbus.Double(v["max_speed"]),
                                    "avg_consumption": dbus.Double(v["avg_consumption"])}, signature="sv")

        def publish(self):
            changed = {}
            for which, name in NAMES.items():
                v = self.trips.values(which)
                if v != self.published.get(which):
                    self.published[which] = v
                    changed[name] = self.variant(which)
            if changed:
                self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))

        @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, name):
            for which, n in NAMES.items():
                if n == name:
                    return self.variant(which)
            raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary({n: self.variant(w) for w, n in NAMES.items()}, signature="sv")

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

        @dbus.service.method(IFACE, in_signature="s")
        def Reset(self, which):
            which = str(which)
            if which not in WHICH:
                raise dbus.exceptions.DBusException(f"unknown trip {which!r}; known: {', '.join(WHICH)}",
                                                    name="de.r80.Trip1.Error.UnknownTrip")
            self.trips.reset(which)
            log(f"reset {which}")
            self.publish()
            self.save()

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Trip(bus)
    log(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, state {state_path}")
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/trip.ini and /etc/r80/trip.ini")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state", default=str(state_home / "r80" / "trip.json"), help="where the trips are saved")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[tripd] bad config: {e}")
    run_service(cfg, Path(a.state), a.system)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
