#!/usr/bin/env python3
"""TC_HU_029: what mediad reads from the files (test library, dev/media_tags.py):
title, artist, album, track number and the embedded cover from ID3 tags (one cover
file per album), else artist and title from the file name, the album from the
folder and the folder's cover.png; a duration for every track; the documented
D-Bus types (TrackIndex, TrackCount, Scanned: int32; UpNext: aa{sv}); and an
unknown source refused with de.r80.Media1.Error.UnknownSource."""
import dbus

from common import MEDIA_IFACE, MEDIA_PATH, MEDIA_SERVICE, check, finish, media, media_queue, wait_media

ok, p, waited = wait_media(lambda p: p.get("TrackCount", 0) > 0 and p.get("Scanned") == p["TrackCount"], timeout=20.0)
check(ok, f"all tracks read (Scanned {p.get('Scanned')} of {p.get('TrackCount')} after {waited:.1f} s)")
queue = media_queue()
by_title = {t["title"]: t for t in queue}

a, b = by_title.get("Kilometer Null"), by_title.get("Red Horizon")
check(a is not None and b is not None, f"tagged tracks by their tag title (titles: {sorted(by_title)})")
if a and b:
    check(a["artist"] == "The Quattro Lines" and a["album"] == "Night Drive",
          f"artist and album from the tag (got {a['artist']!r}, {a['album']!r})")
    check((a["trackNumber"], b["trackNumber"]) == (1, 2), f"track numbers 1 and 2 (got {a['trackNumber']}, {b['trackNumber']})")
    check(a["cover"].endswith(".png") and "/covers/" in a["cover"],
          f"embedded cover saved in the cache (got {a['cover']!r})")
    check(a["cover"] == b["cover"], "one cover file for the album's two tracks")

c = by_title.get("Coastline")
check(c is not None, "untagged track titled from its file name")
if c:
    check(c["artist"] == "Marta Kovac" and c["album"] == "Blue Roads",
          f"artist from the name, album from the folder (got {c['artist']!r}, {c['album']!r})")
    check(c["cover"].endswith("Blue Roads/cover.png"), f"the folder's cover.png (got {c['cover']!r})")
    check(c["trackNumber"] == 0, f"no track number without a tag (got {c['trackNumber']})")
n = by_title.get("Night Drive")
check(n is not None and n["cover"] == "", f"no cover for a loose untagged file (got {n and n['cover']!r})")

durations = {t["title"]: t["duration"] for t in queue}
check(durations and all(20 <= d <= 28 for d in durations.values()), f"every duration known before playing (got {durations})")

raw = dbus.SessionBus().get_object(MEDIA_SERVICE, MEDIA_PATH).GetAll(MEDIA_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
types = {k: type(raw[k]).__name__ for k in ("TrackIndex", "TrackCount", "Scanned")}
check(all(t == "Int32" for t in types.values()), f"TrackIndex, TrackCount, Scanned are int32 (got {types})")
check(raw["UpNext"].signature == "a{sv}", f"UpNext is aa{{sv}} (got a{raw['UpNext'].signature})")

source = p.get("Source")
try:
    media().SetSource("Tape")
    check(False, "SetSource('Tape') refused")
except dbus.exceptions.DBusException as e:
    check(e.get_dbus_name() == "de.r80.Media1.Error.UnknownSource", f"SetSource('Tape') refused with UnknownSource (got {e.get_dbus_name()})")
ok, p, _ = wait_media(lambda p: p.get("Source") == source, timeout=1.0)
check(ok, f"the source stays {source!r} (got {p.get('Source')!r})")
finish()
