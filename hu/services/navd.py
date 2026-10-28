#!/usr/bin/env python3
"""hu-navd: the navigation service of the R80 headunit (decision D11).

The phone navigates; the R80 Companion app sends the guidance of the phone's navigation
app over the companion link (hu/companion_link.py, docs/companion-protocol.md). navd
runs the HU's side of that link and publishes what to show:

    bus name   de.r80.Nav
    object     /de/r80/Nav
    interface  de.r80.Nav1
      properties  Phone (a{sv}): connected (b), device (s), app (s: name and version),
                                 via (s: "Bluetooth ..:EE:FF", "TCP <ip>", "local socket"),
                                 bad_lines (u: dropped invalid lines, all sessions)
                  Guidance (a{sv}): active (b), stale (b: the phone link is lost, last state kept),
                                 source (s), maneuver (s), modifier (s, "" = none), exit (u, 0 = none),
                                 distance_m (d), street (s), text (s), remaining_m (d), remaining_s (d)
                                 (-1 = not sent by the phone), arrival (x: unix time, 0 = unknown)
                  Weather (a{sv}): from the phone (an internet weather service): valid (b), source (s),
                                 time (x: when the service made it, unix s; 0 = none yet), temp_c (d),
                                 code (i: WMO weather code), days (aa{sv}: date s, code i, max_c d, min_c d;
                                 today first). Kept after the link is gone; the UI decides when it is too old
                  Position (a{sv}): from the phone: valid (b), time (x), alt_m (d), accuracy_m (d),
                                 heading_deg (d) (-1 = not sent). The phone never sends coordinates
                  Assistant (a{sv}): the phone answers for the voice assistant: connected (b: a phone with
                                 caps assistant), ready (b), provider (s), model (s), reason (s: why not ready)
      methods     Ask(s request) -> s reply: the voice assistant's question (hu-assistd), see below
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

To a phone that wants it (caps car_status) navd sends how the car is (car_status): after the
phone's hello, every [car_status] interval_s and a final one when the ignition goes off
(IgnitionState Off, else Power off),
from hu-vehicled, hu-tripd, hu-warnd and hu-sysd (the accent colour). car_status() builds it
without D-Bus. To a phone with caps remote (a passenger's remote) navd sends what plays and the
volume (media, from hu-mediad and hu-audiod, Remote), carries out its media_cmd (unless the
setting phone_remote is off) and answers its browse requests from hu-mediad's browse tree.
To a phone with caps update navd says which software runs and how an update goes
(update_status, from hu-sysd's Update); the phone may offer a newer update file and send it
in pieces (UpdateTransfer, --update-dir); hu-sysd checks and installs it (InstallFile). Nothing
the phone sends is trusted: the signature check is sysd's. A transfer that broke off resumes.
For the voice assistant (caps assistant) the phone asks the LLM with the user's own key: hu-assistd
calls Ask with JSON {messages, tools, max_tokens}; navd sends it as assist_request and returns the
phone's assist_reply as JSON ({ok, message, finish, usage, ms} or {ok: false, code, error}). No phone,
no answer within [assistant] timeout_s or the link lost: {ok: false, code: no_phone | timeout}. What
is asked and answered never goes into the log.

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
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion_link as cl  # noqa: E402
import dlt  # noqa: E402
import update  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "nav.ini"
SYSTEM_CONFIG = Path("/etc/r80/nav.ini")
VERSION = "0.2"
CAPS = ["weather", "position", "car_status", "remote", "update", "assistant"]   # navd's hello: what it wants (weather, position) and offers
MEDIA_EVERY_S = 0.5                       # the remote's media state at most this often
VEHICLE = {"fuel_pct": "FuelLevel", "range_km": "Range", "odometer_km": "Odometer", "battery_v": "BatteryVoltage",
           "outside_c": "OutsideTemp", "service_km": "ServiceDistance", "service_days": "ServiceDays"}
KEYS = {"link": {"heartbeat_s": (0.2, 60), "link_timeout_s": (0.5, 600), "hello_timeout_s": (0.5, 600)},
        "guidance": {"keep_after_loss_s": (0, 3600)}, "car_status": {"interval_s": (5, 3600)},
        "assistant": {"timeout_s": (2, 300)}}


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


def car_status(vehicle: dict, trip: dict, warnings: list, settings: dict, now: float, final: bool = False) -> dict:
    """The car_status message from the services' D-Bus properties (plain values): hu-vehicled's
    (signals, LinkUp, StaleSignals), hu-tripd's SinceStart, hu-warnd's Active, hu-sysd's Settings.
    Stale signals and everything without the MCU link are left out."""
    values = {}
    if vehicle.get("LinkUp"):
        stale = set(vehicle.get("StaleSignals", []))
        for key, sig in VEHICLE.items():
            v = vehicle.get(sig)
            if v is not None and sig not in stale:
                values[key] = round(float(v), 1)
    if trip:
        values["trip"] = {"km": round(float(trip.get("distance", 0)), 1), "minutes": int(trip.get("time", 0)) // 60,
                          "avg_kmh": round(float(trip.get("avg_speed", 0)))}
    values["warnings"] = [{"severity": w["severity"], "text": w["text"]} for w in warnings
                          if w.get("severity") in cl.SEVERITIES][:cl.MAX_WARNINGS]
    if settings.get("accent"):
        values["accent"] = settings["accent"]
    return cl.car_status(int(now), final, **values)


class Remote:
    """The remote's view of the HU (companion `media`): hu-mediad's and hu-audiod's properties
    and the setting phone_remote, as plain values. update() says whether the phone has to hear
    of it: anything shown changed, or the position jumped (a seek), not the position running on."""

    MEDIA = ("PlaybackStatus", "Source", "Sources", "Metadata", "Shuffle", "RepeatAll", "TrackIndex",
             "TrackCount", "QueueTitle", "UpNext")
    AUDIO = ("Master", "Max", "Muted")

    def __init__(self):
        self.media: dict = {}
        self.audio: dict = {}
        self.allowed = True
        self.position_s = 0.0
        self.position_at = 0.0          # wall time of position_s

    def update(self, media: dict | None = None, audio: dict | None = None, allowed: bool | None = None,
               now: float | None = None) -> bool:
        now = time.time() if now is None else now
        changed = False
        if media:
            for k in self.MEDIA:
                if k in media and media[k] != self.media.get(k):
                    self.media[k] = media[k]
                    changed = True
            if "Position" in media:
                pos = float(media["Position"]) / 1e6
                if abs(pos - self.expected(now)) > 2.0:
                    changed = True              # a seek, a new track: not just running on
                self.position_s, self.position_at = pos, now
        if audio:
            for k in self.AUDIO:
                if k in audio and audio[k] != self.audio.get(k):
                    self.audio[k] = audio[k]
                    changed = True
        if allowed is not None and allowed != self.allowed:
            self.allowed = allowed
            changed = True
        return changed

    def expected(self, now: float) -> float:
        playing = self.media.get("PlaybackStatus") == "playing"
        return self.position_s + (now - self.position_at if playing else 0.0)

    def message(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        m, a, meta = self.media, self.audio, self.media.get("Metadata", {})
        dur = meta.get("duration")
        return {"type": cl.MEDIA, "allowed": self.allowed, "status": m.get("PlaybackStatus") or "stopped",
                "source": m.get("Source", ""), "sources": list(m.get("Sources", [])),
                "title": meta.get("title", ""), "artist": meta.get("artist", ""), "album": meta.get("album", ""),
                "duration_s": float(dur) if dur else None, "position_s": round(max(0.0, self.expected(now)), 1),
                "time": round(now, 2), "shuffle": bool(m.get("Shuffle", False)), "repeat": bool(m.get("RepeatAll", False)),
                "track": m.get("TrackIndex") if m.get("TrackCount") else None, "tracks": m.get("TrackCount"),
                "queue": m.get("QueueTitle", ""),
                "up_next": [{"title": u.get("title", ""), "artist": u.get("artist", "")}
                            for u in m.get("UpNext", [])[:cl.MAX_UP_NEXT]],
                "volume": a.get("Master"), "volume_max": a.get("Max"), "muted": bool(a.get("Muted", False))}


def browse_result(req: dict, title: str, total: int, entries: list) -> dict:
    """The answer to a browse request, as many entries as fit into one line."""
    page = [{"kind": e.get("kind", "track"), "id": e.get("id", ""), "title": e.get("title", ""),
             "subtitle": e.get("subtitle", ""), "index": e.get("index", -1) if e.get("kind") == "track" else -1}
            for e in entries if e.get("kind") in cl.KINDS]
    while True:
        msg = {"type": cl.BROWSE_RESULT, "id": req["id"], "path": req["path"], "title": title, "total": total,
               "offset": req["offset"], "entries": page}
        try:
            cl.encode(msg)
            return msg
        except cl.ProtocolError:
            if not page:
                raise
            page = page[:-1]                    # too long for a line: one entry less, the phone pages on


class TransferError(Exception):
    pass


class UpdateTransfer:
    """An update file from the phone (caps update, docs/companion-protocol.md): its update_offer,
    the update_chunks in order, update_done. It lands in `folder`; hu-sysd checks the signature
    and installs it, so the size and the SHA-256 are all this checks. A transfer that broke off
    resumes: the partial file is kept under its SHA-256 until another update is offered."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.offer: dict | None = None
        self.received = 0

    def part(self, sha: str) -> Path:
        return self.folder / f"{sha}.part"

    def start(self, offer: dict, running: str, pending: str, busy: bool) -> str:
        """"" if taken (self.received: where the phone goes on), else why not."""
        v = offer["version"]
        if busy:
            return "the HU is installing an update"
        try:
            update.parse_version(v)
        except update.UpdateError:
            return f"not a version: {v}"
        if not update.newer(v, running):
            return f"{v} is not newer than the running {running}"
        if pending and not update.newer(v, pending):
            return f"{pending} is already waiting for the next start"
        self.folder.mkdir(parents=True, exist_ok=True)
        for f in self.folder.iterdir():                  # one transfer at a time: older pieces go
            if f.name != self.part(offer["sha256"]).name:
                f.unlink()
        if shutil.disk_usage(self.folder).free < offer["size"] * 5:
            return "not enough space on the HU"
        p = self.part(offer["sha256"])
        have = p.stat().st_size if p.exists() else 0
        if have > offer["size"]:
            p.unlink()
            have = 0
        self.offer, self.received = offer, have
        return ""

    def chunk(self, msg: dict) -> int | None:
        """Where the transfer is after this piece (None: not this transfer). A piece that is not
        the next one is not written; the answer tells the phone where to go on."""
        if not self.offer or msg["id"] != self.offer["id"]:
            return None
        if msg["offset"] != self.received:
            return self.received
        if self.received + len(msg["data"]) > self.offer["size"]:
            raise TransferError("more data than offered")
        with self.part(self.offer["sha256"]).open("ab") as f:
            f.write(msg["data"])
        self.received += len(msg["data"])
        return self.received

    def finish(self, msg: dict) -> Path:
        """The complete file, ready for hu-sysd; TransferError if it is not what was offered."""
        o = self.offer
        if not o or msg["id"] != o["id"]:
            raise TransferError("no such transfer")
        if self.received != o["size"]:
            raise TransferError(f"only {self.received} of {o['size']} bytes arrived")
        p = self.part(o["sha256"])
        h = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1 << 16), b""):
                h.update(block)
        self.offer = None
        if h.hexdigest() != o["sha256"]:
            p.unlink()
            raise TransferError("the file is not the one offered (SHA-256)")
        done = self.folder / f"r80-hu-{re.sub(r'[^0-9A-Za-z.+-]', '_', o['version'])}{update.SUFFIX}"
        p.replace(done)
        return done

    def stop(self):
        """The link is gone: the pieces stay for a resume."""
        self.offer = None


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
        self.weather: dict | None = None
        self.position: dict | None = None
        self.assist: dict | None = None   # the phone's assist_status (whether it can answer)
        self.caps: set = set()            # what the phone said it takes part in (its hello)
        self.requests: list[dict] = []    # media_cmd and browse from the phone, for the service to carry out
        self.arrival = 0
        self.stale = False
        self.lost_at: float | None = None
        self.close = False
        self.why = ""          # why `close` was set, for the log
        self.last_rx = self.last_tx = self.connected_at = 0.0

    def connect(self, now: float):
        self.connected, self.greeted, self.close = True, False, False
        self.caps = set()
        self.requests = []
        self.assist = None
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
            self.caps = set(msg["caps"])
            return [cl.hello("r80-hu", VERSION, caps=CAPS, heartbeat_s=self.cfg["heartbeat_s"])]
        if t == cl.GUIDANCE:
            if msg["active"]:
                self.guidance = msg
                rs = msg["remaining_s"]
                self.arrival = int((time.time() if wall is None else wall) + rs) if rs is not None else 0
            else:
                self.guidance, self.arrival = None, 0
            self.stale, self.lost_at = False, None
        elif t == cl.WEATHER:
            self.weather = msg
        elif t == cl.POSITION:
            self.position = msg
        elif t == cl.ASSIST_STATUS:
            self.assist = msg
        elif t in (cl.MEDIA_CMD, cl.BROWSE, cl.UPDATE_OFFER, cl.UPDATE_CHUNK, cl.UPDATE_DONE, cl.ASSIST_REPLY):
            self.requests.append(msg)
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

    def assist_view(self) -> dict:
        a = self.assist or {}
        on = self.connected and self.greeted and "assistant" in self.caps
        return {"connected": on, "ready": on and bool(a.get("ready")), "provider": a.get("provider", "") if on else "",
                "model": a.get("model", "") if on else "",
                "reason": (a.get("reason", "") if a else "the app said nothing yet") if on else "no phone with the app"}

    def weather_view(self) -> dict:
        w = self.weather
        if not w:
            return {"valid": False, "source": "", "time": 0, "temp_c": 0.0, "code": 0, "days": []}
        return {"valid": True, "source": w["source"], "time": w["time"], "temp_c": float(w["now"]["temp_c"]),
                "code": w["now"]["code"], "days": [{"date": d["date"], "code": d["code"], "max_c": float(d["max_c"]),
                                                    "min_c": float(d["min_c"])} for d in w["days"]]}

    def position_view(self) -> dict:
        p = self.position or {}

        def num(k):
            return -1.0 if p.get(k) is None else float(p[k])
        return {"valid": bool(p) and p.get("alt_m") is not None, "time": p.get("time", 0), "alt_m": num("alt_m"),
                "accuracy_m": num("accuracy_m"), "heading_deg": num("heading_deg")}

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


