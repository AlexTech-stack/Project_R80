#!/usr/bin/env python3
"""TC_HU_003: power states follow IgnitionState and bus sleep, with the shutdown handshake.

  ignition on -> Power on
  ignition off (bus still awake) -> standby
  bus silent -> MCU asks Linux to shut down -> Linux answers SHUTDOWN_READY -> off
  bus wakes with ignition on -> on
"""
from common import ADDRESS, Restbus, check, finish, mcu, wait_for

with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=3.0)
    check(ok, "ignition on -> Power on")

    rb.set(IgnitionState="Accessory")
    ok, _, _ = wait_for(lambda p: p["Power"] == "acc", timeout=3.0)
    check(ok, "accessory -> Power acc")

    rb.set(IgnitionState="Off")
    ok, _, _ = wait_for(lambda p: p["Power"] == "standby", timeout=3.0)
    check(ok, "ignition off, bus awake -> Power standby")

    rb.silence()
    ok, _, dt = wait_for(lambda p: p["Power"] == "shutdown", timeout=5.0)
    check(ok, f"bus asleep -> Linux told to shut down ({dt:.1f} s)")
    ok, _, dt = wait_for(lambda p: p["Power"] == "off", timeout=5.0)
    check(ok, f"shutdown handshake done -> Power off ({dt:.1f} s)")
    ok, _, _ = wait_for(lambda _p: mcu({"cmd": "status"})["power"] == "off", timeout=2.0)
    check(ok, "MCU cut power after SHUTDOWN_READY")
    check(mcu({"cmd": "status"})["link_up"], "MCU <-> Linux link stays up (MCU is always on)")

    rb.set(IgnitionState="IgnitionOn")
    rb.wake()
    ok, _, dt = wait_for(lambda p: p["Power"] == "on", timeout=3.0)
    check(ok, f"bus wake-up with ignition on -> Power on ({dt:.1f} s)")

finish()
