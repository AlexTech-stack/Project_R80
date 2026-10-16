#!/usr/bin/env python3
"""TC_HU_016: a missing CAN message becomes a 'No data' warning and clears when it is back;
with the HU off there are no warnings at all (D10)."""
from common import ADDRESS, Restbus, check, finish, wait_for, wait_warnings, warn_rules

general, rules = warn_rules()
rule = rules["sensor_missing.CoolantTemp"]
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", FuelLevel=8)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    ok, _, _ = wait_warnings(lambda a: "sensor_missing.CoolantTemp" not in a, timeout=5.0)
    check(ok, "CoolantTemp arrives: no 'No data' warning")

    rb.stop_message("R80_CoolantTemp")
    ok, act, dt = wait_warnings(lambda a: "sensor_missing.CoolantTemp" in a, timeout=rule["for_s"] + 4)
    check(ok, f"CoolantTemp stopped: '{act.get('sensor_missing.CoolantTemp', {}).get('text')}' after {dt:.1f} s")
    rb.start_message("R80_CoolantTemp")
    ok, _, _ = wait_warnings(lambda a: "sensor_missing.CoolantTemp" not in a, timeout=4.0)
    check(ok, "CoolantTemp back: cleared")

    ok, act, _ = wait_warnings(lambda a: "fuel_low" in a, timeout=rules["fuel_low"]["for_s"] + 4)
    check(ok, "a warning is active (fuel low) ...")
    rb.set(IgnitionState="Off")
    ok, _, _ = wait_for(lambda p: p["Power"] not in general["active_power"], timeout=5.0)
    ok, act, _ = wait_warnings(lambda a: not a, timeout=3.0)
    check(ok, f"... and the HU switched off: no warnings ({list(act)})")
    rb.set(IgnitionState="IgnitionOn", FuelLevel=50)
finish()
