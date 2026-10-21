#!/usr/bin/env python3
"""TC_HU_034: contacts and call history from the phone (hu/phonebook.py, PBAP), kept per
phone on the HU with consent. Stand-ins for PipeWire's telephony and BlueZ's obexd
(dev/phone_emu/) on the session bus play two phones with made-up phonebooks. A new phone:
Consent "" (the UI asks); no -> nothing copied; Sync -> contacts and history copied
(vCard 2.1 quoted-printable names, 3.0 folding, the owner card left out), the file 0600,
obexd's temporary files gone; GetContacts in pages; a ringing number gets its name from
the copy; favourites survive a re-sync; after reconnecting the copy is there without a
new sync; a second phone has its own copy; a phone that refuses: SyncState failed;
DeleteCopy forgets everything. Real Bluetooth is not part of this test."""
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, check, finish, phone_service, wait_phone

sys.path.insert(0, str(DEV / "phone_emu"))
from obex_emu import OBEX, FakeObex  # noqa: E402
from telephony_emu import TEL, FakeTelephony  # noqa: E402

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
STATE = RUN / "phone"                         # where hu-virtual.sh and start_dut.sh keep the copies
A, B, C = "AA:BB:CC:00:01:01", "AA:BB:CC:00:01:02", "AA:BB:CC:00:01:03"
PB_A = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN:Owner;Test;;;\r\nTEL;CELL:+4915100000000\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:2.1\r\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=C3=BCrgen;;;\r\n"
        "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:J=C3=BCrgen M=C3=BC=\r\nller\r\nTEL;CELL:+49 170 0000001\r\n"
        "TEL;HOME:089 0000002\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Anna Example\r\nTEL;TYPE=CELL:+49 151 0000003\r\nitem1.TEL;TYPE=WORK:0711 00\r\n"
        " 00004\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Workshop\r\nTEL;TYPE=WORK:+49 711 0000005\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Only Mail\r\nEMAIL:x@example.org\r\nEND:VCARD\r\n")
CCH_A = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Anna Example\r\nTEL:+491510000003\r\n"
         "X-IRMC-CALL-DATETIME;TYPE=MISSED:20261020T144400\r\nEND:VCARD\r\n"
         "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:\r\nTEL:0711 0000005\r\nX-IRMC-CALL-DATETIME;TYPE=DIALED:20261019T081500\r\n"
         "END:VCARD\r\n")
PB_B = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Owner B\r\nTEL:+4916000000\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Bea Second\r\nTEL;TYPE=CELL:+49 160 0000009\r\nEND:VCARD\r\n")


