"""Shared helpers for the R80 headunit BoAt tests.

Each test is a standalone script (exit 0 = pass) so `boat test run` can run it
as a subprocess. Stimulus goes in through BoAt (restbus, frame send) and the
MCU emulator's control socket; the verdict is read from hu-vehicled on D-Bus,
i.e. from what the Linux side of the headunit actually saw.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVICES = REPO / "hu" / "services"          # the HU's services (target software)
DEV = REPO / "dev"                           # PC stand-ins: MCU emulator, phone emulator
sys.path.insert(0, str(REPO / "test" / "boat"))
sys.path.insert(0, str(DEV / "mcu_emu"))

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


def media_queue() -> list:
    """The whole play queue (GetQueue), as plain dicts."""
    m = media()
    n = int(media_props().get("TrackCount", 0))
    return [_plain(t) for t in m.GetQueue(0, n)]


def power_settled(timeout=12.0):
    """Wait until hu-vehicled's Power is "off": after a test that closed its restbus the
    bus falls asleep a few seconds later, and hu-audiod pauses media at "off" (TC_HU_032).
    Media tests start after that, so no power change hits them half-way."""
    ok, _, _ = wait_for(lambda p: p["Power"] == "off", timeout=timeout)
    time.sleep(0.5)                     # hu-audiod's pause at "off" is a D-Bus round trip away
    return ok


def media_reset():
    """Known start: power settled, no shuffle, repeat on, track 0 playing from the start."""
    power_settled()
    m = media()
    m.SetShuffle(False)
    m.SetRepeatAll(True)
    m.SetTrack(0)
    return m


# ---- phone (hu/phoned.py) ---------------------------------------------------
PHONE_SERVICE, PHONE_PATH, PHONE_IFACE = "de.r80.Phone", "/de/r80/Phone", "de.r80.Phone1"


def phone_service():
    """The de.r80.Phone1 interface (Dial, Answer, Hangup, ...)."""
    return dbus.Interface(dbus.SessionBus().get_object(PHONE_SERVICE, PHONE_PATH), PHONE_IFACE)


def phone_props() -> dict:
    obj = dbus.SessionBus().get_object(PHONE_SERVICE, PHONE_PATH)
    raw = obj.GetAll(PHONE_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def wait_phone(cond, timeout=3.0, step=0.05):
    """Poll cond(phone props) until true; returns (ok, last props, seconds waited)."""
    t0 = time.monotonic()
    props = {}
    while time.monotonic() - t0 < timeout:
        props = phone_props()
        if cond(props):
            return True, props, time.monotonic() - t0
        time.sleep(step)
    return False, props, time.monotonic() - t0


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
    sys.path.insert(0, str(SERVICES))
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
    sys.path.insert(0, str(SERVICES))
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
    sys.path.insert(0, str(SERVICES))
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
    sys.path.insert(0, str(SERVICES))
    import navd
    return navd, navd.load_config()


def phone(device="Test phone", wait_free=True):
    """A fresh emulated phone (not connected yet) for navd's companion link socket.
    Waits until navd is up and, with wait_free, until no other phone is connected."""
    sys.path.insert(0, str(DEV / "phone_emu"))
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
    sys.path.insert(0, str(SERVICES))
    import sysd
    return sysd, sysd.load_config()


# ---- the DLT log (hu/services/dlt-daemon.sh, as DLT Viewer reads it) ----------------------------
DLT_PORT = int(os.environ.get("DLT_DAEMON_TCP_PORT", "3490"))


def _dc():
    sys.path.insert(0, str(SERVICES))
    import dltclient
    return dltclient


class DltStream:
    """A DLT client: every message the daemon sends, collected in the background."""

    def __init__(self):
        self.sock = socket.create_connection(("127.0.0.1", DLT_PORT), timeout=3.0)
        self.sock.settimeout(None)          # a quiet stream (seconds without a message) must not end the reader
        self.parser, self.messages, self.lock = _dc().Parser(), [], threading.Lock()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.messages += self.parser.feed(data)

    def send(self, data: bytes):
        self.sock.sendall(data)

    def wait(self, cond, timeout=4.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            with self.lock:
                hit = [m for m in self.messages if cond(m)]
            if hit:
                return hit[-1]
            time.sleep(0.05)
        return None

    def log_info(self, timeout=3.0) -> dict:
        """Get Log Info: {apid: {"description", "contexts": {ctid: {"level", "description"}}}}."""
        with self.lock:
            self.messages = [m for m in self.messages if m.service != _dc().GET_LOG_INFO]
        self.send(_dc().get_log_info())
        m = self.wait(lambda m: m.service == _dc().GET_LOG_INFO and m.subtype == _dc().CONTROL_RESPONSE, timeout)
        return _dc().log_info(m.data, m.big_endian) if m and m.status == 7 else {}


# ---- the system log (hu-syslogd reads the virtual mode's stand-in journal) ---------------------
JOURNAL = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "journal.jsonl"


def journal(message, priority=6, **fields):
    """Appends one entry to the stand-in journal, as journalctl -o json would print it."""
    entry = {"MESSAGE": message, "PRIORITY": str(priority), **fields}
    with JOURNAL.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ---- the voice assistant (hu-assistd with recorded speech, the transcript recognizer, a silent voice) ----
AST_SERVICE, AST_PATH, AST_IFACE = "de.r80.Assistant", "/de/r80/Assistant", "de.r80.Assistant1"
ASSIST_MIC = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu" / "assistant-mic"


def assistant():
    """The de.r80.Assistant1 interface (Command, Conversation, Stop)."""
    return dbus.Interface(dbus.SessionBus().get_object(AST_SERVICE, AST_PATH), AST_IFACE)


def assistant_props() -> dict:
    obj = dbus.SessionBus().get_object(AST_SERVICE, AST_PATH)
    raw = obj.GetAll(AST_IFACE, dbus_interface="org.freedesktop.DBus.Properties")
    return {str(k): _plain(v) for k, v in raw.items()}


def wait_assistant(cond, timeout=5.0, step=0.05):
    t0 = time.monotonic()
    p = {}
    while time.monotonic() - t0 < timeout:
        p = assistant_props()
        if cond(p):
            return True, p, time.monotonic() - t0
        time.sleep(step)
    return False, p, time.monotonic() - t0


def assistant_logic():
    """assistd's own config, so tests never repeat its numbers."""
    sys.path.insert(0, str(SERVICES))
    import assistd
    return assistd, assistd.load_config()


