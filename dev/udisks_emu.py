"""A stand-in for udisks2 (org.freedesktop.UDisks2) with USB sticks, PC only.

What hu-mediad (hu/services/removable.py) talks to on the target: the ObjectManager at
/org/freedesktop/UDisks2 with drives and block devices (Block, Filesystem: MountPoints,
Mount(options) -> mount path, Unmount). A "stick" is a folder on the PC; mounting it
just reports that folder. Driven from Python by the BoAt tests:

    ud = FakeUDisks(conn)                       # conn: dbus-python connection with a GLib main loop
    conn.request_name("org.freedesktop.UDisks2")
    stick = ud.add("sdz", "UUID-1", "LABEL", "/path/of/the/folder")
    stick.mount_calls, stick.unmount_calls      # what the HU asked for (Mount's options)
    ud.remove("sdz")                            # pulled
"""
from __future__ import annotations

import dbus
import dbus.service

UD = "org.freedesktop.UDisks2"
ROOT = "/org/freedesktop/UDisks2"
OM, PROPS = "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
BLOCK, FS, DRIVE = UD + ".Block", UD + ".Filesystem", UD + ".Drive"


def mounts(*paths):
    return dbus.Array([dbus.ByteArray(p.encode() + b"\x00") for p in paths], signature="ay")


class Device(dbus.service.Object):
    """A block device with a filesystem: Filesystem.Mount and Unmount, as udisks2 does them."""

    def __init__(self, conn, path, fake, mount_dir):
        super().__init__(conn, path)
        self.fake, self.mount_dir, self.mount_calls, self.unmount_calls = fake, mount_dir, [], 0
        self.fail_unmount = None                  # an error name: Unmount fails like a busy filesystem

    def set_mounts(self, value):
        self.fake.objects[self._object_path][FS]["MountPoints"] = value
        self.PropertiesChanged(FS, {"MountPoints": value}, dbus.Array([], signature="s"))

    @dbus.service.method(FS, in_signature="a{sv}", out_signature="s")
    def Mount(self, options):
        if self.fake.objects[self._object_path][FS]["MountPoints"]:
            raise dbus.exceptions.DBusException("already mounted", name=UD + ".Error.AlreadyMounted")
        self.mount_calls.append({str(k): v for k, v in options.items()})
        self.set_mounts(mounts(self.mount_dir))
        return self.mount_dir

    @dbus.service.method(FS, in_signature="a{sv}")
    def Unmount(self, options):
        if self.fail_unmount:
            raise dbus.exceptions.DBusException("target is busy", name=UD + ".Error." + self.fail_unmount)
        self.unmount_calls += 1
        self.set_mounts(mounts())

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass


class FakeUDisks(dbus.service.Object):
    def __init__(self, conn):
        super().__init__(conn, ROOT)
        self.conn, self.objects, self.devices = conn, {}, {}

    @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return self.objects

    @dbus.service.signal(OM, signature="oa{sa{sv}}")
    def InterfacesAdded(self, path, ifaces):
        pass

    @dbus.service.signal(OM, signature="oas")
    def InterfacesRemoved(self, path, ifaces):
        pass

    def add(self, name, uuid, label, mount_dir, mounted_at=None, fstab=False, signal=True) -> Device:
        drive = f"{ROOT}/drives/{name}"
        block = f"{ROOT}/block_devices/{name}1"
        self.objects[drive] = {DRIVE: {"ConnectionBus": "usb", "Removable": True, "MediaRemovable": False}}
        config = [("fstab", {"dir": dbus.ByteArray(b"/mnt/r80\x00")})] if fstab else []
        self.objects[block] = {
            BLOCK: {"Drive": dbus.ObjectPath(drive), "IdUUID": uuid, "IdLabel": label, "HintSystem": False,
                    "HintIgnore": False, "HintAuto": True,
                    "Configuration": dbus.Array(config, signature="(sa{sv})")},
            FS: {"MountPoints": mounts(mounted_at) if mounted_at else mounts()}}
        self.devices[block] = Device(self.conn, block, self, mount_dir)
        if signal:
            self.InterfacesAdded(dbus.ObjectPath(drive), self.objects[drive])
            self.InterfacesAdded(dbus.ObjectPath(block), self.objects[block])
        return self.devices[block]

    def remove(self, name):
        for path, ifaces in ((f"{ROOT}/block_devices/{name}1", [BLOCK, FS]), (f"{ROOT}/drives/{name}", [DRIVE])):
            self.objects.pop(path, None)
            self.InterfacesRemoved(dbus.ObjectPath(path), dbus.Array(ifaces, signature="s"))
            if path in self.devices:
                self.devices.pop(path).remove_from_connection()
