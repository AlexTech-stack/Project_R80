#!/usr/bin/env python3
"""Poke the MCU emulator: turn the knob, press buttons, override dimming.

    mcuctl.py status
    mcuctl.py knob 1          # one detent clockwise (-1 = counter-clockwise)
    mcuctl.py push            # press the knob
    mcuctl.py tilt -1         # push the knob sideways
    mcuctl.py button HOME     # HOME BACK NAV MEDIA RADIO PHONE CAR SETUP VOL_UP VOL_DOWN MUTE
    mcuctl.py dim 30          # force display level 0..100, "auto" = follow LightState
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

DEFAULT_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-mcu.sock"


def call(cmd: dict, sock_path: str | os.PathLike = None) -> dict:
    """Send one command to the MCU emulator and return its JSON reply."""
    path = str(sock_path or os.environ.get("R80_MCU_SOCK", DEFAULT_SOCK))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        s.connect(path)
        s.sendall((json.dumps(cmd) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, *rest = argv
    c = {"cmd": cmd}
    if cmd in ("knob", "tilt"):
        c["value"] = int(rest[0]) if rest else 1
    elif cmd == "button":
        c["name"] = rest[0]
    elif cmd == "dim":
        c["level"] = rest[0]
    reply = call(c)
    print(json.dumps(reply, indent=2))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
