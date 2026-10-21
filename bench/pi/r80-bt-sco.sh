#!/usr/bin/env bash
# Raspberry Pi bench only: the built-in Bluetooth chip (BCM43438 on the Pi 3, driver
# hci_uart_bcm) sends call audio (SCO) to its PCM pins by default, where nothing is
# connected, so hands-free calls are silent. This switches SCO routing to HCI (to Linux)
# with Broadcom's vendor command Write_SCO_PCM_Int_Param (routing 1 = transport).
# The chip forgets it on a reset; r80-bt-sco.service runs this after every bluetooth start.
# A USB Bluetooth adapter routes SCO over USB anyway: then this does nothing.
set -euo pipefail
dev=/sys/class/bluetooth/hci0/device/uevent
for _ in $(seq 20); do [[ -e "$dev" ]] && break; sleep 0.5; done
if ! grep -q "DRIVER=hci_uart_bcm" "$dev" 2>/dev/null; then
  echo "hci0 is not the Pi's built-in Broadcom chip: nothing to do"
  exit 0
fi
for _ in $(seq 20); do hciconfig hci0 2>/dev/null | grep -q "UP RUNNING" && break; sleep 0.5; done
# a wedged chip never answers: do not hang the bench on it
if ! timeout 5 hcitool -i hci0 cmd 0x3f 0x1c 0x01 0x02 0x00 0x01 0x01 >/dev/null; then
  echo "hci0 did not answer the vendor command (reset it: sudo hciconfig hci0 reset, or reboot)" >&2
  exit 1
fi
echo "hci0: SCO routed to HCI (read back: $(timeout 5 hcitool -i hci0 cmd 0x3f 0x1d | tail -1 | xargs))"
