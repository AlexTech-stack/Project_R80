#!/usr/bin/env python3
"""TC_HU_036: music from the phone (hu/btmedia.py, AVRCP). A stand-in for BlueZ's player of
a connected phone (dev/phone_emu/bluez_player_emu.py, session bus; mediad runs with
--bluetooth session) brings the "Bluetooth" source; on it mediad passes Play, Pause, Next,
Previous and shuffle on to the phone, shows its track and state, browsing is on the phone,
a call pauses and resumes the phone (audiod), leaving the source pauses the phone, the
phone starting its music switches over when nothing else plays, and the phone going away
falls back to the Library. The sound (A2DP, the PipeWire stage) needs the bench."""
import os
import sys
import threading

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, audio, check, finish, media, media_props, power_settled, wait_media

sys.path.insert(0, str(DEV / "phone_emu"))
from bluez_player_emu import BLUEZ, FakePlayerBlueZ  # noqa: E402

TRACKS = [{"Title": "Phone Song One", "Artist": "Test Band", "Album": "On the Phone", "Duration": 200000},
          {"Title": "Phone Song Two", "Artist": "Test Band", "Album": "On the Phone", "Duration": 150000}]

power_settled()
m = media()
a = audio()
a.SetCallState("idle")
m.SetSource("Library")
m.SetShuffle(False)
m.SetTrack(0)
wait_media(lambda p: p["Source"] == "Library" and p["PlaybackStatus"] == "playing", timeout=4.0)

loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
bz = FakePlayerBlueZ(conn)
conn.request_name(BLUEZ, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
dev = bz.add_phone("AA:BB:CC:00:03:01", "Test Phone")
player = bz.add_player(dev, TRACKS)
ok, p, _ = wait_media(lambda p: "Bluetooth" in p["Sources"], timeout=5.0)
check(ok and p["Source"] == "Library", f"a phone with a player: Bluetooth among the sources ({p.get('Sources')}), the Library plays on")

m.SetSource("Bluetooth")
ok, p, _ = wait_media(lambda p: p["Source"] == "Bluetooth" and p["PlaybackStatus"] == "playing", timeout=4.0)
md = p.get("Metadata", {})
check(ok and "Play" in player.calls, f"SetSource('Bluetooth') while playing: the phone plays ({player.calls})")
check(md.get("title") == "Phone Song One" and md.get("artist") == "Test Band" and md.get("duration") == 200,
      f"the phone's track ({md.get('title')!r}, {md.get('artist')!r}, {md.get('duration')} s)")
check(p["QueueTitle"] == "Test Phone" and p["TrackCount"] == 1 and p["UpNext"] == [],
      f"the queue is on the phone ({p['QueueTitle']!r}, {p['TrackCount']}, {p['UpNext']})")
m.Next()
ok, p, _ = wait_media(lambda p: p["Metadata"]["title"] == "Phone Song Two")
check(ok and player.calls[-1] == "Next", "Next goes to the phone")
m.Previous()
ok, p, _ = wait_media(lambda p: p["Metadata"]["title"] == "Phone Song One")
check(ok and player.calls[-1] == "Previous", "Previous goes to the phone")
m.Pause()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "paused")
check(ok and player.calls[-1] == "Pause", "Pause goes to the phone")
m.PlayPause()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing")
check(ok and player.calls[-1] == "Play", "PlayPause: playing again")
m.SetShuffle(True)
ok, p, _ = wait_media(lambda p: p["Shuffle"])
check(ok and "Set Shuffle=alltracks" in player.calls, "shuffle is the phone's")
m.SetShuffle(False)
title, total, entries = m.Browse("", 0, 10)
check(str(title) == "Test Phone" and int(total) == 0, "browsing happens on the phone (an empty list)")

a.SetCallState("ringing")
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "paused", timeout=3.0)
check(ok and player.calls[-1] == "Pause", "a call pauses the phone's music")
a.SetCallState("idle")
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=3.0)
check(ok and player.calls[-1] == "Play", "after the call it plays again")

m.SetSource("Library")
ok, p, _ = wait_media(lambda p: p["Source"] == "Library", timeout=4.0)
check(ok and player.calls[-1] == "Pause", "leaving Bluetooth pauses the phone")
m.Pause()
wait_media(lambda p: p["PlaybackStatus"] == "paused")
player.play_on_phone()
ok, p, _ = wait_media(lambda p: p["Source"] == "Bluetooth", timeout=4.0)
check(ok, "the phone starts its music while nothing plays: Bluetooth takes over")

bz.remove_player(player)
ok, p, _ = wait_media(lambda p: p["Source"] == "Library" and "Bluetooth" not in p["Sources"], timeout=4.0)
check(ok, f"the phone's player gone: back to the Library ({p.get('Source')}, {p.get('Sources')})")
conn.release_name(BLUEZ)
m.Pause()
finish()
