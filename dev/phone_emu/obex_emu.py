"""A stand-in for BlueZ's obexd (org.bluez.obex) for contacts over PBAP, PC only.

What hu-phoned (hu/phonebook.py) talks to on the target: Client1.CreateSession(address,
{Target: pbap}) -> session; PhonebookAccess1.Select(location, phonebook) and PullAll(file,
filters) -> (transfer, {Filename}); Transfer1.Status queued -> active -> complete | error;
Client1.RemoveSession. The phonebooks are vCard texts per phone address, written to a
temporary file per transfer as obexd does:

    obex = FakeObex(conn, outdir, {"AA:BB:...": {"pb": vcards, "cch": vcards}})
    conn.request_name("org.bluez.obex")
    obex.refuse.add("AA:BB:...")              # the phone's user does not allow it
    obex.sessions, obex.removed, obex.pulls   # what the HU asked for
"""
from __future__ import annotations

from pathlib import Path

import dbus
import dbus.service
from gi.repository import GLib

OBEX = "org.bluez.obex"
CLIENT_PATH, CLIENT = "/org/bluez/obex", "org.bluez.obex.Client1"
PBAP, TRANSFER = "org.bluez.obex.PhonebookAccess1", "org.bluez.obex.Transfer1"
PROPS = "org.freedesktop.DBus.Properties"


class Transfer(dbus.service.Object):
    def __init__(self, conn, path: str, filename: str, fail: bool):
        super().__init__(conn, path)
        self.props = {"Status": "queued", "Filename": filename}
        GLib.timeout_add(50, self.step, "active")
        GLib.timeout_add(150, self.step, "error" if fail else "complete")

    def step(self, status):
        self.props["Status"] = status
        self.PropertiesChanged(TRANSFER, dbus.Dictionary({"Status": status}, signature="sv"), dbus.Array([], signature="s"))
        if status in ("complete", "error"):
            GLib.timeout_add(100, lambda: self.remove_from_connection() and False)   # obexd drops it
        return False

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.props[str(name)]

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class Session(dbus.service.Object):
    def __init__(self, obex: "FakeObex", path: str, address: str):
        super().__init__(obex.conn, path)
        self.obex, self.path, self.address, self.phonebook = obex, path, address, "pb"

    @dbus.service.method(PBAP, in_signature="ss")
    def Select(self, location, phonebook):
        self.phonebook = str(phonebook)

    @dbus.service.method(PBAP, in_signature="sa{sv}", out_signature="oa{sv}")
    def PullAll(self, targetfile, filters):
        o = self.obex
        o.pulls.append((self.address, self.phonebook, {str(k): (str(v) if isinstance(v, dbus.String) else int(v))
                                                       for k, v in filters.items()}))
        o.count += 1
        text = o.books.get(self.address, {}).get(self.phonebook, "")
        f = o.outdir / f"pbap-{o.count}.vcf"
        f.write_text(text, encoding="utf-8")
        path = f"{self.path}/transfer{o.count}"
        o.transfers.append(Transfer(o.conn, path, str(f), self.address in o.fail_transfer))
        return dbus.ObjectPath(path), dbus.Dictionary({"Filename": str(f), "Size": dbus.UInt64(len(text))}, signature="sv")


class FakeObex(dbus.service.Object):
    def __init__(self, conn, outdir: Path, books: dict):
        super().__init__(conn, CLIENT_PATH)
        self.conn, self.outdir, self.books = conn, Path(outdir), books
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.refuse: set[str] = set()
        self.fail_transfer: set[str] = set()
        self.sessions, self.removed, self.pulls, self.transfers = [], [], [], []
        self.count = 0

    @dbus.service.method(CLIENT, in_signature="sa{sv}", out_signature="o")
    def CreateSession(self, destination, args):
        address = str(destination)
        if str(args.get("Target", "")).lower() != "pbap":
            raise dbus.exceptions.DBusException("only PBAP here", name="org.bluez.obex.Error.InvalidArguments")
        if address in self.refuse or address not in self.books:
            raise dbus.exceptions.DBusException("Unable to connect", name="org.bluez.obex.Error.Failed")
        path = f"{CLIENT_PATH}/client/session{len(self.sessions) + 1}"
        self.sessions.append(Session(self, path, address))
        return dbus.ObjectPath(path)

    @dbus.service.method(CLIENT, in_signature="o")
    def RemoveSession(self, session):
        for s in [s for s in self.sessions if s.path == str(session)]:
            self.removed.append(s.path)
            s.remove_from_connection()