def run_service(cfg: dict, sock_path: Path, system: bool, tcp_port: int | None = None, bluez_bus: str | None = None,
                update_dir: Path | None = None):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    BUS_NAME, OBJ_PATH, IFACE = "de.r80.Nav", "/de/r80/Nav", "de.r80.Nav1"
    SOURCES = {"vehicle": ("de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1"),
               "trip": ("de.r80.Trip", "/de/r80/Trip", "de.r80.Trip1"),
               "warnings": ("de.r80.Warnings", "/de/r80/Warnings", "de.r80.Warnings1"),
               "system": ("de.r80.System", "/de/r80/System", "de.r80.System1"),
               "media": ("de.r80.Media", "/de/r80/Media", "de.r80.Media1"),
               "audio": ("de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1")}
    BLUEZ, PROFILE_PATH = "org.bluez", "/de/r80/Nav/companion_profile"
    PROPS = "org.freedesktop.DBus.Properties"
    TYPES = {"connected": dbus.Boolean, "device": dbus.String, "app": dbus.String, "bad_lines": dbus.UInt32, "via": dbus.String,
             "active": dbus.Boolean, "stale": dbus.Boolean, "source": dbus.String, "maneuver": dbus.String,
             "modifier": dbus.String, "exit": dbus.UInt32, "distance_m": dbus.Double, "street": dbus.String,
             "text": dbus.String, "remaining_m": dbus.Double, "remaining_s": dbus.Double, "arrival": dbus.Int64}

    TYPES.update({"valid": dbus.Boolean, "time": dbus.Int64, "temp_c": dbus.Double, "code": dbus.Int32,
                  "alt_m": dbus.Double, "accuracy_m": dbus.Double, "heading_deg": dbus.Double, "date": dbus.String,
                  "max_c": dbus.Double, "min_c": dbus.Double, "ready": dbus.Boolean, "provider": dbus.String,
                  "model": dbus.String, "reason": dbus.String})

    def variant(d: dict):
        def one(k, v):
            if k == "days":
                return dbus.Array([variant(x) for x in v], signature="a{sv}")
            return TYPES[k](v)
        return dbus.Dictionary({k: one(k, v) for k, v in d.items()}, signature="sv")

    def plain(v):
        if isinstance(v, dbus.Boolean):
            return bool(v)
        if isinstance(v, dbus.String):
            return str(v)
        if isinstance(v, dbus.Dictionary):
            return {str(k): plain(x) for k, x in v.items()}
        if isinstance(v, dbus.Array):
            return [plain(x) for x in v]
        if isinstance(v, (dbus.Double, float)):
            return float(v)
        if isinstance(v, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
            return int(v)
        return v

    class Nav(dbus.service.Object):
        def __init__(self, bus):
            super().__init__(bus, OBJ_PATH)
            self.bus = bus
            self.link = Link(cfg)
            self.status_sent = 0.0               # monotonic: when car_status went out last
            self.power = ""
            self.final_sent = False
            bus.add_signal_receiver(self.on_vehicle, "PropertiesChanged", PROPS, None, SOURCES["vehicle"][1])
            # the remote: what plays, the volume, whether the phone may control them
            self.remote = Remote()
            self.transfer = UpdateTransfer(update_dir or sock_path.parent / "update-incoming")
            self.sys_update: dict = {}                                # hu-sysd's Update
            self.handed: Path | None = None                           # a received file sysd is checking
            self.media_due = None                                     # a pending (throttled) media message
            self.media_sent = 0.0
            for name, handler in (("media", self.on_media), ("audio", self.on_audio), ("system", self.on_system)):
                svc, path, iface = SOURCES[name]
                bus.add_signal_receiver(handler, "PropertiesChanged", PROPS, None, path)

                def appeared(owner, svc=svc, path=path, iface=iface, h=handler):
                    if owner:                    # there now (also: started after navd): read all of it once
                        bus.call_async(svc, path, PROPS, "GetAll", "s", (iface,), lambda p: h(iface, p, []),
                                       lambda _e: None, timeout=2.0)
                bus.watch_name_owner(svc, appeared)
            svc, path, iface = SOURCES["vehicle"]                    # the power state navd starts in
            bus.call_async(svc, path, PROPS, "Get", "ss", (iface, "Power"),
                           lambda p: setattr(self, "power", self.power or str(p)), lambda _e: None, timeout=2.0)
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
            self.asks: dict[int, tuple] = {}      # assist_request id -> (reply callback, timeout source, sent at)
            self.ask_id = 0
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
                was = self.link.greeted
                self.send(self.link.receive(now, msg))
                if not was and self.link.greeted:
                    self.send_status()               # how the car is, right after the hello
                    self.media_changed()             # and what plays, for the remote
                    self.send_update_status()        # and which software runs
            for req in self.link.requests:
                try:
                    self.carry_out(req)
                except Exception:                    # one bad request must not stop reading the link
                    log.exception(f"phone request {req.get('cmd') or req['type']} failed")
            self.link.requests.clear()
            for _ in range(self.decoder.errors - before):
                self.link.bad_line()
            if self.decoder.errors > before:
                log.warning(f"dropped {self.decoder.errors - before} bad line(s): {self.decoder.last_error}")
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
            if self.transfer.offer:
                log.info(f"update transfer stopped at {self.transfer.received} bytes: the link is gone")
            self.transfer.stop()
            self.fail_asks("no_phone", "the phone went away")
            self.status_sent = 0.0
            self.publish()

        # ---- the remote: media and volume to and from the phone (caps remote) ---
        def wants_remote(self):
            return self.conn is not None and self.link.greeted and "remote" in self.link.caps

        def on_media(self, iface, changed, _inv):
            if self.remote.update(media=plain(changed)):
                self.media_changed()

        def on_audio(self, iface, changed, _inv):
            if self.remote.update(audio=plain(changed)):
                self.media_changed()

        def on_system(self, iface, changed, _inv):
            if "Update" in changed:
                self.sys_update = plain(changed["Update"])
                if self.handed and self.sys_update.get("state") in ("ready", "failed"):
                    self.handed.unlink(missing_ok=True)               # installed (or refused): not needed any more
                    self.handed = None
                self.send_update_status()
            settings = plain(changed.get("Settings", {}))
            if "phone_remote" in settings and self.remote.update(allowed=bool(settings["phone_remote"])):
                log.info(f"the phone may {'' if self.remote.allowed else 'not '}control the HU")
                self.media_changed()

        def media_changed(self):
            """Send the media state, at most every MEDIA_EVERY_S (a burst of changes is one message)."""
            if not self.wants_remote() or self.media_due is not None:
                return
            wait = max(0.0, MEDIA_EVERY_S - (time.monotonic() - self.media_sent))
            self.media_due = GLib.timeout_add(int(wait * 1000), self.send_media)

        def send_media(self):
            self.media_due = None
            if self.wants_remote():
                self.media_sent = time.monotonic()
                self.send([self.remote.message()])
            return False

        # ---- updates from the phone (caps update, D12) ---------------------------
        def wants_update(self):
            return self.conn is not None and self.link.greeted and "update" in self.link.caps

        def send_update_status(self, state: str | None = None, message: str | None = None):
            if not self.wants_update():
                return
            u = self.sys_update
            t = self.transfer
            st = state or ("receiving" if t.offer else u.get("state", "idle"))
            self.send([cl.update_status(u.get("version", "unknown") or "unknown", st, pending=u.get("pending", ""),
                                        message=u.get("message", "") if message is None else message,
                                        id=t.offer["id"] if t.offer else None, received=t.received if t.offer else None)])

        def on_update(self, req: dict):
            t = self.transfer
            if req["type"] == cl.UPDATE_OFFER:
                if not self.sys_update:
                    why = "the HU's system service is not there"
                else:
                    why = t.start(req, self.sys_update.get("version", ""), self.sys_update.get("pending", ""),
                                  self.sys_update.get("state") in ("checking", "unpacking"))
                if why:
                    log.info(f"update {req['version']} from the phone not taken: {why}")
                    self.send_update_status("refused", why)
                    return
                log.info(f"update {req['version']} from the phone: receiving {req['size']} bytes"
                         + (f", going on at {t.received}" if t.received else ""))
                self.send_update_status("receiving", "")
            elif req["type"] == cl.UPDATE_CHUNK:
                try:
                    got = t.chunk(req)
                except (TransferError, OSError) as e:
                    log.warning(f"update transfer failed: {e}")
                    t.stop()
                    self.send_update_status("failed", str(e))
                    return
                if got is not None:
                    self.send([cl.update_ack(req["id"], got)])
            else:                                                     # update_done
                try:
                    path = t.finish(req)
                except (TransferError, OSError) as e:
                    log.warning(f"update from the phone not complete: {e}")
                    self.send_update_status("failed", str(e))
                    return
                log.info(f"update file from the phone complete: {path.name}, for hu-sysd to check")
                svc, spath, siface = SOURCES["system"]
                # sysd answers once it started checking, before its result: from then on the file
                # may go when sysd is done with it (ready / failed)
                self.bus.call_async(svc, spath, siface, "InstallFile", "ss", (str(path), "phone"),
                                    lambda *_: setattr(self, "handed", path),
                                    lambda e: self.send_update_status("failed", e.get_dbus_message()), timeout=5.0)

        # ---- the voice assistant's questions (caps assistant): the phone asks the LLM ----------
        def ask_done(self, rid: int, reply: dict):
            entry = self.asks.pop(rid, None)
            if entry is None:
                return                                # too late: it timed out, or the link went away
            done, timer, t0 = entry
            if timer:
                GLib.source_remove(timer)
            how = "answered" if reply.get("ok") else f"not answered ({reply.get('code')})"
            log.info(f"assistant request {rid} {how} after {time.monotonic() - t0:.1f} s")
            done(json.dumps({k: v for k, v in reply.items() if k not in ("type", "id")}))

        def fail_asks(self, code: str, why: str):
            for rid in list(self.asks):
                self.ask_done(rid, {"ok": False, "code": code, "error": why})

        @dbus.service.method(IFACE, in_signature="s", out_signature="s", async_callbacks=("done", "failed"))
        def Ask(self, request, done, failed):
            try:
                req = json.loads(str(request))
                if not isinstance(req, dict):
                    raise ValueError("not a JSON object")
                self.ask_id += 1
                msg = cl.assist_request(self.ask_id, req.get("messages"), req.get("tools"), req.get("max_tokens"))
                line = cl.encode(msg)
            except (ValueError, cl.ProtocolError) as e:
                failed(dbus.exceptions.DBusException(f"bad request: {e}", name="de.r80.Nav1.Error.BadRequest"))
                return
            rid = self.ask_id
            if not self.link.assist_view()["connected"]:
                done(json.dumps({"ok": False, "code": "no_phone", "error": "no phone with the R80 Companion app"}))
                return
            timer = GLib.timeout_add(int(cfg["timeout_s"] * 1000),
                                     lambda: (self.ask_done(rid, {"ok": False, "code": "timeout",
                                                                  "error": "no answer from the phone in time"}), False)[1])
            self.asks[rid] = (done, timer, time.monotonic())
            log.info(f"assistant request {rid}: {len(msg['messages'])} message(s), {len(line)} bytes, to the phone")
            try:
                self.conn.sendall(line)
                self.link.sent(time.monotonic())
            except OSError as e:
                self.link.close, self.link.why = True, f"send failed: {e}"
                self.ask_done(rid, {"ok": False, "code": "no_phone", "error": "the link to the phone failed"})

        def carry_out(self, req: dict):
            """A media_cmd, browse, update or assist_reply message from the phone."""
            if req["type"] == cl.ASSIST_REPLY:
                self.ask_done(req["id"], req)
                return
            if req["type"] in (cl.UPDATE_OFFER, cl.UPDATE_CHUNK, cl.UPDATE_DONE):
                self.on_update(req)
                return
            msvc, mpath, miface = SOURCES["media"]
            if req["type"] == cl.BROWSE:
                def answer(title, total, entries):
                    self.send([browse_result(req, str(title), int(total), plain(entries))])

                def missing(_e):
                    self.send([browse_result(req, "", -1, [])])
                self.bus.call_async(msvc, mpath, miface, "Browse", "sii", (req["path"], req["offset"], req["count"]),
                                    answer, missing, timeout=5.0)
                return
            if not self.remote.allowed:
                log.info(f"phone command {req['cmd']} ignored: the phone may not control the HU (Settings -> Phone)")
                self.media_changed()
                return
            cmd, v = req["cmd"], req.get("value")
            # the method and its arguments, built only for this command (each value has its own type)
            calls = {"play": lambda: (miface, "Play", "", ()), "pause": lambda: (miface, "Pause", "", ()),
                     "next": lambda: (miface, "Next", "", ()), "previous": lambda: (miface, "Previous", "", ()),
                     "seek": lambda: (miface, "SetPosition", "x", (int(v * 1e6),)),
                     "shuffle": lambda: (miface, "SetShuffle", "b", (v,)), "repeat": lambda: (miface, "SetRepeatAll", "b", (v,)),
                     "source": lambda: (miface, "SetSource", "s", (v,)),
                     "play_from": lambda: (miface, "PlayFrom", "si", (req["path"], req["index"])),
                     "volume": lambda: (SOURCES["audio"][2], "SetMaster", "i", (v,)),
                     "mute": lambda: (SOURCES["audio"][2], "SetMuted", "b", (v,))}
            iface, method, sig, args = calls[cmd]()
            svc, path = (SOURCES["audio"][0], SOURCES["audio"][1]) if iface == SOURCES["audio"][2] else (msvc, mpath)
            log.debug(f"phone command {cmd}")
            self.bus.call_async(svc, path, iface, method, sig, args, lambda *_: None,
                                lambda e: log.warning(f"phone command {cmd}: {e.get_dbus_message()}"), timeout=5.0)

        # ---- car_status: how the car is, to a phone that wants it ------------
        def wants_status(self):
            return self.conn is not None and self.link.greeted and "car_status" in self.link.caps

        def on_vehicle(self, iface, changed, _inv):
            # The final status when the ignition goes off, while the signals are still fresh;
            # Power going off (the bus asleep) is the fallback. Once per ignition cycle.
            ign = str(changed.get("IgnitionState", ""))
            if ign in ("IgnitionOn", "Cranking"):
                self.final_sent = False
            if "Power" in changed:
                power = str(changed["Power"])
                if power == "on":
                    self.final_sent = False
                gone = power in ("off", "shutdown") and self.power not in ("", "off", "shutdown")
                self.power = power
            else:
                gone = False
            if (ign == "Off" or gone) and not self.final_sent and self.wants_status():
                self.final_sent = True
                self.send_status(final=True)

        def send_status(self, final=False):
            """Gathers the services' properties (each may be missing), then sends car_status."""
            if not self.wants_status():
                return
            self.status_sent = time.monotonic()
            got, left = {}, set(SOURCES)

            def done(name, props):
                got[name] = plain(props) if props is not None else {}
                left.discard(name)
                if not left and self.wants_status():
                    v, s = got["vehicle"], got["system"]
                    msg = car_status(v, got["trip"].get("SinceStart", {}), got["warnings"].get("Active", []),
                                     s.get("Settings", {}), time.time(), final)
                    self.send([msg])
            for name, (svc, path, iface) in SOURCES.items():
                self.bus.call_async(svc, path, PROPS, "GetAll", "s", (iface,),
                                    lambda p, n=name: done(n, p), lambda _e, n=name: done(n, None), timeout=2.0)

        def on_tick(self):
            greeted = self.link.greeted
            self.send(self.link.tick(time.monotonic()))
            if greeted and self.wants_status() and time.monotonic() - self.status_sent >= cfg["interval_s"]:
                self.send_status()
            if self.link.close and self.conn:
                log.warning(f"phone link lost: {self.link.why}")
                self.drop()
            self.publish()
            return True

        # ---- D-Bus ----------------------------------------------------------
        def props(self):
            phone = self.link.phone()
            phone["via"] = self.conn_from if phone["connected"] else ""
            return {"Phone": phone, "Guidance": self.link.view(), "Weather": self.link.weather_view(),
                    "Position": self.link.position_view(), "Assistant": self.link.assist_view()}

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
            mac = str(device).rsplit("/", 1)[-1].removeprefix("dev_").replace("_", ":")
            self.nav.adopt(conn, f"Bluetooth {dlt.address(mac)}")     # it goes into the log

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
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    ap.add_argument("--update-dir", default=str(cache / "r80" / "update-incoming"),
                    help="where an update file from the phone is put together (hu-sysd then installs it)")
    a = ap.parse_args()
    dlt.app("NAV", "Navigation service", "navd")
    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        sys.exit(f"[navd] bad config: {e}")
    run_service(cfg, Path(a.socket), a.system, a.tcp, a.bluetooth, Path(a.update_dir))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
