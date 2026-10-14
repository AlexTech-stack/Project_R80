#!/usr/bin/env python3
"""TC_HU_020: the companion link protocol (docs/companion-protocol.md, hu/companion_link.py).
Pure protocol test, no services: every message type survives encode -> decode, the
decoder copes with how a byte stream arrives (split lines, several per read, CRLF), and
bad input is dropped and counted without losing the messages around it."""
import json
import sys

from common import ROOT, check, finish

sys.path.insert(0, str(ROOT / "hu"))
import companion_link as cl  # noqa: E402

msgs = [cl.hello("r80-companion", "0.1.0", caps=["guidance"], device="Redmi Note 12 Pro 5G"),
        cl.hello("r80-hu", "0.1", heartbeat_s=2.0),
        cl.heartbeat(),
        cl.guidance("google_maps", "turn", "right", distance_m=350, street="Hauptstraße",
                    remaining_m=8300, remaining_s=720),
        cl.guidance("osmand", "roundabout", exit=3, distance_m=120.5, text="3. Ausfahrt"),
        cl.guidance("google_maps", "unknown", text="Weiter auf B27"),
        cl.guidance_ended(),
        cl.bye("user")]
wire = b"".join(cl.encode(m) for m in msgs)
check(all(line.endswith(b"}") for line in wire.split(b"\n")[:-1]) and wire.count(b"\n") == len(msgs),
      f"{len(msgs)} messages, one JSON line each ({len(wire)} bytes)")

d = cl.Decoder()
whole = d.feed(wire)
check(whole == [cl.validate(m) for m in msgs] and d.errors == 0, "all types survive encode -> decode unchanged")
check(whole[3]["street"] == "Hauptstraße" and "Hauptstraße".encode() in wire, "UTF-8 street names on the wire, not escaped")

d = cl.Decoder()
got = []
for i in range(0, len(wire), 7):          # a stream arrives in arbitrary pieces
    got += d.feed(wire[i:i + 7])
check(got == whole, "the same messages when the stream arrives 7 bytes at a time")
check(cl.Decoder().feed(wire.replace(b"\n", b"\r\n")) == whole, "CRLF line ends are accepted")

hb = cl.encode(cl.heartbeat())
bad = [b"not json\n", b"[1, 2]\n", b'{"active": true}\n',
       b'{"type":"guidance","active":true,"source":"x","maneuver":{"type":"jump"}}\n',
       b'{"type":"guidance","active":true,"source":"x","maneuver":{"type":"turn","modifier":"up"}}\n',
       b'{"type":"guidance","active":true,"source":"x","maneuver":{"type":"turn"},"distance_m":true}\n',
       b'{"type":"guidance","active":true,"source":"x","maneuver":{"type":"turn"},"distance_m":NaN}\n',
       b'{"type":"guidance","active":true,"source":"x","maneuver":{"type":"turn"},"distance_m":-5}\n',
       b'{"type":"guidance","active":"yes"}\n', b'{"type":"hello","app":"a","version":"1"}\n',
       b"\xff\xfe\n"]
d = cl.Decoder()
out = d.feed(hb + b"".join(bad) + hb)
check(out == [{"type": "heartbeat"}] * 2 and d.errors == len(bad),
      f"{len(bad)} bad lines dropped and counted, the messages around them kept (last: {d.last_error})")

d = cl.Decoder()
out = d.feed(b'{"type":"lanes","lanes":[]}\n' + b'{"type":"heartbeat","extra":1}\n')
check(out == [{"type": "heartbeat"}] and d.unknown == 1 and d.errors == 0,
      "unknown types are skipped (not errors), unknown fields ignored")

d = cl.Decoder()
long_line = b'{"type":"bye","reason":"' + b"x" * cl.MAX_LINE + b'"}\n'
out = d.feed(long_line[:3000]) + d.feed(long_line[3000:] + hb)
check(out == [{"type": "heartbeat"}] and d.errors == 1, f"a line over {cl.MAX_LINE} bytes is dropped, the next one kept")

g = json.loads(cl.encode(cl.guidance("google_maps", "turn", "left", street="S" * 500)))
check(len(g["street"]) == cl.MAX_TEXT and "exit" not in g["maneuver"] and "text" not in g,
      f"strings cut to {cl.MAX_TEXT} chars; unset fields are left out")
try:
    cl.encode({"type": "guidance", "active": True, "source": "x", "maneuver": {"type": "fly"}})
    check(False, "encode refuses what the decoder would reject")
except cl.ProtocolError:
    check(True, "encode refuses what the decoder would reject")
finish()
