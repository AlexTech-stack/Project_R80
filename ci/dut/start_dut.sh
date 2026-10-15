#!/usr/bin/env bash
# Runs inside the DUT container: the MCU stand-in, the vehicle, media, audio, warning, trip and navigation service,
# like r80_pi_testbench/r80-kiosk.sh on the Pi (without the UI). mediad plays the demo
# tones into $MEDIA_ARGS (the caller passes --sink fakesink).
#   start_dut.sh <path to hu-virtual>
# Needs XDG_RUNTIME_DIR (shared with the host: UART link, MCU control socket, companion link socket) and
# DBUS_SESSION_BUS_ADDRESS (the host's bus, so the BoAt tests see vehicled).
set -euo pipefail
HU="$1"
echo "DUT: $(uname -m), $(python3 --version), $(. /etc/os-release && echo "$PRETTY_NAME")"
rm -f "$XDG_RUNTIME_DIR/r80-mcu-uart"
python3 "$HU/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 "${MCU_CAN2:-vcan_motor}" --can2-bus "${MCU_CAN2_BUS:-motor}" &
for _ in $(seq 150); do [[ -e "$XDG_RUNTIME_DIR/r80-mcu-uart" ]] && break; sleep 0.2; done
python3 "$HU/hu/vehicled.py" &
# shellcheck disable=SC2086  # MEDIA_ARGS is a list of flags
python3 "$HU/hu/mediad.py" --music-dir "$XDG_RUNTIME_DIR/r80-hu/music" --demo ${MEDIA_ARGS:-} &
python3 "$HU/hu/audiod.py" --state "$XDG_RUNTIME_DIR/r80-hu/audio-state.json" &
# shellcheck disable=SC2086  # WARN_ARGS is a list of flags
python3 "$HU/hu/warnd.py" ${WARN_ARGS:-} &
python3 "$HU/hu/tripd.py" --state "$XDG_RUNTIME_DIR/r80-hu/trip-state.json" &
python3 "$HU/hu/navd.py" --socket "$XDG_RUNTIME_DIR/r80-hu/companion.sock" --bluetooth session &
wait -n   # either one ending ends the DUT
echo "DUT: a process exited"
exit 1
