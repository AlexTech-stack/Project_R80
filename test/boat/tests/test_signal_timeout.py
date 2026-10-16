#!/usr/bin/env python3
"""TC_HU_002: a missing message is flagged stale, and recovers when it comes back.

R80_VehicleSpeed has a 20 ms cycle, so hu-vehicled's timeout is max(3 x 20 ms, 500 ms).
"""
import time

from common import ADDRESS, Restbus, check, finish, wait_for

with Restbus(address=ADDRESS) as rb:
    ok, _, _ = wait_for(lambda p: "VehicleSpeed" not in p["StaleSignals"], timeout=3.0)
    check(ok, "VehicleSpeed fresh while the restbus sends it")

    rb.stop_message("R80_VehicleSpeed")
    t0 = time.monotonic()
    ok, p, dt = wait_for(lambda p: "VehicleSpeed" in p["StaleSignals"], timeout=3.0)
    check(ok, f"VehicleSpeed flagged stale {dt:.2f} s after it stopped")
    check(ok and dt < 2.0, "stale detection within 2 s (timeout 0.5 s + 1 s check period)")
    check("EngineSpeed" not in p["StaleSignals"], "other signals stay fresh")

    rb.start_message("R80_VehicleSpeed")
    ok, _, dt = wait_for(lambda p: "VehicleSpeed" not in p["StaleSignals"], timeout=3.0)
    check(ok, f"VehicleSpeed fresh again after {dt:.2f} s")

finish()
