"""A DLT client (AUTOSAR Diagnostic Log and Trace, protocol version 1), standard library only.

What hu-sysd reads from the HU's DLT daemon (Settings -> System -> Diagnostics), and what
the tests and the export use to read DLT files. Over TCP the daemon sends the messages
without a storage header; a file has one in front of every message ("DLT"+0x01, time,
ECU ID).

    parser = Parser()                      # Parser(storage=True) for a .dlt file
    for m in parser.feed(data):            # bytes as they come; complete messages out
        m.apid, m.ctid, m.level, m.text    # a log message: level 1 fatal ... 6 verbose
        m.service, m.status, m.data        # a control response
    sock.send(set_log_level("MED", "", 5)) # "" = every context of the application
    sock.send(get_log_info())              # -> responses: log_info(m.data)
    sock.send(store_configuration())       # the daemon keeps the levels across restarts

The layout: standard header (HTYP, MCNT, LEN, then ECU ID, session ID, timestamp as HTYP
says), extended header (MSIN, NOAR, APID, CTID), payload: verbose arguments (type info +
value) or, for control messages, the service ID and its fields.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

UEH, MSBF, WEID, WSID, WTMS = 0x01, 0x02, 0x04, 0x08, 0x10
VERSION = 1
TYPE_LOG, TYPE_CONTROL = 0, 3
CONTROL_REQUEST, CONTROL_RESPONSE = 1, 2
SET_LOG_LEVEL, GET_LOG_INFO, STORE_CONFIG = 0x01, 0x03, 0x05
LEVELS = ("off", "fatal", "error", "warning", "info", "debug", "verbose")
STORAGE_PATTERN = b"DLT\x01"
# verbose type info bits
BOOL, SINT, UINT, FLOA, STRG, RAWD = 0x10, 0x20, 0x40, 0x80, 0x200, 0x400
VARI, FIXP = 0x800, 0x1000


@dataclass
class Message:
    ecu: str = ""
    apid: str = ""
    ctid: str = ""
    kind: int = TYPE_LOG             # MSTP: 0 log, 3 control
    subtype: int = 0                 # MTIN: the log level, or 1 request / 2 response
    timestamp: float = -1.0          # s since the ECU started (0.1 ms steps); -1: not sent
    time: float = -1.0               # unix s from the storage header (files only)
    text: str = ""                   # a log message's arguments, joined by spaces
    service: int = -1                # a control message's service ID
    status: int = -1                 # ... and a response's status: 0 ok, 1 not supported, 2 error
    data: bytes = field(default=b"", repr=False)    # a control response's fields after the status
    big_endian: bool = False

    @property
    def level(self) -> int:
        return self.subtype if self.kind == TYPE_LOG else 0


def _id(raw: bytes) -> str:
    return raw.rstrip(b"\0").decode("ascii", "replace")


def _args(payload: bytes, count: int, big: bool) -> str:
    """The verbose arguments as text (strings, numbers, bools; raw data as hex)."""
    e = ">" if big else "<"
    out, pos = [], 0
    for _ in range(count):
        if pos + 4 > len(payload):
            break
        ti = struct.unpack_from(e + "I", payload, pos)[0]
        pos += 4
        tyle = ti & 0x0F
        size = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}.get(tyle, 0)
        if ti & VARI:                                  # name (and unit) in front of the value: skip
            n = struct.unpack_from(e + "H", payload, pos)[0]
            u = struct.unpack_from(e + "H", payload, pos + 2)[0] if ti & (SINT | UINT | FLOA) else 0
            pos += 2 + (2 if ti & (SINT | UINT | FLOA) else 0) + n + u
        if ti & (STRG | RAWD):
            n = struct.unpack_from(e + "H", payload, pos)[0]
            raw = payload[pos + 2:pos + 2 + n]
            pos += 2 + n
            out.append(raw.rstrip(b"\0").decode("utf-8", "replace") if ti & STRG else raw.hex(" "))
        elif ti & BOOL:
            out.append("true" if payload[pos] else "false")
            pos += 1
        elif ti & (SINT | UINT) and size:
            fmt = {1: "b", 2: "h", 4: "i", 8: "q"}.get(size)
            if fmt is None:
                pos += size
                continue
            out.append(str(struct.unpack_from(e + (fmt if ti & SINT else fmt.upper()), payload, pos)[0]))
            pos += size
        elif ti & FLOA and size in (4, 8):
            out.append(f"{struct.unpack_from(e + ('f' if size == 4 else 'd'), payload, pos)[0]:g}")
            pos += size
        else:                                          # a type this client does not show
            break
    return " ".join(out)


def parse(msg: bytes) -> Message:
    """One message: standard header, extended header and payload (no storage header)."""
    htyp = msg[0]
    m = Message(big_endian=bool(htyp & MSBF))
    pos = 4
    if htyp & WEID:
        m.ecu = _id(msg[pos:pos + 4])
        pos += 4
    if htyp & WSID:
        pos += 4
    if htyp & WTMS:
        m.timestamp = struct.unpack_from(">I", msg, pos)[0] / 10000
        pos += 4
    count = 0
    verbose = False
    if htyp & UEH:
        msin, count = msg[pos], msg[pos + 1]
        m.apid, m.ctid = _id(msg[pos + 2:pos + 6]), _id(msg[pos + 6:pos + 10])
        verbose = bool(msin & 1)
        m.kind, m.subtype = (msin >> 1) & 0x07, (msin >> 4) & 0x0F
        pos += 10
    payload = msg[pos:]
    if m.kind == TYPE_CONTROL and len(payload) >= 4:
        e = ">" if m.big_endian else "<"
        m.service = struct.unpack_from(e + "I", payload, 0)[0]
        if m.subtype == CONTROL_RESPONSE and len(payload) >= 5:
            m.status, m.data = payload[4], payload[5:]
        else:
            m.data = payload[4:]
    elif verbose:
        m.text = _args(payload, count, m.big_endian)
    elif len(payload) >= 4:                            # non-verbose: a message ID and its data
        m.text = f"[{struct.unpack_from('<I', payload, 0)[0]}] {payload[4:].hex(' ')}"
    return m


class Parser:
    """Splits a byte stream (TCP, or a file with storage=True) into messages; resyncs on junk."""

    def __init__(self, storage: bool = False):
        self.storage = storage
        self.buf = b""
        self.skipped = 0

    def feed(self, data: bytes) -> list[Message]:
        self.buf += data
        out = []
        while True:
            m = self._next()
            if m is None:
                return out
            out.append(m)

    def _next(self):
        b = self.buf
        stamp = None
        if self.storage:
            i = b.find(STORAGE_PATTERN)
            if i < 0:
                self.skipped += max(0, len(b) - 3)
                self.buf = b[-3:]
                return None
            if i:
                self.skipped += i
                b = self.buf = b[i:]
            if len(b) < 16 + 4:
                return None
            secs, usecs = struct.unpack_from("<Ii", b, 4)
            stamp = (secs + usecs / 1e6, _id(b[12:16]))
            b = b[16:]
        if len(b) < 4:
            return None
        if (b[0] >> 5) & 0x07 != VERSION or struct.unpack_from(">H", b, 2)[0] < 4:
            self.skipped += 1                              # not a message start: look further
            self.buf = self.buf[1:]
            return self._next()
        n = struct.unpack_from(">H", b, 2)[0]
        if len(b) < n:
            return None
        m = parse(b[:n])
        if stamp:
            m.time = stamp[0]
            m.ecu = m.ecu or stamp[1]
        self.buf = b[n:]
        return m


def _control(service: int, body: bytes = b"") -> bytes:
    payload = struct.pack("<I", service) + body
    ext = bytes([(TYPE_CONTROL << 1) | (CONTROL_REQUEST << 4), 0]) + b"APP\0" + b"CON\0"
    head_len = 4 + 4 + len(ext)
    return bytes([UEH | WEID | (VERSION << 5), 0]) + struct.pack(">H", head_len + len(payload)) + b"R80\0" + ext + payload


def _pad(s: str) -> bytes:
    return s.encode("ascii")[:4].ljust(4, b"\0")


def set_log_level(apid: str, ctid: str, level: int) -> bytes:
    """Set Log Level (0x01); ctid "" = all contexts of apid; level -1 = the default."""
    return _control(SET_LOG_LEVEL, _pad(apid) + _pad(ctid) + struct.pack("<b", level) + b"remo")


def get_log_info() -> bytes:
    """Get Log Info (0x03), option 7: every application and context with level, trace status, descriptions."""
    return _control(GET_LOG_INFO, bytes([7]) + b"\0" * 8 + b"remo")


def store_configuration() -> bytes:
    return _control(STORE_CONFIG)


def log_info(data: bytes, big: bool = False) -> dict:
    """The fields of a Get Log Info response (option 7, status 7):
    {apid: {"description": str, "contexts": {ctid: {"level": int (-1 default), "description": str}}}}"""
    e = ">" if big else "<"
    out: dict = {}
    try:
        (apps,), pos = struct.unpack_from(e + "H", data, 0), 2
        for _ in range(apps):
            apid = _id(data[pos:pos + 4])
            (ctxs,) = struct.unpack_from(e + "H", data, pos + 4)
            pos += 6
            contexts = {}
            for _ in range(ctxs):
                ctid = _id(data[pos:pos + 4])
                level = struct.unpack_from("b", data, pos + 4)[0]
                (n,) = struct.unpack_from(e + "H", data, pos + 6)
                contexts[ctid] = {"level": level, "description": data[pos + 8:pos + 8 + n].decode("utf-8", "replace")}
                pos += 8 + n
            (n,) = struct.unpack_from(e + "H", data, pos)
            out[apid] = {"description": data[pos + 2:pos + 2 + n].decode("utf-8", "replace"), "contexts": contexts}
            pos += 2 + n
    except struct.error:
        pass
    return out


def read_file(path) -> list[Message]:
    with open(path, "rb") as f:
        return Parser(storage=True).feed(f.read())
