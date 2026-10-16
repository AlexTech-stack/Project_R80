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
    """Collect de.r80.Vehicle1.Input signals in a background GLib loop.

    Create it before any other D-Bus call in the test: dbus-python shares one session
    connection, and it can only receive signals if a main loop is set before it exists."""

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


# ---- media (hu/mediad.py) -------------------------------------------------
MEDIA_SERVICE, MEDIA_PATH, MEDIA_IFACE = "de.r80.Media", "/de/r80/Media", "de.r80.Media1"


def media():
    """The de.r80.Media1 interface (Play, Pause, Next, SetTrack, ...)."""
    return dbus.Interface(dbus.SessionBus().get_object(MEDIA_SERVICE, MEDIA_PATH), MEDIA_IFACE)


def media_props() -> dict:
    obj = dbus.SessionBus().get_object(MEDIA_SERVICE, MEDIA_PATH)
    raw = obj.GetAll(MEDIA_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def _plain(v):
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, dbus.String):
        return str(v)
    if isinstance(v, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
        return int(v)
    if isinstance(v, dbus.Double):
        return float(v)
    if isinstance(v, dbus.Dictionary):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, dbus.Array):
        return [_plain(x) for x in v]
    return v


def wait_media(cond, timeout=3.0, step=0.05):
    """Poll cond(media props) until true; returns (ok, last props, seconds waited)."""
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        props = media_props()
        if cond(props):
            return True, props, time.monotonic() - t0
        time.sleep(step)
    return False, props, time.monotonic() - t0


def media_reset():
    """Known start: no shuffle, repeat on, track 0 playing from the start."""
    m = media()
    m.SetShuffle(False)
    m.SetRepeatAll(True)
    m.SetTrack(0)
    return m


# ---- audio (hu/audiod.py) -------------------------------------------------
AUDIO_SERVICE, AUDIO_PATH, AUDIO_IFACE = "de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1"
# Where hu-virtual.sh and ci/dut/start_dut.sh let audiod save its volumes.
AUDIO_STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "audio-state.json"


def audio():
    """The de.r80.Audio1 interface (SetMaster, SetVolume, SetMuted, ...)."""
    return dbus.Interface(dbus.SessionBus().get_object(AUDIO_SERVICE, AUDIO_PATH), AUDIO_IFACE)


def audio_props() -> dict:
    obj = dbus.SessionBus().get_object(AUDIO_SERVICE, AUDIO_PATH)
    raw = obj.GetAll(AUDIO_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def wait_audio(cond, timeout=3.0, step=0.05):
    """Poll cond(audio props) until true; returns (ok, last props, seconds waited)."""
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        props = audio_props()
        if cond(props):
            return True, props, time.monotonic() - t0
        time.sleep(step)
    return False, props, time.monotonic() - t0


def audio_config():
    """audiod's own config loader and gain formula, so tests never repeat its numbers."""
    sys.path.insert(0, str(ROOT / "hu"))
    import audiod
    return audiod, audiod.load_config()


# ---- warnings (hu/warnd.py) -----------------------------------------------
WARN_SERVICE, WARN_PATH, WARN_IFACE = "de.r80.Warnings", "/de/r80/Warnings", "de.r80.Warnings1"


def warnings():
    """The de.r80.Warnings1 interface (Acknowledge, AcknowledgeAll)."""
    return dbus.Interface(dbus.SessionBus().get_object(WARN_SERVICE, WARN_PATH), WARN_IFACE)


def active_warnings() -> dict:
    """id -> warning dict of the active warnings."""
    obj = dbus.SessionBus().get_object(WARN_SERVICE, WARN_PATH)
    raw = obj.Get(WARN_IFACE, "Active", dbus_interface="org.freedesktop.DBus.Properties")
    return {str(w["id"]): _plain(w) for w in raw}


def wait_warnings(cond, timeout=3.0, step=0.1):
    """Poll cond(active warnings by id) until true; returns (ok, last dict, seconds waited)."""
    t0 = time.monotonic()
    act = {}
    while time.monotonic() - t0 < timeout:
        act = active_warnings()
        if cond(act):
            return True, act, time.monotonic() - t0
        time.sleep(step)
    return False, act, time.monotonic() - t0


def warn_rules():
    """warnd's own config loader: rule id -> rule, so tests never repeat its numbers."""
    sys.path.insert(0, str(ROOT / "hu"))
    import warnd
    general, rules = warnd.load_config()
    return general, {r["id"]: r for r in rules}


# ---- trip computer (hu/tripd.py) ------------------------------------------
TRIP_SERVICE, TRIP_PATH, TRIP_IFACE = "de.r80.Trip", "/de/r80/Trip", "de.r80.Trip1"
TRIP_STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "trip-state.json"


def trip():
    """The de.r80.Trip1 interface (Reset)."""
    return dbus.Interface(dbus.SessionBus().get_object(TRIP_SERVICE, TRIP_PATH), TRIP_IFACE)


def trip_props() -> dict:
    obj = dbus.SessionBus().get_object(TRIP_SERVICE, TRIP_PATH)
    raw = obj.GetAll(TRIP_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def wait_trip(cond, timeout=4.0, step=0.1):
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        props = trip_props()
        if cond(props):
            return True, props, time.monotonic() - t0
        time.sleep(step)
    return False, props, time.monotonic() - t0


def trip_logic():
    """tripd's own config and Trips class, so tests never repeat its numbers."""
    sys.path.insert(0, str(ROOT / "hu"))
    import tripd
    return tripd, tripd.load_config()


# ---- navigation (hu-navd, D11) ---------------------------------------------------
NAV_SERVICE, NAV_PATH, NAV_IFACE = "de.r80.Nav", "/de/r80/Nav", "de.r80.Nav1"
COMPANION_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "companion.sock"


def nav_props() -> dict:
    obj = dbus.SessionBus().get_object(NAV_SERVICE, NAV_PATH)
    raw = obj.GetAll(NAV_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def wait_nav(cond, timeout=3.0, step=0.05):
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        try:
            props = nav_props()
            if cond(props):
                return True, props, time.monotonic() - t0
        except dbus.DBusException:
            pass
        time.sleep(step)
    return False, props, time.monotonic() - t0


def nav_logic():
    """navd's own config and Link class, so tests never repeat its numbers."""
    sys.path.insert(0, str(ROOT / "hu"))
    import navd
    return navd, navd.load_config()


def phone(device="Test phone", wait_free=True):
    """A fresh emulated phone (not connected yet) for navd's companion link socket.
    Waits until navd is up and, with wait_free, until no other phone is connected."""
    sys.path.insert(0, str(ROOT / "phone_emu"))
    from phone_emu import Phone
    wait_nav(lambda p: not p["Phone"]["connected"] or not wait_free, timeout=10.0)
    return Phone(COMPANION_SOCKET, device=device)


# ---- system and settings (hu-sysd, D12) --------------------------------------------
SYS_SERVICE, SYS_PATH, SYS_IFACE = "de.r80.System", "/de/r80/System", "de.r80.System1"
SETTINGS_STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "settings.json"


def system():
    """The de.r80.System1 interface (Set, Reset, ResetAll)."""
    return dbus.Interface(dbus.SessionBus().get_object(SYS_SERVICE, SYS_PATH), SYS_IFACE)


def sys_props() -> dict:
    obj = dbus.SessionBus().get_object(SYS_SERVICE, SYS_PATH)
    raw = obj.GetAll(SYS_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def sys_logic():
    """sysd's own config and Settings class, so tests never repeat its numbers."""
    sys.path.insert(0, str(ROOT / "hu"))
    import sysd
    return sysd, sysd.load_config()
