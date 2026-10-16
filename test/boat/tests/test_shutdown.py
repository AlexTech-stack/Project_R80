#!/usr/bin/env python3
"""TC_HU_026: shutdown coordination (hu-sysd, D12) through the real chain: bus sleep ->
MCU announces off -> vehicled Power = shutdown -> sysd asks the savers (audiod, tripd) to
save -> sysd saves its own settings -> vehicled acknowledges -> MCU cuts the power.
Also: a saver that never answers delays the acknowledgement by save_timeout_s at most and
is reported; the ignition coming back during saving cancels it (no acknowledgement, the MCU
stays on); a saver whose process ended is not waited for. save_timeout_s from system.ini."""
import json
import os
import threading
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import ADDRESS, SETTINGS_STATE, Restbus, check, finish, mcu, sys_logic, sys_props, system, wait_for

sysd, cfg = sys_logic()
timeout = cfg["shutdown"]["save_timeout_s"]
s = system()


def shutdown():
    return sys_props()["Shutdown"]


def wait_sys(cond, t=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        sd = shutdown()
        if cond(sd):
            return True, sd
        time.sleep(0.05)
    return False, shutdown()


def power_cycle_off(rb):
    """ignition off and bus asleep -> the MCU asks Linux to shut down"""
    rb.set(IgnitionState="Off")
    wait_for(lambda p: p["Power"] == "standby", timeout=3.0)
    rb.silence()
    ok, _, _ = wait_for(lambda p: p["Power"] == "shutdown", timeout=5.0)
    return ok


def power_on(rb):
    rb.set(IgnitionState="IgnitionOn")
    rb.wake()
    return wait_for(lambda p: p["Power"] == "on", timeout=4.0)[0]


ok, sd = wait_sys(lambda sd: {"audiod", "tripd"} <= set(sd["savers"]), t=8.0)
check(ok, f"audiod and tripd registered as savers ({sd['savers']})")

with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn")
    wait_for(lambda p: p["Power"] == "on", timeout=3.0)

    # ---- normal shutdown ----------------------------------------------------------
    num = next(n for n, d in cfg["settings"].items() if d["type"] == "number")
    new = cfg["settings"][num]["min"]
    check(power_cycle_off(rb), "bus asleep -> Power shutdown")
    s.Set(num, dbus.Double(new))                 # saved half a second later, unless the shutdown flushes it
    ok, sd = wait_sys(lambda sd: sd["state"] == "acked", t=timeout + 2)
    check(ok and {"audiod", "tripd"} <= set(sd["last_saved"]) and not sd["last_timed_out"],
          f"savers asked and answered: saved {sd['last_saved']}, no answer {sd['last_timed_out']}, {sd['last_ms']} ms")
    ok, _, _ = wait_for(lambda p: p["Power"] == "off", timeout=3.0)
    check(ok, "vehicled acknowledged -> Power off")
    ok, _, _ = wait_for(lambda _p: mcu({"cmd": "status"})["power"] == "off", timeout=3.0)
    check(ok, "MCU cut the power after the acknowledgement")
    try:
        on_disk = json.loads(SETTINGS_STATE.read_text()).get(num)
    except (OSError, ValueError):
        on_disk = None
    check(on_disk == new, f"a setting changed just before is on disk at the acknowledgement ({num} = {on_disk})")
    check(power_on(rb), "ignition on and bus awake -> Power on")
    ok, sd = wait_sys(lambda sd: sd["state"] == "idle", t=3.0)
    check(ok, "sysd back to idle")

    # ---- a saver that never answers -----------------------------------------------
    loop = DBusGMainLoop()
    slow = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
    threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
    dbus.Interface(slow.get_object("de.r80.System", "/de/r80/System"), "de.r80.System1").RegisterSaver("test-slow")
    check("test-slow" in shutdown()["savers"], "a test saver registered (it will never answer)")
    t0 = time.monotonic()
    check(power_cycle_off(rb), "bus asleep -> Power shutdown")
    ok, sd = wait_sys(lambda sd: sd["state"] == "acked", t=timeout + 3)
    waited = time.monotonic() - t0
    check(ok and sd["last_timed_out"] == ["test-slow"] and sd["last_ms"] >= timeout * 1000 - 100,
          f"acknowledged after save_timeout_s = {timeout:g} s without it ({sd['last_ms']} ms; no answer: {sd['last_timed_out']})")
    ok, _, _ = wait_for(lambda _p: mcu({"cmd": "status"})["power"] == "off", timeout=3.0)
    check(ok and waited < 10, f"MCU off before its own 10 s deadline ({waited:.1f} s after the bus slept)")
    check(power_on(rb), "Power on again")

    # ---- the ignition comes back while saving ------------------------------------
    check(power_cycle_off(rb), "bus asleep -> Power shutdown (test saver still pending)")
    ok, sd = wait_sys(lambda sd: sd["state"] == "saving", t=2.0)
    check(ok, "sysd is waiting for the savers")
    check(power_on(rb), "ignition on during saving -> Power on")
    ok, sd = wait_sys(lambda sd: sd["last_cancelled"], t=2.0)
    check(ok, f"sysd cancelled the shutdown (last_cancelled, after {sd['last_ms']} ms)")
    time.sleep(timeout + 0.5)
    st = sys_props()["Shutdown"]["state"]
    check(st in ("cancelled", "idle") and mcu({"cmd": "status"})["power"] == "on"
          and wait_for(lambda p: p["Power"] == "on", timeout=0.5)[0],
          f"no acknowledgement after save_timeout_s: MCU and HU stay on (sysd {st})")

    # ---- a saver whose process ended -------------------------------------------------
    slow.close()
    ok, sd = wait_sys(lambda sd: "test-slow" not in sd["savers"], t=3.0)
    check(ok, f"the test saver is gone -> no longer waited for ({sd['savers']})")
    rb.set(IgnitionState="IgnitionOn")

# the logic on its own: cancel never acknowledges
sd = sysd.Shutdown(timeout)
sd.register("x")
sd.start(0.0)
sd.cancel()
check(not sd.check(timeout + 1) and sd.state == "cancelled" and sd.last["cancelled"],
      "Shutdown logic: a cancelled shutdown is never acknowledged")
s.ResetAll()
finish()
