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
                  Consent (s): may the HU keep a copy of this phone's contacts and call
                               history? "" = not asked yet (the UI asks), yes, no
                  SyncState (s): idle | syncing | failed;  SyncError (s);  SyncedAt (x: unix s, 0 = never)
                  ContactCount (i);  History (aa{sv}: name, number, kind in|out|missed, time)
                  Favourites (aa{sv}: id, name, numbers aa{sv} number/type): local to the HU
                  CallGain (d): the far end's level, from hu-audiod (phone volume, D9)
                  MicMuted (b): the HU's microphone is cut off from the phone (per call)
                  MicAvailable (b): during a call, a real microphone feeds the phone (else
                                    the stream to the phone stays muted: no echo of the output)
      methods     Dial(s number), Answer() (the ringing call), Hangup() (the ringing call is
                  rejected, else the current call ends), HangupAll(), SendTones(s)
                  SetGain(d gain, u fade_ms) (from hu-audiod), SetMicMuted(b),
                  SetConsent(b) (yes: copy now), Sync() (copy again, implies consent),
                  DeleteCopy() (forget contacts, history, favourites; consent no),
                  GetContacts(i offset, i count) -> aa{sv} (id, name, numbers), SetFavourite(s id, b)
                  errors: de.r80.Phone1.Error.NoPhone, .NoCall, .Failed (the phone said no), .Busy

