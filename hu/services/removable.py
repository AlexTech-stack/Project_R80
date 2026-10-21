"""Removable media for hu-mediad: USB sticks through udisks2 (org.freedesktop.UDisks2).

Watches udisks2's objects. A filesystem counts as removable media when udisks does not
mark it as a system or ignored device, it is not in /etc/fstab (the bench's own
storage stick is), and udisks would mount it automatically (HintAuto) or its drive is
on USB. A disk image a user (not root) attached with `udisksctl loop-setup` counts as
a stick too, although udisks marks every loop device as a system device (the bench's
test stick, docs/bench-pi.md). Such a filesystem is used where it is mounted, or mounted read-only first
(Filesystem.Mount with options=ro, without a password prompt; on the target a polkit
rule must allow that for the HU's user). It is gone when udisks removes it or it is
unmounted.

    watcher = RemovableMedia(bus, on_added, on_removed)
    on_added(key, name, mount_path, initial)    key: "usb:<filesystem UUID>", name: its label or "",
                                                initial: it was there when udisks2 was first asked
    on_removed(key)

    watcher.open_for_writing(key, done, failed)  # key "" = the first stick: unmount, mount writable,
                                                 # done(key, mount_path) | failed(reason)
    watcher.close_for_writing(key, done)         # unmount, mount read-only again: done(mount_path | None)

While a stick is lent out for writing (hu-sysd's log export), its mounts changing is not a
medium going or coming; pulling it still is.

Runs udisks2 on the system bus on the target; the BoAt tests put a stand-in on the
session bus (mediad --usb session). Needs a dbus-python bus with a GLib main loop.
"""
from __future__ import annotations

import dbus

import dlt

log = dlt.context("USB", "USB sticks (udisks2)")
UDISKS = "org.freedesktop.UDisks2"
ROOT = "/org/freedesktop/UDisks2"
OM = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
BLOCK, FS, DRIVE, LOOP = UDISKS + ".Block", UDISKS + ".Filesystem", UDISKS + ".Drive", UDISKS + ".Loop"


def _message(e) -> str:
    return e.get_dbus_message() if hasattr(e, "get_dbus_message") else str(e)


def _path(mount_point) -> str:
    """A MountPoints entry (aay, NUL-terminated bytes) as a str."""
    return bytes(mount_point).rstrip(b"\x00").decode("utf-8", "replace")


