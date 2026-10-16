"""Minimal DBC reader for the headunit (no third-party dependencies).

Covers what the R80 databases use: BO_, SG_ (Intel and Motorola, signed and
unsigned, no multiplexing), VAL_ value tables and GenMsgCycleTime. Enough to
decode and encode classic CAN frames; swap for cantools if the real DBC needs more.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
_SG = re.compile(r"^\s*SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
                 r"\(([^,]+),([^)]+)\)\s*\[([^|]+)\|([^\]]+)\]\s*\"([^\"]*)\"")
_VAL = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*);")
_CYCLE = re.compile(r'^BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;')

CAN_EFF_FLAG = 0x80000000


@dataclass
class Signal:
    name: str
    start: int
    length: int
    intel: bool
    signed: bool
    factor: float
    offset: float
    minimum: float
    maximum: float
    unit: str
    choices: dict[int, str] = field(default_factory=dict)

    def _bits(self):
        """Yield (byte, bit) positions from LSB to MSB of the raw value."""
        if self.intel:
            for i in range(self.length):
                p = self.start + i
                yield p // 8, p % 8
        else:
            pos = []
            p = self.start
            for _ in range(self.length):
                pos.append((p // 8, p % 8))
                p = p - 1 if p % 8 else p + 15
            yield from reversed(pos)

    def decode(self, data: bytes):
        raw = 0
        for i, (byte, bit) in enumerate(self._bits()):
            if byte < len(data) and data[byte] >> bit & 1:
                raw |= 1 << i
        if self.signed and raw & (1 << (self.length - 1)):
            raw -= 1 << self.length
        if raw in self.choices:
            return self.choices[raw]
        return raw * self.factor + self.offset

    def encode_into(self, buf: bytearray, value) -> None:
        if isinstance(value, str):
            raw = next(k for k, v in self.choices.items() if v == value)
        else:
            raw = round((value - self.offset) / self.factor)
        raw &= (1 << self.length) - 1
        for i, (byte, bit) in enumerate(self._bits()):
            if raw >> i & 1:
                buf[byte] |= 1 << bit
            else:
                buf[byte] &= ~(1 << bit) & 0xFF


@dataclass
class Message:
    frame_id: int          # without the extended flag
    extended: bool
    name: str
    dlc: int
    sender: str
    cycle_ms: int = 0
    signals: list[Signal] = field(default_factory=list)

    def decode(self, data: bytes) -> dict:
        return {s.name: s.decode(data) for s in self.signals}

    def encode(self, values: dict) -> bytes:
        buf = bytearray(self.dlc)
        for s in self.signals:
            if s.name in values:
                s.encode_into(buf, values[s.name])
        return bytes(buf)


class Database:
    def __init__(self, path: str):
        self.messages: list[Message] = []
        by_raw: dict[int, Message] = {}
        cur = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if m := _BO.match(line):
                    raw = int(m[1])
                    cur = Message(raw & 0x1FFFFFFF, bool(raw & CAN_EFF_FLAG), m[2], int(m[3]), m[4])
                    self.messages.append(cur)
                    by_raw[raw] = cur
                elif (m := _SG.match(line)) and cur:
                    cur.signals.append(Signal(m[1], int(m[2]), int(m[3]), m[4] == "1", m[5] == "-",
                                              float(m[6]), float(m[7]), float(m[8]), float(m[9]), m[10]))
                elif m := _VAL.match(line):
                    msg = by_raw.get(int(m[1]))
                    pairs = re.findall(r'(-?\d+)\s+"([^"]*)"', m[3])
                    for s in (msg.signals if msg else []):
                        if s.name == m[2]:
                            s.choices = {int(k): v for k, v in pairs}
                elif m := _CYCLE.match(line):
                    if msg := by_raw.get(int(m[1])):
                        msg.cycle_ms = int(m[2])
                elif not line.strip():
                    cur = None
        self._by_key = {(m.frame_id, m.extended): m for m in self.messages}

    def get(self, frame_id: int, extended: bool):
        return self._by_key.get((frame_id, extended))
