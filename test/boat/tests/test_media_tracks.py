#!/usr/bin/env python3
"""TC_HU_008: media track navigation: SetTrack, Next, Previous (restart after 3 s,
otherwise the track before), wrap-around with repeat, stop at the end without repeat,
SetPosition, and the duration learned for a played track."""
import time

from common import check, finish, media_props, media_reset, wait_media

m = media_reset()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == 0 and p["PlaybackStatus"] == "playing", timeout=5.0)
check(ok, "SetTrack(0) -> track 0 playing")
n = p.get("TrackCount", 0)
last = n - 1

m.Next()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == 1 and p["PlaybackStatus"] == "playing", timeout=3.0)
check(ok, f"Next -> track 1 (got {p.get('TrackIndex')})")
ok, p, _ = wait_media(lambda p: p["Metadata"]["duration"] > 0, timeout=3.0)
check(ok, f"duration of the playing track is known (got {p['Metadata']['duration']} s)")

m.SetPosition(5_000_000)
ok, p, _ = wait_media(lambda p: p["Position"] >= 5_000_000, timeout=3.0)
check(ok, f"SetPosition(5 s) -> position >= 5 s (got {p.get('Position')})")
# The service writes the requested position at once; that the player really jumped
# shows a little later, when Position comes from the player again.
ok, p, _ = wait_media(lambda p: 5_500_000 < p["Position"] < 7_500_000, timeout=3.0)
check(ok, f"playback continues from about 5 s (got {p.get('Position')})")
m.Previous()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == 1 and p["Position"] < 3_000_000, timeout=3.0)
check(ok, f"Previous after 5 s -> same track from the start (track {p.get('TrackIndex')}, pos {p.get('Position')})")
m.Previous()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == 0, timeout=3.0)
check(ok, f"Previous within 3 s -> track 0 (got {p.get('TrackIndex')})")
m.Previous()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == last, timeout=3.0)
check(ok, f"Previous on track 0 with repeat -> last track {last} (got {p.get('TrackIndex')})")
m.Next()
ok, p, _ = wait_media(lambda p: p["TrackIndex"] == 0, timeout=3.0)
check(ok, f"Next on the last track with repeat -> track 0 (got {p.get('TrackIndex')})")

m.SetRepeatAll(False)
m.SetTrack(last)
wait_media(lambda p: p["TrackIndex"] == last and p["PlaybackStatus"] == "playing", timeout=3.0)
m.Next()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "stopped", timeout=3.0)
check(ok, f"Next on the last track without repeat -> stopped (got {p.get('PlaybackStatus')})")
time.sleep(1.0)
p = media_props()
check(p["PlaybackStatus"] == "stopped", f"... and it stays stopped 1 s later (got {p['PlaybackStatus']})")
check(not p.get("CanGoNext", True), "CanGoNext is false on the last track without repeat")

m.SetRepeatAll(True)
m.SetTrack(0)
m.Pause()
finish()
