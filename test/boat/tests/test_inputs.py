#!/usr/bin/env python3
"""TC_HU_005: knob and button events from the MCU reach D-Bus in order."""
import time

from common import ADDRESS, InputListener, Restbus, check, finish, mcu

with Restbus(address=ADDRESS):
    time.sleep(0.5)  # power on, so the MCU forwards
    rx = InputListener()
    sent = [({"cmd": "knob", "value": 2}, ("knob", 2)),
            ({"cmd": "knob", "value": -1}, ("knob", -1)),
            ({"cmd": "push"}, ("push", 1)),
            ({"cmd": "tilt", "value": 1}, ("tilt", 1)),
            ({"cmd": "button", "name": "HOME"}, ("button:HOME", 1)),
            ({"cmd": "button", "name": "VOL_UP"}, ("button:VOL_UP", 9))]
    for cmd, _ in sent:
        check(mcu(cmd)["ok"], f"MCU accepted {cmd}")
    deadline = time.monotonic() + 2
    while len(rx.events) < len(sent) and time.monotonic() < deadline:
        time.sleep(0.05)
    rx.close()
    want = [e for _, e in sent]
    check(rx.events == want, f"D-Bus Input events in order: {rx.events}")
    check(not mcu({"cmd": "button", "name": "NOPE"})["ok"], "unknown button rejected")

finish()
