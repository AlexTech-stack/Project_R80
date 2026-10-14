#!/usr/bin/env python3
"""hu-navd: the navigation service of the R80 headunit (decision D11).

The phone navigates; the R80 Companion app sends the guidance of the phone's navigation
app over the companion link (hu/companion_link.py, docs/companion-protocol.md). navd
runs the HU's side of that link and publishes what to show:

    bus name   de.r80.Nav
    object     /de/r80/Nav
    interface  de.r80.Nav1
      properties  Phone (a{sv}): connected (b), device (s), app (s: name and version),
                                 bad_lines (u: dropped invalid lines, all sessions)
                  Guidance (a{sv}): active (b), stale (b: the phone link is lost, last state kept),
                                 source (s), maneuver (s), modifier (s, "" = none), exit (u, 0 = none),
                                 distance_m (d), street (s), text (s), remaining_m (d), remaining_s (d)
                                 (-1 = not sent by the phone), arrival (x: unix time, 0 = unknown)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

One phone at a time: a new connection replaces the old one (a phone that reconnects
before the old link timed out). The timing is in nav.ini. The transport here is a local
stream socket (--socket; the phone emulator in the virtual environment connects to it);
Bluetooth RFCOMM on the target comes later and only replaces how bytes arrive.
The session logic (Link) has no sockets and no clock, so tests can drive it with their own time.
"""
from __future__ import annotations

import argparse
import configparser
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion_link as cl  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "nav.ini"
SYSTEM_CONFIG = Path("/etc/r80/nav.ini")
VERSION = "0.1"
KEYS = {"link": {"heartbeat_s": (0.2, 60), "link_timeout_s": (0.5, 600), "hello_timeout_s": (0.5, 600)},
        "guidance": {"keep_after_loss_s": (0, 3600)}}


def log(*a):
    print("[navd]", *a, flush=True)


class ConfigError(ValueError):
    pass


def load_config(extra: str | None = None) -> dict:
    cp = configparser.ConfigParser()
    if extra and not Path(extra).is_file():
        raise ConfigError(f"config file not found: {extra}")
    cp.read([str(f) for f in [DEFAULT_CONFIG, SYSTEM_CONFIG] + ([Path(extra)] if extra else []) if f.is_file()])
    cfg = {}
    for s in cp.sections():
        if s not in KEYS:
            raise ConfigError(f"unknown section [{s}]")
        unknown = set(cp.options(s)) - set(KEYS[s])
        if unknown:
            raise ConfigError(f"[{s}] unknown key(s): {', '.join(sorted(unknown))}")
    for s, keys in KEYS.items():
        for k, (lo, hi) in keys.items():
            try:
                v = float(cp.get(s, k))
            except (configparser.Error, ValueError) as e:
                raise ConfigError(f"[{s}] {k}: {e}") from None
            if not lo <= v <= hi:
                raise ConfigError(f"[{s}] {k} = {v} is outside {lo}..{hi}")
            cfg[k] = v
    if cfg["link_timeout_s"] <= cfg["heartbeat_s"]:
        raise ConfigError("[link] link_timeout_s must be longer than heartbeat_s")
    return cfg


