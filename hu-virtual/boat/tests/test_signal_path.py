#!/usr/bin/env python3
"""TC_HU_001: restbus values arrive decoded on the Linux side (CAN -> MCU -> UART -> D-Bus).

Covers unsigned, signed, offset, enum, 32-bit and the one extended (29-bit) ID.
"""
from common import ADDRESS, Restbus, check, finish, wait_for

CASES = [
    {"VehicleSpeed": 123.45, "Gear": "R", "OutsideTemp": -7.5, "BoostPressure": -0.25,
     "Odometer": 200001.3, "ServiceDays": 42, "ServiceDistance": -150},
    {"VehicleSpeed": 0.0, "Gear": "D", "OutsideTemp": 31.0, "BoostPressure": 1.1,
     "Odometer": 187432.4, "ServiceDays": -3, "ServiceDistance": 6400},
]
TOL = {"VehicleSpeed": 0.01, "OutsideTemp": 0.5, "BoostPressure": 0.001, "Odometer": 0.1}

with Restbus(address=ADDRESS) as rb:
    for i, case in enumerate(CASES, 1):
        rb.set(**case)

        def matches(p, case=case):
            for k, want in case.items():
                got = p.get(k)
                if isinstance(want, str):
                    if got != want:
                        return False
                elif got is None or abs(got - want) > TOL.get(k, 0.5):
                    return False
            return True

        ok, props, dt = wait_for(matches, timeout=3.0)
        check(ok, f"case {i}: all values seen on D-Bus ({dt * 1000:.0f} ms)")
        if not ok:
            for k, want in case.items():
                print(f"     {k}: want {want!r}, got {props.get(k)!r}")
        check(props.get("LinkUp") is True, f"case {i}: MCU link up")

finish()
