#!/usr/bin/env python3
"""TC_HU_014: a warning is raised after its debounce time, holds through the hysteresis
band, clears beyond it, and can be acknowledged; a rule tied to the running engine stays
quiet with the engine off (D10, thresholds from hu/warnings.ini)."""
import time

from common import ADDRESS, Restbus, active_warnings, check, finish, wait_for, wait_warnings, warn_rules, warnings

general, rules = warn_rules()
fuel, oil = rules["fuel_low"], rules["oil_pressure_low"]
w = warnings()
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", FuelLevel=50, EngineSpeed=800, OilPressure=3.0)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    ok, act, _ = wait_warnings(lambda a: "fuel_low" not in a, timeout=5.0)
    check(ok, "fuel 50 %: no fuel warning")

    rb.set(FuelLevel=fuel["raise_"] - 2)
    t0 = time.monotonic()
    time.sleep(max(0.0, fuel["for_s"] - 1.5))
    check("fuel_low" not in active_warnings(), f"fuel {fuel['raise_'] - 2} %: not raised before for_s ({fuel['for_s']} s)")
    ok, act, _ = wait_warnings(lambda a: "fuel_low" in a, timeout=5.0)
    dt = time.monotonic() - t0
    check(ok, f"fuel low raised after {dt:.1f} s: {act.get('fuel_low', {}).get('text')}")
    check(ok and act["fuel_low"]["severity"] == fuel["severity"], f"severity {fuel['severity']}")

    w.Acknowledge("fuel_low")
    ok, act, _ = wait_warnings(lambda a: a.get("fuel_low", {}).get("acknowledged"))
    check(ok, "Acknowledge -> acknowledged, still listed")

    rb.set(FuelLevel=(fuel["raise_"] + fuel["clear"]) / 2)
    time.sleep(3.0)
    check("fuel_low" in active_warnings(), "fuel between the thresholds: still active (hysteresis)")
    rb.set(FuelLevel=fuel["clear"] + 3)
    ok, _, _ = wait_warnings(lambda a: "fuel_low" not in a, timeout=4.0)
    check(ok, f"fuel {fuel['clear'] + 3} %: cleared")

    rb.set(EngineSpeed=0, OilPressure=oil["raise_"] - 0.3)
    time.sleep(oil["for_s"] + 1.5)
    check("oil_pressure_low" not in active_warnings(), "oil pressure low with the engine off: no warning")
    rb.set(EngineSpeed=800)
    ok, act, _ = wait_warnings(lambda a: "oil_pressure_low" in a, timeout=oil["for_s"] + 3)
    check(ok, f"engine running: {act.get('oil_pressure_low', {}).get('text')} ({act.get('oil_pressure_low', {}).get('severity')})")
    rb.set(OilPressure=3.0)
    ok, _, _ = wait_warnings(lambda a: "oil_pressure_low" not in a, timeout=4.0)
    check(ok, "oil pressure back: cleared")
finish()
