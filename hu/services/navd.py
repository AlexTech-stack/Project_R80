#!/usr/bin/env python3
"""hu-navd: the navigation service of the R80 headunit (decision D11).

The phone navigates; the R80 Companion app sends the guidance of the phone's navigation
app over the companion link (hu/companion_link.py, docs/companion-protocol.md). navd
runs the HU's side of that link and publishes what to show:

    bus name   de.r80.Nav
    object     /de/r80/Nav
    interface  de.r80.Nav1
      properties  Phone (a{sv}): connected (b), device (s), app (s: name and version),
                                 via (s: "Bluetooth dev_…", "TCP <ip>", "local socket"),
                                 bad_lines (u: dropped invalid lines, all sessions)
                  Guidance (a{sv}): active (b), stale (b: the phone link is lost, last state kept),
                                 source (s), maneuver (s), modifier (s, "" = none), exit (u, 0 = none),
                                 distance_m (d), street (s), text (s), remaining_m (d), remaining_s (d)
                                 (-1 = not sent by the phone), arrival (x: unix time, 0 = unknown)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

One phone at a time: a new connection replaces the old one (a phone that reconnects
before the old link timed out). The timing is in nav.ini. Ways in, all the same protocol:
  Bluetooth   --bluetooth system: navd registers the companion service (RFCOMM, UUID
              companion_link.SERVICE_UUID) with BlueZ (org.bluez.ProfileManager1); BlueZ hands
              over each connection of a paired phone (Profile1.NewConnection). Registration is
              renewed whenever bluetoothd (re)starts. --bluetooth session looks for BlueZ on
              the session bus instead (the tests' stand-in BlueZ).
  local       --socket: a local stream socket (the phone emulator, the tests)
  TCP         --tcp PORT: development with a real phone over Wi-Fi (no authentication or
              encryption: only on a trusted network, never on the target)
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
import dlt  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "nav.ini"
SYSTEM_CONFIG = Path("/etc/r80/nav.ini")
VERSION = "0.1"
KEYS = {"link": {"heartbeat_s": (0.2, 60), "link_timeout_s": (0.5, 600), "hello_timeout_s": (0.5, 600)},
        "guidance": {"keep_after_loss_s": (0, 3600)}}


log = dlt.context("MAIN", "Navigation service")


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


def run_service(cfg: dict, sock_path: Path, system: bool, tcp_port: int | None = None, bluez_bus: str | None = None):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.Nav", "/de/r80/Nav", "de.r80.Nav1"
    BLUEZ, PROFILE_PATH = "org.bluez", "/de/r80/Nav/companion_profile"
    PROPS = "org.freedesktop.DBus.Properties"
    TYPES = {"connected": dbus.Boolean, "device": dbus.String, "app": dbus.String, "bad_lines": dbus.UInt32, "via": dbus.String,
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
            self.conn_from = ""
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
            GLib.io_add_watch(self.server.fileno(), GLib.IO_IN, self.on_accept, self.server)
            if tcp_port:
                tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                tcp.bind(("0.0.0.0", tcp_port))
                tcp.listen(2)
                self.tcp = tcp
                GLib.io_add_watch(tcp.fileno(), GLib.IO_IN, self.on_accept, tcp)
                log.warning(f"phone link also on TCP port {tcp_port} (development only: no authentication)")
            GLib.timeout_add(200, self.on_tick)

        # ---- transport ------------------------------------------------------
        def on_accept(self, _fd, _cond, server):
            conn, addr = server.accept()
            self.adopt(conn, "TCP " + addr[0] if server.family == socket.AF_INET else "local socket")
            return True

        def adopt(self, conn: socket.socket, how: str):
            """Takes over a new phone connection, whichever way it came in."""
            if self.conn:
                log.info("a new phone connection replaces the old one")
                self.drop()
            conn.setblocking(False)
            self.conn, self.decoder, self.conn_from = conn, cl.Decoder(), how
            self.link.connect(time.monotonic())
            self.watch = GLib.io_add_watch(conn.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_data)
            log.info(f"phone connection opened ({how})")

        def on_data(self, _fd, cond):
            try:
                data = self.conn.recv(65536) if cond & GLib.IO_IN else b""
            except BlockingIOError:
                return True
            except OSError:
                data = b""
            if not data:
                log.info("phone link closed by the phone")
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
                log.error(f"dropped {self.decoder.errors - before} bad line(s): {self.decoder.last_error}")
            if self.link.close:
                log.info(f"closing the phone link: {self.link.why}")
                self.watch = None
                self.drop()
                return False
            if self.link.greeted and not self.published.get("Phone", {}).get("connected"):
                log.info(f"phone hello: {self.link.app}")      # not the device's name: it is often the driver's
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
                log.warning(f"phone link lost: {self.link.why}")
                self.drop()
            self.publish()
            return True

        # ---- D-Bus ----------------------------------------------------------
        def props(self):
            phone = self.link.phone()
            phone["via"] = self.conn_from if phone["connected"] else ""
            return {"Phone": phone, "Guidance": self.link.view()}

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

    class Profile(dbus.service.Object):
        """org.bluez.Profile1: BlueZ calls this for each RFCOMM connection to our UUID."""

        def __init__(self, bt_bus, nav):
            super().__init__(bt_bus, PROFILE_PATH)
            self.bt_bus, self.nav = bt_bus, nav
            self.devices: dict[str, socket.socket] = {}
            bt_bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                       "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=BLUEZ)
            if bt_bus.name_has_owner(BLUEZ):
                self.register()
            else:
                log.info(f"waiting for BlueZ on the {bluez_bus} bus")

        def on_owner(self, _name, _old, new):
            if new:
                self.register()

        def register(self):
            # Without "Channel" BlueZ registers a custom UUID with an L2CAP-only service record and
            # no RFCOMM listener: phones find the service but cannot connect.
            opts = dbus.Dictionary({"Name": "R80 Companion", "Role": "server",
                                    "Channel": dbus.UInt16(cl.RFCOMM_CHANNEL),
                                    "RequireAuthentication": True, "RequireAuthorization": False},
                                   signature="sv")
            self.bt_bus.call_async(BLUEZ, "/org/bluez", "org.bluez.ProfileManager1", "RegisterProfile", "osa{sv}",
                                   (dbus.ObjectPath(PROFILE_PATH), cl.SERVICE_UUID, opts),
                                   lambda: log.info(f"Bluetooth: companion service registered with BlueZ ({cl.SERVICE_UUID})"),
                                   lambda e: log.error(f"Bluetooth: BlueZ refused the companion service: {e.get_dbus_message()}"),
                                   timeout=5.0)

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}")
        def NewConnection(self, device, fd, _props):
            conn = socket.socket(fileno=fd.take())
            self.devices[str(device)] = conn
            self.nav.adopt(conn, f"Bluetooth {str(device).rsplit('/', 1)[-1]}")

        @dbus.service.method("org.bluez.Profile1", in_signature="o")
        def RequestDisconnection(self, device):
            conn = self.devices.pop(str(device), None)
            if conn is not None and conn is self.nav.conn:
                log.info("Bluetooth: BlueZ asks to disconnect the phone")
                self.nav.drop()

        @dbus.service.method("org.bluez.Profile1")
        def Release(self):
            log.info("Bluetooth: BlueZ released the companion service")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    nav = Nav(bus)
    log.info(f"serving {BUS_NAME} on the {'system' if system else 'session'} bus, phone link on {sock_path}")
    if bluez_bus:
        bt_bus = dbus.SystemBus() if bluez_bus == "system" else dbus.SessionBus()
        Profile(bt_bus, nav)
    GLib.MainLoop().run()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config file, read after hu/nav.ini and /etc/r80/nav.ini")
    run = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
    ap.add_argument("--socket", default=str(run / "companion.sock"), help="local socket the phone (emulator) connects to")
    ap.add_argument("--tcp", type=int, metavar="PORT", help="also accept the phone on this TCP port (development, trusted network only)")
    ap.add_argument("--bluetooth", choices=("system", "session"), metavar="BUS",
                    help="accept the phone over Bluetooth: register with BlueZ on this bus (system = the real "
                         "Bluetooth stack, session = the tests' stand-in)")
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()
    dlt.app("NAV", "Navigation service", "navd")
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[navd] bad config: {e}")
    run_service(cfg, Path(a.socket), a.system, a.tcp, a.bluetooth)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