def say_next(text: str, seconds: float = 1.5, name: str | None = None) -> Path:
    """What the driver says at the assistant's next listen: a recording (a tone standing in for
    speech) in its microphone folder, with its text for the transcript recognizer."""
    import array
    import math
    import wave
    ASSIST_MIC.mkdir(parents=True, exist_ok=True)
    name = name or f"say-{time.monotonic_ns()}"
    pcm = array.array("h", (int(8000 * math.sin(i / 4)) for i in range(int(seconds * 16000))))
    tmp = ASSIST_MIC / f"{name}.tmp"
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    (ASSIST_MIC / f"{name}.txt").write_text(text + "\n")
    wav = ASSIST_MIC / f"{name}.wav"
    tmp.rename(wav)                          # whole, or not there at all
    return wav


def assistant_idle(timeout=10.0):
    """No session running and nothing left in the microphone folder from an earlier test."""
    for f in ASSIST_MIC.glob("*.wav"):
        f.unlink()
    a = assistant()
    if assistant_props()["Mode"] != "idle":
        a.Stop()
    return wait_assistant(lambda p: p["Available"] and p["Mode"] == "idle", timeout=timeout)[0]


class StateRecorder:
    """Every State the assistant passes through, and audiod's Voice at the same time (polled)."""

    def __init__(self, step=0.03):
        self.states, self.voice = [], []
        self.step = step
        self.running = True
        self.t = threading.Thread(target=self.run, daemon=True)
        self.t.start()

    def run(self):
        while self.running:
            try:
                s, v = assistant_props()["State"], audio_props()["Voice"]
            except dbus.DBusException:
                s = v = None
            if s and (not self.states or self.states[-1] != s):
                self.states.append(s)
            if v and (not self.voice or self.voice[-1] != v):
                self.voice.append(v)
            time.sleep(self.step)

    def stop(self):
        self.running = False
        self.t.join()
        return self.states, self.voice