class RemovableMedia:
    def __init__(self, bus, on_added, on_removed):
        self.bus = bus
        self.on_added, self.on_removed = on_added, on_removed
        self.objects: dict[str, dict] = {}     # object path -> {interface: {property: value}}
        self.present: dict[str, str] = {}      # object path -> key of a medium in use
        self.mounting: set[str] = set()
        self.initial: set[str] = set()         # filesystems udisks2 listed at our start
        self.writing: set[str] = set()         # object paths lent out writable (or on their way)
        bus.add_signal_receiver(self.on_ifaces_added, "InterfacesAdded", OM, UDISKS, ROOT)
        bus.add_signal_receiver(self.on_ifaces_removed, "InterfacesRemoved", OM, UDISKS, ROOT)
        bus.add_signal_receiver(self.on_props, "PropertiesChanged", PROPS, UDISKS, None, path_keyword="path")
        bus.add_signal_receiver(self.on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                                "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=UDISKS)
        if bus.name_has_owner(UDISKS):
            self.load()
        else:
            log.info("waiting for udisks2")

    # ---- udisks2 objects -------------------------------------------------
    def load(self):
        self.bus.call_async(UDISKS, ROOT, OM, "GetManagedObjects", "", (), self.on_objects,
                            lambda e: log.error(f"udisks2: {e}"), timeout=5.0)

    def on_objects(self, objects):
        self.objects = {str(p): {str(i): dict(props) for i, props in ifaces.items()} for p, ifaces in objects.items()}
        # only filesystems: udisks keeps loop0..7 as objects, a stick may appear on one later
        self.initial = {p for p, ifaces in self.objects.items() if FS in ifaces}
        for path in list(self.objects):
            self.check(path)

    def on_owner(self, _name, _old, new):
        for path in list(self.present):
            self.gone(path)
        self.objects.clear()
        if new:
            self.load()

    def on_ifaces_added(self, path, ifaces):
        path = str(path)
        self.objects.setdefault(path, {}).update({str(i): dict(p) for i, p in ifaces.items()})
        self.check(path)

    def on_ifaces_removed(self, path, ifaces):
        path = str(path)
        obj = self.objects.get(path, {})
        for i in ifaces:
            obj.pop(str(i), None)
        if FS not in obj:
            self.initial.discard(path)                     # what comes here next is plugged in
        if not obj:
            self.objects.pop(path, None)
        if path in self.present and (FS not in obj or BLOCK not in obj):
            self.gone(path)

    def on_props(self, iface, changed, _invalidated, path=None):
        path = str(path)
        if path in self.objects and str(iface) in self.objects[path]:
            self.objects[path][str(iface)].update({str(k): v for k, v in changed.items()})
            self.check(path)

    # ---- removable or not, mounted or not ----------------------------------
    def candidate(self, path: str) -> bool:
        obj = self.objects.get(path, {})
        block, fs = obj.get(BLOCK), obj.get(FS)
        if block is None or fs is None or block.get("HintIgnore"):
            return False
        if any(str(kind) == "fstab" for kind, _details in block.get("Configuration", [])):
            return False                                   # mounted by the system, e.g. /mnt/r80
        if LOOP in obj:
            return int(obj[LOOP].get("SetupByUID", 0)) != 0      # a user's disk image: a test stick
        if block.get("HintSystem"):
            return False
        drive = self.objects.get(str(block.get("Drive", "/")), {}).get(DRIVE, {})
        return bool(block.get("HintAuto")) or str(drive.get("ConnectionBus", "")) == "usb"

    def key(self, path: str) -> str:
        block = self.objects[path][BLOCK]
        return "usb:" + (str(block.get("IdUUID", "")) or path.rsplit("/", 1)[-1])

    def check(self, path: str):
        if not self.candidate(path):
            if path in self.present:
                self.gone(path)
            return
        if path in self.writing:                           # unmounted / remounted on purpose
            return
        mounts = [_path(m) for m in self.objects[path][FS].get("MountPoints", [])]
        if mounts:
            if path not in self.present:
                key = self.key(path)
                self.present[path] = key                   # the same medium on a new device: on_added again
                log.info(f"removable medium {key} at {mounts[0]}")
                self.on_added(key, str(self.objects[path][BLOCK].get("IdLabel", "")), mounts[0], path in self.initial)
        elif path in self.present:
            self.gone(path)                                # unmounted under us
        elif path not in self.mounting:
            self.mount(path)

    def mount(self, path: str, options: str = "ro", done=None, failed=None):
        self.mounting.add(path)
        opts = dbus.Dictionary({"options": options, "auth.no_user_interaction": True}, signature="sv")

        def ok(mount_path):
            self.mounting.discard(path)
            if path in self.objects:                       # MountPoints may not have changed yet
                self.objects[path][FS]["MountPoints"] = [dbus.ByteArray(str(mount_path).encode() + b"\x00")]
            if done:
                done(str(mount_path))
            else:
                self.check(path)

        def err(e):
            self.mounting.discard(path)
            log.warning(f"cannot mount {path} ({options}): {_message(e)}")
            if failed:
                failed(_message(e))
        self.bus.call_async(UDISKS, path, FS, "Mount", "a{sv}", (opts,), ok, err, timeout=30.0)

    def unmount(self, path: str, done, failed):
        opts = dbus.Dictionary({"auth.no_user_interaction": True}, signature="sv")

        def err(e):
            log.error(f"cannot unmount {path}: {_message(e)}")
            failed(_message(e))
        self.bus.call_async(UDISKS, path, FS, "Unmount", "a{sv}", (opts,), lambda *_: done(), err, timeout=30.0)

    # ---- lent out writable (the log export) ---------------------------------
    def open_for_writing(self, key: str, done, failed):
        path = next((p for p, k in self.present.items() if not key or k == key), None)
        if path is None or path in self.writing:
            failed("no USB stick" if path is None else "the stick is already lent out")
            return
        key = self.present[path]
        self.writing.add(path)

        def back(reason):
            self.writing.discard(path)
            self.check(path)                               # mounted read-only again if it can be
            failed(reason)
        self.unmount(path, lambda: self.mount(path, "rw", lambda mp: done(key, mp), back), back)

    def close_for_writing(self, key: str, done):
        path = next((p for p, k in self.present.items() if k == key and p in self.writing), None)
        if path is None:
            done(None)
            return

        def mounted(mp):
            self.writing.discard(path)
            done(mp)

        def failed(_reason):
            self.writing.discard(path)
            self.check(path)
            done(None)
        self.unmount(path, lambda: self.mount(path, "ro", mounted, failed), failed)

    def gone(self, path: str):
        self.writing.discard(path)
        key = self.present.pop(path, None)
        if key and key not in self.present.values():      # not still there on another device
            log.info(f"removable medium {key} gone")
            self.on_removed(key)
