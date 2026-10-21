#!/usr/bin/env python3
"""TC_HU_039: weather and altitude from the phone (companion link, hu-navd). The HU asks for
them in its hello (caps weather, position); the phone emulator sends a weather message and
a position; navd publishes them as Weather and Position (days in order, negative
temperatures, the altitude, -1 for what was not sent). A bad weather message is dropped
and counted, the last good one stays; a newer one replaces it; after the link is gone the
weather is kept (the UI decides when it is too old). The phone's coordinates are not part
of the protocol: a position never carries them. Real internet weather is the app's part."""
import time

from common import check, finish, nav_props, phone, wait_nav

p = phone(device="Weather test phone")
hu = p.connect(caps=("guidance", "weather", "position"))
check(hu is not None and set(hu.get("caps") or []) >= {"weather", "position"},
      f"the HU asks for weather and position in its hello ({(hu or {}).get('caps')})")

import companion_link as cl  # noqa: E402  (phone() put hu/services on the path)

t0 = int(time.time())
days = [("2026-10-21", 3, 13.1, 5.8), ("2026-10-22", 61, 10.2, 4.9), ("2026-10-23", 0, 12.7, -1.5),
        ("2026-10-24", 71, 2.0, -3.2)]
p.send(cl.weather("open-meteo", t0 - 300, -2.4, 71, days))
ok, n, _ = wait_nav(lambda n: n["Weather"]["valid"] and n["Weather"]["time"] == t0 - 300)
w = n.get("Weather", {})
check(ok and w["source"] == "open-meteo" and abs(w["temp_c"] + 2.4) < 1e-6 and w["code"] == 71,
      f"Weather: source, time, current temperature (below zero) and code ({w})")
check([(d["date"], d["code"], round(d["max_c"], 1), round(d["min_c"], 1)) for d in w.get("days", [])] == days,
      "the days in order, today first, with code, max and min")

p.send(cl.position(t0, alt_m=412.3, accuracy_m=6))
ok, n, _ = wait_nav(lambda n: n["Position"]["valid"] and n["Position"]["time"] == t0)
pos = n.get("Position", {})
check(ok and abs(pos["alt_m"] - 412.3) < 1e-6 and pos["accuracy_m"] == 6 and pos["heading_deg"] == -1,
      f"Position: altitude and accuracy, no heading sent: -1 ({pos})")
check(set(pos) == {"valid", "time", "alt_m", "accuracy_m", "heading_deg"}, "no coordinates in Position")

bad_before = nav_props()["Phone"]["bad_lines"]
p.send_raw(b'{"type":"weather","source":"x","time":1,"now":{"temp_c":5,"code":1},"days":[{"date":"21.10.2026","code":1,"max_c":1,"min_c":0}]}\n')
p.send_raw(b'{"type":"position","alt_m":100}\n')
ok, n, _ = wait_nav(lambda n: n["Phone"]["bad_lines"] == bad_before + 2)
check(ok and n["Weather"]["time"] == t0 - 300 and n["Position"]["time"] == t0,
      f"a bad date and a position without time: dropped and counted, the last good ones stay "
      f"({n['Phone']['bad_lines'] - bad_before} bad)")

p.send(cl.weather("open-meteo", t0, 18.0, 0))
ok, n, _ = wait_nav(lambda n: n["Weather"]["time"] == t0)
check(ok and n["Weather"]["code"] == 0 and n["Weather"]["days"] == [], "a newer weather replaces it (no days sent: none)")

p.close(bye=True)
ok, n, _ = wait_nav(lambda n: not n["Phone"]["connected"])
check(ok and n["Weather"]["valid"] and n["Weather"]["time"] == t0 and n["Position"]["valid"],
      "the phone gone: weather and altitude are kept")
finish()
