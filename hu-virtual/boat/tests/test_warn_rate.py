#!/usr/bin/env python3
"""TC_HU_015: a fast tyre pressure drop is a warning even while the pressure is still fine
(D10). Falling faster than drop_rate raises it before the low-pressure information; a slow
drop raises nothing. Oil pressure has no drop-rate rule (it falls fast on every lift-off)."""
import time

from common import ADDRESS, Restbus, check, finish, wait_for, wait_warnings, warn_rules

general, rules = warn_rules()
tyre = rules["tyre_dropping.TyrePressureFL"]
low = rules["tyre_low.TyrePressureFL"]
check(not any(r.startswith("oil_pressure_dropping") for r in rules), "no drop-rate rule for oil pressure")


def ramp(rb, name, start, rate, seconds, step=0.1):
    v = start
    for _ in range(int(seconds / step)):
        v -= rate * step
        rb.set(**{name: round(v, 3)})
        time.sleep(step)
    return v


with Restbus(address=ADDRESS) as rb:
    start = 2.5                                   # far enough above the low limit for the ramp
    rb.set(IgnitionState="IgnitionOn", EngineSpeed=800, TyrePressureFL=start)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    time.sleep(tyre["window"] + 1.0)

    end = ramp(rb, "TyrePressureFL", start, tyre["raise_"] * 1.5, tyre["window"] + 1.0)
    ok, act, _ = wait_warnings(lambda a: "tyre_dropping.TyrePressureFL" in a, timeout=3.0)
    check(ok, f"front left falling {tyre['raise_'] * 1.5:.2f} bar/s: {act.get('tyre_dropping.TyrePressureFL', {}).get('text')}")
    check(ok and act["tyre_dropping.TyrePressureFL"]["severity"] == "warning", "severity warning (act within seconds)")
    check(end > low["raise_"] and "tyre_low.TyrePressureFL" not in act,
          f"while the pressure itself ({end:.2f} bar) is still above the low limit")
    rb.set(TyrePressureFL=start)
    ok, _, dt = wait_warnings(lambda a: "tyre_dropping.TyrePressureFL" not in a, timeout=tyre["hold"] + 5)
    check(ok and dt >= tyre["hold"] - 3, f"cleared {dt:.1f} s after the drop stopped (held ~{tyre['hold']:.0f} s)")

    time.sleep(tyre["window"] + 1.0)
    ramp(rb, "TyrePressureFL", start, tyre["raise_"] * 0.3, tyre["window"] + 2.0)
    ok, _, _ = wait_warnings(lambda a: "tyre_dropping.TyrePressureFL" in a, timeout=1.5)
    check(not ok, f"slow drop ({tyre['raise_'] * 0.3:.2f} bar/s): no warning")
    rb.set(TyrePressureFL=2.3)
finish()
