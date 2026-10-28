#!/usr/bin/env python3
"""TC_HU_046: the voice assistant's conversation mode (hu-assistd). The button TALK starts it: it
greets, then listens and answers turn after turn, also after a pause with nothing said, until TALK is
pressed again ("Okay", then idle). A call stops it at once and the music comes back. The button VOICE
during a conversation stops it too. Recorded speech, the transcript recognizer, a silent voice and the
echo backend stand in for the real speech and LLM."""
import time

from common import (ADDRESS, Restbus, wait_for, StateRecorder, assistant, assistant_idle, assistant_logic, audio, check, finish, mcu, say_next,
                    system, wait_assistant, wait_audio)

with Restbus(address=ADDRESS) as rb:      # the HU on (while it is off assistd does not start)
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=10.0)
    check(ok, "ignition on: the HU is on")
    assistd, cfg = assistant_logic()
    check(assistant_idle(), "assistd is ready and idle")
    system().Set("assistant", True)
    a = audio()
    a.SetCallState("idle")

    # ---- two turns, a pause, a third turn ------------------------------------------------------------------
    first, second, third = "How far can I drive?", "And when is the next service?", "Thank you."
    say_next(first, 1.2, "a1")
    say_next(second, 1.6, "a2")
    rec = StateRecorder()
    check(mcu({"cmd": "button", "name": "TALK"})["ok"], "MCU sends the button TALK")
    ok, p, _ = wait_assistant(lambda p: p["Mode"] == "conversation", timeout=2.0)
    check(ok, "the button starts conversation mode")
    ok, p, _ = wait_assistant(lambda p: p["Turns"] == 2 and p["State"] == "listening", timeout=15.0)
    check(ok, f"two answers, then it listens again (Turns {p['Turns']}, State {p['State']})")
    check(p["Heard"] == second and p["Answer"] == f"You said: {second}", f"the second turn: {p['Heard']!r} -> {p['Answer']!r}")
    # nothing said for a while (shorter than conversation_idle_s): it keeps listening
    time.sleep(cfg["no_speech_s"] + 1.5)
    p = wait_assistant(lambda p: True)[1]
    check(p["Mode"] == "conversation" and p["State"] == "listening",
          f"a pause of {cfg['no_speech_s'] + 1.5:.0f} s: still in the conversation, listening ({p['State']})")
    say_next(third, 0.8, "a3")
    ok, p, _ = wait_assistant(lambda p: p["Turns"] == 3, timeout=cfg["no_speech_s"] + 8)
    check(ok and p["Heard"] == third, f"after the pause it hears the third turn ({p['Heard']!r})")
    ok, p, _ = wait_assistant(lambda p: p["State"] == "listening", timeout=8.0)

    # ---- TALK again: "Okay", then idle -------------------------------------------------------------------------
    check(mcu({"cmd": "button", "name": "TALK"})["ok"], "the button TALK again")
    ok, p, dt = wait_assistant(lambda p: p["Mode"] == "idle", timeout=6.0)
    states, voice = rec.stop()
    check(ok, f"the conversation ends ({dt:.1f} s, after saying {cfg['conversation_end']!r})")
    check(states[-2:] == ["speaking", "idle"], f"... it speaks before it ends ({states[-4:]})")
    check(states.count("thinking") == 3 and states.count("greeting") == 1, f"three turns, one greeting: {states}")
    check(p["Turns"] == 3, f"Turns {p['Turns']}")
    check(voice[-1] == "idle", f"audiod: the music back up (Voice {voice})")

    # ---- a call stops it at once ----------------------------------------------------------------------------
    assistant().Conversation()
    ok, _, _ = wait_assistant(lambda p: p["State"] == "listening", timeout=3.0)
    check(ok, "a new conversation listens")
    a.SetCallState("ringing")
    ok, p, dt = wait_assistant(lambda p: p["Mode"] == "idle", timeout=1.5)
    check(ok and p["Notice"] == "a call", f"a call stops it at once ({dt:.2f} s, Notice {p['Notice']!r})")
    ok, _, _ = wait_audio(lambda p: p["Voice"] == "idle", timeout=2.0)
    check(ok, "audiod: the assistant no longer ducks (the call rules take over)")
    a.SetCallState("idle")
    wait_audio(lambda p: p["CallState"] == "idle", timeout=2.0)
    time.sleep(0.3)                          # assistd hears of it from audiod's PropertiesChanged

    # ---- VOICE during a conversation stops it -------------------------------------------------------------------
    assistant().Conversation()
    ok, _, _ = wait_assistant(lambda p: p["State"] == "listening", timeout=3.0)
    check(ok, "after the call a conversation starts again")
    mcu({"cmd": "button", "name": "VOICE"})
    ok, p, dt = wait_assistant(lambda p: p["Mode"] == "idle", timeout=1.5)
    check(ok, f"the button VOICE stops a conversation ({dt:.2f} s)")
finish()
