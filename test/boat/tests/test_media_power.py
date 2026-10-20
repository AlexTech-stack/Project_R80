#!/usr/bin/env python3
"""TC_HU_032: media pauses while the HU is off (hu-audiod, pause_media_when_off). Playing
when the bus falls asleep: paused once Power is "off" (after the shutdown save, which
must still see it playing), playing again when the HU is back on. Paused by the driver:
stays paused. A call running when the power comes back keeps it paused until it ends."""
import json
import os
from pathlib import Path

from common import ADDRESS, Restbus, audio, check, finish, media, media_reset, wait_for, wait_media


def off_and_on(rb, during_on=None):
    rb.set(IgnitionState="Off")
    rb.silence()
    ok, _, _ = wait_for(lambda p: p["Power"] == "off", timeout=10.0)
    check(ok, "bus asleep -> Power off")
    ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] != "playing", timeout=3.0)
    status_off = p.get("PlaybackStatus")
    if during_on:
        during_on()
    rb.wake()
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=10.0)
    check(ok, "bus awake, ignition on -> Power on")
    return status_off


STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "media-state.json"
a = audio()
a.SetCallState("idle")
m = media_reset()
with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn")
    wait_for(lambda p: p["Power"] == "on", timeout=5.0)
    ok, _, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=4.0)
    check(ok, "media playing with the HU on")

    STATE.unlink(missing_ok=True)
    saved = {}

    def read_state():
        saved.update(json.loads(STATE.read_text()) if STATE.exists() else {})
    status = off_and_on(rb, during_on=read_state)
    check(status == "paused", f"HU off -> media paused (got {status})")
    check(saved.get("playing") is True, f"the shutdown save still saw it playing (state file: playing {saved.get('playing')})")
    ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=4.0)
    check(ok, f"HU on again -> media plays again (got {p.get('PlaybackStatus')})")

    m.Pause()
    wait_media(lambda p: p["PlaybackStatus"] == "paused", timeout=2.0)
    off_and_on(rb)
    ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=2.0)
    check(not ok, f"paused by the driver: stays paused after power on (got {p.get('PlaybackStatus')})")

    m.Play()
    wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=3.0)
    off_and_on(rb, during_on=lambda: a.SetCallState("active"))
    ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=2.0)
    check(not ok, f"a call running at power on: media stays paused (got {p.get('PlaybackStatus')})")
    a.SetCallState("idle")
    ok, p, _ = wait_media(lambda p: p["PlaybackStatus"] == "playing", timeout=3.0)
    check(ok, f"... and plays when the call ends (got {p.get('PlaybackStatus')})")
m.Pause()
finish()
