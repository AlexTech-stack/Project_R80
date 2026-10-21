#!/usr/bin/env python3
"""Phone emulator: stands in for the R80 Companion app on the driver's phone (PC only).

Connects to hu-navd's companion link socket and speaks the companion protocol
(hu/companion_link.py). Two uses:

  library   `Phone` for the BoAt tests: connect, say hello, send any message or raw
            bytes, read what the HU sends, stop heartbeats to provoke a link loss.
  program   plays a route (route_demo.json) as the guidance a navigation app would show:
            the distance to the next maneuver counts down with the car's speed
            (VehicleSpeed from hu-vehicled when it runs, else --speed-kmh), rounded the
            way navigation apps show it. At the destination it ends the guidance and
            starts over. Reconnects when navd restarts. Like the app, it also sends a demo
            weather and the altitude when the HU asks for them (caps in its hello).

    python3 phone_emu.py                         # demo route, until Ctrl+C
    python3 phone_emu.py --route my_route.json --speed-kmh 80
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "hu" / "services"))
import companion_link as cl  # noqa: E402

DEFAULT_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "companion.sock"
APP, VERSION = "r80-companion", "phone_emu"


def log(*a):
    print("[phone_emu]", *a, flush=True)


class Phone:
    """One emulated phone connection. Thread-safe enough for tests: a reader thread
    collects everything the HU sends in `received`; a heartbeat thread keeps the link
    alive at the interval from the HU's hello unless `heartbeats` is False."""

    def __init__(self, path: Path | str = DEFAULT_SOCKET, device: str = "Emulated phone"):
        """path: navd's local socket, or "tcp:HOST:PORT" for navd --tcp."""
        self.path, self.device = str(path), device
        self.sock: socket.socket | None = None
        self.decoder = cl.Decoder()
        self.received: list[dict] = []
        self.closed_by_hu = threading.Event()
        self.heartbeats = True
        self.heartbeat_s = 2.0
        self._last_tx = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def connect(self, hello: bool = True, proto: int = cl.PROTO_VERSION, timeout: float = 3.0,
                sock: socket.socket | None = None, caps=("guidance",)) -> dict | None:
        """Connect (or use `sock`, an already connected stream, e.g. the phone's end of what a test hands
        to navd as a Bluetooth connection); with hello, send ours and wait for the HU's.
        Returns the HU's hello (or None)."""
        if sock is not None:
            self.sock = sock
        elif self.path.startswith("tcp:"):           # tcp:host:port, e.g. a Pi's navd --tcp
            host, port = self.path[4:].rsplit(":", 1)
            self.sock = socket.create_connection((host, int(port)), timeout=5)
            self.sock.settimeout(None)
        else:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.path)
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._beater, daemon=True).start()
        if not hello:
            return None
        msg = cl.hello(APP, VERSION, caps=list(caps), device=self.device)
        msg["proto"] = proto
        self.send_raw((json.dumps({k: v for k, v in msg.items() if v is not None}) + "\n").encode())
        reply = self.wait_for(cl.HELLO, timeout)
        if reply and reply.get("heartbeat_s"):
            self.heartbeat_s = reply["heartbeat_s"]
        return reply

    def send(self, msg: dict):
        self.send_raw(cl.encode(msg))

    def send_raw(self, data: bytes):
        with self._lock:
            self.sock.sendall(data)
            self._last_tx = time.monotonic()

    def wait_for(self, msg_type: str, timeout: float = 3.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in self.received:
                if m["type"] == msg_type:
                    return m
            if self.closed_by_hu.is_set():
                break
            time.sleep(0.02)
        return next((m for m in self.received if m["type"] == msg_type), None)

    def close(self, bye: bool = False):
        self._stop.set()
        if self.sock:
            try:
                if bye:
                    self.send(cl.bye("user"))
                self.sock.shutdown(socket.SHUT_RDWR)   # wakes the reader; close() alone would not end the link
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass

    def _reader(self):
        while not self._stop.is_set():
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            if not data:
                self.closed_by_hu.set()
                return
            self.received += self.decoder.feed(data)

    def _beater(self):
        while not self._stop.wait(0.1):
            if self.heartbeats and not self.closed_by_hu.is_set() and time.monotonic() - self._last_tx >= self.heartbeat_s:
                try:
                    self.send(cl.heartbeat())
                except OSError:
                    return


def demo_weather(now: float | None = None) -> dict:
    """A weather message as the app sends it: partly cloudy, then four days from today."""
    now = time.time() if now is None else now
    days = [(time.strftime("%Y-%m-%d", time.localtime(now + 86400 * i)), code, hi, lo)
            for i, (code, hi, lo) in enumerate([(2, 14.2, 6.1), (0, 17.0, 7.3), (61, 11.4, 5.2), (71, 1.5, -2.6)])]
    return cl.weather("open-meteo", int(now) - 600, 12.3, 2, days)


def demo_position(now: float | None = None) -> dict:
    return cl.position(int(time.time() if now is None else now), alt_m=412.0, accuracy_m=5.0)


# ---- route player -------------------------------------------------------------

def shown_distance(m: float) -> float:
    """Round like a navigation app: 100 m steps from 1 km, 50 m from 300 m, else 10 m."""
    step = 100 if m >= 1000 else 50 if m >= 300 else 10
    return float(round(m / step) * step)


def vehicle_speed():
    """VehicleSpeed (km/h) from hu-vehicled, or None if it does not run."""
    try:
        import dbus
        obj = dbus.SessionBus().get_object("de.r80.Vehicle", "/de/r80/Vehicle")
        return float(obj.Get("de.r80.Vehicle1", "VehicleSpeed", dbus_interface="org.freedesktop.DBus.Properties"))
    except Exception:
        return None


class RoutePlayer:
    """A route as a navigation app shows it. Feed it the metres driven; guidance() is the
    message the app would send now (distance and remaining rounded like an app shows them).
    Route file: {"name", "source", "average_kmh", "legs": [{"after_m", "maneuver", "modifier",
    "exit", "street", "text"}]} (route_demo.json)."""

    def __init__(self, route: dict):
        self.route = route
        self.legs = route["legs"]
        self.total = float(sum(leg["after_m"] for leg in self.legs))
        self.avg_mps = route.get("average_kmh", 40) / 3.6
        self.driven = 0.0

    @property
    def arrived(self) -> bool:
        return self.driven >= self.total

    def advance(self, metres: float):
        self.driven = min(self.total, max(0.0, self.driven + metres))

    def leg_index(self) -> int:
        at = 0.0
        for i, leg in enumerate(self.legs):
            at += leg["after_m"]
            if at > self.driven:
                return i
        return len(self.legs) - 1

    def guidance(self) -> dict:
        if self.arrived:
            return cl.guidance(self.route["source"], "arrive", distance_m=0, street=self.legs[-1]["street"],
                               remaining_m=0, remaining_s=0)
        i = self.leg_index()
        leg = self.legs[i]
        at = sum(lg["after_m"] for lg in self.legs[:i + 1])
        remaining = self.total - self.driven
        return cl.guidance(self.route["source"], leg["maneuver"], leg.get("modifier"), leg.get("exit"),
                           distance_m=shown_distance(at - self.driven), street=leg["street"],
                           text=leg.get("text"), remaining_m=shown_distance(remaining),
                           remaining_s=round(remaining / self.avg_mps / 60) * 60.0)


def play(route: dict, path: str, fallback_kmh: float):
    player = RoutePlayer(route)
    while True:
        phone = Phone(path, device=route.get("device", "Emulated phone"))
        try:
            hu = phone.connect(caps=("guidance", "weather", "position"))
            if not hu:
                raise OSError("no hello from the HU")
            wants = set(hu.get("caps") or [])
            if "weather" in wants:
                phone.send(demo_weather())
            if "position" in wants:
                phone.send(demo_position())
        except OSError as e:
            log(f"HU not reachable ({e}), retrying")
            phone.close()
            time.sleep(1)
            continue
        log(f"connected, playing '{route['name']}' ({player.total / 1000:.1f} km)")
        player.driven, last_sent, t = 0.0, None, time.monotonic()
        last_position = t
        try:
            while not phone.closed_by_hu.is_set():
                time.sleep(0.25)
                now = time.monotonic()
                kmh = vehicle_speed()
                player.advance((fallback_kmh if kmh is None else kmh) / 3.6 * (now - t))
                t = now
                if player.arrived:
                    phone.send(player.guidance())
                    time.sleep(5)
                    phone.send(cl.guidance_ended())
                    log("arrived, guidance ended; starting over in 5 s")
                    time.sleep(5)
                    player.driven, last_sent, t = 0.0, None, time.monotonic()
                    continue
                if "position" in wants and now - last_position >= 60:
                    phone.send(demo_position())
                    last_position = now
                msg = player.guidance()
                if msg != last_sent:
                    phone.send(msg)
                    last_sent = msg
            log("HU closed the link, reconnecting")
        except OSError as e:
            log(f"link error ({e}), reconnecting")
        phone.close()
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", default=str(DEFAULT_SOCKET),
                    help="hu-navd's companion link socket, or tcp:HOST:PORT (navd --tcp)")
    ap.add_argument("--route", default=str(HERE / "route_demo.json"), help="route to play")
    ap.add_argument("--speed-kmh", type=float, default=50, help="speed when hu-vehicled does not run")
    a = ap.parse_args()
    play(json.loads(Path(a.route).read_text()), a.socket, a.speed_kmh)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
