#!/usr/bin/env python3
"""R80 restbus for BoAt: simulates the rest of the car on the Infotainment CAN.

Reads the R80 test DBC (hu-can/r80_test.dbc) as a BoAt PDU database, which it
builds on first use with BoAt's tools/dbc2boatjson.py into hu-virtual/build/
(git-ignored, rebuilt when the DBC changes), and sends every message at its
CycleTime through the BoAt gateway (FrameService.SendFrame), so the traffic can
be recorded, traced and replayed with the usual BoAt tools.

Two ways to use it:

  As a node (drive cycle: idle, accelerate, cruise, brake, 60 s loop)
      python3 boat/restbus.py --address localhost:50061 --drive

  From a test script (manual values)
      rb = Restbus(address="localhost:50061")
      rb.start()
      rb.set(VehicleSpeed=120, Gear="D")
      rb.stop_message("R80_VehicleSpeed")     # simulate a missing sender
      rb.silence()                            # whole bus quiet -> MCU sees bus sleep
      rb.close()

Signal values are physical (km/h, °C, enum names), packed client-side with the
PDU DB's StartPos/Length/Factor/Offset.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOAT_ROOT = Path(os.environ.get("BOAT_ROOT", Path.home() / "BoAt"))
sys.path.insert(0, str(BOAT_ROOT / "boat-platform" / "sdk" / "python"))

from boat.frame_node import FrameNode  # noqa: E402

DBC = HERE.parents[1] / "hu-can" / "r80_test.dbc"
DEFAULT_DB = HERE.parent / "build" / "r80_test_pdu_db.json"
DEFAULT_BUS_MAP = {"Infotainment": "vcan_info", "Motor": "vcan_motor", "Comfort": "vcan_comfort"}
CAN_EFF_FLAG = 0x80000000

# Values while parked with the ignition on. The drive model overwrites some.
DEFAULTS = {
    "VehicleSpeed": 0, "EngineSpeed": 800, "BoostPressure": -0.6, "Gear": "P",
    "IgnitionState": "IgnitionOn", "LightState": "Off",
    "CoolantTemp": 88, "OilTemp": 92, "OutsideTemp": 12, "OilPressure": 1.8,
    "BatteryVoltage": 14.2, "FuelLevel": 62, "Range": 471, "AvgConsumption": 11.8,
    "Odometer": 187432.4, "TripDistance": 43.7, "ServiceDistance": 6400,
    "TyrePressureFL": 2.3, "TyrePressureFR": 2.3, "TyrePressureRL": 2.2, "TyrePressureRR": 2.2,
    "ServiceDays": 112,
}


def ensure_pdu_db(db_path=DEFAULT_DB, dbc=DBC) -> Path:
    """Build the BoAt PDU database from the DBC if it is missing or older than the DBC."""
    import subprocess
    db_path = Path(db_path)
    if db_path.exists() and db_path.stat().st_mtime >= Path(dbc).stat().st_mtime:
        return db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(BOAT_ROOT / "tools" / "dbc2boatjson.py"), "--bus", "Infotainment",
                    "--bus-type", "CAN", str(BOAT_ROOT / "boat-platform" / "config" / "pdu_db.schema.json"),
                    str(dbc), str(db_path)], check=True, stdout=subprocess.DEVNULL)
    return db_path


class PduMessage:
    def __init__(self, m: dict, iface: str):
        self.name = m["MessageName"]
        self.iface = iface
        self.can_id = m["Identifier"]          # already carries 0x80000000 for extended IDs
        if m.get("FrameType") == 1:
            self.can_id |= CAN_EFF_FLAG
        self.length = m["Length"]
        self.cycle = m.get("CycleTime", 0) / 1000
        self.signals = m["signals"]
        self.enabled = True
        self.next_due = 0.0

    def pack(self, values: dict) -> bytes:
        buf = bytearray(self.length)
        for s in self.signals:
            v = values.get(s["SignalName"], s.get("InitValue", 0))
            if isinstance(v, str):
                enum = {name: int(k) for k, name in (s.get("EnumValues") or {}).items()}
                raw = enum[v]
            else:
                raw = round((v - s.get("Offset", 0.0)) / (s.get("Factor") or 1.0))
            raw &= (1 << s["Length"]) - 1
            for i in range(s["Length"]):
                if s["ByteOrder"] == 0:
                    pos = s["StartPos"] + i
                else:  # Motorola, sawtooth bit numbering
                    pos = s["StartPos"]
                    for _ in range(s["Length"] - 1 - i):
                        pos = pos - 1 if pos % 8 else pos + 15
                if raw >> i & 1:
                    buf[pos // 8] |= 1 << (pos % 8)
        return bytes(buf)


class Restbus:
    def __init__(self, db_path=DEFAULT_DB, bus_map=None, address=None):
        bus_map = {**DEFAULT_BUS_MAP, **(bus_map or {})}
        if Path(db_path) == DEFAULT_DB:
            ensure_pdu_db()
        db = json.loads(Path(db_path).read_text())
        self.messages = [PduMessage(m, bus_map.get(m["Bus"], m["Bus"])) for m in db["messages"]
                         if m.get("BusType") in ("CAN", None) and m.get("CycleTime", 0) > 0]
        self.by_name = {m.name: m for m in self.messages}
        self.values = dict(DEFAULTS)
        self.node = FrameNode(address)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.paused = False   # whole bus quiet, per-message on/off kept
        self.sent = 0
        self.errors = 0

    # ---- control ---------------------------------------------------------
    def set(self, **values):
        with self._lock:
            self.values.update(values)

    def stop_message(self, name):
        self.by_name[name].enabled = False

    def start_message(self, name):
        self.by_name[name].enabled = True

    def silence(self):
        for m in self.messages:
            m.enabled = False

    def wake(self):
        for m in self.messages:
            m.enabled = True

    # ---- scheduling --------------------------------------------------------
    def start(self, model=None):
        """Send in a background thread. `model(t)` may return values to apply each 10 ms."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(model,), daemon=True)
        self._thread.start()
        return self

    def _run(self, model):
        t0 = time.monotonic()
        for m in self.messages:  # spread first sends a little so the bus is not bursty
            m.next_due = t0 + (hash(m.name) % 10) / 1000
        while not self._stop.is_set():
            now = time.monotonic()
            if model:
                self.set(**model(now - t0))
            with self._lock:
                vals = dict(self.values)
            for m in self.messages:
                if now >= m.next_due:
                    m.next_due += m.cycle
                    if m.next_due < now:          # fell behind (e.g. gateway restart): resync
                        m.next_due = now + m.cycle
                    if m.enabled and not self.paused:
                        try:
                            self.node.send_can(m.iface, m.can_id, m.pack(vals))
                            self.sent += 1
                        except Exception:
                            self.errors += 1
            nxt = min(m.next_due for m in self.messages)
            self._stop.wait(max(0.0, min(nxt - time.monotonic(), 0.01)))

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


