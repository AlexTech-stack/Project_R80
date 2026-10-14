#!/usr/bin/env python3
"""TC_HU_010: hu-audiod remembers the volumes and caps the master volume at startup.

Checks that changes reach audiod's state file, and that audiod's own startup logic, fed
with exactly that file and audio.ini, restores the source volumes and caps the master.
(A real restart of audiod is not part of this test.)"""
import json
import time

from common import AUDIO_STATE, audio, audio_config, check, finish, wait_audio

audiod, cfg = audio_config()
cap, vmax = cfg["startup_cap"], cfg["max"]
a = audio()
loud = min(vmax, cap + 5)
quiet = max(0, cap - 4)

a.SetMaster(loud)
a.SetVolume("radio", 7)
wait_audio(lambda p: p["Master"] == loud and p["Volumes"]["radio"] == 7)
saved, t0 = None, time.monotonic()
while time.monotonic() - t0 < 3.0:
    try:
        saved = json.loads(AUDIO_STATE.read_text())
        if saved.get("master") == loud and saved.get("volumes", {}).get("radio") == 7:
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.1)
check(saved and saved.get("master") == loud, f"state file has master {loud} ({AUDIO_STATE}: {saved})")
check(saved and saved.get("volumes", {}).get("radio") == 7, "state file has radio volume 7")

master, volumes = audiod.startup_state(cfg, saved)
check(master == cap, f"start after master {loud} -> capped at {cap} (got {master})")
check(volumes["radio"] == 7, f"start restores radio volume 7 (got {volumes['radio']})")
master, _ = audiod.startup_state(cfg, dict(saved, master=quiet))
check(master == quiet, f"start after master {quiet} (below the cap) -> stays {quiet} (got {master})")

a.SetMaster(cfg["default_master"])
a.SetVolume("radio", cfg["default_volumes"]["radio"])
finish()
