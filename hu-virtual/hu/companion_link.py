"""Companion app <-> headunit link protocol, v1 (decision D11).

The R80 Companion app on the driver's Android phone sends the turn-by-turn guidance
of the phone's navigation app to the headunit. On the target the transport is a
Bluetooth RFCOMM channel; in the virtual environment it is a local socket to the
phone emulator. Both sides only see a byte stream, so the same code runs on both.
The specification is docs/companion-protocol.md; keep this file and that document
in step, and keep all framing in this file.

Framing: one JSON object per line, UTF-8, ending in "\\n" (a "\\r" before it is
ignored). A line is at most MAX_LINE bytes; longer lines are dropped. Every object
has a "type". Unknown types and unknown fields are ignored, so later versions can
add both without breaking older peers. NaN and Infinity are not valid numbers.
"""
from __future__ import annotations

import json
import math

PROTO_VERSION = 1
SERVICE_UUID = "b4184390-fb7f-44db-9eaa-6985447914af"   # RFCOMM service record of the HU
MAX_LINE = 4096
MAX_TEXT = 200          # longer strings are cut, not rejected

# message types
HELLO = "hello"         # both ways, first message on a new connection
HEARTBEAT = "heartbeat"  # both ways, keeps the link alive
GUIDANCE = "guidance"   # phone -> HU, the whole current guidance state
BYE = "bye"             # both ways, the sender closes the link
TYPES = (HELLO, HEARTBEAT, GUIDANCE, BYE)

# guidance.maneuver
MANEUVERS = ("depart", "turn", "continue", "merge", "fork", "on_ramp", "off_ramp",
             "roundabout", "uturn", "arrive", "unknown")
MODIFIERS = ("straight", "slight_left", "left", "sharp_left", "slight_right", "right", "sharp_right")


class ProtocolError(ValueError):
    pass


class UnknownType(ProtocolError):
    """A message type this version does not know. Not an error of the peer: skip it."""


def _text(msg: dict, key: str, required: bool = False):
    v = msg.get(key)
    if v is None:
        if required:
            raise ProtocolError(f"{msg.get('type')}: '{key}' is missing")
        return None
    if not isinstance(v, str):
        raise ProtocolError(f"{msg.get('type')}: '{key}' must be a string")
    return v[:MAX_TEXT]


def _number(msg: dict, key: str, integer: bool = False, lo: float = 0, hi: float = math.inf):
    v = msg.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (integer and not isinstance(v, int)):
        raise ProtocolError(f"{msg.get('type')}: '{key}' must be {'an integer' if integer else 'a number'}")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ProtocolError(f"{msg.get('type')}: '{key}' = {v} is outside {lo}..{hi}")
    return v


def validate(msg) -> dict:
    """Check one decoded message; returns a copy with exactly the known fields of its type.
    Raises UnknownType for a type this version does not know, ProtocolError for a bad message."""
    if not isinstance(msg, dict):
        raise ProtocolError("a message must be a JSON object")
    t = msg.get("type")
    if not isinstance(t, str):
        raise ProtocolError("'type' is missing")
    if t not in TYPES:
        raise UnknownType(f"unknown type {t!r}")
    if t == HELLO:
        caps = msg.get("caps", [])
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise ProtocolError("hello: 'caps' must be a list of strings")
        proto = _number(msg, "proto", integer=True, lo=1, hi=65535)
        if proto is None:
            raise ProtocolError("hello: 'proto' is missing")
        return {"type": t, "proto": proto,
                "app": _text(msg, "app", required=True), "version": _text(msg, "version", required=True),
                "device": _text(msg, "device"), "caps": [c[:MAX_TEXT] for c in caps],
                "heartbeat_s": _number(msg, "heartbeat_s", lo=0.1, hi=3600)}
    if t == HEARTBEAT:
        return {"type": t}
    if t == BYE:
        return {"type": t, "reason": _text(msg, "reason")}
    # guidance
    active = msg.get("active")
    if not isinstance(active, bool):
        raise ProtocolError("guidance: 'active' must be true or false")
    if not active:
        return {"type": t, "active": False}
    m = msg.get("maneuver")
    if not isinstance(m, dict):
        raise ProtocolError("guidance: 'maneuver' must be an object")
    kind = m.get("type")
    if kind not in MANEUVERS:
        raise ProtocolError(f"guidance: maneuver type {kind!r} is not one of {', '.join(MANEUVERS)}")
    modifier = m.get("modifier")
    if modifier is not None and modifier not in MODIFIERS:
        raise ProtocolError(f"guidance: maneuver modifier {modifier!r} is not one of {', '.join(MODIFIERS)}")
    exit_no = _number({"type": t, **m}, "exit", integer=True, lo=1, hi=99)
    return {"type": t, "active": True, "source": _text(msg, "source", required=True),
            "maneuver": {"type": kind, "modifier": modifier, "exit": exit_no},
            "distance_m": _number(msg, "distance_m"), "street": _text(msg, "street"),
            "text": _text(msg, "text"), "remaining_m": _number(msg, "remaining_m"),
            "remaining_s": _number(msg, "remaining_s")}


