#!/usr/bin/env python3
"""R80 MCU emulator: stands in for the always-on vehicle MCU on a PC.

What the real MCU does, and what this process does instead:

  CAN          two channels as in architecture v0.3 (D8): CAN 1 on Infotainment
               (receive + transmit), CAN 2 listen-only on Motor or Comfort.
               Frames go to Linux over the UART. It sends on Infotainment when
               Linux asks and NEVER sends on the CAN 2 bus.
  Power        derives the power state from IgnitionState (0x120) and bus
               activity, tells Linux, waits for SHUTDOWN_READY before "cutting
               power".
  Knob/buttons real hardware on MCU pins; here injected through a control
               socket (see mcuctl.py).
  Dimming      day/night from LightState (0x121), overridable via mcuctl.
  UART         a pseudo-terminal; its slave end is symlinked to --uart so the
               Linux side opens it exactly like /dev/ttyAMA0.

    python3 mcu_emu.py --can1 vcan_info --can2 vcan_motor --can2-bus motor
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hu import mcu_link as L  # noqa: E402

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))

CAN_FRAME = struct.Struct("=IB3x8s")
IGNITION_ID, LIGHT_ID = 0x120, 0x121
BUS_SLEEP_S = 2.0          # no Infotainment traffic for this long -> bus asleep
SHUTDOWN_TIMEOUT_S = 10.0  # Linux gets this long to answer SHUTDOWN_READY
DAY_LEVEL, NIGHT_LEVEL = 100, 40


def log(*a):
    print("[mcu]", *a, flush=True)


def open_can(iface: str) -> socket.socket:
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.bind((iface,))
    s.setblocking(False)
    return s


class Mcu:
    def __init__(self, args):
        self.sel = selectors.DefaultSelector()
        self.seq = 0
        self.t0 = time.monotonic()
        self.decoder = L.Decoder()
        self.link_up = False
        self.last_host_hb = 0.0

        # CAN: bus id -> socket. Only INFO is ever written to.
        self.can = {}
        can2_bus = {"motor": L.BUS_MOTOR, "comfort": L.BUS_COMFORT}[args.can2_bus]
        for bus, iface in ((L.BUS_INFO, args.can1), (can2_bus, args.can2)):
            if iface:
                s = open_can(iface)
                self.can[bus] = s
                self.sel.register(s, selectors.EVENT_READ, ("can", bus))
                log(f"listening on {iface} ({L.BUS_NAMES[bus]})" + (" rx+tx" if bus == L.BUS_INFO else " rx only"))
        self.forward = {L.BUS_INFO} | ({can2_bus} if args.forward_can2 else set())

        # UART: pty pair, slave symlinked where the Linux side expects the port.
        self.uart, slave = os.openpty()
        os.set_blocking(self.uart, False)
        import tty
        tty.setraw(slave)
        self.uart_link = Path(args.uart)
        self.uart_link.unlink(missing_ok=True)
        self.uart_link.symlink_to(os.ttyname(slave))
        self._slave = slave  # keep open so the pty survives Linux-side reconnects
        self.sel.register(self.uart, selectors.EVENT_READ, ("uart", None))
        log(f"UART at {self.uart_link} -> {os.ttyname(slave)}")

        # Control socket for knob/buttons/dimming overrides.
        self.ctl_path = Path(args.control)
        self.ctl_path.unlink(missing_ok=True)
        self.ctl = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.ctl.bind(str(self.ctl_path))
        self.ctl.listen(4)
        self.ctl.setblocking(False)
        self.sel.register(self.ctl, selectors.EVENT_READ, ("ctl", None))
        log(f"control socket at {self.ctl_path}")

        # Vehicle state as the MCU sees it.
        self.ignition = 0          # raw IgnitionState
        self.light = 0             # raw LightState
        self.last_info_rx = 0.0
        self.power = L.POWER_OFF
        self.shutdown_deadline = None
        self.dim_override = None
        self.dim_sent = None
        self.stats = {"can_rx": 0, "can_fwd": 0, "can_tx": 0, "can_tx_refused": 0}

    # ---- UART ------------------------------------------------------------
    def send(self, msg_type, payload=b""):
        self.seq = (self.seq + 1) & 0xFF
        try:
            os.write(self.uart, L.encode(msg_type, self.seq, payload))
        except BlockingIOError:
            pass  # nobody reading and pty buffer full: drop, like a UART would

    def on_uart(self):
        try:
            data = os.read(self.uart, 4096)
        except (BlockingIOError, OSError):
            return
        for m in self.decoder.feed(data):
            self.on_host(m)

    def on_host(self, m):
        if m.type == L.HOST_HELLO:
            log(f"Linux says hello: {m.payload[1:].decode(errors='replace')}")
            self.link_up = True
            self.send(L.HELLO, bytes([L.PROTO_VERSION]) + b"r80-mcu-emu 0.1")
            self.send(L.POWER, bytes([self.power]))
            self.dim_sent = None
        elif m.type == L.HOST_HEARTBEAT:
            self.last_host_hb = time.monotonic()
            self.link_up = True
        elif m.type == L.CAN_TX:
            bus, can_id, data = L.unpack_can(m.payload)
            if bus != L.BUS_INFO or bus not in self.can:
                self.stats["can_tx_refused"] += 1
                log(f"refused CAN_TX on {L.BUS_NAMES.get(bus, bus)} bus (listen-only)")
                return
            self.can[bus].send(CAN_FRAME.pack(can_id, len(data), data.ljust(8, b"\0")))
            self.stats["can_tx"] += 1
        elif m.type == L.SHUTDOWN_READY:
            if self.shutdown_deadline:
                log("Linux is ready for shutdown, cutting power")
                self.shutdown_deadline = None
                self.set_power(L.POWER_OFF, notify=False)

    # ---- CAN -------------------------------------------------------------
    def on_can(self, bus):
        s = self.can[bus]
        while True:
            try:
                raw = s.recv(16)
            except BlockingIOError:
                return
            can_id, dlc, data = CAN_FRAME.unpack(raw)
            data = data[:dlc]
            self.stats["can_rx"] += 1
            if bus == L.BUS_INFO:
                self.last_info_rx = time.monotonic()
                if can_id == IGNITION_ID and dlc:
                    self.ignition = data[0] & 0x07
                elif can_id == LIGHT_ID and dlc:
                    self.light = data[0] & 0x07
            if bus in self.forward and self.power != L.POWER_OFF and self.link_up:
                self.send(L.CAN_RX, L.pack_can(bus, can_id, data))
                self.stats["can_fwd"] += 1

    # ---- power / dimming -------------------------------------------------
    def wanted_power(self):
        if time.monotonic() - self.last_info_rx > BUS_SLEEP_S:
            return L.POWER_OFF
        return {0: L.POWER_STANDBY, 1: L.POWER_STANDBY, 2: L.POWER_ACC,
                3: L.POWER_ON, 4: L.POWER_CRANK}.get(self.ignition, L.POWER_STANDBY)

    def set_power(self, state, notify=True):
        if state != self.power:
            log(f"power {L.POWER_NAMES[self.power]} -> {L.POWER_NAMES[state]}")
        self.power = state
        if notify:
            self.send(L.POWER, bytes([state]))

    def update_power(self):
        want = self.wanted_power()
        if self.shutdown_deadline:
            if want != L.POWER_OFF:
                log("wake-up during shutdown, staying on")
                self.shutdown_deadline = None
                self.set_power(want)
            elif time.monotonic() > self.shutdown_deadline:
                log("Linux did not answer SHUTDOWN_READY in time, cutting power anyway")
                self.shutdown_deadline = None
                self.set_power(L.POWER_OFF, notify=False)
            return
        if want == self.power:
            return
        if want == L.POWER_OFF:
            # Ask Linux to shut down; power stays on until it answers.
            log("bus asleep, requesting Linux shutdown")
            self.send(L.POWER, bytes([L.POWER_OFF]))
            self.shutdown_deadline = time.monotonic() + SHUTDOWN_TIMEOUT_S
        else:
            self.set_power(want)

    def update_dim(self):
        night = self.light >= 2  # LowBeam or HighBeam
        level = self.dim_override if self.dim_override is not None else (NIGHT_LEVEL if night else DAY_LEVEL)
        if (level, night) != self.dim_sent and self.link_up:
            self.send(L.DIM, bytes([level, int(night)]))
            self.dim_sent = (level, night)

    # ---- control socket ----------------------------------------------------
    def on_ctl_accept(self):
        conn, _ = self.ctl.accept()
        conn.setblocking(True)
        conn.settimeout(1.0)
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            reply = self.handle_cmd(json.loads(buf or b"{}"))
        except Exception as e:  # a bad command must never take the MCU down
            reply = {"ok": False, "error": str(e)}
        try:
            conn.sendall((json.dumps(reply) + "\n").encode())
        finally:
            conn.close()

    def handle_cmd(self, c):
        cmd = c.get("cmd")
        if cmd == "knob":
            self.send(L.INPUT, struct.pack("<Bb", L.KNOB_TURN, int(c.get("value", 1))))
        elif cmd == "push":
            self.send(L.INPUT, struct.pack("<Bb", L.KNOB_PUSH, 1))
        elif cmd == "tilt":
            self.send(L.INPUT, struct.pack("<Bb", L.KNOB_TILT, int(c.get("value", 1))))
        elif cmd == "button":
            name = str(c.get("name", "")).upper()
            if name not in L.BUTTON_IDS:
                return {"ok": False, "error": f"unknown button {name}, try {sorted(L.BUTTON_IDS)}"}
            self.send(L.INPUT, struct.pack("<Bb", L.BUTTON, L.BUTTON_IDS[name]))
        elif cmd == "dim":
            v = c.get("level")
            self.dim_override = None if v in (None, "auto") else max(0, min(100, int(v)))
        elif cmd != "status":
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        return {"ok": True, "power": L.POWER_NAMES[self.power], "link_up": self.link_up,
                "ignition": self.ignition, "light": self.light,
                "dim": self.dim_sent, "shutdown_pending": bool(self.shutdown_deadline),
                "crc_errors": self.decoder.crc_errors, **self.stats}

    # ---- main loop ---------------------------------------------------------
    def run(self):
        next_hb = 0.0
        while True:
            for key, _ in self.sel.select(timeout=0.05):
                kind, bus = key.data
                if kind == "can":
                    self.on_can(bus)
                elif kind == "uart":
                    self.on_uart()
                elif kind == "ctl":
                    self.on_ctl_accept()
            now = time.monotonic()
            if self.link_up and self.last_host_hb and now - self.last_host_hb > 3.0:
                log("Linux heartbeat lost")
                self.link_up = False
            self.update_power()
            self.update_dim()
            if now >= next_hb:
                self.send(L.HEARTBEAT, struct.pack("<I", int((now - self.t0) * 1000) & 0xFFFFFFFF))
                next_hb = now + 1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--can1", default="vcan_info", help="CAN 1: Infotainment interface (rx+tx)")
    ap.add_argument("--can2", default="", help="CAN 2: listen-only interface on Motor or Comfort (never sends)")
    ap.add_argument("--can2-bus", default="motor", choices=["motor", "comfort"], help="which bus CAN 2 sits on")
    ap.add_argument("--forward-can2", action="store_true",
                    help="also forward CAN 2 frames to Linux (default: Infotainment only, the test DBC is all there)")
    ap.add_argument("--uart", default=str(RUNTIME / "r80-mcu-uart"), help="symlink for the UART pty")
    ap.add_argument("--control", default=str(RUNTIME / "r80-mcu.sock"), help="control socket path")
    Mcu(ap.parse_args()).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
