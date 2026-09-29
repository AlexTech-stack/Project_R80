#!/usr/bin/env python3
"""TC_HU_004: day/night dimming from LightState, and the MCU's manual override."""
from common import ADDRESS, Restbus, check, finish, mcu, wait_for

with Restbus(address=ADDRESS) as rb:
    mcu({"cmd": "dim", "level": "auto"})
    rb.set(LightState="Off")
    ok, _, _ = wait_for(lambda p: not p["Night"] and p["DimLevel"] == 100, timeout=3.0)
    check(ok, "lights off -> day, level 100")

    rb.set(LightState="LowBeam")
    ok, p, _ = wait_for(lambda p: p["Night"] and p["DimLevel"] == 40, timeout=3.0)
    check(ok, f"low beam -> night, level 40 (got {p.get('Night')}, {p.get('DimLevel')})")

    rb.set(LightState="Parking")
    ok, _, _ = wait_for(lambda p: not p["Night"], timeout=3.0)
    check(ok, "parking lights -> day")

    mcu({"cmd": "dim", "level": 25})
    ok, _, _ = wait_for(lambda p: p["DimLevel"] == 25, timeout=3.0)
    check(ok, "MCU override -> level 25")
    mcu({"cmd": "dim", "level": "auto"})
    ok, _, _ = wait_for(lambda p: p["DimLevel"] == 100, timeout=3.0)
    check(ok, "override released -> back to 100")

finish()
