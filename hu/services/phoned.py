#!/usr/bin/env python3
"""hu-phoned: the phone service of the R80 headunit (calls over Bluetooth hands-free).

Call control comes from PipeWire's Bluetooth telephony service (org.pipewire.Telephony,
PipeWire 1.4+, WirePlumber setting bluez5.telephony-dbus-service): one audio gateway
object per connected phone (/org/pipewire/Telephony/agN) with its calls (.../callN).
No oFono. phoned shows one phone at a time (the one that connected last) and publishes:

    bus name   de.r80.Phone
    object     /de/r80/Phone
    interface  de.r80.Phone1
      properties  Connected (b)
                  Device (a{sv}): address (s), name (s: from BlueZ, else the address),
                                  battery (i: percent, -1 = unknown)
                  Calls (aa{sv}): id (s), number (s), name (s: what the phone sends, may be ""),
                                  state (s: active|held|dialing|alerting|incoming|waiting),
                                  direction (s: in|out), since (x: unix ms it became active, 0 = not yet)
                  CallState (s): idle | ringing (a call comes in) | dialing (we call, not
                                 answered yet) | active (a call is on, maybe held)
      methods     Dial(s number), Answer() (the ringing call), Hangup() (the ringing call is
                  rejected, else the current call ends), HangupAll(), SendTones(s)
                  errors: de.r80.Phone1.Error.NoPhone, .NoCall, .Failed (the phone said no)
    Changes go out as org.freedesktop.DBus.Properties.PropertiesChanged.

phoned tells hu-audiod about calls (SetCallState: ringing / active / idle; dialing counts
as active), so media pauses and radio is silent (D9).

Buses: the HU's own (session or --system); --telephony BUS for PipeWire's service: system,
session, or a D-Bus address (on the bench the desktop's session bus, where WirePlumber
runs: unix:path=/run/user/<uid>/bus); --bluez system|session for the phone's name and
battery (org.bluez.Device1 / Battery1), none to leave them out.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

BUS_NAME, OBJ_PATH, IFACE = "de.r80.Phone", "/de/r80/Phone", "de.r80.Phone1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OM = "org.freedesktop.DBus.ObjectManager"
TEL, TEL_ROOT = "org.pipewire.Telephony", "/org/pipewire/Telephony"
AG_IFACE, CALL_IFACE = TEL + ".AudioGateway1", TEL + ".Call1"
AUDIO = ("de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1")
BLUEZ = "org.bluez"
LIVE_STATES = ("active", "held", "dialing", "alerting", "incoming", "waiting")


def log(*a):
    print("[phoned]", *a, flush=True)


def plain(v):
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, (dbus.String, dbus.ObjectPath)):
        return str(v)
    if isinstance(v, (dbus.Byte, dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64)):
        return int(v)
    if isinstance(v, dbus.Dictionary):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, dbus.Array):
        return [plain(x) for x in v]
    return v


def call_state(calls: list) -> str:
    """The one-word summary of the calls, for the UI and audiod."""
    states = {c["state"] for c in calls}
    if states & {"incoming", "waiting"} and not states & {"active", "held"}:
        return "ringing"
    if states & {"active", "held"}:
        return "active"
    if states & {"dialing", "alerting"}:
        return "dialing"
    return "idle"


class Phone(dbus.service.Object):
    def __init__(self, bus, tel_bus, bluez_bus):
        super().__init__(bus, OBJ_PATH)
        self.bus, self.tel, self.bluez = bus, tel_bus, bluez_bus
        self.ags: dict[str, dict] = {}       # ag path -> {"address", "added"}
        self.calls: dict[str, dict] = {}     # call path -> call (of every ag)
        self.order = 0
        self.device = {"address": "", "name": "", "battery": -1}
        self.props = {}
        self.dirty = set()
        self.audio_state = None
        self.bluez_path = None

        tel_bus.add_signal_receiver(self.on_added, "InterfacesAdded", OM, TEL, None)
        tel_bus.add_signal_receiver(self.on_removed, "InterfacesRemoved", OM, TEL, None)
        tel_bus.add_signal_receiver(self.on_props, "PropertiesChanged", PROPS_IFACE, TEL, None, path_keyword="path")
        tel_bus.add_signal_receiver(self.on_tel_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                    "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=TEL)
        if bluez_bus is not None:
            bluez_bus.add_signal_receiver(self.on_bluez_props, "PropertiesChanged", PROPS_IFACE, BLUEZ, None,
                                          path_keyword="path")
        bus.add_signal_receiver(lambda *_: self.push_audio(force=True), "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=AUDIO[0])
        if tel_bus.name_has_owner(TEL):
            self.load()
        else:
            log("waiting for PipeWire's telephony service (org.pipewire.Telephony)")
        GLib.timeout_add(100, self.flush)
        self.refresh()

    # ---- PipeWire telephony ------------------------------------------------
    def load(self):
        self.tel.call_async(TEL, TEL_ROOT, OM, "GetManagedObjects", "", (), self.on_ags,
                            lambda e: log(f"telephony: {e}"), timeout=5.0)

    def on_ags(self, objects):
        for path, ifaces in objects.items():
            if AG_IFACE in ifaces:
                self.add_ag(str(path), plain(ifaces[AG_IFACE]))

    def add_ag(self, path: str, props: dict):
        if path in self.ags:                     # listed and announced at the same time
            return
        self.order += 1
        self.ags[path] = {"address": props.get("Address", ""), "added": self.order}
        log(f"phone connected: {path} ({self.ags[path]['address']})")
        self.tel.call_async(TEL, path, OM, "GetManagedObjects", "", (), lambda objs: self.on_calls(path, objs),
                            lambda e: log(f"calls of {path}: {e}"), timeout=5.0)
        self.refresh()

    def on_calls(self, ag: str, objects):
        for path, ifaces in objects.items():
            if CALL_IFACE in ifaces:
                self.add_call(ag, str(path), plain(ifaces[CALL_IFACE]))

    def add_call(self, ag: str, path: str, props: dict):
        if path in self.calls:
            return
        state = props.get("State", "")
        self.calls[path] = {"ag": ag, "number": props.get("LineIdentification", ""), "name": props.get("Name", ""),
                            "state": state, "direction": "in" if state in ("incoming", "waiting") else "out",
                            "since": int(time.time() * 1000) if state == "active" else 0}
        log(f"call {path.rsplit('/', 1)[-1]}: {state}")
        self.refresh()

    def on_tel_owner(self, _name, _old, new):
        self.ags.clear()
        self.calls.clear()
        self.refresh()
        if new:
            self.load()
        else:
            log("PipeWire's telephony service is gone")

    def on_added(self, path, ifaces):
        path = str(path)
        if AG_IFACE in ifaces:
            self.add_ag(path, plain(ifaces[AG_IFACE]))
        elif CALL_IFACE in ifaces:
            self.add_call(path.rsplit("/", 1)[0], path, plain(ifaces[CALL_IFACE]))

    def on_removed(self, path, ifaces):
        path = str(path)
        if path in self.calls and CALL_IFACE in ifaces:
            log(f"call {path.rsplit('/', 1)[-1]}: ended")
            del self.calls[path]
        elif path in self.ags and AG_IFACE in ifaces:
            log(f"phone disconnected: {path}")
            del self.ags[path]
            for c in [c for c, call in self.calls.items() if call["ag"] == path]:
                del self.calls[c]
        self.refresh()

    def on_props(self, iface, changed, _invalidated, path=None):
        path, changed = str(path), plain(changed)
        call = self.calls.get(path)
        if str(iface) != CALL_IFACE or call is None:
            return
        if "State" in changed:
            if changed["State"] == "active" and not call["since"]:
                call["since"] = int(time.time() * 1000)
            call["state"] = changed["State"]
            log(f"call {path.rsplit('/', 1)[-1]}: {call['state']}")
        if "LineIdentification" in changed:
            call["number"] = changed["LineIdentification"]
        if "Name" in changed:
            call["name"] = changed["Name"]
        if call["state"] == "disconnected":
            del self.calls[path]
        self.refresh()

    # ---- the phone: the latest one; its name and battery from BlueZ ------------
    def current(self) -> str | None:
        return max(self.ags, key=lambda p: self.ags[p]["added"]) if self.ags else None

    def my_calls(self) -> list:
        ag = self.current()
        return [dict(c, id=p.rsplit("/", 1)[-1], path=p) for p, c in sorted(self.calls.items())
                if c["ag"] == ag and c["state"] in LIVE_STATES]

    def update_device(self):
        ag = self.current()
        address = self.ags[ag]["address"] if ag else ""
        if address != self.device["address"]:
            self.device = {"address": address, "name": address, "battery": -1}
            if address and self.bluez is not None:
                self.bluez_path = None
                self.bluez.call_async(BLUEZ, "/", OM, "GetManagedObjects", "", (),
                                      lambda objs: self.on_bluez_objects(address, objs), lambda e: None, timeout=5.0)

    def on_bluez_objects(self, address: str, objects):
        for path, ifaces in objects.items():
            dev = plain(ifaces.get(BLUEZ + ".Device1", {}))
            if dev.get("Address", "").upper() == address.upper() and self.device["address"] == address:
                self.bluez_path = str(path)
                self.device["name"] = dev.get("Alias") or dev.get("Name") or address
                bat = plain(ifaces.get(BLUEZ + ".Battery1", {}))
                self.device["battery"] = int(bat.get("Percentage", -1))
                self.refresh()

    def on_bluez_props(self, iface, changed, _invalidated, path=None):
        if str(path) != getattr(self, "bluez_path", None):
            return
        changed = plain(changed)
        if str(iface) == BLUEZ + ".Battery1" and "Percentage" in changed:
            self.device["battery"] = int(changed["Percentage"])
        elif str(iface) == BLUEZ + ".Device1" and "Alias" in changed:
            self.device["name"] = changed["Alias"]
        else:
            return
        self.refresh()

    # ---- audiod (D9) ---------------------------------------------------------
    def push_audio(self, force=False):
        state = {"ringing": "ringing", "dialing": "active", "active": "active"}.get(self.props.get("CallState"), "idle")
        if state != self.audio_state or force:
            self.audio_state = state
            self.bus.call_async(AUDIO[0], AUDIO[1], AUDIO[2], "SetCallState", "s", (state,),
                                lambda *_: None, lambda e: None, timeout=2.0)

    # ---- properties ------------------------------------------------------------
    def refresh(self):
        self.update_device()
        calls = self.my_calls()
        self.set("Connected", self.current() is not None)
        self.set("Device", dict(self.device))
        self.set("Calls", [{k: c[k] for k in ("id", "number", "name", "state", "direction", "since")} for c in calls])
        self.set("CallState", call_state(calls))
        self.push_audio()

    def set(self, name, value):
        if self.props.get(name) != value:
            self.props[name] = value
            self.dirty.add(name)

    def prop(self, name):
        v = self.props[name]
        if name == "Device":
            return dbus.Dictionary({"address": v["address"], "name": v["name"], "battery": dbus.Int32(v["battery"])},
                                   signature="sv")
        if name == "Calls":
            return dbus.Array([dbus.Dictionary({**{k: dbus.String(c[k]) for k in ("id", "number", "name", "state", "direction")},
                                                "since": dbus.Int64(c["since"])}, signature="sv") for c in v],
                              signature="a{sv}")
        return dbus.Boolean(v) if isinstance(v, bool) else dbus.String(v)

    def flush(self):
        if self.dirty:
            changed = {k: self.prop(k) for k in self.dirty}
            self.dirty.clear()
            self.PropertiesChanged(IFACE, dbus.Dictionary(changed, signature="sv"), dbus.Array([], signature="s"))
        return True

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.prop(str(name))

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({k: self.prop(k) for k in self.props}, signature="sv")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    # ---- methods ---------------------------------------------------------------
    @staticmethod
    def error(kind, text):
        return dbus.exceptions.DBusException(text, name=f"{IFACE}.Error.{kind}")

    def tel_call(self, path, iface, method, sig="", args=(), reply=None, error=None):
        """Call PipeWire asynchronously; the D-Bus caller gets its answer when PipeWire answers."""
        def failed(e):
            error(self.error("Failed", e.get_dbus_message() if hasattr(e, "get_dbus_message") else str(e)))
        self.tel.call_async(TEL, path, iface, method, sig, args, lambda *r: reply(), failed, timeout=30.0)

    def find(self, states) -> dict | None:
        return next((c for c in self.my_calls() if c["state"] in states), None)

    @dbus.service.method(IFACE, in_signature="s", async_callbacks=("reply", "error"))
    def Dial(self, number, reply, error):
        ag = self.current()
        if ag is None:
            raise self.error("NoPhone", "no phone connected")
        number = str(number).strip()
        if not number or any(ch not in "+0123456789*#" for ch in number.replace(" ", "")):
            raise self.error("Failed", f"not a phone number: {number!r}")
        log("dialling")                           # never the number: the logs stay free of personal data
        self.tel_call(ag, AG_IFACE, "Dial", "s", (number.replace(" ", ""),), reply, error)

    @dbus.service.method(IFACE, async_callbacks=("reply", "error"))
    def Answer(self, reply, error):
        call = self.find(("incoming", "waiting"))
        if call is None:
            raise self.error("NoCall", "no call is ringing")
        self.tel_call(call["path"], CALL_IFACE, "Answer", reply=reply, error=error)

    @dbus.service.method(IFACE, async_callbacks=("reply", "error"))
    def Hangup(self, reply, error):
        call = (self.find(("incoming", "waiting")) if call_state(self.my_calls()) == "ringing"
                else self.find(("active", "dialing", "alerting", "held")))
        if call is None:
            raise self.error("NoCall", "no call")
        self.tel_call(call["path"], CALL_IFACE, "Hangup", reply=reply, error=error)

    @dbus.service.method(IFACE, async_callbacks=("reply", "error"))
    def HangupAll(self, reply, error):
        ag = self.current()
        if ag is None:
            raise self.error("NoPhone", "no phone connected")
        self.tel_call(ag, AG_IFACE, "HangupAll", reply=reply, error=error)

    @dbus.service.method(IFACE, in_signature="s", async_callbacks=("reply", "error"))
    def SendTones(self, tones, reply, error):
        ag = self.current()
        if ag is None:
            raise self.error("NoPhone", "no phone connected")
        self.tel_call(ag, AG_IFACE, "SendTones", "s", (str(tones),), reply, error)


def bus_for(spec: str):
    if spec == "system":
        return dbus.SystemBus()
    if spec == "session":
        return dbus.SessionBus()
    return dbus.bus.BusConnection(spec)          # a D-Bus address, e.g. the desktop's session bus


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", action="store_true", help="publish on the system bus (target) instead of the session bus")
    ap.add_argument("--telephony", default="session", metavar="BUS",
                    help="where PipeWire's org.pipewire.Telephony is: system, session or a D-Bus address (default session)")
    ap.add_argument("--bluez", choices=("system", "session", "none"), default="system",
                    help="BlueZ for the phone's name and battery (default system)")
    a = ap.parse_args()
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    tel = bus_for(a.telephony)
    bluez = None if a.bluez == "none" else bus_for(a.bluez)
    Phone(bus, tel, bluez)
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus; telephony on {a.telephony}, "
        f"BlueZ on {a.bluez}")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
