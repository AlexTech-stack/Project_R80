#!/usr/bin/env python3
"""TC_HU_047: the voice assistant's answers come from the phone (hu-assistd -> hu-navd -> companion
link caps assistant -> the app's LLM; here the phone emulator). Without a phone, with the app not
ready (no API key), or when the phone's LLM fails, the assistant says why and the question leaves
the conversation. A ready phone gets the instructions (assistant.ini's system_prompt with the date),
the question and max_tokens; a conversation sends the earlier turns along. Answers are cleaned for
the voice (no markdown). A phone that goes away mid-question, or never answers ([assistant]
timeout_s of nav.ini), gives an answer at once / after the timeout. What was said and answered never
reaches the DLT log."""
import json
import time

from common import (ADDRESS, DltStream, Restbus, assistant, assistant_idle, assistant_logic, check, finish, phone,
                    say_next, wait_assistant, wait_for, wait_nav)

assistd, cfg = assistant_logic()
navd_timeout = 30.0                    # nav.ini [assistant] timeout_s
SECRET = "Where is the hidden treasure of Captain Flint?"     # must never show up in the log


def ask(text, timeout=15.0):
    """The driver asks one thing in command mode; returns assistd's properties when it is done."""
    say_next(text, 1.0)
    assistant().Command()
    wait_assistant(lambda p: p["Mode"] == "command", timeout=2.0)
    return wait_assistant(lambda p: p["Mode"] == "idle", timeout=timeout)[1]


