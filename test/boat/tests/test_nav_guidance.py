#!/usr/bin/env python3
"""TC_HU_021: navigation guidance from the phone reaches D-Bus (hu-navd, D11).
An emulated phone says hello and sends guidance over the companion link socket;
de.r80.Nav shows it, computes the arrival time with the HU's clock, keeps the link
through bad and unknown lines, ends the guidance, and refuses a wrong protocol
version and a connection without hello. Timing comes from navd's own nav.ini."""
import time

from common import check, finish, nav_logic, phone, wait_nav

navd, cfg = nav_logic()
cl = navd.cl

p = phone("Test phone A")
hu = p.connect()
check(hu is not None and hu["app"] == "r80-hu" and hu["proto"] == cl.PROTO_VERSION,
      f"the HU answers hello ({hu and hu['app']} {hu and hu['version']}, proto {hu and hu['proto']})")
check(hu is not None and hu["heartbeat_s"] == cfg["heartbeat_s"], f"and asks for a heartbeat every {cfg['heartbeat_s']} s (nav.ini)")
ok, props, _ = wait_nav(lambda q: q["Phone"]["connected"])
check(ok and props["Phone"]["device"] == "Test phone A" and props["Phone"]["app"].startswith("r80-companion"),
      f"Phone: connected, device '{props.get('Phone', {}).get('device')}', app '{props.get('Phone', {}).get('app')}'")
p.send(cl.guidance_ended())                     # a clean start, whatever an earlier test left
wait_nav(lambda q: not q["Guidance"]["active"])

sent_at = time.time()
p.send(cl.guidance("google_maps", "turn", "right", distance_m=350, street="Hauptstraße",
                   remaining_m=8300, remaining_s=720))
ok, props, dt = wait_nav(lambda q: q["Guidance"]["active"] and q["Guidance"]["street"] == "Hauptstraße")
g = props.get("Guidance", {})
check(ok and g["maneuver"] == "turn" and g["modifier"] == "right" and g["distance_m"] == 350
      and g["remaining_m"] == 8300 and g["remaining_s"] == 720 and g["source"] == "google_maps" and not g["stale"],
      f"guidance on D-Bus after {dt * 1000:.0f} ms: {g.get('maneuver')} {g.get('modifier')} in {g.get('distance_m')} m into {g.get('street')}")
check(ok and abs(g["arrival"] - (sent_at + 720)) < 3, f"arrival from the HU's clock: now + 720 s (off by {g.get('arrival', 0) - sent_at - 720:.1f} s)")

p.send(cl.guidance("google_maps", "roundabout", exit=2, distance_m=120, street="B27"))
ok, props, _ = wait_nav(lambda q: q["Guidance"]["maneuver"] == "roundabout")
g = props.get("Guidance", {})
check(ok and g["exit"] == 2 and g["modifier"] == "" and g["remaining_m"] == -1 and g["remaining_s"] == -1 and g["arrival"] == 0,
      "each message is the whole state: fields the phone left out are cleared (-1, '', arrival 0)")
p.send(cl.guidance("osmand", "unknown", text="Weiter auf B27 Richtung Ulm"))
ok, props, _ = wait_nav(lambda q: q["Guidance"]["maneuver"] == "unknown")
check(ok and props["Guidance"]["text"] == "Weiter auf B27 Richtung Ulm" and props["Guidance"]["source"] == "osmand",
      "an unknown maneuver carries the navigation app's own text")

bad_before = props["Phone"]["bad_lines"]
p.send_raw(b"garbage\n" + b'{"type":"guidance","active":true}\n' + b'{"type":"lanes","lanes":[1]}\n')
p.send(cl.guidance("google_maps", "turn", "left", distance_m=80, street="Ringstraße"))
ok, props, _ = wait_nav(lambda q: q["Guidance"]["street"] == "Ringstraße")
check(ok and props["Phone"]["bad_lines"] == bad_before + 2 and props["Phone"]["connected"],
      f"2 bad lines counted (bad_lines {bad_before} -> {props['Phone']['bad_lines']}), an unknown type ignored, link kept")

p.received.clear()
hb = p.wait_for(cl.HEARTBEAT, timeout=cfg["heartbeat_s"] + 1.0)
check(hb is not None, f"the HU sends a heartbeat within {cfg['heartbeat_s']} s")

p.send(cl.guidance_ended())
ok, props, _ = wait_nav(lambda q: not q["Guidance"]["active"])
check(ok and props["Guidance"]["street"] == "" and props["Guidance"]["distance_m"] == -1, "guidance ended: nothing shown")
p.close(bye=True)
ok, props, _ = wait_nav(lambda q: not q["Phone"]["connected"])
check(ok, "bye: the phone is shown as disconnected")

p = phone("Future phone")
p.connect(proto=cl.PROTO_VERSION + 1, timeout=2.0)
bye = p.wait_for(cl.BYE, timeout=2.0)
check(bye is not None and p.closed_by_hu.wait(2.0) and str(cl.PROTO_VERSION) in (bye.get("reason") or ""),
      f"another protocol version: bye ('{bye and bye.get('reason')}') and closed")
check(not any(m["type"] == cl.HELLO for m in p.received), "and no hello from the HU")
p.close()

p = phone("Silent phone")
p.connect(hello=False)
t0 = time.monotonic()
closed = p.closed_by_hu.wait(cfg["hello_timeout_s"] + 2.0)
waited = time.monotonic() - t0
check(closed and cfg["hello_timeout_s"] - 0.5 <= waited, f"no hello: closed after {waited:.1f} s (hello_timeout_s {cfg['hello_timeout_s']})")
ok, props, _ = wait_nav(lambda q: not q["Phone"]["connected"])
check(ok and not props["Guidance"]["active"], "it never counted as connected")
p.close()
finish()
