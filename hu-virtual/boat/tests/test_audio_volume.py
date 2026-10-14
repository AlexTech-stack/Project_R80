#!/usr/bin/env python3
"""TC_HU_009: hu-audiod owns the volume. Master and source volume and mute reach the
media player as audiod's gain; the MCU's VOL_UP / VOL_DOWN / MUTE keys work without the UI."""
import dbus

from common import ADDRESS, Restbus, audio, audio_config, audio_props, check, finish, mcu, wait_audio, wait_for, wait_media

audiod, cfg = audio_config()
vmax = cfg["max"]
a = audio()
p = audio_props()
check(p["Max"] == vmax and p["StartupCap"] == cfg["startup_cap"], f"Max and StartupCap come from audio.ini ({p['Max']}, {p['StartupCap']})")


def expect(master, media, muted, what):
    g = audiod.gain(cfg, master, media, muted)
    ok, p, _ = wait_audio(lambda p: p["Master"] == master and p["Muted"] == muted and abs(p["Gains"]["media"] - g) < 1e-6)
    check(ok, f"{what}: audiod master {p.get('Master')}, muted {p.get('Muted')}, media gain {p.get('Gains', {}).get('media')} (want {g})")
    ok, m, _ = wait_media(lambda m: abs(m.get("Gain", -1) - g) < 1e-6)
    check(ok, f"{what}: mediad plays at gain {m.get('Gain')} (want {g})")


a.SetMuted(False)
a.SetVolume("media", vmax)
a.SetMaster(10)
expect(10, vmax, False, "master 10, media max")
a.SetVolume("media", vmax // 2)
expect(10, vmax // 2, False, "media volume half")
a.SetMuted(True)
expect(10, vmax // 2, True, "muted")
ok, p, _ = wait_audio(lambda p: all(g == 0 for g in p["Gains"].values()))
check(ok, f"muted: every source at gain 0 ({p.get('Gains')})")
a.ToggleMute()
expect(10, vmax // 2, False, "ToggleMute -> unmuted")
a.SetMaster(vmax + 5)
expect(vmax, vmax // 2, False, f"SetMaster above Max is clamped to {vmax}")

try:
    a.SetVolume("bogus", 3)
    check(False, "unknown source rejected")
except dbus.DBusException as e:
    check("UnknownSource" in e.get_dbus_name(), f"unknown source rejected ({e.get_dbus_name()})")

with Restbus(address=ADDRESS) as rb:          # ignition on: the HU takes key presses
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    check(ok, "ignition on -> Power on (audiod ignores keys while the HU is off)")
    a.SetMaster(10)
    wait_audio(lambda p: p["Master"] == 10)
    mcu({"cmd": "button", "name": "VOL_UP"})
    ok, p, _ = wait_audio(lambda p: p["Master"] == 11)
    check(ok, f"MCU VOL_UP -> master 11 (got {p.get('Master')})")
    mcu({"cmd": "button", "name": "VOL_DOWN"})
    mcu({"cmd": "button", "name": "VOL_DOWN"})
    ok, p, _ = wait_audio(lambda p: p["Master"] == 9)
    check(ok, f"MCU VOL_DOWN x2 -> master 9 (got {p.get('Master')})")
    mcu({"cmd": "button", "name": "MUTE"})
    ok, p, _ = wait_audio(lambda p: p["Muted"])
    check(ok, "MCU MUTE -> muted")
    mcu({"cmd": "button", "name": "MUTE"})
    ok, p, _ = wait_audio(lambda p: not p["Muted"])
    check(ok, "MCU MUTE again -> unmuted")

a.SetMaster(cfg["default_master"])
a.SetVolume("media", cfg["default_volumes"]["media"])
finish()
