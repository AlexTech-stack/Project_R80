"""MCU <-> Linux link protocol (placeholder v0).

The always-on vehicle MCU talks to the Linux computer over a UART. On the
bench that is a real serial port (e.g. /dev/ttyAMA0 on a Raspberry Pi); in the
virtual environment it is a pseudo-terminal created by the MCU emulator. Both
sides only see a byte stream, so the same code runs on both.

    NOTE: this protocol is a stand-in until it is aligned with the HU
    architecture doc (hu-architecture v0.3). Keep all framing in this file so
    it can be swapped in one place.

Framing (HDLC-like):

    0x7E | escape( type:u8  seq:u8  len:u8  payload[len]  crc16:u16le ) | 0x7E

    escape: 0x7E -> 0x7D 0x5E, 0x7D -> 0x7D 0x5D
    crc16:  CRC-16/CCITT-FALSE over type..payload
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

PROTO_VERSION = 0

# MCU -> Linux
HELLO = 0x01          # proto:u8, fw:str
HEARTBEAT = 0x02      # uptime_ms:u32
CAN_RX = 0x10         # bus:u8, can_id:u32 (bit31 = extended), dlc:u8, data
POWER = 0x20          # state:u8
INPUT = 0x30          # event:u8, value:i8
DIM = 0x40            # level:u8 (0..100), night:u8

# Linux -> MCU
HOST_HELLO = 0x81     # proto:u8, sw:str
HOST_HEARTBEAT = 0x82
CAN_TX = 0x90         # bus:u8, can_id:u32, dlc:u8, data  (MCU only forwards on INFO)
SHUTDOWN_READY = 0xA0

BUS_MOTOR, BUS_INFO, BUS_COMFORT = 0, 1, 2
BUS_NAMES = {BUS_MOTOR: "motor", BUS_INFO: "info", BUS_COMFORT: "comfort"}

POWER_OFF, POWER_STANDBY, POWER_ACC, POWER_ON, POWER_CRANK = range(5)
POWER_NAMES = {POWER_OFF: "off", POWER_STANDBY: "standby", POWER_ACC: "acc",
               POWER_ON: "on", POWER_CRANK: "crank"}

# INPUT events. KNOB_TURN/KNOB_TILT carry a signed step, BUTTON carries a button id.
KNOB_TURN, KNOB_PUSH, KNOB_TILT, BUTTON = 1, 2, 3, 4
BUTTONS = {1: "HOME", 2: "BACK", 3: "NAV", 4: "MEDIA", 5: "RADIO", 6: "PHONE",
           7: "CAR", 8: "SETUP", 9: "VOL_UP", 10: "VOL_DOWN", 11: "MUTE"}
BUTTON_IDS = {v: k for k, v in BUTTONS.items()}

CAN_EFF_FLAG = 0x80000000

_FLAG, _ESC = 0x7E, 0x7D


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode(msg_type: int, seq: int, payload: bytes = b"") -> bytes:
    body = bytes([msg_type, seq & 0xFF, len(payload)]) + payload
    body += struct.pack("<H", crc16(body))
    out = bytearray([_FLAG])
    for b in body:
        if b in (_FLAG, _ESC):
            out += bytes([_ESC, b ^ 0x20])
        else:
            out.append(b)
    out.append(_FLAG)
    return bytes(out)


@dataclass
class Message:
    type: int
    seq: int
    payload: bytes


class Decoder:
    """Feed raw bytes, get complete messages. Bad CRCs are counted and dropped."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._esc = False
        self.crc_errors = 0

    def feed(self, data: bytes) -> list[Message]:
        out = []
        for b in data:
            if b == _FLAG:
                if len(self._buf) >= 5:
                    m = self._finish(bytes(self._buf))
                    if m:
                        out.append(m)
                self._buf.clear()
                self._esc = False
            elif b == _ESC:
                self._esc = True
            else:
                self._buf.append(b ^ 0x20 if self._esc else b)
                self._esc = False
        return out

    def _finish(self, body: bytes):
        data, (crc,) = body[:-2], struct.unpack("<H", body[-2:])
        if crc16(data) != crc or data[2] != len(data) - 3:
            self.crc_errors += 1
            return None
        return Message(data[0], data[1], data[3:])


# ---- payload helpers ----------------------------------------------------------

def pack_can(bus: int, can_id: int, data: bytes) -> bytes:
    return struct.pack("<BIB", bus, can_id, len(data)) + bytes(data)


def unpack_can(p: bytes) -> tuple[int, int, bytes]:
    bus, can_id, dlc = struct.unpack_from("<BIB", p)
    return bus, can_id, p[6:6 + dlc]


def open_serial(path: str, baud: int = 921600) -> int:
    """Open a serial port (or pty) raw and non-blocking; returns the fd."""
    import os
    import termios
    import tty
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    speed = getattr(termios, f"B{baud}", termios.B115200)
    attrs[4] = attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd
