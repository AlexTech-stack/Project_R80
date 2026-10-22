"""Software updates of the HU software (decision D12): versions, update files, their check.

An update file (r80-hu-<version>.r80u, made by ci/make_bundle.py) is a plain tar of three members:

    manifest.json    {"format": 1, "product": "r80-hu", "version": "0.2.0", "min_version": "0.0.0",
                      "created": "<ISO time>", "key_id": "<16 hex>",
                      "payload": {"file": "payload.tar.gz", "size": n, "sha256": "..."},
                      "files": {"hu/services/sysd.py": "<sha256>", ...}}
    manifest.sig     Ed25519 signature of manifest.json (openssl pkeyutl -sign -rawin)
    payload.tar.gz   the release: hu/, hu-can/r80_test.dbc, VERSION

The HU trusts the public keys (*.pem) of its running release (hu/update-keys/) and, only when
allowed (system.ini [update] allow_dev_key), a local folder of development keys. Whoever
brings the file (the phone, a USB stick) is not trusted: the signature and every hash are
checked before anything is used. The check runs openssl, so no Python package is needed.

    m = verify(path, keys)          # the manifest, or UpdateError (code: signature, format, ...)
    unpack(path, m, dest)           # the payload into dest (a new folder), every file checked
    newer("0.2.0", "0.1.0")         # True; 0.2.0-dev.3+abc < 0.2.0
No D-Bus here, so tests can use it.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

FORMAT = 1
PRODUCT = "r80-hu"
SUFFIX = ".r80u"
MAX_MANIFEST = 1_000_000                 # bytes
MAX_PAYLOAD = 200_000_000                # bytes, unpacked
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")


class UpdateError(Exception):
    """code: format | signature | product | version | hash | space | io"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_version(v: str) -> tuple:
    """A sortable key of a version (semantic versioning: a pre-release sorts before its release,
    build metadata after '+' is ignored)."""
    m = VERSION_RE.match(v or "")
    if not m:
        raise UpdateError("version", f"not a version: {v!r}")
    pre = m.group(4)
    if pre is None:
        tail = (1,)                                        # a release sorts after its pre-releases
    else:
        tail = (0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) + tail


def newer(a: str, b: str) -> bool:
    """True if version a is newer than b. An unknown b (not a version): anything valid is newer."""
    try:
        kb = parse_version(b)
    except UpdateError:
        return True
    return parse_version(a) > kb


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_id(public_pem: Path) -> str:
    """16 hex characters naming a public key: the SHA-256 of its DER form."""
    der = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(public_pem), "-outform", "DER"],
                         capture_output=True, timeout=10)
    if der.returncode != 0:
        raise UpdateError("signature", f"not a public key: {public_pem.name}")
    return sha256(der.stdout)[:16]


def _members(path: Path) -> dict[str, bytes]:
    """manifest.json and manifest.sig of an update file (the payload stays in the file)."""
    try:
        with tarfile.open(path, "r:") as t:
            out = {}
            for name in ("manifest.json", "manifest.sig"):
                try:
                    info = t.getmember(name)
                except KeyError:
                    raise UpdateError("format", f"{path.name}: no {name}") from None
                if not info.isfile() or info.size > MAX_MANIFEST:
                    raise UpdateError("format", f"{path.name}: {name} is not a small file")
                out[name] = t.extractfile(info).read()
            return out
    except (tarfile.TarError, OSError) as e:
        raise UpdateError("format", f"{path.name}: not an update file ({e})") from None


def check_signature(data: bytes, sig: bytes, public_pem: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        d, s = Path(tmp) / "data", Path(tmp) / "sig"
        d.write_bytes(data)
        s.write_bytes(sig)
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_pem), "-rawin",
                            "-in", str(d), "-sigfile", str(s)], capture_output=True, timeout=10)
        return r.returncode == 0


def verify(path: Path, keys: list[Path]) -> dict:
    """The manifest of an update file whose signature one of `keys` (public PEM files) made and
    whose payload is the one it names; UpdateError otherwise."""
    path = Path(path)
    parts = _members(path)
    data, sig = parts["manifest.json"], parts["manifest.sig"]
    try:
        m = json.loads(data)
    except ValueError:
        raise UpdateError("format", "the manifest is not JSON") from None
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise UpdateError("format", f"unknown update format {m.get('format') if isinstance(m, dict) else '?'}")
    wanted = m.get("key_id")
    ids = {}
    for k in keys:
        try:
            ids[k] = key_id(k)
        except UpdateError:
            continue
    signers = [k for k, i in ids.items() if i == wanted]
    if not signers:
        raise UpdateError("signature", f"signed with a key this HU does not trust ({wanted})")
    if not check_signature(data, sig, signers[0]):
        raise UpdateError("signature", "the signature does not match")
    # signed: now the content can be believed
    if m.get("product") != PRODUCT:
        raise UpdateError("product", f"not an update for this HU ({m.get('product')})")
    parse_version(m.get("version", ""))
    parse_version(m.get("min_version", "0.0.0"))
    p = m.get("payload")
    if not isinstance(p, dict) or not isinstance(m.get("files"), dict):
        raise UpdateError("format", "the manifest has no payload or files")
    try:
        with tarfile.open(path, "r:") as t:
            info = t.getmember(p.get("file", ""))
            h = hashlib.sha256()
            f = t.extractfile(info)
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
    except (KeyError, tarfile.TarError, OSError) as e:
        raise UpdateError("format", f"the payload is missing ({e})") from None
    if info.size != p.get("size") or h.hexdigest() != p.get("sha256"):
        raise UpdateError("hash", "the payload is not the one the manifest names")
    return m


def _safe(name: str) -> bool:
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts


def unpack(path: Path, m: dict, dest: Path):
    """The payload of a verified update file into dest (must not exist): every file is checked
    against the manifest; only regular files and folders, no links, nothing outside dest."""
    dest = Path(dest)
    if dest.exists():
        raise UpdateError("io", f"{dest} exists")
    tmp = dest.with_name(dest.name + ".unpacking")
    shutil.rmtree(tmp, ignore_errors=True)
    files = m["files"]
    seen, total = set(), 0
    try:
        tmp.mkdir(parents=True)
        with tarfile.open(path, "r:") as outer:
            payload = outer.extractfile(outer.getmember(m["payload"]["file"])).read()
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as t:
            for info in t:
                if not _safe(info.name):
                    raise UpdateError("format", f"unsafe path in the payload: {info.name}")
                target = tmp / info.name
                if info.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not info.isfile():
                    raise UpdateError("format", f"not a regular file in the payload: {info.name}")
                total += info.size
                if total > MAX_PAYLOAD:
                    raise UpdateError("space", "the payload is too large")
                data = t.extractfile(info).read()
                if files.get(info.name) != sha256(data):
                    raise UpdateError("hash", f"{info.name} is not the file the manifest names")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o755 if info.mode & 0o111 else 0o644)
                seen.add(info.name)
        missing = set(files) - seen
        if missing:
            raise UpdateError("hash", f"{len(missing)} file(s) of the manifest are missing, e.g. {sorted(missing)[0]}")
        tmp.rename(dest)
    except UpdateError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except (tarfile.TarError, OSError, KeyError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise UpdateError("space" if isinstance(e, OSError) and e.errno == 28 else "io", f"unpacking failed: {e}") from None