def _reject_constant(name):
    raise ValueError(f"{name} is not a valid number")


def encode(msg: dict) -> bytes:
    """One message as one line. Validates first, so a peer never gets what we would reject."""
    clean = validate(msg)
    if clean["type"] == GUIDANCE and clean["active"]:
        clean["maneuver"] = {k: v for k, v in clean["maneuver"].items() if v is not None}
    line = json.dumps({k: v for k, v in clean.items() if v is not None},
                      ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(line) > MAX_LINE:
        raise ProtocolError(f"message is {len(line)} bytes, more than {MAX_LINE}")
    return line


class Decoder:
    """Feed raw bytes, get valid messages. Bad lines are counted in `errors` (last one in
    `last_error`) and dropped; messages of unknown types are counted in `unknown`."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._overlong = False
        self.errors = 0
        self.unknown = 0
        self.last_error = ""

    def feed(self, data: bytes) -> list[dict]:
        out = []
        start = 0
        while True:
            nl = data.find(b"\n", start)
            part = data[start:] if nl < 0 else data[start:nl]
            if not self._overlong:
                self._buf += part
                if len(self._buf) > MAX_LINE:
                    self._fail(f"line longer than {MAX_LINE} bytes")
                    self._buf.clear()
                    self._overlong = True
            if nl < 0:
                return out
            if not self._overlong:
                m = self._line(bytes(self._buf).rstrip(b"\r"))
                if m is not None:
                    out.append(m)
            self._buf.clear()
            self._overlong = False
            start = nl + 1

    def _line(self, line: bytes):
        if not line.strip():
            return None
        try:
            return validate(json.loads(line.decode(), parse_constant=_reject_constant))
        except UnknownType:
            self.unknown += 1
        except (ValueError, ProtocolError) as e:   # JSONDecodeError and UnicodeDecodeError are ValueErrors
            self._fail(str(e))
        return None

    def _fail(self, why: str):
        self.errors += 1
        self.last_error = why


# ---- message helpers --------------------------------------------------------

def hello(app: str, version: str, caps=(), device: str | None = None, heartbeat_s: float | None = None) -> dict:
    return {"type": HELLO, "proto": PROTO_VERSION, "app": app, "version": version,
            "device": device, "caps": list(caps), "heartbeat_s": heartbeat_s}


def heartbeat() -> dict:
    return {"type": HEARTBEAT}


def bye(reason: str | None = None) -> dict:
    return {"type": BYE, "reason": reason}


def guidance(source: str, maneuver: str, modifier: str | None = None, exit: int | None = None,
             distance_m: float | None = None, street: str | None = None, text: str | None = None,
             remaining_m: float | None = None, remaining_s: float | None = None) -> dict:
    return {"type": GUIDANCE, "active": True, "source": source,
            "maneuver": {"type": maneuver, "modifier": modifier, "exit": exit},
            "distance_m": distance_m, "street": street, "text": text,
            "remaining_m": remaining_m, "remaining_s": remaining_s}


def guidance_ended() -> dict:
    return {"type": GUIDANCE, "active": False}
