#!/usr/bin/env python3
"""CI check of the update files (ci/make_bundle.py, hu/services/update.py), with throwaway keys:
a file built from this tree verifies and unpacks to the tree's files; a foreign key, a changed
manifest and a changed payload are refused; versions sort as semantic versions. Needs openssl."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hu" / "services"))
import update  # noqa: E402

failed = []


def check(ok, what):
    print(f"   {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failed.append(what)


def refused(path, keys, code):
    try:
        update.verify(path, keys)
    except update.UpdateError as e:
        return e.code == code
    return False


def rewrite(src: Path, dst: Path, change):
    with tarfile.open(src) as t:
        parts = {n: t.extractfile(n).read() for n in ("manifest.json", "manifest.sig", "payload.tar.gz")}
    change(parts)
    with tarfile.open(dst, "w:") as t:
        for n, d in parts.items():
            i = tarfile.TarInfo(n)
            i.size = len(d)
            t.addfile(i, io.BytesIO(d))


with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    for name in ("a", "b"):
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(T / f"{name}.key")],
                       check=True, capture_output=True)
        (T / f"{name}.pem").write_bytes(subprocess.run(["openssl", "pkey", "-in", str(T / f"{name}.key"), "-pubout"],
                                                       capture_output=True, check=True).stdout)
    out = subprocess.run([sys.executable, str(REPO / "ci" / "make_bundle.py"), "--out", str(T), "--key", str(T / "a.key"),
                          "--version", "1.2.3"], capture_output=True, text=True)
    check(out.returncode == 0, f"make_bundle builds a file {out.stderr.strip()}")
    f = Path(out.stdout.strip() or T / "missing")
    try:
        m = update.verify(f, [T / "b.pem", T / "a.pem"])
        check(m["version"] == "1.2.3" and "hu/services/sysd.py" in m["files"] and "hu-can/r80_test.dbc" in m["files"],
              "it verifies with its key; version, hu/ and the DBC in it")
        update.unpack(f, m, T / "rel")
        check((T / "rel" / "VERSION").read_text().strip() == "1.2.3"
              and (T / "rel" / "hu" / "services" / "sysd.py").read_bytes() == (REPO / "hu" / "services" / "sysd.py").read_bytes(),
              "it unpacks to the tree's files and a VERSION")
    except update.UpdateError as e:
        check(False, f"verify and unpack: {e}")
    check(refused(f, [T / "b.pem"], "signature"), "a key the HU does not trust: refused")

    def bump(p):
        m = json.loads(p["manifest.json"])
        m["version"] = "9.9.9"
        p["manifest.json"] = json.dumps(m).encode()

    def flip(p):
        b = bytearray(p["payload.tar.gz"])
        b[len(b) // 2] ^= 1
        p["payload.tar.gz"] = bytes(b)
    rewrite(f, T / "t1.r80u", bump)
    rewrite(f, T / "t2.r80u", flip)
    check(refused(T / "t1.r80u", [T / "a.pem"], "signature"), "a changed manifest: refused (signature)")
    check(refused(T / "t2.r80u", [T / "a.pem"], "hash"), "a changed payload: refused (hash)")
    order = ["0.1.0-dev.2+a", "0.1.0-dev.10+b", "0.1.0", "0.1.1", "0.2.0-rc.1", "0.2.0", "0.10.0", "1.0.0"]
    check(sorted(order, key=update.parse_version) == order, "versions sort as semantic versions")

if failed:
    sys.exit(f"update file check: {len(failed)} failed")
