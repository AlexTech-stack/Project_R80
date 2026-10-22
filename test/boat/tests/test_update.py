#!/usr/bin/env python3
"""TC_HU_043: software updates of the HU software (D12, hu/services/update.py, hu-sysd). With a
development key of the test's own (trusted through the virtual mode's --dev-keys): an update
file sysd is given (InstallFile) is checked and unpacked as the pending release, which starts
with the next start; one signed with a key the HU does not trust and one whose payload was
changed are refused and say why; RestartNow without a restart command and Rollback without a
previous release are refused. A USB stick with R80-update/ (the udisks2 stand-in) shows its
newer update (Update.found); InstallFound installs it, the older pending one is cleaned up.
The start: update.py select makes the pending release current (on trial); healthy, it stays;
one that never becomes healthy is given up after max_starts starts and the previous one runs
again (kept as the last failure for the page); it is then refused if offered again."""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, REPO, SERVICES, check, finish, sys_props, system

sys.path.insert(0, str(DEV))
sys.path.insert(0, str(SERVICES))
import update  # noqa: E402
from udisks_emu import UD, FakeUDisks  # noqa: E402

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
RELEASES, KEYS, STICK = RUN / "releases", RUN / "update-keys", RUN / "test-update-stick"
TMP = Path(tempfile.mkdtemp(prefix="r80-update-test-"))


def key(name):
    priv = TMP / f"{name}.key"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)], check=True, capture_output=True)
    pub = subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout"], capture_output=True, check=True).stdout
    return priv, pub


def bundle(version, priv, out=TMP):
    r = subprocess.run([sys.executable, str(REPO / "ci" / "make_bundle.py"), "--out", str(out), "--key", str(priv),
                        "--version", version], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return Path(r.stdout.strip())


def upd():
    return sys_props()["Update"]


def install(path, source="file", timeout=20.0):
    system().InstallFile(str(path), source)
    t0 = time.monotonic()
    u = {}
    while time.monotonic() - t0 < timeout:
        u = upd()
        if u["state"] in ("ready", "failed"):
            return u
        time.sleep(0.1)
    return u


def error_of(fn, *args):
    try:
        fn(*args)
    except dbus.exceptions.DBusException as e:
        return e.get_dbus_name().rsplit(".", 1)[-1]
    return None


def wait_update(cond, timeout=8.0):
    t0 = time.monotonic()
    u = {}
    while time.monotonic() - t0 < timeout:
        u = upd()
        if cond(u):
            return True, u
        time.sleep(0.1)
    return False, u


# the test's own development key, trusted by the HU (virtual mode: --dev-keys $RUN/update-keys)
for d in (RELEASES, STICK):
    shutil.rmtree(d, ignore_errors=True)
KEYS.mkdir(parents=True, exist_ok=True)
test_key, test_pub = key("test")
(KEYS / "tc-hu-043.pem").write_bytes(test_pub)
foreign_key, _ = key("foreign")

u = upd()
check(u.get("state") in ("idle", "ready", "failed") and u.get("version"), f"sysd has an Update property ({u})")

# --- from a file (what navd does with the phone's)
good = bundle("50.1.0", test_key)
u = install(good)
pending = RELEASES / "50.1.0"
check(u["state"] == "ready" and u["pending"] == "50.1.0" and "next start" in u["message"],
      f"a signed update: installed, waiting for the next start ({u['state']}: {u['message']})")
check((pending / "hu" / "services" / "sysd.py").is_file() and (pending / "VERSION").read_text().strip() == "50.1.0"
      and (RELEASES / "pending").resolve() == pending.resolve(),
      "its release folder with the HU software, the pending link")

(TMP / "foreign").mkdir()
u = install(bundle("50.2.0", foreign_key, TMP / "foreign"))
check(u["state"] == "failed" and "trust" in u["message"] and u["pending"] == "50.1.0",
      f"signed with a key the HU does not trust: refused, the pending one stays ({u['message']})")

with tarfile.open(good) as t:
    parts = {n: t.extractfile(n).read() for n in ("manifest.json", "manifest.sig", "payload.tar.gz")}
pl = bytearray(parts["payload.tar.gz"])
pl[len(pl) // 2] ^= 1
parts["payload.tar.gz"] = bytes(pl)
bad = TMP / "changed.r80u"
with tarfile.open(bad, "w:") as t:
    for n, data in parts.items():
        info = tarfile.TarInfo(n)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
u = install(bad)
check(u["state"] == "failed" and "payload" in u["message"], f"a changed payload: refused ({u['message']})")
check(error_of(system().InstallFile, str(TMP / "missing.r80u"), "file") == "NotFound", "no such file: NotFound")
check(error_of(system().RestartNow) == "NotAllowed", "RestartNow without a restart command: NotAllowed")
check(error_of(system().Rollback) == "NotFound" and not u["can_rollback"], "Rollback without a previous release: NotFound")

# --- from a USB stick (R80-update/ on it)
(STICK / "R80-update").mkdir(parents=True)
shutil.copy(bundle("50.3.0", test_key), STICK / "R80-update")
loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
ud = FakeUDisks(conn)
conn.request_name(UD, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
time.sleep(1.0)
ud.add("sdv", "R80-UPD-1", "UPDSTICK", str(STICK))
ok, u = wait_update(lambda u: u["found"] == "50.3.0", timeout=10.0)
check(ok, f"a stick with a newer update: found ({u.get('found')!r})")
system().InstallFound()
ok, u = wait_update(lambda u: u["state"] in ("ready", "failed") and u["source"] == "usb", timeout=20.0)
check(ok and u["state"] == "ready" and u["pending"] == "50.3.0" and u["found"] == "",
      f"InstallFound: 50.3.0 waits for the next start, nothing more on the stick ({u['state']}: {u['message']})")
check(not pending.exists() and (RELEASES / "50.3.0").is_dir(), "the older pending release is cleaned up")
ud.remove("sdv")
conn.release_name(UD)
ok, _ = wait_update(lambda u: u["found"] == "")
shutil.rmtree(STICK, ignore_errors=True)

# --- the start (what bench/pi/r80-kiosk.sh asks): a copy of the releases, so sysd's stay as they are
sim = TMP / "start"
shutil.copytree(RELEASES, sim, symlinks=True)
rel = update.Releases(sim, max_starts=2)
first = rel.select()
check(first is not None and first.name == "50.3.0" and rel.on_trial() == "50.3.0" and not rel.version("pending"),
      f"the next start: 50.3.0 is current, on trial ({first})")
check(rel.healthy("50.3.0") and rel.on_trial() == "", "healthy (sysd): it stays")
rel.install(bundle("50.4.0", test_key), [KEYS / "tc-hu-043.pem"], "50.3.0")
starts = [rel.select().name for _ in range(3)]
check(starts == ["50.4.0", "50.4.0", "50.3.0"] and rel.version("current") == "50.3.0"
      and "50.4.0" in rel.state()["failed"] and rel.last_failure() == {"version": "50.4.0", "back_to": "50.3.0"},
      f"never healthy: given up after 2 starts, 50.3.0 runs again ({starts})")
(TMP / "again").mkdir()
try:
    rel.install(bundle("50.4.0", test_key, TMP / "again"), [KEYS / "tc-hu-043.pem"], "50.3.0")
    again = "installed"
except update.UpdateError as e:
    again = str(e)
check("did not start" in again, f"offered again: refused ({again})")

shutil.rmtree(RELEASES, ignore_errors=True)
(KEYS / "tc-hu-043.pem").unlink()
shutil.rmtree(TMP, ignore_errors=True)
finish()
