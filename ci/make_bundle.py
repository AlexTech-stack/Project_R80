#!/usr/bin/env python3
"""Builds a signed update file of the HU software: r80-hu-<version>.r80u (hu/services/update.py).

    ci/make_bundle.py [--out DIR] [--key PRIVATE.pem] [--version V] [--min-version V]
    ci/make_bundle.py --public-key [--key PRIVATE.pem]      # print the key's public part (PEM)

The payload is hu/ plus hu-can/r80_test.dbc (vehicled reads it) as git sees them (tracked and
new files, not the ignored ones such as __pycache__), and a VERSION file. The version comes from the newest tag v<major>.<minor>.<patch> before HEAD:
"0.2.0" on the tag, "0.2.0-dev.<commits since>+<hash>" after it ("0.0.0-dev..." before the first
tag), "+<hash>.dirty" with uncommitted changes under hu/.

Without --key it signs with the development key ~/.config/r80/dev-update-key.pem (made on first
use). A HU trusts that key only when told (system.ini [update] allow_dev_key = yes and its
public part in the HU's local key folder, docs/bench-pi.md). Release files are signed by CI
with the project's release key (secret R80_UPDATE_KEY), whose public part is
hu/update-keys/release.pem.
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hu" / "services"))
import update  # noqa: E402

DEV_KEY = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "r80" / "dev-update-key.pem"
CONTENT = ["hu", "hu-can/r80_test.dbc"]


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()


def version() -> str:
    head = git("rev-parse", "--short=7", "HEAD")
    dirty = bool(git("status", "--porcelain", "--", *CONTENT))
    try:
        desc = git("describe", "--tags", "--match", "v[0-9]*.[0-9]*.[0-9]*", "--long", "HEAD")
        tag, count, _ = desc.rsplit("-", 2)
        base, count = tag[1:], int(count)
    except subprocess.CalledProcessError:
        base, count = "0.0.0", int(git("rev-list", "--count", "HEAD"))
    v = base if count == 0 else f"{base}-dev.{count}+{head}"
    if dirty:
        v += (".dirty" if "+" in v else f"+{head}.dirty")
    update.parse_version(v)
    return v


def public_pem(key: Path) -> bytes:
    return subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"], capture_output=True, check=True).stdout


def dev_key() -> Path:
    if not DEV_KEY.exists():
        DEV_KEY.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(DEV_KEY)], check=True,
                           capture_output=True)
        finally:
            os.umask(old)
        print(f"made a development key: {DEV_KEY}", file=sys.stderr)
    return DEV_KEY


def build(out: Path, key: Path, v: str, min_v: str) -> Path:
    # tracked and new files (not the ignored ones): a dev build carries what is in the working tree
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *CONTENT).split("\0")
    files = sorted({f for f in listed if f and (REPO / f).is_file()})
    hashes, buf = {}, io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as t:
        for f in files + ["VERSION"]:
            data = (v + "\n").encode() if f == "VERSION" else (REPO / f).read_bytes()
            info = tarfile.TarInfo(f)
            info.size, info.mtime = len(data), 0
            info.mode = 0o755 if f != "VERSION" and os.access(REPO / f, os.X_OK) else 0o644
            t.addfile(info, io.BytesIO(data))
            hashes[f] = update.sha256(data)
    payload = buf.getvalue()
    pub = out / ".public.pem"
    pub.write_bytes(public_pem(key))
    try:
        kid = update.key_id(pub)
    finally:
        pub.unlink()
    manifest = json.dumps({
        "format": update.FORMAT, "product": update.PRODUCT, "version": v, "min_version": min_v,
        "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "key_id": kid,
        "payload": {"file": "payload.tar.gz", "size": len(payload), "sha256": update.sha256(payload)},
        "files": hashes}, indent=1, sort_keys=True).encode()
    mf = out / ".manifest.json"
    mf.write_bytes(manifest)
    try:
        sig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(mf)],
                             capture_output=True, check=True).stdout
    finally:
        mf.unlink()
    path = out / f"r80-hu-{v}{update.SUFFIX}"
    with tarfile.open(path, "w:") as t:
        for name, data in (("manifest.json", manifest), ("manifest.sig", sig), ("payload.tar.gz", payload)):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            t.addfile(info, io.BytesIO(data))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "build" / "update"), help="folder for the update file")
    ap.add_argument("--key", help="private Ed25519 key (PEM); default: the development key")
    ap.add_argument("--version", help="instead of the one from git")
    ap.add_argument("--min-version", default="0.0.0", help="the oldest HU version that may install it")
    ap.add_argument("--public-key", action="store_true", help="print the key's public part and exit")
    a = ap.parse_args()
    key = Path(a.key) if a.key else dev_key()
    if a.public_key:
        sys.stdout.write(public_pem(key).decode())
        return
    v = a.version or version()
    update.parse_version(v)
    update.parse_version(a.min_version)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(build(out, key, v, a.min_version))


if __name__ == "__main__":
    try:
        main()
    except (update.UpdateError, subprocess.CalledProcessError) as e:
        sys.exit(f"make_bundle: {e}")