def wait(cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def names(contacts):
    return [str(c["name"]) for c in contacts]


ph = phone_service()
loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
tel = FakeTelephony(conn)
obex = FakeObex(conn, RUN / "obex-tmp", {A: {"pb": PB_A, "cch": CCH_A}, B: {"pb": PB_B, "cch": ""}, C: {"pb": PB_A}})
conn.request_name(TEL, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
conn.request_name(OBEX, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
for addr in (A, B, C):                       # a fresh start: no copies of these phones
    (STATE / (addr.replace(":", "") + ".json")).unlink(missing_ok=True)

ag = tel.add_phone(A)
ok, p, _ = wait_phone(lambda p: p["Connected"] and p["Device"]["address"] == A, timeout=5.0)
check(ok and p["Consent"] == "" and p["ContactCount"] == 0, f"a new phone: not asked yet (Consent {p.get('Consent')!r})")
ph.SetConsent(False)
ok, p, _ = wait_phone(lambda p: p["Consent"] == "no")
time.sleep(0.5)
check(ok and not obex.sessions and p["ContactCount"] == 0, "no: nothing copied, the phone not asked")

ph.Sync()
ok, p, waited = wait_phone(lambda p: p["SyncState"] == "idle" and p["ContactCount"] > 0, timeout=10.0)
check(ok and p["Consent"] == "yes" and p["SyncedAt"] > 0, f"Sync: copied ({p.get('ContactCount')} contacts, {waited:.1f} s)")
contacts = list(ph.GetContacts(0, 50))
check(names(contacts) == ["Anna Example", "Jürgen Müller", "Workshop"],
      f"contacts A-Z, owner and number-less cards left out, quoted-printable and folding ({names(contacts)})")
anna = contacts[0]
check([(str(n["number"]), str(n["type"])) for n in anna["numbers"]] == [("+491510000003", "mobile"), ("07110000004", "work")],
      f"a contact's numbers and types ({[(str(n['number']), str(n['type'])) for n in anna['numbers']]})")
check(names(ph.GetContacts(1, 1)) == ["Jürgen Müller"], "GetContacts in pages")
hist = p["History"]
check([(h["kind"], h["time"]) for h in hist] == [("missed", "2026-10-20 14:44"), ("out", "2026-10-19 08:15")]
      and hist[1]["name"] == "Workshop", f"call history, a nameless entry named from the copy ({hist})")
f = STATE / (A.replace(":", "") + ".json")
check(f.exists() and stat.S_IMODE(f.stat().st_mode) == 0o600, f"the copy is a file only its user can read ({f.name})")
check(wait(lambda: not any((RUN / "obex-tmp").iterdir())), "obexd's temporary files are deleted")
check(len(obex.removed) == len(obex.sessions) == 1, f"the OBEX session is closed ({obex.removed})")
check([(b, pf.get("Format")) for _, b, pf in obex.pulls] == [("pb", "vcard30"), ("cch", "vcard30")]
      and obex.pulls[1][2].get("MaxCount") == 50, f"phonebook, then the last 50 calls ({obex.pulls})")

call = ag.ring("0170 0000001")               # the phone sends no name
ok, p, _ = wait_phone(lambda p: p["CallState"] == "ringing")
check(ok and p["Calls"][0]["name"] == "Jürgen Müller", f"a ringing number gets its name from the copy ({p['Calls'][0]['name'] if p.get('Calls') else ''})")
call.end()
wait_phone(lambda p: p["CallState"] == "idle")

ph.SetFavourite(str(anna["id"]), True)
ok, p, _ = wait_phone(lambda p: names(p["Favourites"]) == ["Anna Example"])
check(ok, f"SetFavourite: a favourite ({names(p['Favourites'])})")
ph.Sync()
ok, p, _ = wait_phone(lambda p: p["SyncState"] == "idle" and len(obex.removed) == 2, timeout=10.0)
check(ok and names(p["Favourites"]) == ["Anna Example"], "a re-sync keeps the favourites")

tel.remove_phone(ag)
wait_phone(lambda p: not p["Connected"])
ag = tel.add_phone(A)
ok, p, _ = wait_phone(lambda p: p["Connected"] and p["ContactCount"] == 3, timeout=5.0)
time.sleep(0.5)
check(ok and len(obex.sessions) == 2, f"reconnected: the copy is there, no new sync ({p.get('ContactCount')}, {len(obex.sessions)} sessions)")

agb = tel.add_phone(B)
ok, p, _ = wait_phone(lambda p: p["Device"]["address"] == B)
check(ok and p["Consent"] == "" and p["ContactCount"] == 0, "a second phone: its own copy, not asked yet")
ph.SetConsent(True)
ok, p, _ = wait_phone(lambda p: p["SyncState"] == "idle" and p["ContactCount"] == 1, timeout=10.0)
check(ok and names(ph.GetContacts(0, 10)) == ["Bea Second"], "yes: its contacts copied at once")
tel.remove_phone(agb)
ok, p, _ = wait_phone(lambda p: p["Device"]["address"] == A and p["ContactCount"] == 3)
check(ok and names(p["Favourites"]) == ["Anna Example"], "back to the first phone: its copy")

agc = tel.add_phone(C)
obex.refuse.add(C)
wait_phone(lambda p: p["Device"]["address"] == C)
ph.SetConsent(True)
ok, p, _ = wait_phone(lambda p: p["SyncState"] == "failed", timeout=10.0)
check(ok and p["SyncError"] != "" and p["ContactCount"] == 0, f"a phone that refuses: failed ({p.get('SyncError')!r})")
tel.remove_phone(agc)

wait_phone(lambda p: p["Device"]["address"] == A)
ph.DeleteCopy()
ok, p, _ = wait_phone(lambda p: p["ContactCount"] == 0)
data = json.loads(f.read_text())
check(ok and p["Favourites"] == [] and p["History"] == [] and p["Consent"] == "no"
      and data["contacts"] == data["history"] == data["favourites"] == [],
      "DeleteCopy: contacts, history and favourites gone, also from the file")

tel.remove_phone(ag)
conn.release_name(TEL)
conn.release_name(OBEX)
finish()
