#!/usr/bin/env python3
"""TC_HU_022: losing the phone (hu-navd, D11). A phone that goes silent is dropped after
link_timeout_s, one that disconnects at once; either way the last guidance stays, marked
stale, and a reconnect continues it. A second phone replaces the first. That stale guidance
is cleared after keep_after_loss_s is checked with navd's own Link logic and a simulated
clock (nobody waits that long in a test). Timing from navd's nav.ini."""
import time

from common import check, finish, nav_logic, phone, wait_nav

navd, cfg = nav_logic()
cl = navd.cl
TURN = cl.guidance("google_maps", "turn", "right", distance_m=500, street="Bergstraße", remaining_m=4000, remaining_s=400)

p = phone("Test phone A")
p.connect()
p.send(TURN)
ok, _, _ = wait_nav(lambda q: q["Guidance"]["active"] and q["Guidance"]["street"] == "Bergstraße" and not q["Guidance"]["stale"])
check(ok, "guidance shown")

p.heartbeats = False                            # the phone goes quiet (app killed, out of range)
t0 = time.monotonic()
closed = p.closed_by_hu.wait(cfg["link_timeout_s"] + 2.0)
waited = time.monotonic() - t0
check(closed and waited >= cfg["link_timeout_s"] - 0.5,
      f"a silent phone is dropped after {waited:.1f} s (link_timeout_s {cfg['link_timeout_s']})")
ok, props, _ = wait_nav(lambda q: not q["Phone"]["connected"])
g = props.get("Guidance", {})
check(ok and g["active"] and g["stale"] and g["street"] == "Bergstraße", "the last guidance stays, marked stale")
p.close()

p = phone("Test phone A")
p.connect()
p.send(TURN)
ok, props, _ = wait_nav(lambda q: q["Phone"]["connected"] and not q["Guidance"]["stale"])
check(ok and props["Guidance"]["active"], "reconnect: guidance live again")

p.close()                                       # the socket just goes away, no bye
ok, props, dt = wait_nav(lambda q: not q["Phone"]["connected"] and q["Guidance"]["stale"], timeout=2.0)
check(ok, f"a closed connection is noticed at once ({dt * 1000:.0f} ms): stale")

a = phone("Test phone A")
a.connect()
b = phone("Test phone B", wait_free=False)
b.connect()
ok, props, _ = wait_nav(lambda q: q["Phone"]["device"] == "Test phone B" and q["Phone"]["connected"])
check(ok and a.closed_by_hu.wait(2.0), "a second phone replaces the first, whose link the HU closes")
b.send(cl.guidance_ended())
wait_nav(lambda q: not q["Guidance"]["active"])
b.close(bye=True)
a.close()

# keep_after_loss_s with navd's own logic and a simulated clock
keep = cfg["keep_after_loss_s"]


def session(link, now):
    link.connect(now)
    link.receive(now, cl.validate(cl.hello("r80-companion", "t", caps=["guidance"])))
    link.receive(now, cl.validate(TURN), wall=1_000_000.0)


link = navd.Link(cfg)
session(link, 0.0)
link.lost(10.0)
link.tick(10.0 + keep - 1)
check(link.view()["active"] and link.view()["stale"], f"stale guidance still shown {keep - 1:.0f} s after the loss")
link.tick(10.0 + keep + 1)
check(not link.view()["active"], f"and cleared {keep + 1:.0f} s after it (keep_after_loss_s {keep})")

link = navd.Link(cfg)
session(link, 0.0)
link.lost(10.0)
session(link, 20.0)
link.tick(10.0 + keep + 1)
check(link.view()["active"] and not link.view()["stale"], "a reconnect with guidance before then continues it")
check(link.view()["arrival"] == 1_000_000 + 400, "arrival = HU clock at reception + remaining_s")
finish()
