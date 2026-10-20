#!/usr/bin/env python3
"""TC_HU_030: USB sticks as media sources (hu/removable.py, udisks2). A stand-in for
udisks2 on the session bus (dev/hu-virtual.sh and ci/dut/start_dut.sh start mediad
with --usb session) offers an fstab-mounted disk, which must be ignored, then plugs in
a stick: mediad mounts it read-only without a prompt, names the source after the
label, switches to it and plays its tracks. Each source keeps its own track and
position (Library <-> stick), the state file holds the source and the resume points,
the same stick mounted elsewhere next time keeps its resume point and its tags come from
the cache, the same stick on a second device stays one source, a second stick without a
label is "USB", and pulling the playing stick falls back to the Library, paused. A real USB port and a real udisks2 are not part of this test."""
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import DEV, check, finish, media, media_props, media_queue, power_settled, wait_media

sys.path.insert(0, str(DEV))
import media_tags  # noqa: E402

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "r80-hu"
STATE = RUN / "media-state.json"          # where hu-virtual.sh and start_dut.sh let mediad save it
UD = "org.freedesktop.UDisks2"
ROOT = "/org/freedesktop/UDisks2"
OM, PROPS = "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
BLOCK, FS, DRIVE = UD + ".Block", UD + ".Filesystem", UD + ".Drive"


def mounts(*paths):
    return dbus.Array([dbus.ByteArray(p.encode() + b"\x00") for p in paths], signature="ay")


class Device(dbus.service.Object):
    """A block device with a filesystem: Filesystem.Mount, as udisks2 does it."""

    def __init__(self, conn, path, fake, mount_dir):
        super().__init__(conn, path)
        self.fake, self.mount_dir, self.mount_calls = fake, mount_dir, []

    @dbus.service.method(FS, in_signature="a{sv}", out_signature="s")
    def Mount(self, options):
        self.mount_calls.append({str(k): v for k, v in options.items()})
        self.fake.objects[self._object_path][FS]["MountPoints"] = mounts(self.mount_dir)
        self.PropertiesChanged(FS, {"MountPoints": mounts(self.mount_dir)}, dbus.Array([], signature="s"))
        return self.mount_dir

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

    def add(self, name, uuid, label, mount_dir, mounted_at=None, fstab=False, signal=True):
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


def make_stick(root: Path, album: str, titles):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    png = media_tags.cover("grid")
    for n, title in enumerate(titles, 1):
        f = root / f"{n:02d}.wav"
        media_tags.tone_wav(f, 210 if n % 2 else 245, 30)
        media_tags.tag(f, title=title, artist="USB Artist", album=album, track=n, total=len(titles), png=png)


stick_dir, stick2_dir = RUN / "test-stick", RUN / "test-stick-2"
make_stick(stick_dir, "Stick Album", ["Stick One", "Stick Two", "Stick Three"])
make_stick(stick2_dir, "Second Stick", ["Other One"])
power_settled()
m = media()
m.SetSource("Library")

loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
ud = FakeUDisks(conn)
sysdisk = ud.add("sdy", "SYS-UUID", "R80", "/mnt/r80", mounted_at="/mnt/r80", fstab=True, signal=False)
conn.request_name(UD, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
time.sleep(1.5)
p = media_props()
check(p["Sources"] == ["Library"], f"an fstab-mounted disk is no media source (Sources {p['Sources']})")
check(not sysdisk.mount_calls, "and mediad does not try to mount it")

stick = ud.add("sdz", "R80-TEST-1", "MUSICSTICK", str(stick_dir))
ok, p, waited = wait_media(lambda p: p["Source"] == "MUSICSTICK" and p["PlaybackStatus"] == "playing", timeout=8.0)
check(ok, f"plugged-in stick becomes the source and plays ({p.get('Source')}, {p.get('PlaybackStatus')}, {waited:.1f} s)")
check(p["Sources"] == ["Library", "MUSICSTICK"], f"Sources lists it by its label ({p['Sources']})")
opts = stick.mount_calls[-1] if stick.mount_calls else {}
check(opts.get("options") == "ro" and bool(opts.get("auth.no_user_interaction")),
      f"mounted read-only, without a password prompt ({opts})")
ok, p, _ = wait_media(lambda p: p["TrackCount"] == 3 and p["Scanned"] == 3, timeout=10.0)
titles = [t["title"] for t in media_queue()]
check(ok and titles == ["Stick One", "Stick Two", "Stick Three"], f"the stick's tracks, tags read ({titles})")

m.SetTrack(1)
wait_media(lambda p: p["TrackIndex"] == 1 and p["PlaybackStatus"] == "playing", timeout=3.0)
m.SetPosition(10_000_000)
wait_media(lambda p: p["Position"] >= 11_000_000, timeout=4.0)
m.SetSource("Library")
ok, p, _ = wait_media(lambda p: p["Source"] == "Library" and p["PlaybackStatus"] == "playing", timeout=4.0)
check(ok, f"SetSource('Library') switches and keeps playing ({p.get('Source')}, {p.get('PlaybackStatus')})")
m.SetSource("MUSICSTICK")
ok, p, _ = wait_media(lambda p: p["Source"] == "MUSICSTICK" and p["TrackIndex"] == 1 and p["Position"] >= 10_000_000,
                      timeout=4.0)
check(ok, f"back on the stick: same track from about where it was (track {p.get('TrackIndex')}, "
          f"{p.get('Position', 0) / 1e6:.1f} s)")
try:
    st = json.loads(STATE.read_text())
except (OSError, ValueError):
    st = {}
check(st.get("source") == "usb:R80-TEST-1" and "library" in st.get("resume", {}) and "usb:R80-TEST-1" in st.get("resume", {}),
      f"state file: active source and a resume point per source ({st.get('source')}, {sorted(st.get('resume', {}))})")

# pulled at track 1, about 11 s; back on another mount point (a desktop does that when the
# old one is busy): same source, same place, tags from the cache (paths inside the medium)
ud.remove("sdz")
wait_media(lambda p: p["Source"] == "Library", timeout=4.0)
moved = RUN / "test-stick-moved"
if moved.exists():
    shutil.rmtree(moved)
shutil.copytree(stick_dir, moved)                     # copy2: same sizes and mtimes
first = {}
ud.add("sdz", "R80-TEST-1", "MUSICSTICK", str(moved))
ok, p, _ = wait_media(lambda p: p["Source"] == "MUSICSTICK", timeout=8.0)
first = p
ok2, p, _ = wait_media(lambda p: p["TrackIndex"] == 1 and p["Position"] >= 10_000_000, timeout=4.0)
check(ok and ok2, f"the stick back on another mount point resumes (track {p.get('TrackIndex')}, {p.get('Position', 0) / 1e6:.1f} s)")
check(first.get("Scanned") == 3, f"... with its tags from the cache at once (Scanned {first.get('Scanned')} of 3)")
ud.add("sdv", "R80-TEST-1", "MUSICSTICK", str(moved))
ok, p, _ = wait_media(lambda p: len(p["Sources"]) != 2, timeout=2.0)
check(not ok and p["Sources"] == ["Library", "MUSICSTICK"], f"the same stick on a second device: one source ({p['Sources']})")
ud.remove("sdv")
ok, p, _ = wait_media(lambda p: p["Source"] != "MUSICSTICK", timeout=2.0)
check(not ok, f"... and one of the two gone: it stays ({p['Source']})")

ud.add("sdx", "R80-TEST-2", "", str(stick2_dir))
ok, p, _ = wait_media(lambda p: p["Source"] == "USB", timeout=8.0)
check(ok and p["Sources"] == ["Library", "MUSICSTICK", "USB"],
      f"a stick without a label is 'USB' and plays at once ({p.get('Sources')}, {p.get('Source')})")
ud.remove("sdx")
ok, p, _ = wait_media(lambda p: p["Sources"] == ["Library", "MUSICSTICK"], timeout=4.0)
check(ok, f"pulled -> gone from Sources ({p.get('Sources')})")

m.SetSource("MUSICSTICK")
wait_media(lambda p: p["Source"] == "MUSICSTICK" and p["PlaybackStatus"] == "playing", timeout=4.0)
ud.remove("sdz")
ok, p, _ = wait_media(lambda p: p["Source"] == "Library" and p["PlaybackStatus"] != "playing", timeout=4.0)
check(ok, f"pulling the playing stick falls back to the Library, paused ({p.get('Source')}, {p.get('PlaybackStatus')})")
check(p["Sources"] == ["Library"], f"Sources is the Library again ({p['Sources']})")

conn.release_name(UD)
m.Pause()
finish()
