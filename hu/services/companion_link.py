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
RFCOMM_CHANNEL = 22      # fixed, so BlueZ puts it into the service record (phones look it up by UUID)
MAX_LINE = 4096
MAX_TEXT = 200          # longer strings are cut, not rejected

# message types
HELLO = "hello"         # both ways, first message on a new connection
HEARTBEAT = "heartbeat"  # both ways, keeps the link alive
GUIDANCE = "guidance"   # phone -> HU, the whole current guidance state
BYE = "bye"             # both ways, the sender closes the link
WEATHER = "weather"     # phone -> HU, the weather where the phone is (from an internet service)
POSITION = "position"   # phone -> HU, the altitude (never coordinates)
CAR_STATUS = "car_status"   # HU -> phone, how the car is (also when parked)
TYPES = (HELLO, HEARTBEAT, GUIDANCE, BYE, WEATHER, POSITION, CAR_STATUS)
MAX_DAYS = 7
MAX_WARNINGS = 10
SEVERITIES = ("warning", "information", "notice")

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
    if t == WEATHER:
        return _weather(msg)
    if t == CAR_STATUS:
        return _car_status(msg)
    if t == POSITION:
        when = _number(msg, "time", integer=True, lo=0, hi=2**40)
        if when is None:
            raise ProtocolError("position: 'time' is missing")
        return {"type": t, "time": when, "alt_m": _number(msg, "alt_m", lo=-500, hi=9000),
                "accuracy_m": _number(msg, "accuracy_m"), "heading_deg": _number(msg, "heading_deg", lo=0, hi=360)}
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


def _weather(msg: dict) -> dict:
    t = msg["type"]
    when = _number(msg, "time", integer=True, lo=0, hi=2**40)
    if when is None:
        raise ProtocolError("weather: 'time' is missing")
    now = msg.get("now")
    if not isinstance(now, dict):
        raise ProtocolError("weather: 'now' must be an object")
    temp = _number({"type": t, **now}, "temp_c", lo=-100, hi=100)
    code = _number({"type": t, **now}, "code", integer=True, lo=0, hi=99)
    if temp is None or code is None:
        raise ProtocolError("weather: 'now' needs temp_c and code")
    days = msg.get("days", [])
    if not isinstance(days, list) or not all(isinstance(d, dict) for d in days):
        raise ProtocolError("weather: 'days' must be a list of objects")
    out_days = []
    for d in days[:MAX_DAYS]:
        date = _text({"type": t, **d}, "date", required=True)
        if len(date) != 10 or date[4] != "-" or date[7] != "-" or not (date[:4] + date[5:7] + date[8:]).isdigit():
            raise ProtocolError(f"weather: date {date!r} is not YYYY-MM-DD")
        day = {"date": date, "code": _number({"type": t, **d}, "code", integer=True, lo=0, hi=99),
               "max_c": _number({"type": t, **d}, "max_c", lo=-100, hi=100),
               "min_c": _number({"type": t, **d}, "min_c", lo=-100, hi=100)}
        if None in day.values():
            raise ProtocolError("weather: a day needs date, code, max_c and min_c")
        out_days.append(day)
    return {"type": t, "source": _text(msg, "source", required=True), "time": when,
            "now": {"temp_c": temp, "code": code}, "days": out_days}


def _car_status(msg: dict) -> dict:
    t = msg["type"]
    when = _number(msg, "time", integer=True, lo=0, hi=2**40)
    final = msg.get("final")
    if when is None or not isinstance(final, bool):
        raise ProtocolError("car_status: 'time' and 'final' are required")
    out = {"type": t, "time": when, "final": final,
           "fuel_pct": _number(msg, "fuel_pct", hi=100), "range_km": _number(msg, "range_km"),
           "odometer_km": _number(msg, "odometer_km"), "battery_v": _number(msg, "battery_v", hi=100),
           "outside_c": _number(msg, "outside_c", lo=-100, hi=100),
           "service_km": _number(msg, "service_km", lo=-1e6, hi=1e6),
           "service_days": _number(msg, "service_days", lo=-1e5, hi=1e5), "accent": _text(msg, "accent")}
    trip = msg.get("trip")
    if trip is not None:
        if not isinstance(trip, dict):
            raise ProtocolError("car_status: 'trip' must be an object")
        tt = {"type": t, **trip}
        out["trip"] = {"km": _number(tt, "km"), "minutes": _number(tt, "minutes"), "avg_kmh": _number(tt, "avg_kmh")}
    warnings = msg.get("warnings")
    if warnings is not None:
        if not isinstance(warnings, list) or not all(isinstance(w, dict) for w in warnings):
            raise ProtocolError("car_status: 'warnings' must be a list of objects")
        out["warnings"] = []
        for w in warnings[:MAX_WARNINGS]:
            if w.get("severity") not in SEVERITIES:
                raise ProtocolError(f"car_status: severity {w.get('severity')!r} is not one of {', '.join(SEVERITIES)}")
            out["warnings"].append({"severity": w["severity"], "text": _text({"type": t, **w}, "text", required=True)})
    return out


def _reject_constant(name):
    raise ValueError(f"{name} is not a valid number")


def encode(msg: dict) -> bytes:
    """One message as one line. Validates first, so a peer never gets what we would reject."""
    clean = validate(msg)
    if clean["type"] == GUIDANCE and clean["active"]:
        clean["maneuver"] = {k: v for k, v in clean["maneuver"].items() if v is not None}
    if clean["type"] == CAR_STATUS and "trip" in clean:
        clean["trip"] = {k: v for k, v in clean["trip"].items() if v is not None}
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


def weather(source: str, time: int, temp_c: float, code: int, days=()) -> dict:
    """days: (date, code, max_c, min_c) tuples, today first."""
    return {"type": WEATHER, "source": source, "time": time, "now": {"temp_c": temp_c, "code": code},
            "days": [{"date": d, "code": c, "max_c": hi, "min_c": lo} for d, c, hi, lo in days]}


def car_status(time: int, final: bool = False, **values) -> dict:
    """values: fuel_pct, range_km, odometer_km, battery_v, outside_c, service_km, service_days,
    trip ({km, minutes, avg_kmh}), warnings ([{severity, text}]), accent; None = not known."""
    return {"type": CAR_STATUS, "time": time, "final": final, **values}


def position(time: int, alt_m: float | None = None, accuracy_m: float | None = None,
             heading_deg: float | None = None) -> dict:
    return {"type": POSITION, "time": time, "alt_m": alt_m, "accuracy_m": accuracy_m, "heading_deg": heading_deg}
