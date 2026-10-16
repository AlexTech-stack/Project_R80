#!/usr/bin/env python3
"""TC_HU_023: the phone over Bluetooth (hu-navd, D11). A stand-in for BlueZ
(org.bluez.ProfileManager1 on the session bus; dev/hu-virtual.sh starts navd with
--bluetooth session) checks how navd registers the companion service: RFCOMM server,
the protocol's UUID, only paired (authenticated) phones. It then hands navd a
connection the way bluetoothd does (Profile1.NewConnection with a file descriptor),
the emulated phone talks over it, BlueZ asks to disconnect, and when bluetoothd
restarts navd registers again. Real radio and pairing are not part of this test."""
import os
import socket
import sys
import threading
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from common import SERVICES, check, finish, nav_props, phone, wait_nav

sys.path.insert(0, str(SERVICES))
import companion_link as cl  # noqa: E402

DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


class FakeBluez(dbus.service.Object):
    """Just enough of bluetoothd: ProfileManager1.RegisterProfile / UnregisterProfile."""

    def __init__(self, conn):
        super().__init__(conn, "/org/bluez")
        self.registrations = []

    @dbus.service.method("org.bluez.ProfileManager1", in_signature="osa{sv}", sender_keyword="sender")
    def RegisterProfile(self, path, uuid, options, sender=None):
        self.registrations.append((str(sender), str(path), str(uuid), {str(k): v for k, v in options.items()}))

    @dbus.service.method("org.bluez.ProfileManager1", in_signature="o")
    def UnregisterProfile(self, path):
        pass


def wait(cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


loop = DBusGMainLoop()
conn = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"], mainloop=loop)
threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
bluez = FakeBluez(conn)
conn.request_name("org.bluez", dbus.bus.NAME_FLAG_DO_NOT_QUEUE)

check(wait(lambda: bluez.registrations), "navd registers the companion service when BlueZ appears")
sender, path, uuid, opts = bluez.registrations[-1] if bluez.registrations else ("", "", "", {})
check(uuid == cl.SERVICE_UUID, f"with the protocol's service UUID ({uuid})")
check(int(opts.get("Channel", 0)) == cl.RFCOMM_CHANNEL,
      f"with a fixed RFCOMM channel ({opts.get('Channel')}), so the service record tells phones where to connect")
check(opts.get("Role") == "server" and bool(opts.get("RequireAuthentication")) and not bool(opts.get("RequireAuthorization", True)),
      f"as RFCOMM server, paired phones only, no extra prompt (Role {opts.get('Role')}, "
      f"RequireAuthentication {opts.get('RequireAuthentication')}, RequireAuthorization {opts.get('RequireAuthorization')})")

wait_nav(lambda p: not p["Phone"]["connected"], timeout=10.0)
hu_end, phone_end = socket.socketpair()
profile = dbus.Interface(conn.get_object(sender, path), "org.bluez.Profile1")
profile.NewConnection(dbus.ObjectPath(DEVICE), dbus.types.UnixFd(hu_end.fileno()), dbus.Dictionary({}, signature="sv"))
hu_end.close()                                  # navd has its own copy of the descriptor now
p = phone("Bluetooth phone")
hu = p.connect(sock=phone_end)
check(hu is not None and hu["app"] == "r80-hu", "a connection handed over by BlueZ speaks the companion protocol")
ok, props, _ = wait_nav(lambda q: q["Phone"]["connected"])
check(ok and props["Phone"]["via"] == "Bluetooth dev_AA_BB_CC_DD_EE_FF" and props["Phone"]["device"] == "Bluetooth phone",
      f"Phone: connected via '{props.get('Phone', {}).get('via')}'")
p.send(cl.guidance("google_maps", "turn", "left", distance_m=200, street="Bluetoothweg"))
ok, props, _ = wait_nav(lambda q: q["Guidance"]["street"] == "Bluetoothweg")
check(ok and not props["Guidance"]["stale"], "guidance arrives over it")

profile.RequestDisconnection(dbus.ObjectPath(DEVICE))
check(p.closed_by_hu.wait(2.0), "BlueZ asks to disconnect: navd closes the link")
ok, props, _ = wait_nav(lambda q: not q["Phone"]["connected"])
check(ok and props["Guidance"]["stale"], "phone shown disconnected, guidance kept as stale")
p.close()

count = len(bluez.registrations)
conn.release_name("org.bluez")                  # bluetoothd stops ...
time.sleep(0.5)
conn.request_name("org.bluez", dbus.bus.NAME_FLAG_DO_NOT_QUEUE)    # ... and starts again
check(wait(lambda: len(bluez.registrations) > count), "bluetoothd restarted: navd registers again")

p = phone("Cleanup")
p.connect()
p.send(cl.guidance_ended())
wait_nav(lambda q: not q["Guidance"]["active"])
p.close(bye=True)
conn.release_name("org.bluez")
check(not nav_props()["Guidance"]["active"], "clean end")
finish()
