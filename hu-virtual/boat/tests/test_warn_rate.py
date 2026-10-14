#!/usr/bin/env python3
"""TC_HU_015: a fast pressure drop is urgent even while the pressure is still fine (D10).
Oil and tyre pressure falling faster than drop_rate raise a critical warning before the
low-pressure warning; a slow drop raises nothing."""
import time

from common import ADDRESS, Restbus, check, finish, wait_for, wait_warnings, warn_rules

general, rules = warn_rules()
oil = rules["oil_pressure_dropping"]
tyre = rules["tyre_dropping.TyrePressureFL"]


def ramp(rb, name, start, rate, seconds, step=0.1):
    v = start
    for _ in range(int(seconds / step)):
        v -= rate * step
        rb.set(**{name: round(v, 3)})
        time.sleep(step)
    return v


with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", EngineSpeed=800, OilPressure=3.0, TyrePressureFL=2.3)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    time.sleep(oil["window"] + 0.5)

    end = ramp(rb, "OilPressure", 3.0, oil["raise_"] * 1.5, oil["window"] + 1.0)
    ok, act, _ = wait_warnings(lambda a: "oil_pressure_dropping" in a, timeout=2.0)
    check(ok, f"oil pressure falling {oil['raise_'] * 1.5:.2f} bar/s: {act.get('oil_pressure_dropping', {}).get('text')}")
    check(ok and act["oil_pressure_dropping"]["severity"] == "critical", "it is critical")
    check(end > rules["oil_pressure_low"]["raise_"] and "oil_pressure_low" not in act,
          f"while the pressure itself ({end:.2f} bar) is still above the low limit")
    rb.set(OilPressure=3.0)
    ok, _, dt = wait_warnings(lambda a: "oil_pressure_dropping" not in a, timeout=oil["hold"] + 5)
    check(ok and dt >= oil["hold"] - 3, f"cleared {dt:.1f} s after the drop stopped (held ~{oil['hold']:.0f} s)")

    time.sleep(oil["window"] + 0.5)
    ramp(rb, "OilPressure", 3.0, oil["raise_"] * 0.3, oil["window"] + 2.0)
    ok, _, _ = wait_warnings(lambda a: "oil_pressure_dropping" in a, timeout=1.0)
    check(not ok, f"slow drop ({oil['raise_'] * 0.3:.2f} bar/s): no warning")
    rb.set(OilPressure=3.0)

    end = ramp(rb, "TyrePressureFL", 2.3, tyre["raise_"] * 1.5, tyre["window"] + 2.0)
    ok, act, _ = wait_warnings(lambda a: "tyre_dropping.TyrePressureFL" in a, timeout=3.0)
    check(ok, f"tyre front left falling: {act.get('tyre_dropping.TyrePressureFL', {}).get('text')}")
    check(ok and act["tyre_dropping.TyrePressureFL"]["severity"] == "critical", "it is critical")
    rb.set(TyrePressureFL=2.3)
finish()
