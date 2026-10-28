#!/usr/bin/env python3
"""TC_HU_045: the voice assistant's command mode (hu-assistd). The button VOICE starts it: it greets,
listens while the driver talks, thinks, answers and ends by itself. Meanwhile audiod turns the music
down (Voice: listen, speak) and back up. Nothing said: it says so and ends. Pressed again while it
runs: it stops. Switched off (setting assistant) or during a call: it does not start and says why.
Recorded speech (dev stand-in for the microphone), the transcript recognizer, a silent voice and the
echo backend (until the companion app brings the LLM) stand in for the real speech and LLM."""
import time

from common import (ADDRESS, Restbus, wait_for, ASSIST_MIC, StateRecorder, assistant, assistant_idle, assistant_logic, assistant_props, audio,
                    check, finish, mcu, say_next, system, wait_assistant, wait_audio)

with Restbus(address=ADDRESS) as rb:      # the HU on (while it is off assistd does not start)
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=10.0)
    check(ok, "ignition on: the HU is on")
    assistd, cfg = assistant_logic()
    check(assistant_idle(), "assistd is ready and idle")
    sysd = system()
    sysd.Set("assistant", True)
    a = audio()
    a.SetCallState("idle")

    # ---- a question -------------------------------------------------------------------------------
    question = "How is my tire pressure?"
    wav = say_next(question, 1.5)
    rec = StateRecorder()
    check(mcu({"cmd": "button", "name": "VOICE"})["ok"], "MCU sends the button VOICE")
    ok, p, _ = wait_assistant(lambda p: p["Mode"] == "command", timeout=2.0)
    check(ok, "the button starts command mode")
    ok, p, dt = wait_assistant(lambda p: p["Mode"] == "idle", timeout=15.0)
    states, voice = rec.stop()
    check(ok, f"it ends by itself after the answer ({dt:.1f} s)")
    want = ["greeting", "listening", "thinking", "speaking", "idle"]
    seen = states[1:] if states[:1] == ["idle"] else states        # idle before the button
    check([s for s in seen if s in want] == want,
          f"states in order: {states}")
    check(p["Heard"] == question, f"it heard what was said: {p['Heard']!r}")
    check(p["Answer"] == f"You said: {question}", f"the echo backend answered: {p['Answer']!r}")
    check(p["Turns"] == 1, f"one answer (Turns {p['Turns']})")
    check(not wav.exists() and (ASSIST_MIC / "heard" / wav.name).exists(), "the recording was heard once")
    check("listen" in voice and "speak" in voice and voice[-1] == "idle",
          f"audiod: music down while it listens and speaks, back up afterwards (Voice {voice})")
    t = p["Timing"]
    check(abs(t.get("speech_s", 0) - 1.5) < 0.05 and "recognise_s" in t and t.get("think_s", 0) >= cfg["think_s"] * 0.9
          and "first_sound_s" in t, f"timing published: {t}")

    # ---- while it listens, audiod ducks media to listen_duck_level -------------------------------------
    say_next("What is the outside temperature?", 3.0)
    assistant().Command()
    ok, _, _ = wait_assistant(lambda p: p["State"] == "listening", timeout=3.0)
    ok, ap, _ = wait_audio(lambda p: p["Voice"] == "listen", timeout=2.0)
    check(ok, "audiod knows the assistant listens")
    # ---- pressed again: it stops at once -----------------------------------------------------------------
    check(mcu({"cmd": "button", "name": "VOICE"})["ok"], "the button VOICE again while it listens")
    ok, p, dt = wait_assistant(lambda p: p["Mode"] == "idle", timeout=1.5)
    check(ok, f"it stops at once ({dt:.2f} s)")
    ok, _, _ = wait_audio(lambda p: p["Voice"] == "idle", timeout=2.0)
    check(ok, "audiod: the music comes back")
    for f in ASSIST_MIC.glob("*.wav"):
        f.unlink()

    # ---- nothing said ------------------------------------------------------------------------------------
    t0 = time.monotonic()
    rec = StateRecorder()
    assistant().Command()
    ok, p, _ = wait_assistant(lambda p: p["Mode"] == "command", timeout=2.0)
    ok, p, _ = wait_assistant(lambda p: p["Mode"] == "idle", timeout=cfg["no_speech_s"] + 8)
    states, _ = rec.stop()
    waited = time.monotonic() - t0
    check(ok and waited >= cfg["no_speech_s"], f"nothing said: it gives up after no_speech_s ({waited:.1f} s)")
    check("thinking" not in states and states.count("speaking") == 1 and p["Heard"] == "" and p["Turns"] == 0,
          f"... says so without thinking (states {states}, heard {p['Heard']!r})")

    # ---- switched off, or a call: it does not start --------------------------------------------------------
    sysd.Set("assistant", False)
    ok, p, _ = wait_assistant(lambda p: not p["Enabled"], timeout=3.0)
    check(ok, "the setting assistant off reaches assistd")
    sessions = p["Sessions"]
    mcu({"cmd": "button", "name": "VOICE"})
    ok, p, _ = wait_assistant(lambda p: p["Notice"] == "switched off", timeout=2.0)
    time.sleep(0.3)
    p = assistant_props()
    check(ok and p["Mode"] == "idle" and p["Sessions"] == sessions, f"switched off: not started (Notice {p['Notice']!r})")
    sysd.Set("assistant", True)
    wait_assistant(lambda p: p["Enabled"], timeout=3.0)

    a.SetCallState("ringing")
    time.sleep(0.3)
    assistant().Command()
    ok, p, _ = wait_assistant(lambda p: p["Notice"] == "a call", timeout=2.0)
    check(ok and p["Mode"] == "idle", f"during a call: not started (Notice {p['Notice']!r})")
    a.SetCallState("idle")
finish()