with Restbus(address=ADDRESS) as rb:
    rb.set(IgnitionState="IgnitionOn")
    ok, _, _ = wait_for(lambda p: p["Power"] == "on", timeout=10.0)
    check(ok, "ignition on: the HU is on")
    check(assistant_idle(), "assistd is ready and idle")
    dlt = DltStream()

    # ---- no phone ------------------------------------------------------------------------------------------
    wait_nav(lambda p: not p["Phone"]["connected"], timeout=10.0)
    p = ask("What time is it?")
    check(p["Answer"] == cfg["errors"]["no_phone"] and p["Notice"] == "no_phone" and p["Turns"] == 0,
          f"no phone: it says so ({p['Answer']!r}, Notice {p['Notice']!r})")

    # ---- a phone whose app has no key ------------------------------------------------------------------------
    ph = phone()
    ph.connect(caps=("guidance", "assistant"))
    ph.serve_assistant(answer=lambda m: {"type": "assist_reply", "ok": False, "code": "no_key", "error": "no API key"},
                       ready=False, reason="no API key in the app")
    ok, n, _ = wait_nav(lambda p: p["Assistant"]["connected"] and not p["Assistant"]["ready"], timeout=3.0)
    check(ok and n["Assistant"]["reason"] == "no API key in the app", f"navd: the phone cannot answer ({n['Assistant']})")
    ok, a, _ = wait_assistant(lambda p: "no API key" in p["Engines"]["llm"], timeout=3.0)
    check(ok, f"Settings shows why: {a['Engines']['llm']!r}")
    p = ask("What time is it?")
    check(p["Answer"] == cfg["errors"]["no_key"] and p["Notice"] == "no_key", f"no key: it says so ({p['Answer']!r})")

    # ---- ready: what the phone gets, what is spoken ---------------------------------------------------------------
    ph.serve_assistant(answer=lambda m: "**Fine.**\n- all four at 2.3 bar", model="test-model")
    ok, a, _ = wait_assistant(lambda p: p["Engines"]["llm"] == "test-model (emulator) through the phone", timeout=3.0)
    check(ok, f"Settings shows the model: {a['Engines']['llm']!r}")
    asked = len(ph.asked)
    p = ask(SECRET)
    req = ph.asked[asked] if len(ph.asked) > asked else {"messages": []}
    roles = [m["role"] for m in req["messages"]]
    check(roles == ["system", "user"] and req["messages"][1]["content"] == SECRET,
          f"the phone gets the instructions and the question ({roles})")
    sysmsg = req["messages"][0]["content"] if req["messages"] else ""
    check(sysmsg.startswith(cfg["system_prompt"][:60]) and time.strftime("%Y") in sysmsg,
          f"... the instructions with the date ({sysmsg[-40:]!r})")
    check(req.get("max_tokens") == cfg["max_tokens"], f"... and max_tokens {req.get('max_tokens')}")
    check(p["Answer"] == "Fine. all four at 2.3 bar" and p["Turns"] == 1 and p["Notice"] == "",
          f"the answer, cleaned for the voice: {p['Answer']!r}")

    # ---- a conversation sends the earlier turns along ---------------------------------------------------------------
    ph.serve_assistant(answer=lambda m: f"Answer {sum(1 for x in m if x['role'] == 'user')}.")
    say_next("First question.", 1.0, "c1")
    say_next("Second question.", 1.0, "c2")
    asked = len(ph.asked)
    assistant().Conversation()
    ok, p, _ = wait_assistant(lambda p: p["Turns"] == 2 and p["State"] == "listening", timeout=15.0)
    assistant().Stop()
    second = ph.asked[asked + 1]["messages"] if len(ph.asked) > asked + 1 else []
    check(ok and [m["role"] for m in second] == ["system", "user", "assistant", "user"]
          and second[2]["content"] == "Answer 1." and second[3]["content"] == "Second question.",
          f"the second turn carries the first ({[m['role'] for m in second]})")
    check(p["Answer"] == "Answer 2.", f"... and is answered ({p['Answer']!r})")

    # ---- the phone's LLM fails ------------------------------------------------------------------------------------------
    wait_assistant(lambda p: p["Mode"] == "idle", timeout=3.0)
    ph.serve_assistant(answer=lambda m: {"type": "assist_reply", "ok": False, "code": "offline", "error": "no internet"})
    p = ask("Is it going to rain?")
    check(p["Answer"] == cfg["errors"]["offline"] and p["Notice"] == "offline", f"offline: it says so ({p['Answer']!r})")
    ph.serve_assistant(answer=lambda m: {"type": "assist_reply", "ok": False, "code": "something_new", "error": "?"})
    p = ask("Is it going to rain?")
    check(p["Answer"] == cfg["errors"]["other"], f"a code it does not know: the general sentence ({p['Answer']!r})")

    # ---- the phone goes away mid-question ---------------------------------------------------------------------------------
    ph.serve_assistant(answer=lambda m: "too late", delay=5.0)
    say_next("How far is it?", 1.0)
    assistant().Command()
    ok, _, _ = wait_assistant(lambda p: p["State"] == "thinking", timeout=6.0)
    t0 = time.monotonic()
    ph.close()
    ok, p, _ = wait_assistant(lambda p: p["Notice"] == "no_phone", timeout=10.0)
    check(ok and time.monotonic() - t0 < 8.0, f"the phone gone mid-question: answered with no_phone "
                                              f"({time.monotonic() - t0:.1f} s, {p['Answer']!r})")
    wait_assistant(lambda p: p["Mode"] == "idle", timeout=6.0)

    # ---- no answer at all: navd's timeout -------------------------------------------------------------------------------
    ph = phone()
    ph.connect(caps=("guidance", "assistant"))
    ph.serve_assistant(answer=lambda m: None)
    wait_nav(lambda p: p["Assistant"]["ready"], timeout=3.0)
    t0 = time.monotonic()
    p = ask("Hello?", timeout=navd_timeout + 15)
    dt = time.monotonic() - t0
    check(p["Notice"] == "timeout" and p["Answer"] == cfg["errors"]["timeout"] and navd_timeout <= dt < navd_timeout + 12,
          f"no answer: timeout after {dt:.0f} s ({p['Answer']!r})")

    # ---- the log ---------------------------------------------------------------------------------------------------------
    time.sleep(0.5)
    with dlt.lock:
        texts = [str(m.text) for m in dlt.messages if m.apid in ("AST", "NAV")]
    check(texts and not any("Captain Flint" in t or "all four at" in t for t in texts),
          f"nothing that was said or answered in the DLT log ({len(texts)} lines of AST and NAV)")
    check(any("answer from the phone" in t for t in texts), "... but how the answers went is")
    ph.close(bye=True)
finish()
