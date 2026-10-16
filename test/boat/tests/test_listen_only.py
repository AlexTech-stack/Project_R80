#!/usr/bin/env python3
"""TC_HU_006: the headunit may send on Infotainment but never on Motor or Comfort.

The MCU has CAN 1 on Infotainment and CAN 2 listen-only on Motor (default) or
Comfort; a transmit request for either other bus must be refused.

Linux asks the MCU to transmit (hu-vehicled SendCan) on each bus; BoAt watches
all three buses through the gateway's frame subscription.
"""
import sys
import time

import dbus

from common import ADDRESS, PATH, SERVICE, Restbus, check, finish, mcu

from boat.frame_node import FrameNode  # path set up by common/restbus

TEST_ID = 0x5A5
seen = []
node = FrameNode(ADDRESS)
node.subscribe(lambda f: seen.append((f.iface, f.can.can_id, bytes(f.payload))), bus_types=["CAN"])
time.sleep(0.5)

hu = dbus.Interface(dbus.SessionBus().get_object(SERVICE, PATH), "de.r80.Vehicle1")
with Restbus(address=ADDRESS):
    time.sleep(0.3)
    before = mcu({"cmd": "status"})
    for bus in (0, 2, 1):  # motor, comfort, info
        hu.SendCan(dbus.Byte(bus), dbus.UInt32(TEST_ID), dbus.ByteArray(bytes([bus, 0xA5])))
    time.sleep(1.0)
    after = mcu({"cmd": "status"})
node.stop()

hits = [(i, d) for i, cid, d in seen if cid & 0x1FFFFFFF == TEST_ID]
print("test frames seen by BoAt:", hits, file=sys.stderr)
check(("vcan_info", bytes([1, 0xA5])) in hits, "frame requested on Infotainment appears on vcan_info")
check(not any(i in ("vcan_motor", "vcan_comfort") for i, _ in hits), "nothing appears on Motor or Comfort")
check(after["can_tx_refused"] - before["can_tx_refused"] == 2, "MCU refused both listen-only requests")
check(after["can_tx"] - before["can_tx"] == 1, "MCU sent exactly one frame")

finish()
