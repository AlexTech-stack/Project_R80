#!/usr/bin/env python3
"""TC_HU_007: media play / pause. PlaybackStatus follows what the player really does,
the position runs while playing and stands still while paused, metadata matches the track."""
import time

from common import check, finish, media_reset, wait_media

m = media_reset()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing" and p["Position"] > 500_000, timeout=5.0)
check(ok, f"SetTrack(0) -> playing, position runs (status {p.get('PlaybackStatus')}, pos {p.get('Position')})")
check(p.get("TrackCount", 0) >= 2, f"at least 2 tracks in the library (got {p.get('TrackCount')})")
want = p["Playlist"][p["TrackIndex"]]["title"] if p.get("Playlist") else None
check(p.get("Metadata", {}).get("title") == want, f"Metadata title matches the playlist entry ({want!r})")

m.Pause()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "paused", timeout=3.0)
check(ok, f"Pause -> status paused (got {p.get('PlaybackStatus')})")
pos = p["Position"]
time.sleep(1.0)
p = wait_media(lambda p: True)[1]
check(abs(p["Position"] - pos) < 200_000, f"paused: position stands still ({pos} -> {p['Position']})")

m.Play()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing" and p["Position"] > pos + 300_000, timeout=3.0)
check(ok, f"Play -> playing again and the position moves on (status {p.get('PlaybackStatus')}, pos {p.get('Position')})")

m.PlayPause()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "paused", timeout=3.0)
check(ok, f"PlayPause while playing -> paused (got {p.get('PlaybackStatus')})")
m.PlayPause()
ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=3.0)
check(ok, f"PlayPause while paused -> playing (got {p.get('PlaybackStatus')})")

finish()