class Link:
    """The phone session and the guidance it delivered. Feed it events with the monotonic
    time `now` (and the wall clock `wall` for the arrival time); it returns what to send.
    `close` is set when the connection has to be closed; the caller then calls lost()."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.connected = False
        self.greeted = False
        self.device = ""
        self.app = ""
        self.bad_lines = 0
        self.guidance: dict | None = None
        self.arrival = 0
        self.stale = False
        self.lost_at: float | None = None
        self.close = False
        self.why = ""          # why `close` was set, for the log
        self.last_rx = self.last_tx = self.connected_at = 0.0

    def connect(self, now: float):
        self.connected, self.greeted, self.close = True, False, False
        self.device = self.app = ""
        self.connected_at = self.last_rx = self.last_tx = now

    def lost(self, now: float):
        if not self.connected:
            return
        self.connected = self.greeted = False
        self.close = False
        if self.guidance:
            self.stale, self.lost_at = True, now

    def bad_line(self):
        self.bad_lines += 1

    def receive(self, now: float, msg: dict, wall: float | None = None) -> list[dict]:
        self.last_rx = now
        t = msg["type"]
        if t == cl.BYE:
            self.close, self.why = True, f"the phone said bye ({msg['reason'] or 'no reason'})"
            return []
        if not self.greeted:
            if t != cl.HELLO:
                return []
            if msg["proto"] != cl.PROTO_VERSION:
                self.close, self.why = True, f"the phone speaks protocol {msg['proto']}, not {cl.PROTO_VERSION}"
                return [cl.bye(f"protocol {cl.PROTO_VERSION} expected")]
            self.greeted = True
            self.device = msg["device"] or ""
            self.app = f"{msg['app']} {msg['version']}"
            return [cl.hello("r80-hu", VERSION, heartbeat_s=self.cfg["heartbeat_s"])]
        if t == cl.GUIDANCE:
            if msg["active"]:
                self.guidance = msg
                rs = msg["remaining_s"]
                self.arrival = int((time.time() if wall is None else wall) + rs) if rs is not None else 0
            else:
                self.guidance, self.arrival = None, 0
            self.stale, self.lost_at = False, None
        return []

    def tick(self, now: float) -> list[dict]:
        if self.connected:
            if not self.greeted and now - self.connected_at > self.cfg["hello_timeout_s"]:
                self.close, self.why = True, "no hello in time"
                return [cl.bye("no hello")]
            if now - self.last_rx > self.cfg["link_timeout_s"]:
                self.close, self.why = True, "nothing received in time"
                return []
            if self.greeted and now - self.last_tx >= self.cfg["heartbeat_s"]:
                return [cl.heartbeat()]
        elif self.guidance and self.lost_at is not None and now - self.lost_at > self.cfg["keep_after_loss_s"]:
            self.guidance, self.arrival, self.stale, self.lost_at = None, 0, False, None
        return []

    def sent(self, now: float):
        self.last_tx = now

    def phone(self) -> dict:
        return {"connected": self.connected and self.greeted, "device": self.device, "app": self.app,
                "bad_lines": self.bad_lines}

    def view(self) -> dict:
        g = self.guidance
        if not g:
            return {"active": False, "stale": False, "source": "", "maneuver": "", "modifier": "", "exit": 0,
                    "distance_m": -1.0, "street": "", "text": "", "remaining_m": -1.0, "remaining_s": -1.0, "arrival": 0}
        m = g["maneuver"]

        def num(k):
            return -1.0 if g[k] is None else float(g[k])
        return {"active": True, "stale": self.stale, "source": g["source"], "maneuver": m["type"],
                "modifier": m["modifier"] or "", "exit": m["exit"] or 0, "distance_m": num("distance_m"),
                "street": g["street"] or "", "text": g["text"] or "", "remaining_m": num("remaining_m"),
                "remaining_s": num("remaining_s"), "arrival": self.arrival}


def run_service(cfg: dict, sock_path: Path, system: bool):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.Nav", "/de/r80/Nav", "de.r80.Nav1"
    PROPS = "org.freedesktop.DBus.Properties"
    TYPES = {"connected": dbus.Boolean, "device": dbus.String, "app": dbus.String, "bad_lines": dbus.UInt32,
             "active": dbus.Boolean, "stale": dbus.Boolean, "source": dbus.String, "maneuver": dbus.String,
             "modifier": dbus.String, "exit": dbus.UInt32, "distance_m": dbus.Double, "street": dbus.String,
             "text": dbus.String, "remaining_m": dbus.Double, "remaining_s": dbus.Double, "arrival": dbus.Int64}

    def variant(d: dict):
        return dbus.Dictionary({k: TYPES[k](v) for k, v in d.items()}, signature="sv")

    class Nav(dbus.service.Object):
        def __init__(self, bus):
            super().__init__(bus, OBJ_PATH)
            self.link = Link(cfg)
            self.conn: socket.socket | None = None
            self.watch = None
            self.decoder = cl.Decoder()
            self.published = {}
            sock_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                sock_path.unlink()
            except FileNotFoundError:
                pass
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(str(sock_path))
            self.server.listen(2)
            GLib.io_add_watch(self.server.fileno(), GLib.IO_IN, self.on_accept)
            GLib.timeout_add(200, self.on_tick)

        # ---- transport ------------------------------------------------------
        def on_accept(self, *_):
            conn, _addr = self.server.accept()
            if self.conn:
                log("a new phone connection replaces the old one")
                self.drop()
            conn.setblocking(False)
            self.conn, self.decoder = conn, cl.Decoder()
            self.link.connect(time.monotonic())
            self.watch = GLib.io_add_watch(conn.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_data)
            log("phone connection opened")
            return True

        def on_data(self, _fd, cond):
            try:
                data = self.conn.recv(65536) if cond & GLib.IO_IN else b""
            except BlockingIOError:
                return True
            except OSError:
                data = b""
            if not data:
                log("phone link closed by the phone")
                self.watch = None          # returning False removes this watch
                self.drop()
                return False
            now = time.monotonic()
            self.link.last_rx = now        # any bytes, even a bad line, show the link is alive
            before = self.decoder.errors
            for msg in self.decoder.feed(data):
                self.send(self.link.receive(now, msg))
            for _ in range(self.decoder.errors - before):
                self.link.bad_line()
            if self.decoder.errors > before:
                log(f"dropped {self.decoder.errors - before} bad line(s): {self.decoder.last_error}")
            if self.link.close:
                log(f"closing the phone link: {self.link.why}")
                self.watch = None
                self.drop()
                return False
            if self.link.greeted and not self.published.get("Phone", {}).get("connected"):
                log(f"phone hello: {self.link.device or 'unnamed device'}, {self.link.app}")
            self.publish()
            return True

        def send(self, msgs):
            for m in msgs:
                if not self.conn:
                    return
                try:
                    self.conn.sendall(cl.encode(m))
                    self.link.sent(time.monotonic())
                except OSError as e:
                    self.link.close, self.link.why = True, f"send failed: {e}"
                    return

        def drop(self):
            if self.watch is not None:
                GLib.source_remove(self.watch)
                self.watch = None
            if self.conn:
                try:
                    self.conn.close()
                except OSError:
                    pass
                self.conn = None
            self.link.lost(time.monotonic())
            self.publish()

        def on_tick(self):
            self.send(self.link.tick(time.monotonic()))
            if self.link.close and self.conn:
                log(f"phone link lost: {self.link.why}")
                self.drop()
            self.publish()
            return True

        # ---- D-Bus ----------------------------------------------------------
        def props(self):
            return {"Phone": self.link.phone(), "Guidance": self.link.view()}

        def publish(self):
            changed = {}
            for name, v in self.props().items():
                if v != self.published.get(name):
                    self.published[name] = v
                    changed[name] = variant(v)
            if changed:
                self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))

        @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, name):
            p = self.props()
            if name not in p:
                raise dbus.exceptions.DBusException(f"no property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")
            return variant(p[name])

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return dbus.Dictionary({k: variant(v) for k, v in self.props().items()}, signature="sv")

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):
            pass

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Nav(bus)
    log(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, phone link on {sock_path}")
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/nav.ini and /etc/r80/nav.ini")
    run = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
    ap.add_argument("--socket", default=str(run / "companion.sock"), help="local socket the phone (emulator) connects to")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[navd] bad config: {e}")
    run_service(cfg, Path(a.socket), a.system)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
