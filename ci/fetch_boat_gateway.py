#!/usr/bin/env python3
"""Fetch boat_gateway for one BoAt commit from BoAt's public container image, without Docker.

    python3 ci/fetch_boat_gateway.py <commit sha> <dest file>

BoAt's CI pushes ghcr.io/alextech-stack/boat:ci-<full sha> for every master commit
whose CI passed (built from boat-platform/Dockerfile.runtime, linux/amd64 + arm64).
This reads the image for this machine (linux/amd64 or linux/arm64) over the registry API
and extracts
/usr/local/bin/boat_gateway. Exit 2 if there is no image for that commit (yet),
exit 3 if the binary is not built for this machine (AlexTech-stack/BoAt#51: the arm64
image carries the x86-64 binary).

Standard library only.
"""
from __future__ import annotations

import io
import json
import os
import platform
import sys
import tarfile
import urllib.error
import urllib.request

REGISTRY = "https://ghcr.io"
IMAGE = os.environ.get("BOAT_IMAGE", "alextech-stack/boat")
MEMBER = "usr/local/bin/boat_gateway"
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
ARCH = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine(), platform.machine())
# ELF e_machine values, to check what the image really contains.
ELF_MACHINE = {0x3E: "amd64", 0xB7: "arm64"}


def get(url: str, token: str, accept: str = ACCEPT) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": accept})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    sha, dest = sys.argv[1], sys.argv[2]
    tag = f"ci-{sha}"
    with urllib.request.urlopen(f"{REGISTRY}/token?scope=repository:{IMAGE}:pull", timeout=30) as r:
        token = json.load(r)["token"]
    try:
        manifest = json.loads(get(f"{REGISTRY}/v2/{IMAGE}/manifests/{tag}", token))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"no image {IMAGE}:{tag}")
            return 2
        raise
    if "manifests" in manifest:  # multi-arch index: pick our platform
        entry = next((m for m in manifest["manifests"]
                      if m.get("platform", {}).get("os") == "linux"
                      and m.get("platform", {}).get("architecture") == ARCH), None)
        if entry is None:
            print(f"{IMAGE}:{tag} has no linux/{ARCH} image")
            return 2
        manifest = json.loads(get(f"{REGISTRY}/v2/{IMAGE}/manifests/{entry['digest']}", token))
    # The COPY of the gateway is one of the last layers, so search from the top.
    for layer in reversed(manifest["layers"]):
        blob = get(f"{REGISTRY}/v2/{IMAGE}/blobs/{layer['digest']}", token, accept="*/*")
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tar:
            try:
                f = tar.extractfile(MEMBER)
            except KeyError:
                continue
            data = f.read()
        got = ELF_MACHINE.get(int.from_bytes(data[18:20], "little"), "unknown") if data[:4] == b"\x7fELF" else "not ELF"
        if got != ARCH:
            print(f"{IMAGE}:{tag} linux/{ARCH} contains a {got} boat_gateway, not {ARCH} (AlexTech-stack/BoAt#51)")
            return 3
        with open(dest, "wb") as out:
            out.write(data)
        os.chmod(dest, 0o755)
        print(f"boat_gateway from {IMAGE}:{tag} (linux/{ARCH}) -> {dest}")
        return 0
    print(f"{IMAGE}:{tag} does not contain /{MEMBER}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
