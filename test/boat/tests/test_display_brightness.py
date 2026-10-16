#!/usr/bin/env python3
"""TC_HU_027: display brightness (hu-sysd, D12) through the real chain: LightState on the
bus -> MCU day/night and dim level -> vehicled -> sysd DisplayBrightness. By day it is the
user's brightness; at night the car's dimmer is the base and the user's setting shifts it;
"dim at night" off keeps the user's brightness; never below the floor. Expected values from
sysd's own display_brightness() and system.ini."""
import time

import dbus

from common import ADDRESS, Restbus, check, finish, mcu, sys_logic, sys_props, system, wait_for

sysd, cfg = sys_logic()
s = system()
floor = cfg["brightness"]["floor"]


def display(want, t=3.0):
    t0 = time.monotonic()
    got = None
    while time.monotonic() - t0 < t:
        got = round(sys_props()["DisplayBrightness"], 3)
        if abs(got - want) < 0.002:
            return True, got
        time.sleep(0.05)
    return False, got


def expect(user, dimming, night, level):
    return sysd.display_brightness(cfg, {"brightness": user, "night_dimming": dimming}, night, level)


s.ResetAll()
default = cfg["settings"]["brightness"]["default"]
with Restbus(address=ADDRESS) as rb:
    mcu({"cmd": "dim", "level": "auto"})
    rb.set(IgnitionState="IgnitionOn", LightState="Off")
    wait_for(lambda p: not p["Night"] and p["DimLevel"] == 100, timeout=3.0)
    ok, got = display(expect(default, True, False, 100))
    check(ok, f"day: the user's brightness ({got})")
    s.Set("brightness", dbus.Double(0.5))
    ok, got = display(expect(0.5, True, False, 100))
    check(ok, f"day, brightness 0.5 -> {got}")

    s.Set("brightness", dbus.Double(default))
    rb.set(LightState="LowBeam")
    ok, p, _ = wait_for(lambda p: p["Night"], timeout=3.0)
    level = p.get("DimLevel", 0)
    ok, got = display(expect(default, True, True, level))
    check(ok, f"night, dimmer {level}, setting at its default: follows the dimmer ({got})")

    for lvl in (100, 0):
        mcu({"cmd": "dim", "level": lvl})
        wait_for(lambda p: p["DimLevel"] == lvl, timeout=3.0)
        ok, got = display(expect(default, True, True, lvl))
        check(ok, f"night, dimmer {lvl} -> {got}")

    mcu({"cmd": "dim", "level": 50})
    wait_for(lambda p: p["DimLevel"] == 50, timeout=3.0)
    base = expect(default, True, True, 50)
    s.Set("brightness", dbus.Double(default / 2))
    ok, got = display(expect(default / 2, True, True, 50))
    check(ok and abs(got - max(floor, base / 2)) < 0.002, f"night: half the setting -> half the dimmer's value ({base} -> {got})")

    s.Set("night_dimming", dbus.Boolean(False))
    ok, got = display(expect(default / 2, False, True, 50))
    check(ok, f"dim at night off: the user's brightness at night ({got})")

    s.Set("night_dimming", dbus.Boolean(True))
    s.Set("brightness", dbus.Double(cfg["settings"]["brightness"]["min"]))
    mcu({"cmd": "dim", "level": 0})
    ok, got = display(floor)
    check(ok, f"darkest setting, dimmer at 0: never below the floor ({got})")

    mcu({"cmd": "dim", "level": "auto"})
    rb.set(LightState="Off")
    s.ResetAll()
    ok, got = display(expect(default, True, False, 100))
    check(ok, f"lights off again: back to the user's brightness ({got})")
finish()
