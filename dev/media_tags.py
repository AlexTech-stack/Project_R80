#!/usr/bin/env python3
"""Test media for the R80 headunit: ID3v2.3 tags with a cover drawn in code (PC only).

Writes title, artist, album, track number and an embedded front cover (PNG) in
front of an audio file. GStreamer's id3demux reads such a tag in front of any
format, so the BoAt tests tag plain WAV tones with it; MP3 is the usual case.
The covers are simple generated pictures (no third-party images, AGENTS.md 6).
Standard library only.

    python3 dev/media_tags.py tag song.mp3 --title "Let Go" --artist "Someone" \\
        --album "Night Drive" --track 2 --cover sun
    python3 dev/media_tags.py cover sun cover.png      # only the picture
    python3 dev/media_tags.py show song.mp3            # what the file's tag holds
    python3 dev/media_tags.py library DIR              # the test library of the virtual HU

The test library (dev/hu-virtual.sh and ci/dut/start_dut.sh play it; the BoAt
tests check what mediad reads from it), short tones of 20 to 28 s:

    Blue Roads/cover.png                      folder cover
    Blue Roads/Marta Kovac - Coastline.wav    no tag: artist and title from the name,
    Blue Roads/Marta Kovac - Low Tide.wav       album from the folder
    Neon Autobahn - Night Drive.wav           no tag, no cover
    Night Drive/01.wav, 02.wav                ID3: title, artist, album, track, embedded cover
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
import zlib
from array import array
from pathlib import Path

COVER_SIZE = 320
STYLES = ("sun", "waves", "rings", "road", "void", "grid")


# ---- covers ----------------------------------------------------------------
def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _pixel(style: str, x: float, y: float):
    """Colour at (x, y) in 0..1 for one cover style."""
    if style == "sun":          # sun over water, cut by horizontal stripes
        sky = _mix((40, 10, 60), (230, 90, 40), y)
        d = math.hypot(x - 0.5, y - 0.45)
        if d < 0.28:
            cut = y > 0.45 and int((y - 0.45) * 60) % 3 == 0
            return sky if cut else _mix((255, 210, 60), (240, 80, 50), (y - 0.17) / 0.56)
        return sky if y < 0.72 else _mix((20, 30, 70), (10, 10, 30), (y - 0.72) / 0.28)
    if style == "waves":        # sea lines
        k = math.sin(x * 14 + math.sin(y * 9) * 2) * 0.02
        band = int((y + k) * 18) % 2
        return _mix((10, 70, 120), (200, 230, 240), y) if band else (15, 40, 70)
    if style == "rings":        # concentric circles
        d = math.hypot(x - 0.5, y - 0.5)
        return (240, 240, 230) if int(d * 22) % 2 else _mix((200, 30, 60), (30, 20, 40), d * 1.4)
    if style == "road":         # perspective road with a dashed centre line
        if y < 0.4:
            return _mix((90, 160, 220), (250, 200, 150), y / 0.4)
        half = 0.05 + (y - 0.4) * 0.75
        if abs(x - 0.5) < half:
            line = abs(x - 0.5) < 0.004 + (y - 0.4) * 0.03 and int(math.log(y - 0.39) * 12) % 2
            return (250, 250, 250) if line else (60, 60, 65)
        return (40, 120, 50)
    if style == "void":         # dark field with an off-centre glow and echo rings
        d = math.hypot(x - 0.62, y - 0.38)
        glow = max(0.0, 1 - d * 2.2)
        ring = 0.5 if 0.012 > abs((d * 9) % 1 - 0.5) / 9 else 0
        v = min(1.0, glow ** 2 + ring * (1 - d))
        return _mix((5, 5, 20), (170, 140, 255), v)
    if style == "grid":         # squares in a checker of two colours
        return (250, 180, 0) if (int(x * 8) + int(y * 8)) % 2 else (20, 20, 20)
    raise ValueError(f"unknown cover style {style!r} (one of {', '.join(STYLES)})")


def cover(style: str, size: int = COVER_SIZE) -> bytes:
    """A square PNG cover in one of STYLES."""
    rows = []
    for j in range(size):
        y = (j + 0.5) / size
        rows.append(bytes(c for i in range(size) for c in _pixel(style, (i + 0.5) / size, y)))
    return _png(size, size, rows)


# ---- ID3v2.3 ---------------------------------------------------------------
def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _frame(fid: str, data: bytes) -> bytes:
    return fid.encode() + struct.pack(">I", len(data)) + b"\x00\x00" + data


def _text(fid: str, value: str) -> bytes:
    return _frame(fid, b"\x01" + value.encode("utf-16"))          # UTF-16 with BOM


def strip_id3(data: bytes) -> bytes:
    """The audio without a leading ID3v2 tag (if there is one)."""
    if data[:3] != b"ID3" or len(data) < 10:
        return data
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    footer = 10 if data[5] & 0x10 else 0
    return data[10 + size + footer:]


def build_id3(title: str = "", artist: str = "", album: str = "", track: int = 0,
              total: int = 0, png: bytes | None = None, comment: str = "") -> bytes:
    frames = b""
    for fid, value in (("TIT2", title), ("TPE1", artist), ("TALB", album)):
        if value:
            frames += _text(fid, value)
    if track:
        frames += _text("TRCK", f"{track}/{total}" if total else str(track))
    if comment:
        frames += _frame("COMM", b"\x00eng\x00" + comment.encode("latin-1", "replace"))
    if png:
        frames += _frame("APIC", b"\x00image/png\x00\x03\x00" + png)    # 3 = front cover
    return b"ID3\x03\x00\x00" + _syncsafe(len(frames)) + frames


def tag(path: Path, **tags) -> None:
    """Replace the file's ID3v2 tag (title, artist, album, track, total, png, comment)."""
    audio = strip_id3(path.read_bytes())
    path.write_bytes(build_id3(**tags) + audio)


