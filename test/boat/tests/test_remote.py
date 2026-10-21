#!/usr/bin/env python3
"""TC_HU_041: the passenger's remote over the companion link (hu-navd, caps remote). A phone
that asks gets the media state after its hello (status, track, queue, up next, sources, the
master volume, allowed) and again when something changes; its commands reach hu-mediad and
hu-audiod (pause, play, next, shuffle, seek, volume, mute, source by name, play_from; an
unknown source is refused and the link stays); it browses the
library page by page (the same ids as the HU's Browse screen; a missing list: total -1).
With the setting phone_remote off the state says allowed: false and commands are ignored;
on again, they work. A phone without caps remote gets no media state."""
import time

from common import audio, audio_props, check, finish, media, media_props, nav_logic, nav_props, phone, system, wait_audio, wait_media

navd, _cfg = nav_logic()
import companion_link as cl  # noqa: E402


def last(p, t):
    ms = [m for m in p.received if m["type"] == t]
    return ms[-1] if ms else None


def wait_msg(p, t, cond=lambda m: True, timeout=4.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        hit = [m for m in p.received if m["type"] == t and cond(m)]
        if hit:
            return hit[-1]
        time.sleep(0.05)
    return None


def cmd(p, c, **kw):
    p.send({"type": cl.MEDIA_CMD, "cmd": c, **kw})


s = system()
s.Set("phone_remote", True)
m = media()
m.SetSource("Library")
m.SetShuffle(False)
m.SetRepeatAll(True)
m.SetTrack(0)
m.Play()
wait_media(lambda x: x["PlaybackStatus"] == "playing", timeout=5.0)

quiet = phone(device="No remote phone")
quiet.connect(caps=("guidance",))
time.sleep(1.0)
check(last(quiet, cl.MEDIA) is None, "a phone without caps remote gets no media state")
quiet.close(bye=True)

p = phone(device="Remote phone")
hu = p.connect(caps=("guidance", "remote"))
check("remote" in (hu or {}).get("caps", []), "the HU offers remote in its hello")
st = wait_msg(p, cl.MEDIA)
mp, ap = media_props(), audio_props()
check(st is not None and st["allowed"] and st["status"] == "playing" and st["title"] == mp["Metadata"]["title"]
      and st["tracks"] == mp["TrackCount"] and st["track"] == mp["TrackIndex"] and st["volume"] == ap["Master"]
      and st["volume_max"] == ap["Max"] and "Library" in st["sources"],
      f"the media state after the hello: playing, the track, the queue, the volume ({(st or {}).get('title')})")
check(len((st or {}).get("up_next", [])) == min(5, len(mp["UpNext"])), "with up to 5 tracks up next")

cmd(p, "pause")
ok, _, _ = wait_media(lambda x: x["PlaybackStatus"] == "paused")
check(ok and wait_msg(p, cl.MEDIA, lambda x: x["status"] == "paused") is not None, "pause: mediad pauses, the phone hears of it")
cmd(p, "play")
ok, _, _ = wait_media(lambda x: x["PlaybackStatus"] == "playing")
check(ok, "play")
before = media_props()["TrackIndex"]
cmd(p, "next")
ok, _, _ = wait_media(lambda x: x["TrackIndex"] == before + 1)
check(ok and wait_msg(p, cl.MEDIA, lambda x: x["track"] == before + 1) is not None, "next: the next track, the phone hears of it")
cmd(p, "shuffle", value=True)
ok, _, _ = wait_media(lambda x: x["Shuffle"])
check(ok, "shuffle on")
cmd(p, "shuffle", value=False)
wait_media(lambda x: not x["Shuffle"])
cmd(p, "seek", value=12.0)
ok, x, _ = wait_media(lambda x: 11_000_000 <= x["Position"] <= 16_000_000, timeout=4.0)
st = wait_msg(p, cl.MEDIA, lambda y: 11 <= (y.get("position_s") or 0) <= 16)
check(ok and st is not None, f"seek to 12 s: mediad there, the phone told of the jump ({x.get('Position', 0) / 1e6:.1f} s)")

vol0 = audio_props()["Master"]
target = max(0, vol0 - 2)
cmd(p, "volume", value=target)
ok, _, _ = wait_audio(lambda a: a["Master"] == target)
check(ok and wait_msg(p, cl.MEDIA, lambda y: y["volume"] == target) is not None, f"volume {vol0} -> {target}: audiod, and back to the phone")
cmd(p, "mute", value=True)
ok, _, _ = wait_audio(lambda a: a["Muted"])
check(ok, "mute")
cmd(p, "mute", value=False)
wait_audio(lambda a: not a["Muted"])
audio().SetMaster(vol0)

# --- choosing the source (a text value): the same one, an unknown one; the link stays
bad = nav_props()["Phone"]["bad_lines"]
cmd(p, "source", value="Library")
ok, x, _ = wait_media(lambda x: x["Source"] == "Library")
cmd(p, "source", value="No such source")
time.sleep(1.0)
check(ok and nav_props()["Phone"]["connected"] and nav_props()["Phone"]["bad_lines"] == bad and not p.closed_by_hu.is_set(),
      "source: chosen by name; an unknown one is refused by mediad, the link stays")
cmd(p, "pause")
ok, _, _ = wait_media(lambda x: x["PlaybackStatus"] == "paused")
check(ok, "... and the next command still works")
cmd(p, "play")
wait_media(lambda x: x["PlaybackStatus"] == "playing")

# --- browsing: the top, a list, a missing one; play from a list
p.send({"type": cl.BROWSE, "id": 1, "path": "", "offset": 0, "count": 20})
r = wait_msg(p, cl.BROWSE_RESULT, lambda y: y["id"] == 1)
ids = [e["id"] for e in (r or {}).get("entries", [])]
check(r is not None and ids == ["folders", "artists", "albums", "tracks"], f"browse the top: folders, artists, albums, all tracks ({ids})")
p.send({"type": cl.BROWSE, "id": 2, "path": "albums", "offset": 0, "count": 2})
r = wait_msg(p, cl.BROWSE_RESULT, lambda y: y["id"] == 2)
check(r is not None and r["total"] >= 1 and 1 <= len(r["entries"]) <= 2 and r["entries"][0]["kind"] == "album",
      f"browse albums, a page of 2 ({(r or {}).get('total')} in all)")
album = r["entries"][0]["id"] if r and r["entries"] else ""
p.send({"type": cl.BROWSE, "id": 3, "path": album, "offset": 0, "count": 20})
r = wait_msg(p, cl.BROWSE_RESULT, lambda y: y["id"] == 3)
tracks = [e for e in (r or {}).get("entries", []) if e["kind"] == "track"]
check(tracks and tracks[0]["index"] == 0, f"an album's tracks with their index ({len(tracks)})")
p.send({"type": cl.BROWSE, "id": 4, "path": "albums/no%20such%20album"})
r = wait_msg(p, cl.BROWSE_RESULT, lambda y: y["id"] == 4)
check(r is not None and r["total"] == -1 and r["entries"] == [], "a list that is not there: total -1")
if tracks:
    want = tracks[-1]["title"]
    cmd(p, "play_from", path=album, index=tracks[-1]["index"])
    ok, x, _ = wait_media(lambda x: x["Metadata"]["title"] == want and x["QueueTitle"] != "All tracks")
    check(ok, f"play_from: that album is the queue, from the chosen track ({x.get('Metadata', {}).get('title')})")

# --- not allowed
s.Set("phone_remote", False)
st = wait_msg(p, cl.MEDIA, lambda y: not y["allowed"])
check(st is not None, "phone_remote off: the phone is told allowed: false")
status = media_props()["PlaybackStatus"]
cmd(p, "pause" if status == "playing" else "play")
time.sleep(1.0)
check(media_props()["PlaybackStatus"] == status, "... and its commands are ignored")
n = len(p.received)
s.Set("phone_remote", True)
t0 = time.monotonic()
while time.monotonic() - t0 < 4 and not any(y["type"] == cl.MEDIA and y["allowed"] for y in p.received[n:]):
    time.sleep(0.05)
check(any(y["type"] == cl.MEDIA and y["allowed"] for y in p.received[n:]), "phone_remote on again: allowed: true")
cmd(p, "pause")
ok, _, _ = wait_media(lambda x: x["PlaybackStatus"] == "paused")
check(ok, "on again: commands work")
p.close(bye=True)
m.SetSource("Library")
m.Pause()
finish()
