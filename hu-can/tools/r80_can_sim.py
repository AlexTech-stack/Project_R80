#!/usr/bin/env python3
"""R80 CAN simulator: plays a simple drive cycle using r80_test.dbc.

Each message is sent at its own cycle time from the DBC. Two outputs:

  # write a candump-format log (no hardware needed)
  python3 r80_can_sim.py --log drive.log --seconds 60

  # send live on a CAN interface, e.g. a virtual bus or the Pi's CAN HAT
  sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
  python3 r80_can_sim.py --channel vcan0          # watch with: candump -a vcan0

Needs: pip install cantools python-can
"""
import argparse
import math
import time
from pathlib import Path

import can
import cantools

DBC = Path(__file__).resolve().parent.parent / "r80_test.dbc"


class Car:
    """Very small drive model: idle, accelerate, cruise, brake, repeat (60 s loop)."""

    def __init__(self):
        self.odometer = 187432.4
        self.trip = 43.7
        self.fuel = 62.0          # %
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        phase = self.t % 60
        if phase < 5:
            speed = 0.0
        elif phase < 20:
            speed = (phase - 5) / 15 * 100
        elif phase < 45:
            speed = 100 + 5 * math.sin(phase)
        else:
            speed = max(0.0, 100 - (phase - 45) / 12 * 100)
        self.speed = speed
        km = speed * dt / 3600
        self.odometer += km
        self.trip += km
        self.fuel = max(0.0, self.fuel - km * 0.12 / 55 * 100 / 10)
        accel = 5 <= phase < 20
        self.gear = "N" if speed < 1 else str(min(6, 1 + int(speed // 22)))
        self.rpm = 800 if speed < 1 else min(6500, 1200 + (speed % 22) * 120 + (3000 if accel else 0) * 0.5)
        self.boost = 0.9 if accel else (0.2 if speed > 1 else -0.6)
        self.oil_pressure = 1.2 + self.rpm / 1500

    def values(self):
        return {
            "VehicleSpeed": self.speed,
            "EngineSpeed": self.rpm,
            "BoostPressure": self.boost,
            "Gear": self.gear,
            "IgnitionState": "IgnitionOn",
            "LightState": "LowBeam",
            "CoolantTemp": 88,
            "OilTemp": 92,
            "OutsideTemp": 12,
            "OilPressure": min(self.oil_pressure, 12.7),
            "BatteryVoltage": 14.2,
            "FuelLevel": self.fuel,
            "Range": round(self.fuel / 100 * 55 / 7.8 * 100),
            "AvgConsumption": 7.8,
            "Odometer": self.odometer,
            "TripDistance": self.trip,
            "ServiceDistance": 6400,
            "TyrePressureFL": 2.3, "TyrePressureFR": 2.3,
            "TyrePressureRL": 2.2, "TyrePressureRR": 2.2,
            "ServiceDays": 112,
        }


def frames(db, seconds, tick=0.01):
    """Yield (timestamp, can.Message) in time order for `seconds` of driving."""
    car = Car()
    due = {m.name: 0.0 for m in db.messages}
    t = 0.0
    while seconds is None or t < seconds:
        car.step(tick)
        vals = car.values()
        for m in db.messages:
            if t + 1e-9 >= due[m.name]:
                sig = m.signals[0]
                data = m.encode({sig.name: vals[sig.name]})
                yield t, can.Message(arbitration_id=m.frame_id, is_extended_id=m.is_extended_frame,
                                     data=data, timestamp=t)
                due[m.name] += m.cycle_time / 1000
        t += tick


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dbc", default=str(DBC))
    ap.add_argument("--log", help="write a candump log file instead of sending")
    ap.add_argument("--seconds", type=float, help="length (default: 60 s for --log, endless live)")
    ap.add_argument("--channel", default="vcan0", help="SocketCAN channel for live mode")
    ap.add_argument("--interface", default="socketcan", help="python-can interface for live mode")
    a = ap.parse_args()
    db = cantools.database.load_file(a.dbc)

    if a.log:
        n = 0
        with open(a.log, "w") as f:
            for t, msg in frames(db, a.seconds or 60):
                ident = f"{msg.arbitration_id:08X}" if msg.is_extended_id else f"{msg.arbitration_id:03X}"
                f.write(f"({1_790_000_000 + t:.6f}) vcan0 {ident}#{msg.data.hex().upper()}\n")
                n += 1
        print(f"wrote {n} frames to {a.log}")
        return

    with can.Bus(interface=a.interface, channel=a.channel) as bus:
        start = time.monotonic()
        for t, msg in frames(db, a.seconds):
            delay = start + t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            bus.send(msg)


if __name__ == "__main__":
    main()
