#!/usr/bin/env python3
"""TC_HU_035: the call's sound settings in hu-phoned (D9): hu-audiod hands it the phone
level (CallGain = audiod's Gains["phone"]) whenever the phone volume or mute changes;
mute silences it outside a call but spares a running call; the microphone mute
(SetMicMuted) holds for the call and is off again for the next one. Putting them on
PipeWire's call streams (hu/callaudio.py) needs a real call and is checked on the bench."""
import os
import sys
import threading

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, audio, check, finish, phone_service, wait_audio, wait_phone

sys.path.insert(0, str(DEV / "phone_emu"))
from telephony_emu import TEL, FakeTelephony  # noqa: E402

a = audio()
a.SetMuted(False)
a.SetCallState("idle")
ph = phone_service()
loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
tel = FakeTelephony(conn)
conn.request_name(TEL, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
ag = tel.add_phone("AA:BB:CC:00:02:01")
wait_phone(lambda p: p["Connected"], timeout=5.0)

for volume in (20, 8):
    a.SetVolume("phone", volume)
    ok, au, _ = wait_audio(lambda au: au["Volumes"]["phone"] == volume)
    want = au["Gains"]["phone"]
    ok, p, _ = wait_phone(lambda p, w=want: abs(p["CallGain"] - w) < 1e-6)
    check(ok, f"phone volume {volume}: phoned's CallGain follows audiod ({p.get('CallGain')} = {want})")

a.SetMuted(True)
ok, p, _ = wait_phone(lambda p: p["CallGain"] == 0)
check(ok, f"muted, no call: CallGain 0 ({p.get('CallGain')})")
call = ag.ring("+49 89 0000010")
wait_phone(lambda p: p["CallState"] == "ringing")
ph.Answer()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "active" and p["CallGain"] > 0)
check(ok, f"muted, but a call is on: the call stays audible (CallGain {p.get('CallGain')})")

check(not p["MicMuted"], "the microphone is on when the call starts")
ph.SetMicMuted(True)
ok, p, _ = wait_phone(lambda p: p["MicMuted"])
check(ok, "SetMicMuted: the microphone is cut off")
call.end()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "idle" and not p["MicMuted"])
check(ok, "the call ends: the microphone is on again for the next one")
a.SetMuted(False)
ok, p, _ = wait_phone(lambda p: p["CallGain"] > 0)
check(ok, "unmuted: CallGain back")

tel.remove_phone(ag)
conn.release_name(TEL)
finish()
