"""A stand-in for BlueZ's AVRCP player of a connected phone (org.bluez.MediaPlayer1), PC only.

What hu-mediad (hu/btmedia.py) talks to on the target: the ObjectManager at "/" with the
phone (/org/bluez/hci0/dev_XX: Device1 Address, Alias) and its player (.../player0:
Status, Track, Position, Shuffle, Repeat; Play, Pause, Next, Previous). The phone side is
driven from Python by the BoAt tests:

    bz = FakePlayerBlueZ(conn)                   # conn: dbus-python connection with a GLib main loop
    conn.request_name("org.bluez")
    phone = bz.add_phone("AA:BB:CC:00:03:01", "Test Phone")
    player = bz.add_player(phone, [{"Title": ..., "Artist": ..., "Duration": ms}, ...])
    player.play_on_phone()                       # the driver starts music on the phone
    player.calls                                 # what the HU asked for: Play, Pause, Next, ...
    bz.remove_player(player)                     # A2DP / AVRCP gone
"""
from __future__ import annotations

import dbus
import dbus.service

BLUEZ, OM, PROPS = "org.bluez", "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
PLAYER, DEVICE = BLUEZ + ".MediaPlayer1", BLUEZ + ".Device1"


class Player(dbus.service.Object):
    def __init__(self, bz: "FakePlayerBlueZ", path: str, tracks: list):
        super().__init__(bz.conn, path)
        self.bz, self.path, self.tracks, self.i = bz, path, tracks, 0
        self.calls: list[str] = []
        self.props = {"Status": "paused", "Position": 0, "Shuffle": "off", "Repeat": "off", "Name": "Music",
                      "Track": self.track()}

    def track(self):
        t = self.tracks[self.i]
        return dbus.Dictionary({"Title": t["Title"], "Artist": t.get("Artist", ""), "Album": t.get("Album", ""),
                                "TrackNumber": dbus.UInt32(self.i + 1), "NumberOfTracks": dbus.UInt32(len(self.tracks)),
                                "Duration": dbus.UInt32(t.get("Duration", 180000))}, signature="sv")

    def wire(self, k, v):
        if k == "Position":
            return dbus.UInt32(v)
        return v if isinstance(v, dbus.Dictionary) else dbus.String(v)

    def ifaces(self):
        return {PLAYER: dbus.Dictionary({k: self.wire(k, v) for k, v in self.props.items()}, signature="sv")}

    def change(self, **changed):
        self.props.update(changed)
        self.PropertiesChanged(PLAYER, dbus.Dictionary({k: self.wire(k, v) for k, v in changed.items()}, signature="sv"),
                               dbus.Array([], signature="s"))

    def play_on_phone(self):
        """The driver presses play on the phone itself."""
        self.change(Status="playing")

    @dbus.service.method(PLAYER)
    def Play(self):
        self.calls.append("Play")
        self.change(Status="playing")

    @dbus.service.method(PLAYER)
    def Pause(self):
        self.calls.append("Pause")
        self.change(Status="paused")

    @dbus.service.method(PLAYER)
    def Next(self):
        self.calls.append("Next")
        self.i = (self.i + 1) % len(self.tracks)
        self.change(Track=self.track(), Position=0)

    @dbus.service.method(PLAYER)
    def Previous(self):
        self.calls.append("Previous")
        self.i = (self.i - 1) % len(self.tracks)
        self.change(Track=self.track(), Position=0)

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.wire(str(name), self.props[str(name)])

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.ifaces()[PLAYER]

    @dbus.service.method(PROPS, in_signature="ssv")
    def Set(self, iface, name, value):
        self.calls.append(f"Set {name}={value}")
        self.change(**{str(name): str(value)})

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class FakePlayerBlueZ(dbus.service.Object):
    def __init__(self, conn):
        super().__init__(conn, "/")
        self.conn = conn
        self.devices: dict[str, dict] = {}
        self.players: dict[str, Player] = {}

    def add_phone(self, address: str, alias: str) -> str:
        path = "/org/bluez/hci0/dev_" + address.replace(":", "_")
        self.devices[path] = {"Address": address, "Alias": alias, "Connected": True}
        self.InterfacesAdded(dbus.ObjectPath(path), self.device_ifaces(path))
        return path

    def device_ifaces(self, path):
        d = self.devices[path]
        return {DEVICE: dbus.Dictionary({"Address": d["Address"], "Alias": d["Alias"], "Connected": d["Connected"]},
                                        signature="sv")}

    def add_player(self, device_path: str, tracks: list) -> Player:
        player = Player(self, device_path + "/player0", tracks)
        self.players[player.path] = player
        self.InterfacesAdded(dbus.ObjectPath(player.path), player.ifaces())
        return player

    def remove_player(self, player: Player):
        self.players.pop(player.path, None)
        self.InterfacesRemoved(dbus.ObjectPath(player.path), dbus.Array([PLAYER], signature="s"))
        player.remove_from_connection()

    @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        objs = {dbus.ObjectPath(p): self.device_ifaces(p) for p in self.devices}
        objs.update({dbus.ObjectPath(p): pl.ifaces() for p, pl in self.players.items()})
        return dbus.Dictionary(objs, signature="oa{sa{sv}}")

    @dbus.service.signal(OM, signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal(OM, signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass
