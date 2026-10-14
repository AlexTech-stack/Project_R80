#!/usr/bin/env python3
"""TC_HU_017: warning chimes (D10). A new 'information' plays the information chime at the
chime volume, a new 'warning' the warning chime, which stays audible when muted (at least
warning_chime_min_gain); a 'notice' is silent. Music ducks while a chime plays."""
import time

import dbus

from common import (ADDRESS, Restbus, WARN_IFACE, WARN_PATH, WARN_SERVICE, audio, audio_config, audio_props,
                    check, finish, wait_audio, wait_for, wait_warnings)

audiod, cfg = audio_config()
a = audio()
obj = dbus.SessionBus().get_object(WARN_SERVICE, WARN_PATH)


def chime():
    p = obj.GetAll(WARN_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return str(p["LastChime"]), float(p["LastChimeGain"]), int(p["ChimeCount"])


def wait_chime(count, timeout=8.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        c = chime()
        if c[2] > count:
            return c
        time.sleep(0.05)
    return chime()


a.SetMuted(False)
a.SetMaster(20)
for s in audiod.SOURCES:
    a.SetVolume(s, cfg["max"])
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn", EngineSpeed=800, FuelLevel=50, Range=400, OilPressure=3.0,
           ServiceDistance=6400)
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on")
    wait_warnings(lambda w: not any(v["severity"] != "notice" for v in w.values()), timeout=8.0)
    time.sleep(1.5)

    n = chime()[2]
    rb.set(FuelLevel=5)
    kind, gain, n2 = wait_chime(n)
    want = audio_props()["Gains"]["chime"]
    check(n2 == n + 1 and kind == "information", f"fuel low (information) -> information chime (got {kind!r}, {n2 - n} played)")
    check(abs(gain - want) < 1e-6 and gain > 0, f"at the chime volume: gain {gain:.3f} (audiod: {want:.3f})")
    ok, p, _ = wait_audio(lambda p: p["Chime"] and p["Duck"] < 1.0, timeout=1.0, step=0.02)
    check(ok, f"music ducks while the chime plays (Duck {p.get('Duck')})")
    ok, p, _ = wait_audio(lambda p: not p["Chime"] and p["Duck"] == 1.0, timeout=4.0)
    check(ok, "after the chime: music back")

    a.SetMuted(True)
    n = chime()[2]
    rb.set(Range=20)
    kind, gain, n2 = wait_chime(n)
    check(kind == "information" and gain == 0.0, f"muted: the information chime is silent (gain {gain})")

    n = chime()[2]
    rb.set(OilPressure=0.0)
    kind, gain, n2 = wait_chime(n)
    want = audio_props()["WarningChimeGain"]
    check(kind == "warning", f"oil pressure gone (warning) -> warning chime (got {kind!r})")
    check(abs(gain - want) < 1e-6 and gain >= cfg["warning_chime_min_gain"],
          f"muted, still audible: gain {gain:.3f} (WarningChimeGain {want:.3f}, min {cfg['warning_chime_min_gain']})")
    a.SetMuted(False)
    wait_audio(lambda p: not p["Chime"], timeout=4.0)

    n = chime()[2]
    rb.set(ServiceDistance=500)
    ok, act, _ = wait_warnings(lambda w: "service_distance" in w, timeout=5.0)
    time.sleep(1.0)
    check(ok and act["service_distance"]["severity"] == "notice" and chime()[2] == n,
          f"service due (notice): listed, no chime ({chime()[2] - n} played)")
    rb.set(FuelLevel=50, Range=400, OilPressure=3.0, ServiceDistance=6400)
a.SetMaster(cfg["default_master"])
finish()