Contacts and call history (hu/phonebook.py: PBAP over BlueZ's obexd, --obex BUS) are
copied per phone into --state-dir, only with consent: the first time a phone connects
the UI asks; afterwards a copy is made again only by Sync (Settings -> Phone). A call
without a name from the phone gets it from the copy. Names and numbers are never logged.

The call's sound runs through PipeWire (hu/callaudio.py, --call-audio pipewire): phoned
puts CallGain and MicMuted on the call's two streams once they exist.
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
import os
import sys
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vcard  # noqa: E402
from callaudio import CallAudio  # noqa: E402
from phonebook import PbapClient, Store  # noqa: E402

BUS_NAME, OBJ_PATH, IFACE = "de.r80.Phone", "/de/r80/Phone", "de.r80.Phone1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OM = "org.freedesktop.DBus.ObjectManager"
TEL, TEL_ROOT = "org.pipewire.Telephony", "/org/pipewire/Telephony"
AG_IFACE, CALL_IFACE = TEL + ".AudioGateway1", TEL + ".Call1"
AUDIO = ("de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1")
BLUEZ = "org.bluez"
LIVE_STATES = ("active", "held", "dialing", "alerting", "incoming", "waiting")
SYNC_TIMEOUT_S = 300                     # a phone that never answers the PBAP request


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
    def __init__(self, bus, tel_bus, bluez_bus, pbap: PbapClient | None, store: Store,
                 audio: CallAudio | None = None):
        super().__init__(bus, OBJ_PATH)
        self.audio = audio
        self.gain, self.mic_muted = 1.0, False
        self.streams: dict = {}                      # the call's PipeWire streams, once found
        self.stream_timer = None
        self.bus, self.tel, self.bluez = bus, tel_bus, bluez_bus
        self.pbap, self.store = pbap, store
        self.book = self.no_book()                   # the current phone's copy (empty: none)
        self.book_address = ""
        self.sync_state, self.sync_error, self.sync_timer = "idle", "", None
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
        return [dict(c, id=p.rsplit("/", 1)[-1], path=p, name=c["name"] or self.name_for(c["number"]))
                for p, c in sorted(self.calls.items()) if c["ag"] == ag and c["state"] in LIVE_STATES]

    # ---- contacts and history: the copy on the HU ---------------------------------
    def name_for(self, number: str) -> str:
        return next((c["name"] for c in self.book["contacts"]
                     if any(vcard.same_number(n["number"], number) for n in c["numbers"])), "") if number else ""

    @staticmethod
    def no_book() -> dict:
        return {"consent": None, "synced": 0, "contacts": [], "history": [], "favourites": []}

    def load_book(self, address: str):
        self.book_address = address
        self.book = self.store.load(address) if address else self.no_book()
        self.sync_state, self.sync_error = "idle", ""
        if address and self.book["consent"] is True and not self.book["synced"]:
            GLib.idle_add(lambda: self.start_sync() and False)     # allowed, never copied yet

    def save_book(self):
        if self.book_address:
            self.store.save(self.book_address, self.book)

    def start_sync(self) -> bool:
        address = self.book_address
        if not address or self.sync_state == "syncing":
            return False
        if self.pbap is None:
            self.sync_state, self.sync_error = "failed", "no OBEX service (obexd) for contacts"
            self.refresh()
            return False
        self.sync_state, self.sync_error = "syncing", ""
        log("copying contacts and call history from the phone")
        self.refresh()

        def done(contacts, history, error):
            if self.sync_timer:
                GLib.source_remove(self.sync_timer)
                self.sync_timer = None
            if address != self.book_address or self.sync_state != "syncing":
                return                                   # another phone by now, or timed out
            if error:
                self.sync_state, self.sync_error = "failed", error
                log(f"copying contacts failed: {error}")
            else:
                self.book.update(contacts=contacts, history=history, synced=int(time.time()))
                self.sync_state = "idle"
                log(f"copied {len(contacts)} contact(s) and {len(history)} call(s)")
                self.save_book()
            self.refresh()

        def timeout():
            self.sync_timer = None
            if self.sync_state == "syncing":
                self.sync_state, self.sync_error = "failed", "the phone did not answer"
                log("copying contacts failed: the phone did not answer")
                self.refresh()
            return False
        self.sync_timer = GLib.timeout_add_seconds(SYNC_TIMEOUT_S, timeout)
        self.pbap.sync(address, done)
        return True

    def favourites(self) -> list:
        by_id = {c["id"]: c for c in self.book["contacts"]}
        return [by_id[i] for i in self.book["favourites"] if i in by_id]

    def update_device(self):
        ag = self.current()
        address = self.ags[ag]["address"] if ag else ""
        if address != self.device["address"]:
            self.device = {"address": address, "name": address, "battery": -1}
            self.load_book(address)
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

    # ---- the call's sound (hu/callaudio.py) -------------------------------------
    def track_streams(self):
        """While a call is on, look for its PipeWire streams until they are there."""
        calling = self.props.get("CallState") in ("ringing", "dialing", "active")
        if not calling:
            self.streams = {}
            if self.mic_muted:
                self.mic_muted = False               # the next call starts with the microphone on
                self.set("MicMuted", False)
            if self.stream_timer:
                GLib.source_remove(self.stream_timer)
                self.stream_timer = None
        elif self.audio is not None and self.audio.ok and self.stream_timer is None:
            self.stream_timer = GLib.timeout_add(1000, self.find_streams)

    def find_streams(self) -> bool:
        if self.props.get("CallState") == "idle":
            self.stream_timer = None
            return False
        self.stream_ticks = getattr(self, "stream_ticks", 0) + 1
        if len(self.streams) == 2 and self.stream_ticks % 5:
            return True                              # both known: check every 5 s only (pw-dump costs)
        found = self.audio.streams(self.device["address"])
        if found is None:
            return True                              # PipeWire did not answer this time: keep the streams
        if found != self.streams:
            self.streams = found
            if found:
                log(f"call audio: streams {found}" + ("" if found.get("mic", True) else " - no microphone: muted"))
            self.apply_audio()
            self.refresh()
        return True                                  # keep looking: SCO can come and go

    def apply_audio(self):
        if self.audio is None:
            return
        if "down" in self.streams and "stage" in self.streams:
            self.audio.set_linear(self.streams["down"], 1.0)          # the phone at full level
            self.audio.set_linear(self.streams["stage"], self.gain)   # the level on the HU
        elif "down" in self.streams:
            self.audio.set_level(self.streams["down"], self.gain)
        if "up" in self.streams:
            # no real microphone: muted, or the phone would get the HU's output (monitor) back
            self.audio.set_mute(self.streams["up"], self.mic_muted or not self.streams.get("mic"))

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
        consent = self.book["consent"]
        self.set("Consent", "" if consent is None else "yes" if consent else "no")
        self.set("SyncState", self.sync_state)
        self.set("SyncError", self.sync_error)
        self.set("SyncedAt", int(self.book["synced"]))
        self.set("ContactCount", len(self.book["contacts"]))
        self.set("History", [dict(h, name=h["name"] or self.name_for(h["number"])) for h in self.book["history"]])
        self.set("Favourites", self.favourites())
        self.set("CallGain", self.gain)
        self.set("MicMuted", self.mic_muted)
        self.set("MicAvailable", bool(self.streams.get("mic", True)))
        self.push_audio()
        self.track_streams()

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
        if name == "CallGain":
            return dbus.Double(v)
        if name in ("SyncedAt",):
            return dbus.Int64(v)
        if name == "ContactCount":
            return dbus.Int32(v)
        if name == "History":
            return dbus.Array([dbus.Dictionary({k: dbus.String(h[k]) for k in ("name", "number", "kind", "time")},
                                               signature="sv") for h in v], signature="a{sv}")
        if name == "Favourites":
            return dbus.Array([self.contact(c) for c in v], signature="a{sv}")
        return dbus.Boolean(v) if isinstance(v, bool) else dbus.String(v)

    @staticmethod
    def contact(c: dict):
        numbers = dbus.Array([dbus.Dictionary({"number": n["number"], "type": n["type"]}, signature="sv")
                              for n in c["numbers"]], signature="a{sv}")
        return dbus.Dictionary({"id": c["id"], "name": c["name"], "numbers": numbers}, signature="sv")

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

    @dbus.service.method(IFACE, in_signature="du")
    def SetGain(self, gain, fade_ms):
        self.gain = max(0.0, min(float(gain), 8.0))     # above 1.0: the call boost
        self.apply_audio()
        self.refresh()

    @dbus.service.method(IFACE, in_signature="b")
    def SetMicMuted(self, muted):
        self.mic_muted = bool(muted)
        self.apply_audio()
        self.refresh()

    @dbus.service.method(IFACE, in_signature="b")
    def SetConsent(self, allowed):
        if not self.book_address:
            raise self.error("NoPhone", "no phone connected")
        self.book["consent"] = bool(allowed)
        self.save_book()
        if allowed:
            self.start_sync()
        self.refresh()

    @dbus.service.method(IFACE)
    def Sync(self):
        if not self.book_address:
            raise self.error("NoPhone", "no phone connected")
        if self.sync_state == "syncing":
            raise self.error("Busy", "already copying")
        self.book["consent"] = True                  # the user asked for it
        self.save_book()
        self.start_sync()
        self.refresh()

    @dbus.service.method(IFACE)
    def DeleteCopy(self):
        if not self.book_address:
            raise self.error("NoPhone", "no phone connected")
        self.book.update(consent=False, synced=0, contacts=[], history=[], favourites=[])
        self.save_book()
        log("deleted the copy of the phone's contacts and call history")
        self.refresh()

    @dbus.service.method(IFACE, in_signature="ii", out_signature="aa{sv}")
    def GetContacts(self, offset, count):
        offset, count = max(0, int(offset)), max(0, int(count))
        return dbus.Array([self.contact(c) for c in self.book["contacts"][offset:offset + count]], signature="a{sv}")

    @dbus.service.method(IFACE, in_signature="sb")
    def SetFavourite(self, contact_id, on):
        contact_id = str(contact_id)
        if not any(c["id"] == contact_id for c in self.book["contacts"]):
            raise self.error("Failed", "no such contact")
        favs = [f for f in self.book["favourites"] if f != contact_id]
        self.book["favourites"] = favs + [contact_id] if on else favs
        self.save_book()
        self.refresh()

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
    ap.add_argument("--obex", default="session", metavar="BUS",
                    help="where BlueZ's obexd (contacts, PBAP) is: system, session, a D-Bus address or none (default session)")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    ap.add_argument("--state-dir", default=str(state_home / "r80" / "phone"),
                    help="the copies of the phones' contacts, one file each (default ~/.local/state/r80/phone)")
    ap.add_argument("--history-max", type=int, default=50, help="calls of the history to copy (default 50)")
    ap.add_argument("--call-audio", choices=("pipewire", "none"), default="pipewire",
                    help="put the phone volume and the microphone mute on the call's PipeWire streams (default pipewire)")
    a = ap.parse_args()
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus() if a.system else dbus.SessionBus()
    name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)  # noqa: F841 (keeps the name)
    tel = bus_for(a.telephony)
    bluez = None if a.bluez == "none" else bus_for(a.bluez)
    pbap = None if a.obex == "none" else PbapClient(bus_for(a.obex), log, a.history_max)
    Phone(bus, tel, bluez, pbap, Store(Path(a.state_dir).expanduser()),
          CallAudio(log) if a.call_audio == "pipewire" else None)
    log(f"serving {BUS_NAME} on the {'system' if a.system else 'session'} bus; telephony on {a.telephony}, "
        f"BlueZ on {a.bluez}, OBEX on {a.obex}")
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
