#!/usr/bin/env python3
"""TC_HU_011: a navigation prompt turns the music down (D9). Media and radio fade to
duck_level over duck_fade_ms (both from audio.ini) and come back after the prompt;
navigation and phone keep their level. mediad plays at the ducked gain."""
import time

from common import audio, audio_config, check, finish, media_reset, wait_audio, wait_media

audiod, cfg = audio_config()
a = audio()
a.SetMuted(False)
a.SetCallState("idle")
a.SetNavPrompt(False)
a.SetMaster(20)
for s in audiod.SOURCES:
    a.SetVolume(s, cfg["max"])
media_reset()
wait_media(lambda m: m["PlaybackStatus"] == "playing", timeout=5.0)
base = audiod.gains_for(cfg, 20, {s: cfg["max"] for s in audiod.SOURCES}, False, 1.0, "idle")
low = audiod.gains_for(cfg, 20, {s: cfg["max"] for s in audiod.SOURCES}, False, cfg["duck_level"], "idle")
ok, p, _ = wait_audio(lambda p: p["Gains"] == base)
check(ok, f"before the prompt: {p.get('Gains')}")

a.SetNavPrompt(True)
t0 = time.monotonic()
ok, p, dt = wait_audio(lambda p: abs(p["Gains"]["media"] - low["media"]) < 1e-6, timeout=3.0, step=0.02)
check(ok, f"prompt: media down to {low['media']} (got {p['Gains']['media']})")
fade = cfg["duck_fade_ms"] / 1000
check(dt >= fade * 0.5, f"prompt: it fades rather than jumps ({dt:.2f} s for a {fade:.2f} s fade)")
check(abs(p["Gains"]["radio"] - low["radio"]) < 1e-6, f"prompt: radio down to {low['radio']} (got {p['Gains']['radio']})")
check(p["Gains"]["navigation"] == base["navigation"] and p["Gains"]["phone"] == base["phone"],
      "prompt: navigation and phone keep their level")
check(p["NavPrompt"] is True, "NavPrompt property is true")
ok, m, _ = wait_media(lambda m: abs(m["Gain"] - low["media"]) < 1e-6)
check(ok, f"prompt: mediad plays at the ducked gain (got {m.get('Gain')})")
check(m["PlaybackStatus"] == "playing", "prompt: media keeps playing")

a.SetNavPrompt(False)
ok, p, _ = wait_audio(lambda p: p["Gains"] == base, timeout=3.0)
check(ok, f"after the prompt: back to {base['media']} for media and radio (got {p.get('Gains')})")
ok, m, _ = wait_media(lambda m: abs(m["Gain"] - base["media"]) < 1e-6)
check(ok, f"after the prompt: mediad back at gain {base['media']} (got {m.get('Gain')})")

a.SetMaster(cfg["default_master"])
media_reset().Pause()
finish()
