"""Music from the phone for hu-mediad: the phone's AVRCP player in BlueZ (org.bluez.MediaPlayer1).

BlueZ publishes the connected phone's player (/org/bluez/hciN/dev_XX/playerN) while A2DP and
AVRCP are up: Status (playing | paused | stopped | forward-seek | reverse-seek | error),
Track (Title, Artist, Album, TrackNumber, NumberOfTracks, Duration ms), Position (ms, sent
on changes only), Shuffle (off | alltracks | group), Repeat (off | singletrack | alltracks |
group); Play, Pause, Next, Previous. The sound itself is PipeWire's (A2DP stream, see
mediad); this only watches and remote-controls the player.

    player = PhonePlayer(bus, on_change)     # on_change(): appeared, gone or changed
    player.present, player.address, player.name, player.track(), player.playing(), player.position_us()
    player.call("Play" | "Pause" | "Next" | "Previous"), player.set_shuffle(b), player.set_repeat(b)

One phone at a time: the player that appeared last. Needs a dbus-python bus with a GLib
main loop (BlueZ on the system bus; the tests' stand-in on the session bus).
"""
from __future__ import annotations

import time

import dbus

import dlt

log = dlt.context("BTPL", "The phone's music player (AVRCP)")
BLUEZ = "org.bluez"
OM, PROPS = "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
PLAYER, DEVICE = BLUEZ + ".MediaPlayer1", BLUEZ + ".Device1"


def _py(v):
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, (dbus.String, dbus.ObjectPath)):
        return str(v)
    if isinstance(v, (dbus.Byte, dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64)):
        return int(v)
    if isinstance(v, dbus.Dictionary):
        return {str(k): _py(x) for k, x in v.items()}
    if isinstance(v, dbus.Array):
        return [_py(x) for x in v]
    return v


class PhonePlayer:
    def __init__(self, bus, on_change):
        self.bus, self.on_change = bus, on_change
        self.players: dict[str, dict] = {}         # player path -> props (+ "_order", "_at")
        self.devices: dict[str, dict] = {}         # device path -> Device1 props
        self.order = 0
        bus.add_signal_receiver(self.on_added, "InterfacesAdded", OM, BLUEZ, "/")
        bus.add_signal_receiver(self.on_removed, "InterfacesRemoved", OM, BLUEZ, "/")
        bus.add_signal_receiver(self.on_props, "PropertiesChanged", PROPS, BLUEZ, None, path_keyword="path")
        bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=BLUEZ)
        if bus.name_has_owner(BLUEZ):
            self.load()

    # ---- BlueZ objects ---------------------------------------------------
    def load(self):
        self.bus.call_async(BLUEZ, "/", OM, "GetManagedObjects", "", (), self.on_objects,
                            lambda e: None, timeout=5.0)      # a BlueZ without players (or a stand-in): nothing

    def on_objects(self, objects):
        for path, ifaces in objects.items():
            self.on_added(path, ifaces, notify=False)
        self.on_change()

    def on_owner(self, _name, _old, new):
        had = self.present
        self.players.clear()
        self.devices.clear()
        if had:
            self.on_change()
        if new:
            self.load()

    def on_added(self, path, ifaces, notify=True):
        path = str(path)
        if DEVICE in ifaces:
            self.devices[path] = _py(ifaces[DEVICE])
        if PLAYER in ifaces and path in self.players:     # listed and announced at the same time
            self.players[path].update(_py(ifaces[PLAYER]))
        elif PLAYER in ifaces:
            self.order += 1
            self.players[path] = dict(_py(ifaces[PLAYER]), _order=self.order, _at=time.monotonic())
            log.info(f"phone player: {path.rsplit('/', 1)[-1]} of {dlt.address(self.device_of(path).get('Address', '?'))}")
            if notify:
                self.on_change()

    def on_removed(self, path, ifaces):
        path = str(path)
        if PLAYER in ifaces and path in self.players:
            del self.players[path]
            log.info("phone player gone")
            self.on_change()
        if DEVICE in ifaces:
            self.devices.pop(path, None)

    def on_props(self, iface, changed, _invalidated, path=None):
        path = str(path)
        if str(iface) == PLAYER and path in self.players:
            changed = _py(changed)
            p = self.players[path]
            if "Position" in changed or "Status" in changed:
                p["_at"] = time.monotonic()           # Position is only sent on changes: count from here
            p.update(changed)
            self.on_change()
        elif str(iface) == DEVICE and path in self.devices:
            self.devices[path].update(_py(changed))

    # ---- the current player --------------------------------------------------
    def current(self) -> str | None:
        return max(self.players, key=lambda p: self.players[p]["_order"]) if self.players else None

    @property
    def present(self) -> bool:
        return bool(self.players)

    def device_of(self, player_path: str) -> dict:
        return self.devices.get(player_path.rsplit("/", 1)[0], {})

    @property
    def address(self) -> str:
        p = self.current()
        return self.device_of(p).get("Address", "") if p else ""

    @property
    def name(self) -> str:
        p = self.current()
        d = self.device_of(p) if p else {}
        return d.get("Alias") or d.get("Name") or self.address

    def props(self) -> dict:
        p = self.current()
        return self.players[p] if p else {}

    def playing(self) -> bool:
        return self.props().get("Status") in ("playing", "forward-seek", "reverse-seek")

    def track(self) -> dict:
        t = self.props().get("Track", {})
        return {"title": t.get("Title", "") or "", "artist": t.get("Artist", "") or "", "album": t.get("Album", "") or "",
                "trackNumber": int(t.get("TrackNumber", 0) or 0), "duration": int(t.get("Duration", 0) or 0) // 1000,
                "cover": ""}

    def position_us(self) -> int:
        p = self.props()
        pos = int(p.get("Position", 0) or 0) * 1000
        if self.playing():
            pos += int((time.monotonic() - p.get("_at", time.monotonic())) * 1_000_000)
        duration = self.track()["duration"] * 1_000_000
        return min(pos, duration) if duration else pos

    def shuffle(self) -> bool:
        return self.props().get("Shuffle", "off") not in ("off", "")

    def repeat(self) -> bool:
        return self.props().get("Repeat", "off") not in ("off", "")

    # ---- remote control --------------------------------------------------------
    def call(self, method: str):
        p = self.current()
        if p:
            self.bus.call_async(BLUEZ, p, PLAYER, method, "", (), lambda *_: None,
                                lambda e: log.warning(f"phone player {method}: {e}"), timeout=5.0)

    def set(self, prop: str, value: str):
        p = self.current()
        if p:
            self.bus.call_async(BLUEZ, p, PROPS, "Set", "ssv", (PLAYER, prop, dbus.String(value, variant_level=1)),
                                lambda *_: None, lambda e: log.warning(f"phone player {prop}: {e}"), timeout=5.0)

    def set_shuffle(self, on: bool):
        self.set("Shuffle", "alltracks" if on else "off")

    def set_repeat(self, on: bool):
        self.set("Repeat", "alltracks" if on else "off")
