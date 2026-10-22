#!/usr/bin/env python3
"""TC_HU_037: the DLT log (hu/services/dlt.py, dlt-daemon.sh) and Settings -> Diagnostics
(hu-sysd, diagnostics.py). Over the DLT daemon's TCP port, as DLT Viewer would
(hu/services/dltclient.py): every service (and hu-syslogd: OS) is registered as its DLT application with a
MAIN context and descriptions; a warning a service logs (navd: a bad line from the phone)
arrives in the stream with its application, context and level, and in sysd's Log (counted,
newest first). SetLogLevel through sysd changes every context of a service at the daemon
(back to default too), refuses unknown levels and applications; ClearLog empties the page.
The DLT files on the HU are TC_HU_038's."""
import time

import dbus

from common import DLT_PORT, DltStream, check, finish, phone, sys_props, system

APPS = ["VEH", "MED", "AUD", "WRN", "TRP", "NAV", "SYS", "PHN", "OS"]


def error_of(fn, *args):
    try:
        fn(*args)
    except dbus.exceptions.DBusException as e:
        return e.get_dbus_name().rsplit(".", 1)[-1]
    return None


def log_view():
    return sys_props()["Log"]


def app_view(apid):
    return next((a for a in log_view()["apps"] if a["id"] == apid), {})


def wait_log(cond, timeout=4.0):
    t0 = time.monotonic()
    v = {}
    while time.monotonic() - t0 < timeout:
        v = log_view()
        if cond(v):
            return True, v
        time.sleep(0.1)
    return False, v


try:
    dlt = DltStream()
except OSError as e:
    check(False, f"the DLT daemon answers on TCP {DLT_PORT} ({e})")
    finish()
check(True, f"the DLT daemon answers on TCP {DLT_PORT}")

info = dlt.log_info()
missing = [a for a in APPS if a not in info]
check(not missing, f"every service is a DLT application ({sorted(info)}; missing {missing})")
check(all("MAIN" in info[a]["contexts"] and info[a]["contexts"]["MAIN"]["description"] for a in APPS if a in info),
      "each with a MAIN context and a description")
check({"USB", "BTPL", "SAVE"} <= set(info.get("MED", {}).get("contexts", {})),
      f"parts are contexts of their service (MED: {sorted(info.get('MED', {}).get('contexts', {}))})")

ok, v = wait_log(lambda v: v["connected"] and all(app_view(a).get("running") for a in APPS), timeout=6.0)
check(ok, f"sysd reads the daemon: connected, every service running ({[(a['id'], a['running']) for a in v.get('apps', [])]})")
check([a["id"] for a in v["apps"]][:10] == ["HMI", "VEH", "MED", "AUD", "WRN", "TRP", "NAV", "SYS", "PHN", "OS"],
      "in the order of system.ini's [diagnostics] apps")

# --- a warning: navd drops a bad line from the phone
system().ClearLog()
wait_log(lambda v: not v["entries"])
before = app_view("NAV").get("warnings", 0)
p = phone(device="DLT test phone")
p.connect()
p.send_raw(b"this is not json\n")
m = dlt.wait(lambda m: m.apid == "NAV" and m.ctid == "MAIN" and m.level == 3 and "bad line" in m.text)
check(m is not None and m.ecu == "R80", f"the warning is in the DLT stream: NAV MAIN warning, ECU R80 ({m})")
ok, v = wait_log(lambda v: app_view("NAV").get("warnings", 0) == before + 1 and v["entries"]
                 and v["entries"][0]["app"] == "NAV")
e = v["entries"][0] if v.get("entries") else {}
check(ok and e.get("level") == "warning" and e.get("context") == "MAIN" and "bad line" in e.get("text", "")
      and abs(e.get("time", 0) - time.time()) < 60, f"... and on the Diagnostics page, counted ({e})")
p.close(bye=True)

# --- log levels through sysd
s = system()
s.SetLogLevel("TRP", "debug")
ok = False
for _ in range(20):
    trp = dlt.log_info().get("TRP", {}).get("contexts", {})
    ok = bool(trp) and all(c["level"] == 5 for c in trp.values())
    if ok:
        break
    time.sleep(0.2)
check(ok, f"SetLogLevel('TRP', 'debug'): every TRP context at debug at the daemon ({trp})")
ok, _ = wait_log(lambda v: app_view("TRP").get("level") == "debug")
check(ok, f"... and the page shows it ({app_view('TRP').get('level')})")
s.SetLogLevel("TRP", "default")
ok, _ = wait_log(lambda v: app_view("TRP").get("level") == "default")
check(ok, "back to default")
check(error_of(s.SetLogLevel, "TRP", "loud") == "InvalidValue", "an unknown level: InvalidValue")
check(error_of(s.SetLogLevel, "", "info") == "UnknownApp", "no application: UnknownApp")

s.ClearLog()
ok, v = wait_log(lambda v: not v["entries"] and all(a["errors"] == a["warnings"] == 0 for a in v["apps"]))
check(ok, "ClearLog: no entries, no counts")
finish()
