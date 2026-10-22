#!/usr/bin/env python3
"""TC_HU_044: a software update over the companion link (caps update, hu-navd -> hu-sysd, D12).
A phone with caps update gets update_status after its hello (the running version); one without
does not. An offer that is not a version is refused. A signed update file (the test's own
development key) offered and sent in pieces (at most UPDATE_WINDOW unacknowledged, every one
acknowledged) is put together, handed to hu-sysd and installed: the phone is told checking ...
ready, and sysd's Update says it waits for the next start. An older version than the waiting one
is refused. A transfer that breaks off (the link goes) resumes where it stopped with the next
offer of the same file. Data that is not the file offered (SHA-256) fails before sysd sees it;
a file signed with a key the HU does not trust arrives but sysd refuses it, and the phone is told."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import REPO, SERVICES, check, finish, phone, sys_props, wait_nav

sys.path.insert(0, str(SERVICES))
import companion_link as cl  # noqa: E402

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
RELEASES, KEYS = RUN / "releases", RUN / "update-keys"
RUN.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="update-phone-test-", dir=RUN))


def key(name):
    priv = TMP / f"{name}.key"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)], check=True, capture_output=True)
    return priv, subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout"], capture_output=True, check=True).stdout


def bundle(version, priv):
    out = TMP / version
    out.mkdir()
    r = subprocess.run([sys.executable, str(REPO / "ci" / "make_bundle.py"), "--out", str(out), "--key", str(priv),
                        "--version", version], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return Path(r.stdout.strip())


def statuses(p, since=0):
    return [m for m in p.received[since:] if m["type"] == cl.UPDATE_STATUS]


shutil.rmtree(RELEASES, ignore_errors=True)
KEYS.mkdir(parents=True, exist_ok=True)
test_key, test_pub = key("test")
(KEYS / "tc-hu-044.pem").write_bytes(test_pub)
foreign_key, _ = key("foreign")
good = bundle("60.1.0", test_key)

# --- caps
quiet = phone(device="No update phone")
quiet.connect(caps=("guidance",))
time.sleep(1.0)
check(not statuses(quiet), "a phone without caps update gets no update_status")
quiet.close(bye=True)

p = phone(device="Update phone")
hu = p.connect(caps=("guidance", "update"))
check("update" in (hu or {}).get("caps", []), "the HU offers update in its hello")
st = p.wait_for(cl.UPDATE_STATUS)
check(st is not None and st["version"] == sys_props()["Update"]["version"] and st["state"] in cl.UPDATE_STATES,
      f"update_status after the hello: the running version ({st})")

# --- refused offers
p.send(cl.update_offer(9, "not-a-version", 10, "0" * 64))
time.sleep(1.0)
r = [m for m in statuses(p) if m["state"] == "refused"]
check(r and "not a version" in r[-1]["message"], f"an offer that is not a version: refused ({r[-1] if r else None})")

# --- a whole update
t0 = time.monotonic()
mark = len(p.received)
end = p.send_update(good, id=1)
took = time.monotonic() - t0
acks = [m for m in p.received[mark:] if m["type"] == cl.UPDATE_ACK]
size = good.stat().st_size
check(acks and acks[-1]["received"] == size and len(acks) == -(-size // cl.MAX_CHUNK),
      f"every piece acknowledged, the last at {size} bytes ({len(acks)} acks)")
seen = [m["state"] for m in statuses(p, mark)]
check(end is not None and end["state"] == "ready" and end["pending"] == "60.1.0" and "checking" in seen,
      f"sent in {took:.1f} s, checked and installed by sysd: {seen[-3:]} ({end and end['message']})")
u = sys_props()["Update"]
check(u["pending"] == "60.1.0" and u["source"] == "phone" and (RELEASES / "60.1.0" / "hu").is_dir(),
      f"sysd: 60.1.0 from the phone waits for the next start ({u['pending']}, {u['source']})")

older = bundle("60.0.5", test_key)
end = p.send_update(older, id=2)
check(end is not None and end["state"] == "refused" and "already waiting" in end["message"],
      f"an older one than the waiting one: refused ({end and end['message']})")

# --- broken off and resumed
newer = bundle("60.2.0", test_key)
p.send_update(newer, id=3, stop_after=40 * cl.MAX_CHUNK)
time.sleep(0.5)
p.close()
wait_nav(lambda n: not n["Phone"]["connected"], timeout=5.0)
p = phone(device="Update phone")
p.connect(caps=("guidance", "update"))
p.wait_for(cl.UPDATE_STATUS)
mark = len(p.received)
end = p.send_update(newer, id=4)
first = next((m for m in statuses(p, mark) if m["state"] == "receiving"), {})
check(first.get("received") == 40 * cl.MAX_CHUNK, f"offered again after the link broke off: goes on at {first.get('received')} bytes")
check(end is not None and end["state"] == "ready" and end["pending"] == "60.2.0", f"... and completes ({end and end['message']})")

# --- not the file offered, and a key the HU does not trust
bad = bytearray(newer.read_bytes())
bad[len(bad) // 2] ^= 1
mark = len(p.received)
sha = hashlib.sha256(newer.read_bytes()).hexdigest()           # what is offered: 60.2.0's file
p.send(cl.update_offer(5, "60.3.0", len(bad), sha))
p.wait_for(cl.UPDATE_STATUS, 2.0)
time.sleep(0.5)
for off in range(0, len(bad), cl.MAX_CHUNK):
    p.send(cl.update_chunk(5, off, bytes(bad[off:off + cl.MAX_CHUNK])))
    if off // cl.MAX_CHUNK % cl.UPDATE_WINDOW == cl.UPDATE_WINDOW - 1:
        time.sleep(0.02)
time.sleep(1.0)
p.send(cl.update_done(5))
time.sleep(1.5)
f = [m for m in statuses(p, mark) if m["state"] == "failed"]
check(f and "SHA-256" in f[-1]["message"] and sys_props()["Update"]["pending"] == "60.2.0",
      f"data that is not the file offered: failed before sysd, 60.2.0 still waits ({f[-1]['message'] if f else None})")
end = p.send_update(bundle("60.4.0", foreign_key), id=6)
check(end is not None and end["state"] == "failed" and "trust" in end["message"],
      f"signed with a key the HU does not trust: sysd refuses it, the phone is told ({end and end['message']})")

p.close(bye=True)
shutil.rmtree(RELEASES, ignore_errors=True)
(KEYS / "tc-hu-044.pem").unlink()
shutil.rmtree(TMP, ignore_errors=True)
finish()
