#!/usr/bin/env python3
"""TC_HU_013: volume keys are ignored while the HU is off. The MCU still sends them (the
Input signal goes out), but hu-audiod leaves the volume alone; after waking up they work."""
import time

from common import ADDRESS, InputListener, Restbus, audio, check, finish, mcu, wait_audio, wait_for

listener = InputListener()      # first: it attaches the shared D-Bus connection to a main loop
a = audio()
a.SetMuted(False)
a.SetMaster(10)
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    rb.set(IgnitionState="Off")
    rb.silence()
    ok, _, _ = wait_for(lambda p: p["Power"] == "off", timeout=10.0)
    check(ok, "bus asleep -> Power off")

    n = len(listener.events)
    mcu({"cmd": "button", "name": "VOL_UP"})
    mcu({"cmd": "button", "name": "MUTE"})
    t0 = time.monotonic()
    while len(listener.events) < n + 2 and time.monotonic() - t0 < 2.0:
        time.sleep(0.05)
    check(len(listener.events) >= n + 2, f"the MCU sent the keys while off ({listener.events[n:]})")
    time.sleep(0.5)
    ok, p, _ = wait_audio(lambda p: p["Master"] == 10 and not p["Muted"])
    check(ok, f"off: VOL_UP and MUTE ignored (master {p.get('Master')}, muted {p.get('Muted')})")

    rb.wake()
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=10.0)
    check(ok, "bus awake, ignition on -> Power on")
    mcu({"cmd": "button", "name": "VOL_UP"})
    ok, p, _ = wait_audio(lambda p: p["Master"] == 11)
    check(ok, f"on again: VOL_UP works (master {p.get('Master')})")
listener.close()
a.SetMaster(10)
finish()
