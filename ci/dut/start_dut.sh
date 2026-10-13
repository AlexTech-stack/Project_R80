#!/usr/bin/env bash
# Runs inside the DUT container: the MCU stand-in and the vehicle service, like
# r80_pi_testbench/r80-kiosk.sh on the Pi (without mediad and the UI).
#   start_dut.sh <path to hu-virtual>
# Needs XDG_RUNTIME_DIR (shared with the host: UART link, MCU control socket) and
# DBUS_SESSION_BUS_ADDRESS (the host's bus, so the BoAt tests see vehicled).
set -euo pipefail
HU="$1"
echo "DUT: $(uname -m), $(python3 --version), $(. /etc/os-release && echo "$PRETTY_NAME")"
rm -f "$XDG_RUNTIME_DIR/r80-mcu-uart"
python3 "$HU/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 "${MCU_CAN2:-vcan_motor}" --can2-bus "${MCU_CAN2_BUS:-motor}" &
for _ in $(seq 150); do [[ -e "$XDG_RUNTIME_DIR/r80-mcu-uart" ]] && break; sleep 0.2; done
python3 "$HU/hu/vehicled.py" &
wait -n   # either one ending ends the DUT
echo "DUT: a process exited"
exit 1
