#!/usr/bin/env python3
"""TC_HU_033: calls over the phone's hands-free link (hu/phoned.py). A stand-in for
PipeWire's telephony service (dev/phone_emu/telephony_emu.py, on the session bus;
dev/hu-virtual.sh and ci/dut/start_dut.sh start phoned with --telephony session) plays
the phone: it connects, a call rings with number and name (audiod: ringing, music
paused), the HU answers and ends it (music back), rejects one, the far end hangs up, the
HU dials (spaces dropped, bad numbers and a refusing phone are errors), the far end
answers; with two phones the newer one counts; PipeWire restarting is survived. Real
Bluetooth and call audio are not part of this test."""
import os
import sys
import threading
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, audio_props, check, finish, media_reset, phone_props, phone_service, wait_audio, wait_media, \
    wait_phone

sys.path.insert(0, str(DEV / "phone_emu"))
from telephony_emu import TEL, FakeTelephony  # noqa: E402

A1, A2 = "AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"


def error_of(fn, *args):
    try:
        fn(*args)
    except dbus.exceptions.DBusException as e:
        return e.get_dbus_name().rsplit(".", 1)[-1]
    return None


media_reset()                                   # music playing, so the call can pause it
wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=5.0)
ph = phone_service()
check(phone_props()["Connected"] is False, "no phone before the telephony service is there")

loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
tel = FakeTelephony(conn)
conn.request_name(TEL, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
ag = tel.add_phone(A1)
ok, p, _ = wait_phone(lambda p: p["Connected"], timeout=5.0)
check(ok and p["Device"]["address"] == A1 and p["Device"]["name"] == A1 and p["Device"]["battery"] == -1,
      f"phone connects: {p.get('Device')}")
check(error_of(ph.Answer) == "NoCall", "Answer without a ringing call: NoCall")

# --- an incoming call, answered and ended at the HU
call = ag.ring("+49 171 0000001", "Test Caller")
ok, p, _ = wait_phone(lambda p: p["CallState"] == "ringing")
c = p["Calls"][0] if p.get("Calls") else {}
check(ok and c.get("number") == "+49 171 0000001" and c.get("name") == "Test Caller" and c.get("direction") == "in"
      and c.get("state") == "incoming", f"a call rings: {c}")
ok, a, _ = wait_audio(lambda a: a["CallState"] == "ringing")
check(ok, f"audiod hears of it: CallState {a.get('CallState')}")
ok, _, _ = wait_media(lambda m: m["PlaybackStatus"] == "paused")
check(ok, "music paused while it rings")
ph.Answer()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "active")
check(ok and call.path in ag.answered and p["Calls"][0]["since"] > 0,
      f"Answer: the phone answers, the call is active since {p['Calls'][0]['since'] if p.get('Calls') else '?'}")
ok, a, _ = wait_audio(lambda a: a["CallState"] == "active")
check(ok, f"audiod: active ({a.get('CallState')})")
ph.Hangup()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "idle" and p["Calls"] == [])
check(ok and call.path in ag.hung_up, "Hangup ends the call")
ok, _, _ = wait_media(lambda m: m["PlaybackStatus"] == "playing", timeout=4.0)
check(ok and audio_props()["CallState"] == "idle", "audiod idle again, music plays on")

# --- rejected, and hung up by the far end
call = ag.ring("+49 89 0000002")
wait_phone(lambda p: p["CallState"] == "ringing")
ph.Hangup()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "idle")
check(ok and call.path in ag.hung_up, "Hangup while it rings rejects it")
call = ag.ring("+49 89 0000003")
wait_phone(lambda p: p["CallState"] == "ringing")
ph.Answer()
wait_phone(lambda p: p["CallState"] == "active")
call.end()
ok, p, _ = wait_phone(lambda p: p["CallState"] == "idle" and p["Calls"] == [])
check(ok, "the far end hangs up: idle")

# --- dialling
ph.Dial("+49 89 123 456")
ok, p, _ = wait_phone(lambda p: p["CallState"] == "dialing")
c = p["Calls"][0] if p.get("Calls") else {}
check(ok and ag.dialled[-1] == "+4989123456" and c.get("direction") == "out",
      f"Dial: the phone dials {ag.dialled[-1:]} ({c})")
ok, a, _ = wait_audio(lambda a: a["CallState"] == "active")
check(ok, f"dialling counts as a call for audiod ({a.get('CallState')})")
dialled = ag.calls[f"{ag.path}/call{ag.count}"]
dialled.set_state("alerting")
ok, _, _ = wait_phone(lambda p: p["CallState"] == "dialing" and p["Calls"][0]["state"] == "alerting")
check(ok, "it rings at the far end: still dialing")
dialled.set_state("active")
ok, _, _ = wait_phone(lambda p: p["CallState"] == "active")
check(ok, "the far end answers: active")
ph.SendTones("1#")
time.sleep(0.3)
check(ag.tones == ["1#"], f"SendTones reaches the phone ({ag.tones})")
ph.HangupAll()
ok, _, _ = wait_phone(lambda p: p["CallState"] == "idle")
check(ok, "HangupAll: idle")
check(error_of(ph.Dial, "call me") == "Failed" and ag.dialled[-1] == "+4989123456", "not a number: Failed, nothing dialled")
ag.fail_dial = "CME"
check(error_of(ph.Dial, "112") == "Failed", "the phone refuses to dial: Failed")
ag.fail_dial = None

# --- two phones: the newer one counts; PipeWire restarting
ag2 = tel.add_phone(A2)
ok, p, _ = wait_phone(lambda p: p["Device"]["address"] == A2)
check(ok, f"a second phone connects: it is the phone now ({p['Device']['address']})")
tel.remove_phone(ag2)
ok, p, _ = wait_phone(lambda p: p["Device"]["address"] == A1 and p["Connected"])
check(ok, f"it goes: back to the first ({p['Device']['address']})")
conn.release_name(TEL)
ok, p, _ = wait_phone(lambda p: not p["Connected"])
check(ok, "PipeWire's service gone: no phone")
conn.request_name(TEL, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
ok, p, _ = wait_phone(lambda p: p["Connected"] and p["Device"]["address"] == A1, timeout=5.0)
check(ok, "it is back: the phone again")
tel.remove_phone(ag)
ok, p, _ = wait_phone(lambda p: not p["Connected"])
check(ok and error_of(ph.Dial, "112") == "NoPhone", "phone gone: not connected, Dial says NoPhone")

conn.release_name(TEL)
finish()
