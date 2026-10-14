#!/usr/bin/env python3
"""TC_HU_018: the trip computer (D10) through the real chain. Distance from odometer steps
in both trips, maximum speed, reset of "since start" only, an odometer jump is not driving,
no driving time while the HU is off, consumption is the car's own value."""
import time

from common import ADDRESS, Restbus, check, finish, trip, trip_logic, trip_props, wait_for, wait_trip

tripd, cfg = trip_logic()
t = trip()
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", Odometer=100000.0, VehicleSpeed=0, AvgConsumption=7.4)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    time.sleep(2.0)                                     # tripd has seen this odometer value
    t.Reset("since_start")
    t.Reset("long_term")
    ok, p, _ = wait_trip(lambda p: p["SinceStart"]["distance"] == 0 and p["LongTerm"]["distance"] == 0)
    check(ok, "both trips reset")

    t0 = time.monotonic()
    for i, speed in enumerate((72, 95, 60), 1):
        rb.set(VehicleSpeed=speed, Odometer=round(100000.0 + 0.1 * i, 1))
        time.sleep(1.5)
    ok, p, _ = wait_trip(lambda p: abs(p["SinceStart"]["distance"] - 0.3) < 0.05 and abs(p["LongTerm"]["distance"] - 0.3) < 0.05)
    check(ok, f"0.3 km driven: since start {p['SinceStart']['distance']} km, long-term {p['LongTerm']['distance']} km")
    check(p["SinceStart"]["max_speed"] == 95, f"max speed 95 km/h (got {p['SinceStart']['max_speed']})")
    driven = time.monotonic() - t0
    check(driven - 2.5 <= p["SinceStart"]["time"] <= driven + 2.5, f"driving time {p['SinceStart']['time']} s (about {driven:.0f} s)")
    check(abs(p["SinceStart"]["avg_consumption"] - 7.4) < 0.05, f"consumption is the car's value (7.4, got {p['SinceStart']['avg_consumption']})")

    t.Reset("since_start")
    ok, p, _ = wait_trip(lambda p: p["SinceStart"]["distance"] == 0)
    check(ok and abs(p["LongTerm"]["distance"] - 0.3) < 0.05, f"reset since start only (long-term still {p['LongTerm']['distance']} km)")

    rb.set(Odometer=100000.3 + cfg["max_jump_km"] + 50)
    time.sleep(2.5)
    check(abs(trip_props()["LongTerm"]["distance"] - 0.3) < 0.05, "an odometer jump is not driving")

    rb.set(IgnitionState="Off")
    ok, _, _ = wait_for(lambda p: p["Power"] not in cfg["count_time_in"], timeout=5.0)
    time.sleep(1.5)   # tripd counts in 1 s ticks and gets the power change a moment after us: let that tick land
    before = trip_props()["LongTerm"]["time"]
    time.sleep(3.0)
    check(trip_props()["LongTerm"]["time"] == before, "no driving time while the HU is off")
    rb.set(IgnitionState="IgnitionOn")
finish()