class DriveCycle:
    """Idle, accelerate, cruise, brake, repeat (60 s), like hu-can/tools/r80_can_sim.py."""

    def __init__(self):
        self.odo, self.trip, self.fuel, self.last = DEFAULTS["Odometer"], DEFAULTS["TripDistance"], 62.0, 0.0

    def __call__(self, t):
        dt, self.last = t - self.last, t
        ph = t % 60
        if ph < 5:
            v = 0.0
        elif ph < 20:
            v = (ph - 5) / 15 * 100
        elif ph < 45:
            v = 100 + 5 * math.sin(ph)
        else:
            v = max(0.0, 100 - (ph - 45) / 12 * 100)
        km = v * dt / 3600
        self.odo += km
        self.trip += km
        self.fuel = max(0.0, self.fuel - km * 0.02)
        accel = 5 <= ph < 20
        rpm = 800 if v < 1 else min(6500, 1200 + (v % 22) * 120 + (1500 if accel else 0))
        return {
            "VehicleSpeed": v, "EngineSpeed": rpm, "Gear": "D" if v >= 1 else ("P" if ph < 2 else "N"),
            "BoostPressure": 0.9 if accel else (0.2 if v > 1 else -0.6),
            "OilPressure": min(1.2 + rpm / 1500, 12.7),
            "Odometer": self.odo, "TripDistance": self.trip, "FuelLevel": self.fuel,
            "Range": round(self.fuel / 100 * 760),
        }


def build_parser():
    ap = argparse.ArgumentParser(description="R80 restbus node (BoAt)")
    ap.add_argument("--address", default=None, help="Gateway address (default: BOAT_HOST, then localhost:50051)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="BoAt PDU database JSON")
    ap.add_argument("--iface", default="vcan_info", help="interface for the DB's Infotainment bus")
    ap.add_argument("--drive", action="store_true", help="run the 60 s drive cycle (default: parked)")
    ap.add_argument("--lights", default="Off", choices=["Off", "Parking", "LowBeam", "HighBeam"])
    ap.add_argument("--ignition", default="IgnitionOn",
                    choices=["Off", "KeyInserted", "Accessory", "IgnitionOn", "Cranking"])
    return ap


def main():
    a = build_parser().parse_args()
    rb = Restbus(a.db, {"Infotainment": a.iface}, a.address)
    rb.set(LightState=a.lights, IgnitionState=a.ignition)
    rb.start(DriveCycle() if a.drive else None)
    print(f"[restbus] {len(rb.messages)} messages on {a.iface}" + (" (drive cycle)" if a.drive else ""), flush=True)
    try:
        while True:
            time.sleep(5)
            print(f"[restbus] sent {rb.sent} frames, {rb.errors} errors", flush=True)
    except KeyboardInterrupt:
        rb.close()


if __name__ == "__main__":
    main()
