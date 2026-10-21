#!/usr/bin/env python3
"""TC_HU_040: how the car is, to the phone (companion link car_status, hu-navd). A phone that
wants it (caps car_status) gets one right after its hello: the vehicle values from the CAN
signals (fuel, range, odometer, battery, outside temperature, service, negative = overdue),
the trip since start, the active warnings as hu-warnd lists them, the HU's accent colour.
A phone that does not ask gets none. When the ignition goes off and the bus falls asleep it
gets a last one with final: true (when IgnitionState goes Off, while the values are still
fresh; only one per ignition cycle). navd's car_status() leaves out stale signals and all
vehicle values without the MCU link. The periodic one (nav.ini interval_s) is not waited for."""
import time

import dbus

from common import ADDRESS, Restbus, check, finish, nav_logic, phone, sys_props, wait_for

navd, _cfg = nav_logic()
import companion_link as cl  # noqa: E402  (nav_logic put hu/services on the path)


def statuses(p):
    return [m for m in p.received if m["type"] == cl.CAR_STATUS]


def wait_status(p, cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        hit = [m for m in statuses(p) if cond(m)]
        if hit:
            return hit[-1]
        time.sleep(0.05)
    return None


# --- the builder on its own
v = {"LinkUp": True, "StaleSignals": ["Range"], "FuelLevel": 40.0, "Range": 300.0, "OutsideTemp": -4.5}
s = navd.car_status(v, {"distance": 12.34, "time": 1500, "avg_speed": 29.6},
                    [{"severity": "warning", "text": "A"}] * 12 + [{"severity": "odd", "text": "B"}],
                    {"accent": "amber"}, 1000.4, final=True)
check(s["fuel_pct"] == 40.0 and "range_km" not in s and s["outside_c"] == -4.5 and s["time"] == 1000 and s["final"],
      f"car_status(): values rounded, a stale signal left out ({s})")
check(s["trip"] == {"km": 12.3, "minutes": 25, "avg_kmh": 30} and len(s["warnings"]) == cl.MAX_WARNINGS
      and s["accent"] == "amber", "trip in km / minutes / km/h, at most 10 warnings, the accent")
s = navd.car_status(dict(v, LinkUp=False), {}, [], {}, 5)
check(not any(k in s for k in navd.VEHICLE) and s["warnings"] == [], "no MCU link: no vehicle values")
cl.validate(s)

# --- live: values from the bus
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", FuelLevel=40, Range=300, BatteryVoltage=14.1, OutsideTemp=-4.5,
           ServiceDistance=-150, ServiceDays=20)
    ok, _, _ = wait_for(lambda h: h["Power"] == "on" and abs(h.get("Range", 0) - 300) < 1 and h.get("ServiceDistance") == -150,
                        timeout=8.0)
    check(ok, "the HU is on and has the values")

    quiet = phone(device="No status phone")
    quiet.connect(caps=("guidance",))
    time.sleep(1.5)
    check(not statuses(quiet), "a phone that does not ask for car_status gets none")
    quiet.close(bye=True)

    p = phone(device="Status phone")
    hu = p.connect(caps=("guidance", "car_status"))
    check("car_status" in (hu or {}).get("caps", []), f"the HU offers car_status in its hello ({(hu or {}).get('caps')})")
    m = wait_status(p, lambda m: not m["final"])
    check(m is not None and abs(m["time"] - time.time()) < 10, "one right after the hello")
    m = m or {}
    check(m.get("fuel_pct") == 40 and m.get("range_km") == 300 and abs(m.get("battery_v", 0) - 14.1) < 0.05
          and m.get("outside_c") == -4.5 and m.get("service_km") == -150 and m.get("service_days") == 20
          and m.get("odometer_km", -1) >= 0,
          f"the vehicle values, overdue service negative ({ {k: m.get(k) for k in navd.VEHICLE} })")
    active = [{"severity": str(w["severity"]), "text": str(w["text"])} for w in dbus.SessionBus().get_object(
        "de.r80.Warnings", "/de/r80/Warnings").Get("de.r80.Warnings1", "Active", dbus_interface="org.freedesktop.DBus.Properties")]
    check(m.get("warnings") == active[:cl.MAX_WARNINGS], f"the warnings as hu-warnd lists them ({len(active)})")
    check(isinstance(m.get("trip"), dict) and m.get("accent") == sys_props()["Settings"]["accent"],
          f"the trip and the HU's accent colour ({m.get('trip')}, {m.get('accent')})")

    rb.set(IgnitionState="Off")
    m = wait_status(p, lambda m: m["final"])
    check(m is not None and m.get("range_km") == 300 and m.get("fuel_pct") == 40,
          f"ignition off: a final car_status, with the values still fresh ({m})")
    rb.silence()
    ok, _, _ = wait_for(lambda h: h["Power"] == "off", timeout=10.0)
    time.sleep(0.5)
    check(ok and len([s for s in statuses(p) if s["final"]]) == 1, "the bus asleep, Power off: no second final one")
    p.close(bye=True)
    rb.wake()
finish()
