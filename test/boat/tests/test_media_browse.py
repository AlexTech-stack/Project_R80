#!/usr/bin/env python3
"""TC_HU_031: browsing and the play queue (hu/browse.py), on the test library
(dev/media_tags.py): the menu, folders (sub-folders before tracks), albums (artist,
cover), artists -> albums -> tracks, paging, PlayFrom making a list the queue
(QueueTitle, Queue, TrackCount, TrackIndex, GetQueue), UpNext with and without
repeat, shuffle as one shuffled order that UpNext shows and Next follows (every
track once), the queue in the state file, and NotFound for unknown lists."""
import json
import os
from pathlib import Path

import dbus

from common import check, finish, media, media_props, media_queue, wait_media

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "media-state.json"
m = media()
m.SetSource("Library")
m.SetShuffle(False)
m.SetRepeatAll(True)
wait_media(lambda p: p["Source"] == "Library" and p["Scanned"] == p["SourceTrackCount"] > 0, timeout=20.0)


def browse(path, offset=0, count=50):
    title, total, entries = m.Browse(path, offset, count)
    return str(title), int(total), [{str(k): (str(v) if isinstance(v, dbus.String) else int(v)) for k, v in e.items()}
                                    for e in entries]


title, total, menu = browse("")
check(title == "Library" and [e["id"] for e in menu] == ["folders", "artists", "albums", "tracks"],
      f"menu of the Library: {[e['title'] for e in menu]}")

_, _, folders = browse("folders")
check([(e["kind"], e["title"]) for e in folders] == [("folder", "Blue Roads"), ("folder", "Night Drive"), ("track", "Night Drive")],
      f"folders first, then the loose track ({[(e['kind'], e['title']) for e in folders]})")
_, _, blue = browse(folders[0]["id"])
check([e["title"] for e in blue] == ["Coastline", "Low Tide"], f"a folder's tracks by file name ({[e['title'] for e in blue]})")

_, _, albums = browse("albums")
by_name = {e["title"]: e for e in albums}
check(["Blue Roads", "Night Drive"] == [e["title"] for e in albums][:2] and len(albums) == 3,
      f"albums A-Z ({[e['title'] for e in albums]})")
nd = by_name.get("Night Drive", {})
check(nd.get("subtitle") == "The Quattro Lines" and nd.get("count") == 2 and nd.get("cover", "").endswith(".png"),
      f"an album: its artist, track count, cover ({nd.get('subtitle')}, {nd.get('count')}, {nd.get('cover')})")
album_title, _, nd_tracks = browse(nd.get("id", "albums/x"))
check(album_title == "Night Drive" and [(e["title"], e["index"]) for e in nd_tracks] == [("Kilometer Null", 0), ("Red Horizon", 1)],
      f"the album's tracks by track number ({[(e['title'], e['index']) for e in nd_tracks]})")

_, _, artists = browse("artists")
check([e["title"] for e in artists] == ["Marta Kovac", "Neon Autobahn", "The Quattro Lines"],
      f"artists A-Z ({[e['title'] for e in artists]})")
_, _, ql = browse(artists[-1]["id"])
_, _, ql_tracks = browse(ql[0]["id"]) if ql else ("", 0, [])
check(len(ql) == 1 and [e["title"] for e in ql_tracks] == ["Kilometer Null", "Red Horizon"],
      f"artist -> albums -> tracks ({[e['title'] for e in ql]}, {[e['title'] for e in ql_tracks]})")

_, total, page = browse("tracks", 1, 2)
check(total == 5 and [e["index"] for e in page] == [1, 2], f"paging: total {total}, entries {[e['index'] for e in page]}")

m.PlayFrom(nd["id"], 1)
ok, p, _ = wait_media(lambda p: p["Queue"] == nd["id"] and p["PlaybackStatus"] == "playing", timeout=4.0)
check(ok and p["QueueTitle"] == "Night Drive" and p["TrackCount"] == 2 and p["TrackIndex"] == 1
      and p["Metadata"]["title"] == "Red Horizon",
      f"PlayFrom(album, 1): queue {p.get('QueueTitle')!r} of {p.get('TrackCount')}, track {p.get('TrackIndex')} "
      f"{p.get('Metadata', {}).get('title')!r}")
check([t["title"] for t in media_queue()] == ["Kilometer Null", "Red Horizon"], "GetQueue: the album's tracks")
check([t["title"] for t in p["UpNext"]] == ["Kilometer Null"], f"UpNext with repeat wraps ({[t['title'] for t in p['UpNext']]})")
m.SetRepeatAll(False)
ok, p, _ = wait_media(lambda p: p["UpNext"] == [], timeout=2.0)
check(ok, "UpNext without repeat on the last track: empty")
m.SetRepeatAll(True)
try:
    st = json.loads(STATE.read_text())
except (OSError, ValueError):
    st = {}
check(st.get("resume", {}).get("library", {}).get("queue") == nd["id"], "the state file keeps the queue")

m.PlayFrom("tracks", 0)
m.SetShuffle(True)
ok, p, _ = wait_media(lambda p: p["Queue"] == "tracks" and p["Shuffle"] and len(p["UpNext"]) == 4, timeout=3.0)
first = p["Metadata"]["title"]
upnext = [t["title"] for t in p["UpNext"]]
check(ok and first not in upnext and len(set(upnext)) == 4, f"shuffle: UpNext shows the other 4 tracks ({upnext})")
played = [first]
for _ in range(4):
    want = media_props()["UpNext"][0]["title"]
    m.Next()
    ok, p, _ = wait_media(lambda p, w=want: p["Metadata"]["title"] == w, timeout=3.0)
    played.append(p["Metadata"]["title"])
check(played[1:] == upnext and len(set(played)) == 5, f"Next follows UpNext, every track once ({played})")
m.SetShuffle(False)

for call, args in (("Browse", ("nope", 0, 10)), ("PlayFrom", ("albums/zz", 0))):
    try:
        getattr(m, call)(*args)
        check(False, f"{call}{args} refused")
    except dbus.exceptions.DBusException as e:
        check(e.get_dbus_name() == "de.r80.Media1.Error.NotFound", f"{call}{args}: NotFound ({e.get_dbus_name()})")

m.PlayFrom("tracks", 0)
m.Pause()
finish()
