#!/usr/bin/env python3
"""TC_HU_024: the user's settings (hu-sysd, D12). Every setting of system.ini can be set
within its type and range, wrong values and unknown names are refused without changing
anything, Reset / ResetAll go back to the defaults, values are saved to the state file,
and saved values that no longer fit system.ini fall back to their default (sysd's own
Settings logic). Names and limits come from sysd's config loader."""
import json
import time

import dbus

from common import SETTINGS_STATE, check, finish, sys_logic, sys_props, system

sysd, cfg = sys_logic()
schema = cfg["settings"]
defaults = {n: s["default"] for n, s in schema.items()}
s = system()

s.ResetAll()
props = sys_props()
check(props["Settings"] == defaults, f"ResetAll: every setting at its default ({len(defaults)} settings)")
check(set(props["Schema"]) == set(schema) and all(props["Schema"][n]["type"] == schema[n]["type"] for n in schema),
      "Schema on D-Bus matches system.ini")


def other_value(n):
    """A valid value different from the default, per type."""
    d = schema[n]
    if d["type"] == "bool":
        return not d["default"]
    if d["type"] == "number":
        return round((d["min"] + d["max"]) / 2, 3) if d["default"] != round((d["min"] + d["max"]) / 2, 3) else d["min"]
    return next(c for c in d["choices"] if c != d["default"])


wanted = {n: other_value(n) for n in schema}
for n, v in wanted.items():
    s.Set(n, v)
got = sys_props()["Settings"]
check(got == wanted, "every setting takes a valid value of its type: " + ", ".join(f"{n}={v}" for n, v in wanted.items()))

saved = None
t0 = time.monotonic()
while time.monotonic() - t0 < 3:
    try:
        saved = json.loads(SETTINGS_STATE.read_text())
        if saved == wanted:
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.1)
check(saved == wanted, f"saved to the state file ({SETTINGS_STATE.name})")

num = next(n for n, d in schema.items() if d["type"] == "number")
flag = next(n for n, d in schema.items() if d["type"] == "bool")
pick = next(n for n, d in schema.items() if d["type"] == "choice")
bad = [(num, dbus.Double(schema[num]["max"] + 1), "InvalidValue"), (num, dbus.String("bright"), "InvalidValue"),
       (flag, dbus.Int32(1), "InvalidValue"), (pick, dbus.String("nonsense"), "InvalidValue"),
       ("no_such_setting", dbus.Boolean(True), "UnknownSetting")]
for n, v, err in bad:
    try:
        s.Set(n, v)
        check(False, f"{n} = {v!r} refused")
    except dbus.DBusException as e:
        check(e.get_dbus_name().endswith(err), f"{n} = {v!r} refused ({e.get_dbus_name().rsplit('.', 1)[-1]})")
check(sys_props()["Settings"] == wanted, "refused values changed nothing")

s.Reset(num)
check(sys_props()["Settings"][num] == defaults[num], f"Reset({num}) back to {defaults[num]}, the others kept")

# a state file written by an older or newer system.ini
old = sysd.Settings(schema, {num: schema[num]["max"] + 5, pick: "renamed_choice", "removed_setting": 1,
                             flag: not defaults[flag]})
check(old.values[num] == defaults[num] and old.values[pick] == defaults[pick] and old.values[flag] == (not defaults[flag]),
      "saved values that no longer fit fall back to their default, the rest is kept")

s.ResetAll()
check(sys_props()["Settings"] == defaults, "ResetAll at the end")
finish()