def show(path: Path) -> dict:
    """The text frames and the cover size of a file's ID3v2.3 tag."""
    data = path.read_bytes()
    out = {}
    if data[:3] != b"ID3":
        return out
    end = 10 + ((data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9])
    i = 10
    while i + 10 <= end and data[i:i + 4].strip(b"\x00"):
        fid = data[i:i + 4].decode("latin-1")
        n = struct.unpack(">I", data[i + 4:i + 8])[0]
        body = data[i + 10:i + 10 + n]
        if fid.startswith("T"):
            out[fid] = body[1:].decode("utf-16" if body[0] == 1 else "latin-1").rstrip("\x00")
        elif fid == "APIC":
            out[fid] = f"{len(body)} bytes"
        i += 10 + n
    return out


# ---- the test library -----------------------------------------------------
LIBRARY = [  # path, frequency (divides 44100), seconds, tags or None
    ("Blue Roads/Marta Kovac - Coastline.wav", 245, 22, None),
    ("Blue Roads/Marta Kovac - Low Tide.wav", 210, 20, None),
    ("Neon Autobahn - Night Drive.wav", 225, 24, None),
    ("Night Drive/01.wav", 315, 26, dict(title="Kilometer Null", artist="The Quattro Lines",
                                         album="Night Drive", track=1, total=2)),
    ("Night Drive/02.wav", 175, 28, dict(title="Red Horizon", artist="The Quattro Lines",
                                         album="Night Drive", track=2, total=2)),
]
LIBRARY_COVERS = {"Blue Roads/cover.png": "waves"}
EMBEDDED_COVER = "sun"


def tone_wav(path: Path, freq: int, secs: int, rate: int = 44100) -> None:
    """A quiet sine tone with 0.1 s fades. Fast on a Pi 3B or under QEMU: one period is
    computed and repeated as bytes, only the fades are per sample."""
    period = rate // freq
    one = array("h", (int(0.25 * 32767 * math.sin(2 * math.pi * k / period)) for k in range(period)))
    total = rate * secs
    samples = array("h")
    samples.frombytes((one.tobytes() * (total // period + 1))[:total * 2])
    edge = rate // 10
    for n in range(edge):
        samples[n] = int(samples[n] * n / edge)
        samples[total - 1 - n] = int(samples[total - 1 - n] * (n + 1) / edge)
    if sys.byteorder == "big":
        samples.byteswap()   # WAV is little-endian
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def library(root: Path) -> None:
    """Write the test library into root; files already there are kept as they are
    (same mtime, so mediad's cache stays valid)."""
    png = None
    for rel, freq, secs, tags in LIBRARY:
        f = root / rel
        if f.exists():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        tone_wav(f, freq, secs)
        if tags:
            png = png or cover(EMBEDDED_COVER)
            tag(f, png=png, comment="R80 test library", **tags)
    for rel, style in LIBRARY_COVERS.items():
        f = root / rel
        if not f.exists():
            f.write_bytes(cover(style))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tag", help="write an ID3v2.3 tag (replaces an existing one)")
    t.add_argument("file", type=Path)
    t.add_argument("--title", default="")
    t.add_argument("--artist", default="")
    t.add_argument("--album", default="")
    t.add_argument("--track", type=int, default=0)
    t.add_argument("--total", type=int, default=0)
    t.add_argument("--cover", choices=STYLES, help="embed a generated cover")
    t.add_argument("--comment", default="")
    c = sub.add_parser("cover", help="write only a cover PNG")
    c.add_argument("style", choices=STYLES)
    c.add_argument("out", type=Path)
    c.add_argument("--size", type=int, default=COVER_SIZE)
    s = sub.add_parser("show", help="print a file's tag")
    s.add_argument("file", type=Path)
    lib = sub.add_parser("library", help="write the test library of the virtual HU")
    lib.add_argument("dir", type=Path)
    a = ap.parse_args()
    if a.cmd == "tag":
        tag(a.file, title=a.title, artist=a.artist, album=a.album, track=a.track, total=a.total,
            png=cover(a.cover) if a.cover else None, comment=a.comment)
    elif a.cmd == "cover":
        a.out.write_bytes(cover(a.style, a.size))
    elif a.cmd == "library":
        library(a.dir)
    else:
        for k, v in show(a.file).items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
