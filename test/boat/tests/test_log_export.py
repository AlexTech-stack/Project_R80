#!/usr/bin/env python3
"""TC_HU_038: the log onto a USB stick (Settings -> Diagnostics -> Export to USB). Without a
stick ExportLog fails with "no USB stick". With one playing (the udisks2 stand-in
dev/udisks_emu.py): hu-mediad lends it out (unmounted, mounted writable, then read-only
again), hu-sysd writes R80-logs/<date_time>/ with the DLT files (DLT protocol version 1,
storage headers, ECU R80, readable with hu/services/dltclient.py: the services' own lines
are in them) and summary.txt; the music stops for that and carries on from where it was.
A stick that cannot be unmounted: the export fails, the stick stays read-only and plays.
A real USB stick and udisks2 are not part of this test (the bench: docs/bench-pi.md)."""
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, SERVICES, check, finish, media, media_props, power_settled, sys_props, system, wait_media

sys.path.insert(0, str(DEV))
sys.path.insert(0, str(SERVICES))
import dltclient as dc  # noqa: E402
import media_tags  # noqa: E402
from udisks_emu import UD, FakeUDisks  # noqa: E402

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
STICK = RUN / "test-log-stick"


def export_state():
    return sys_props()["Export"]


def export(timeout=30.0):
    system().ExportLog()
    t0 = time.monotonic()
    seen = []
    e = {}
    while time.monotonic() - t0 < timeout:
        e = export_state()
        p = media_props()["PlaybackStatus"]
        if not seen or seen[-1] != (e["state"], p):
            seen.append((e["state"], p))
        if e["state"] in ("done", "failed"):
            break
        time.sleep(0.02)
    return e, seen


if STICK.exists():
    shutil.rmtree(STICK)
STICK.mkdir(parents=True)
for n, title in enumerate(["Log One", "Log Two"], 1):
    f = STICK / f"{n:02d}.wav"
    media_tags.tone_wav(f, 230, 30)
    media_tags.tag(f, title=title, artist="USB Artist", album="Log Stick", track=n, total=2)
power_settled()
m = media()
m.SetSource("Library")

loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
ud = FakeUDisks(conn)
conn.request_name(UD, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
time.sleep(1.0)

e, _ = export()
check(e["state"] == "failed" and e["message"] == "no USB stick", f"no stick: the export fails, says so ({e})")

stick = ud.add("sdw", "R80-LOG-1", "LOGSTICK", str(STICK))
ok, p, _ = wait_media(lambda p: p["Source"] == "LOGSTICK" and p["PlaybackStatus"] == "playing", timeout=8.0)
check(ok, f"a stick plugged in plays ({p.get('Source')}, {p.get('PlaybackStatus')})")
m.SetPosition(8_000_000)
wait_media(lambda p: p["Position"] >= 9_000_000, timeout=4.0)

e, seen = export()
check(e["state"] == "done" and e["dir"].startswith("R80-logs/"), f"with it: done ({e})")
check(("writing", "paused") in seen, f"the music stops while it is written ({seen})")
check([c.get("options") for c in stick.mount_calls] == ["ro", "rw", "ro"] and stick.unmount_calls == 2,
      f"mediad: read-only, unmounted, writable, unmounted, read-only again "
      f"({[c.get('options') for c in stick.mount_calls]}, {stick.unmount_calls} unmounts)")
ok, p, _ = wait_media(lambda p: p["Source"] == "LOGSTICK" and p["PlaybackStatus"] == "playing"
                      and p["Position"] >= 8_000_000, timeout=5.0)
check(ok, f"the music carries on from where it was ({p.get('Source')}, {p.get('PlaybackStatus')}, "
          f"{p.get('Position', 0) / 1e6:.1f} s)")

out = STICK / e["dir"]
files = sorted(out.glob("*.dlt"))
summary = (out / "summary.txt").read_text() if (out / "summary.txt").is_file() else ""
check(files and summary.startswith("R80 headunit: log export"), f"{len(files)} DLT file(s) and summary.txt in {e['dir']}")
check(all(f"{a} " in summary for a in ("VEH", "MED", "SYS", "PHN")), "the summary lists the services")
msgs = [msg for f in files for msg in dc.read_file(f)]
check(msgs and all(msg.ecu == "R80" and msg.time > 0 for msg in msgs),
      f"the files: DLT version 1 with storage headers, ECU R80 ({len(msgs)} messages)")
check(any(msg.apid == "SYS" and "serving de.r80.System" in msg.text for msg in msgs),
      "they hold the services' own lines (SYS: serving de.r80.System ...)")
check(e["message"].startswith(f"{len(files)} log file"), f"the page says what was written ({e['message']})")

# --- a stick that cannot be unmounted
stick.fail_unmount = "DeviceBusy"
calls = len(stick.mount_calls)
e, _ = export()
check(e["state"] == "failed", f"unmount refused: the export fails ({e})")
ok, p, _ = wait_media(lambda p: p["Source"] == "LOGSTICK" and p["PlaybackStatus"] == "playing", timeout=5.0)
check(ok and len(stick.mount_calls) == calls and ud.objects[stick._object_path]["org.freedesktop.UDisks2.Filesystem"]["MountPoints"],
      f"the stick stays mounted read-only and plays ({p.get('Source')}, {p.get('PlaybackStatus')})")
stick.fail_unmount = None

ud.remove("sdw")
wait_media(lambda p: p["Source"] == "Library", timeout=4.0)
conn.release_name(UD)
m.Pause()
shutil.rmtree(STICK, ignore_errors=True)
finish()
