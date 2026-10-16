#!/usr/bin/env python3
"""TC_HU_025: tone controls in hu-audiod (D9: audiod owns everything audio; D12 moved them
there from the UI). Bass and treble in whole dB steps within tone_range_db, balance -1..1,
loudness on/off; wrong values and unknown names are refused without a change; the values are
saved with the volumes; saved values that no longer fit fall back to the defaults (audiod's
own logic). Limits and defaults come from audio.ini through audiod's config loader."""
import json
import time

import dbus

from common import AUDIO_STATE, audio, audio_config, audio_props, check, finish

audiod, cfg = audio_config()
rng, dflt = cfg["tone_range_db"], cfg["default_tone"]
a = audio()

for n, v in dflt.items():                       # start from the defaults
    a.SetTone(n, dbus.Boolean(v) if isinstance(v, bool) else dbus.Double(v))
check(audio_props()["Tone"] == dflt, f"Tone at the defaults from audio.ini: {dflt}")

want = {"bass": rng, "treble": -rng, "balance": -0.5, "loudness": not dflt["loudness"]}
for n, v in want.items():
    a.SetTone(n, dbus.Boolean(v) if isinstance(v, bool) else dbus.Int32(v) if isinstance(v, int) else dbus.Double(v))
got = audio_props()["Tone"]
check(got == want, f"set to the limits: {got}")

saved = None
t0 = time.monotonic()
while time.monotonic() - t0 < 3:
    try:
        saved = json.loads(AUDIO_STATE.read_text()).get("tone")
        if saved == want:
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.1)
check(saved == want, "saved with the volumes in audiod's state file")

for n, v, err in [("bass", dbus.Int32(rng + 1), "InvalidValue"), ("treble", dbus.Double(1.5), "InvalidValue"),
                  ("balance", dbus.Double(1.2), "InvalidValue"), ("loudness", dbus.Int32(1), "InvalidValue"),
                  ("fader", dbus.Double(0), "UnknownTone")]:
    try:
        a.SetTone(n, v)
        check(False, f"{n} = {v!r} refused")
    except dbus.DBusException as e:
        check(e.get_dbus_name().endswith(err), f"{n} = {v!r} refused ({e.get_dbus_name().rsplit('.', 1)[-1]})")
check(audio_props()["Tone"] == want, "refused values changed nothing")

old = audiod.startup_tone(cfg, {"tone": {"bass": rng + 5, "treble": 2, "balance": "left", "removed": 1}})
check(old == dict(dflt, treble=2), "saved values that no longer fit fall back to the defaults, the rest is kept")

for n, v in dflt.items():
    a.SetTone(n, dbus.Boolean(v) if isinstance(v, bool) else dbus.Double(v))
check(audio_props()["Tone"] == dflt, "back to the defaults at the end")
finish()
