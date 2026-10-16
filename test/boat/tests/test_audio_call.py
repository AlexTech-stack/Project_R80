#!/usr/bin/env python3
"""TC_HU_012: a call pauses media and silences radio, from ringing on (D9, audio.ini [focus]).
Media resumes after the call only if it was playing before; mute leaves the phone audible
during a call."""
from common import audio, audio_config, check, finish, media, media_reset, wait_audio, wait_media

audiod, cfg = audio_config()
assert cfg["call_starts_on"] == "ring", "this test expects call_starts_on = ring"
a = audio()
a.SetMuted(False)
a.SetNavPrompt(False)
a.SetCallState("idle")
a.SetMaster(20)
full = {s: cfg["max"] for s in audiod.SOURCES}
for s in audiod.SOURCES:
    a.SetVolume(s, cfg["max"])

media_reset()
ok, _, _ = wait_media(lambda m: m["PlaybackStatus"] == "playing", timeout=5.0)
check(ok, "media playing before the call")

a.SetCallState("ringing")
ok, m, _ = wait_media(lambda m: m["PlaybackStatus"] == "paused", timeout=3.0)
check(ok, f"ringing: media paused (got {m.get('PlaybackStatus')})")
want = audiod.gains_for(cfg, 20, full, False, 1.0, "ringing")
ok, p, _ = wait_audio(lambda p: p["Gains"] == want)
check(ok and p["Gains"]["radio"] == 0, f"ringing: radio silent, phone at {want['phone']} ({p.get('Gains')})")

a.SetCallState("active")
a.SetMuted(True)
want = audiod.gains_for(cfg, 20, full, True, 1.0, "active")
ok, p, _ = wait_audio(lambda p: p["Gains"] == want)
check(ok and p["Gains"]["phone"] > 0, f"call + mute: only the phone is audible ({p.get('Gains')})")
a.SetMuted(False)

a.SetCallState("idle")
ok, m, _ = wait_media(lambda m: m["PlaybackStatus"] == "playing", timeout=3.0)
check(ok, f"call over: media resumes (got {m.get('PlaybackStatus')})")
ok, p, _ = wait_audio(lambda p: p["Gains"]["radio"] > 0)
check(ok, "call over: radio audible again")

media().Pause()
wait_media(lambda m: m["PlaybackStatus"] == "paused")
a.SetCallState("ringing")
a.SetCallState("idle")
ok, m, _ = wait_media(lambda m: m["PlaybackStatus"] == "playing", timeout=1.5)
check(not ok, "media paused before the call stays paused afterwards")

a.SetMaster(cfg["default_master"])
finish()
