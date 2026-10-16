#!/usr/bin/env python3
"""TC_HU_019: the trip computer remembers its trips (state file) and starts "since start"
over when the ignition was off longer than auto_reset_h, also when the HU lost power while
driving. Uses tripd's own Trips logic with a simulated clock (nobody waits 2 h in a test);
average speed needs min_time_for_average_s of driving."""
import json
import time

from common import TRIP_STATE, check, finish, trip_logic, trip_props

tripd, cfg = trip_logic()
saved, t0 = None, time.monotonic()
while time.monotonic() - t0 < 8.0:
    try:
        saved = json.loads(TRIP_STATE.read_text())
        break
    except (OSError, ValueError):
        time.sleep(0.2)
check(isinstance(saved, dict) and "since_start" in saved and "long_term" in saved, f"state file written ({TRIP_STATE})")
live = trip_props()["LongTerm"]["distance"]
check(saved and abs(saved["long_term"]["distance"] - live) < 0.2, f"it holds the trips (long-term {saved and saved['long_term']['distance']} km, live {live} km)")

limit = cfg["auto_reset_h"] * 3600
t = tripd.Trips(cfg)
t.on_power(1000.0, "on"); t.on_odometer(100.0); t.tick(300); t.on_odometer(105.0)
v = t.values("since_start")
check(abs(v["avg_speed"] - 60.0) < 0.1, f"5 km in 300 s: average {v['avg_speed']} km/h")
t.on_power(2000.0, "off")
check(not tripd.Trips(cfg, t.state(2000.0)).on_power(2000.0 + limit - 60, "on"), f"back on after {limit - 60:.0f} s: since start kept")
check(tripd.Trips(cfg, t.state(2000.0)).on_power(2000.0 + limit + 60, "on"), f"back on after {limit + 60:.0f} s: since start starts over")
r = tripd.Trips(cfg, t.state(2000.0)); r.on_power(2000.0 + limit + 60, "on")
check(r.values("long_term")["distance"] == 5.0, "long-term kept")

u = tripd.Trips(cfg); u.on_power(1000.0, "on"); u.on_odometer(100.0); u.on_odometer(101.0)
check(tripd.Trips(cfg, u.state(1500.0)).on_power(1500.0 + limit + 60, "on"),
      "HU lost power while driving: the last save counts as switch-off, starts over after the limit")
check(tripd.Trips(cfg).values("since_start")["avg_speed"] == 0, "no average before min_time_for_average_s")
finish()
