#!/usr/bin/env python3
"""hu-vehicled: the Linux-side vehicle service of the R80 headunit.

Reads the MCU over its UART, decodes CAN with the DBC and publishes everything
on D-Bus for the UI and other services:

    bus name   de.r80.Vehicle
    object     /de/r80/Vehicle
    interface  de.r80.Vehicle1
      properties  one per DBC signal (VehicleSpeed, Gear, ...), plus
                  Power (s: off|standby|acc|on|crank|shutdown), LinkUp (b),
                  DimLevel (i 0..100), Night (b), StaleSignals (as)
      signal      Input(s kind, i value)   kind = knob | push | tilt | button:<NAME>
      method      SendCan(y bus, u can_id, ay data) -> b
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged,
    batched every 50 ms.

Runs unchanged on the bench (--uart /dev/ttyAMA0 --system) and in the virtual
environment (session bus, the MCU emulator's pty).
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hu import mcu_link as L  # noqa: E402
from hu.dbc import Database  # noqa: E402

BUS_NAME = "de.r80.Vehicle"
OBJ_PATH = "/de/r80/Vehicle"
IFACE = "de.r80.Vehicle1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))


def log(*a):
    print("[vehicled]", *a, flush=True)


def variant(v):
    if isinstance(v, bool):
        return dbus.Boolean(v)
    if isinstance(v, str):
        return dbus.String(v)
    if isinstance(v, int):
        return dbus.Int32(v)
    if isinstance(v, float):
        return dbus.Double(v)
    if isinstance(v, list):
        return dbus.Array(v, signature="s")
    raise TypeError(type(v))


class Vehicle(dbus.service.Object):
    def __init__(self, bus, db: Database, uart_path: str):
        super().__init__(bus, OBJ_PATH)
        self.db = db
        self.uart_path = uart_path
        self.fd = None
        self.decoder = L.Decoder()
        self.seq = 0
        self.last_mcu_hb = 0.0
        self.props = {"Power": "off", "LinkUp": False, "DimLevel": 100, "Night": False, "StaleSignals": []}
        self.last_rx = {}       # signal name -> monotonic time
        self.timeout = {}       # signal name -> seconds
        for m in db.messages:
            for s in m.signals:
                self.props[s.name] = s.choices.get(0, "") if s.choices else 0.0
                self.timeout[s.name] = max(0.5, 3 * m.cycle_ms / 1000) if m.cycle_ms else None
        self.dirty = set()
        GLib.timeout_add(50, self.flush)
        GLib.timeout_add(1000, self.tick)
        self.try_open()

    # ---- D-Bus API -------------------------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return variant(self.props[name])

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: variant(v) for k, v in self.props.items()}, signature="sv")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    @dbus.service.signal(IFACE, signature="si")
    def Input(self, kind, value):
        pass

    @dbus.service.method(IFACE, in_signature="yuay", out_signature="b")
    def SendCan(self, bus, can_id, data):
        return self.send(L.CAN_TX, L.pack_can(int(bus), int(can_id), bytes(data)))

    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def flush(self):
        if self.dirty:
            changed = {k: variant(self.props[k]) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))
        return True

    # ---- UART ------------------------------------------------------------
    def try_open(self):
        if self.fd is not None:
            return
        try:
            self.fd = L.open_serial(self.uart_path)
        except OSError:
            return
        log(f"opened MCU UART {self.uart_path}")
        GLib.io_add_watch(self.fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_uart)
        self.send(L.HOST_HELLO, bytes([L.PROTO_VERSION]) + b"hu-vehicled 0.1")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            self.set("LinkUp", False)
            log("MCU UART closed")

    def send(self, msg_type, payload=b""):
        if self.fd is None:
            return False
        self.seq = (self.seq + 1) & 0xFF
        try:
            os.write(self.fd, L.encode(msg_type, self.seq, payload))
            return True
        except OSError:
            return False

    def on_uart(self, fd, cond):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self.close()
            return False
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            return True
        except OSError:
            self.close()
            return False
        for m in self.decoder.feed(data):
            self.on_mcu(m)
        return True

    def on_mcu(self, m):
        if m.type == L.HEARTBEAT:
            self.last_mcu_hb = time.monotonic()
            self.set("LinkUp", True)
        elif m.type == L.HELLO:
            log(f"MCU: {m.payload[1:].decode(errors='replace')} (protocol {m.payload[0]})")
        elif m.type == L.CAN_RX:
            bus, can_id, data = L.unpack_can(m.payload)
            msg = self.db.get(can_id & 0x1FFFFFFF, bool(can_id & L.CAN_EFF_FLAG))
            if msg:
                now = time.monotonic()
                for k, v in msg.decode(data).items():
                    self.last_rx[k] = now
                    self.set(k, round(v, 4) if isinstance(v, float) else v)
        elif m.type == L.POWER:
            state = L.POWER_NAMES.get(m.payload[0], "off")
            if state == "off" and self.props["Power"] not in ("off", "shutdown"):
                # MCU asks us to shut down. Here the real HU would save state and
                # stop services; we just give listeners a moment, then say ready.
                self.set("Power", "shutdown")
                GLib.timeout_add(1000, self.shutdown_ready)
            elif state != "off":
                self.set("Power", state)
        elif m.type == L.INPUT:
            ev, val = struct.unpack("<Bb", m.payload[:2])
            kind = {L.KNOB_TURN: "knob", L.KNOB_PUSH: "push", L.KNOB_TILT: "tilt"}.get(ev)
            if ev == L.BUTTON:
                kind = "button:" + L.BUTTONS.get(val, str(val))
            if kind:
                self.Input(kind, val)
        elif m.type == L.DIM:
            self.set("DimLevel", int(m.payload[0]))
            self.set("Night", bool(m.payload[1]))

    def shutdown_ready(self):
        if self.props["Power"] == "shutdown":
            self.send(L.SHUTDOWN_READY)
            self.set("Power", "off")
            log("told MCU we are ready for shutdown")
        return False

    def tick(self):
        self.try_open()
        self.send(L.HOST_HEARTBEAT)
        now = time.monotonic()
        if self.props["LinkUp"] and now - self.last_mcu_hb > 3.0:
            self.set("LinkUp", False)
        stale = sorted(k for k, t in self.timeout.items()
                       if t and now - self.last_rx.get(k, 0) > t)
        self.set("StaleSignals", stale)
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dbc", default=str(Path(__file__).resolve().parents[2] / "hu-can" / "r80_test.dbc"))
    ap.add_argument("--uart", default=str(RUNTIME / "r80-mcu-uart"))
    ap.add_argument("--system", action="store_true", help="use the system bus (target) instead of the session bus")
    a = ap.parse_args()

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    Vehicle(bus, Database(a.dbc), a.uart)
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
