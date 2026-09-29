"""Shared helpers for the R80 headunit BoAt tests.

Each test is a standalone script (exit 0 = pass) so `boat test run` can run it
as a subprocess. Stimulus goes in through BoAt (restbus, frame send) and the
MCU emulator's control socket; the verdict is read from hu-vehicled on D-Bus,
i.e. from what the Linux side of the headunit actually saw.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "boat"))
sys.path.insert(0, str(ROOT / "mcu_emu"))

import dbus  # noqa: E402

from mcuctl import call as mcu  # noqa: E402,F401
from restbus import Restbus  # noqa: E402,F401

ADDRESS = os.environ.get("BOAT_HOST", "localhost:50061")
SERVICE, PATH, IFACE = "de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1"

_failures = []


def hu_props() -> dict:
    obj = dbus.SessionBus().get_object(SERVICE, PATH)
    raw = obj.GetAll(IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    out = {}
    for k, v in raw.items():
        if isinstance(v, dbus.Boolean):
            v = bool(v)
        elif isinstance(v, dbus.String):
            v = str(v)
        elif isinstance(v, dbus.Array):
            v = [str(x) for x in v]
        elif isinstance(v, dbus.Double):
            v = float(v)
        elif isinstance(v, (dbus.Int32, dbus.Int64)):
            v = int(v)
        out[str(k)] = v
    return out


def wait_for(cond, timeout=3.0, step=0.05):
    """Poll cond(props) until true; returns (ok, last props, seconds waited)."""
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        props = hu_props()
        if cond(props):
            return True, props, time.monotonic() - t0
        time.sleep(step)
    return False, props, time.monotonic() - t0


def check(ok, what):
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        _failures.append(what)
    return ok


def finish():
    if _failures:
        print(f"\n{len(_failures)} check(s) failed", flush=True)
        sys.exit(1)
    print("\nall checks passed", flush=True)
    sys.exit(0)


class InputListener:
    """Collect de.r80.Vehicle1.Input signals in a background GLib loop."""

    def __init__(self):
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        DBusGMainLoop(set_as_default=True)
        self.events = []
        self._loop = GLib.MainLoop()
        bus = dbus.SessionBus()
        bus.add_signal_receiver(lambda k, v: self.events.append((str(k), int(v))),
                                "Input", IFACE, None, PATH)
        threading.Thread(target=self._loop.run, daemon=True).start()
        time.sleep(0.2)

    def close(self):
        self._loop.quit()
