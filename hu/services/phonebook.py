"""Contacts and call history from the phone (PBAP over BlueZ's obexd), and their copy on the HU.

PbapClient asks obexd (org.bluez.obex, on the desktop's session bus on the bench) for one
phone's phonebook ("pb") and combined call history ("cch") in one OBEX session:

    Client1.CreateSession(address, {Target: pbap}) -> session
    PhonebookAccess1.Select("int", "pb"), PullAll("", {Format: vcard30}) -> transfer, {Filename}
    Transfer1.Status: queued -> active -> complete | error; then the file is read and deleted
    ... the same for "cch" (MaxCount history_max), Client1.RemoveSession(session)

The phone may ask its user to allow the access the first time (Android: "Allow access to
contacts and call history?"), so CreateSession can take a while.

Store keeps one JSON file per phone (mode 0600, the HU's state directory, never the repo,
never logged): consent (None = not asked yet, True / False), synced (unix s), contacts,
history, favourites (contact ids: local to the HU, they survive a re-sync).
Needs a dbus-python bus with a GLib main loop for PbapClient; standard library otherwise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import dbus

import vcard

OBEX = "org.bluez.obex"
CLIENT_PATH, CLIENT = "/org/bluez/obex", "org.bluez.obex.Client1"
PBAP, TRANSFER = "org.bluez.obex.PhonebookAccess1", "org.bluez.obex.Transfer1"
PROPS = "org.freedesktop.DBus.Properties"
# What a phone's OBEX refusal means for the driver (obexd: "OBEX Connect failed with 0x53")
REFUSALS = {"0x41": "the phone did not allow access to its contacts",
            "0x43": "the phone did not allow access to its contacts",
            "0x53": "the phone does not share its contacts with this headunit: allow contact sharing "
                    "for it in the phone's Bluetooth settings"}


def readable(message: str) -> str:
    return next((text for code, text in REFUSALS.items() if code in message), message)


class PbapClient:
    def __init__(self, bus, log=print, history_max: int = 50):
        self.bus, self.log, self.history_max = bus, log, history_max
        self.transfers: dict[str, tuple] = {}            # transfer path -> (filename, done)
        bus.add_signal_receiver(self.on_transfer, "PropertiesChanged", PROPS, OBEX, None, path_keyword="path")

    def available(self) -> bool:
        try:
            return self.bus.name_has_owner(OBEX) or OBEX in self.bus.list_activatable_names()
        except dbus.exceptions.DBusException:
            return False

    def sync(self, address: str, done):
        """Fetch contacts and history; done(contacts, history, None) or done(None, None, error)."""
        state = {"session": None, "results": {}}

        def fail(e):
            msg = e.get_dbus_message() if isinstance(e, dbus.exceptions.DBusException) else str(e)
            if state["session"]:
                self.remove(state["session"])
            done(None, None, readable(msg or "failed"))

        def pull(phonebook, filters, then):
            def selected(*_):
                self.bus.call_async(OBEX, state["session"], PBAP, "PullAll", "sa{sv}", ("", filters),
                                    lambda path, props: self.watch(str(path), str(props.get("Filename", "")),
                                                                   lambda text, err: got(phonebook, text, err, then)),
                                    fail, timeout=60.0)
            self.bus.call_async(OBEX, state["session"], PBAP, "Select", "ss", ("int", phonebook), selected, fail, timeout=30.0)

        def got(phonebook, text, err, then):
            if err:
                return fail(err)
            state["results"][phonebook] = text
            then()

        def finish():
            self.remove(state["session"])
            done(vcard.contacts(state["results"].get("pb", "")), vcard.history(state["results"].get("cch", "")), None)

        def created(session):
            state["session"] = str(session)
            fmt = dbus.Dictionary({"Format": "vcard30"}, signature="sv")
            hist = dbus.Dictionary({"Format": "vcard30", "MaxCount": dbus.UInt16(self.history_max)}, signature="sv")
            pull("pb", fmt, lambda: pull("cch", hist, finish))

        self.bus.call_async(OBEX, CLIENT_PATH, CLIENT, "CreateSession", "sa{sv}",
                            (address, dbus.Dictionary({"Target": "pbap"}, signature="sv")), created, fail,
                            timeout=120.0)              # the phone may first ask its user

    def watch(self, path: str, filename: str, done):
        self.transfers[path] = (filename, done)
        # it may already be over before we listen: ask once
        self.bus.call_async(OBEX, path, PROPS, "Get", "ss", (TRANSFER, "Status"),
                            lambda status: self.on_transfer(TRANSFER, {"Status": status}, [], path=path),
                            lambda *_: None, timeout=10.0)

    def on_transfer(self, iface, changed, _invalidated, path=None):
        if str(iface) != TRANSFER or str(path) not in self.transfers or "Status" not in changed:
            return
        status = str(changed["Status"])
        if status not in ("complete", "error"):
            return
        filename, done = self.transfers.pop(str(path))
        if status == "error":
            return done(None, "transfer failed")
        try:
            text = Path(filename).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return done(None, f"cannot read the transfer: {e.strerror}")
        try:
            os.unlink(filename)                          # obexd's temporary file: personal data
        except OSError:
            pass
        done(text, None)

    def remove(self, session):
        self.bus.call_async(OBEX, CLIENT_PATH, CLIENT, "RemoveSession", "o", (dbus.ObjectPath(session),),
                            lambda *_: None, lambda *_: None, timeout=10.0)


class Store:
    """One file per phone: consent, synced, contacts, history, favourites."""

    def __init__(self, directory: Path):
        self.dir = directory

    def file(self, address: str) -> Path:
        return self.dir / (address.replace(":", "").upper() + ".json")

    def load(self, address: str) -> dict:
        try:
            data = json.loads(self.file(address).read_text())
        except (OSError, ValueError):
            data = {}
        return {"consent": data.get("consent"), "synced": data.get("synced", 0), "contacts": data.get("contacts", []),
                "history": data.get("history", []), "favourites": data.get("favourites", [])}

    def save(self, address: str, data: dict):
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        f = self.file(address)
        tmp = f.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        os.replace(tmp, f)
