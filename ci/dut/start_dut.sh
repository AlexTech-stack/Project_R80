#!/usr/bin/env bash
# Runs inside the DUT container: the MCU stand-in, the vehicle, media, audio, warning, trip, navigation, system and phone service,
# like bench/pi/r80-kiosk.sh on the Pi (without the UI). mediad plays the test library
# (dev/media_tags.py) into $MEDIA_ARGS (the caller passes --sink fakesink).
#   start_dut.sh <path to the repo>
# Needs XDG_RUNTIME_DIR (shared with the host: UART link, MCU control socket, companion link socket) and
# DBUS_SESSION_BUS_ADDRESS (the host's bus, so the BoAt tests see vehicled).
set -euo pipefail
R="$1"
echo "DUT: $(uname -m), $(python3 --version), $(. /etc/os-release && echo "$PRETTY_NAME")"
rm -f "$XDG_RUNTIME_DIR/r80-mcu-uart"
# the DLT log (hu/services/dlt-daemon.sh); --network host: the tests reach it on port 3490
export DLT_PIPE_DIR=/tmp/r80-dlt
"$R/hu/services/dlt-daemon.sh" /tmp/r80-dlt-state "$DLT_PIPE_DIR" &
python3 "$R/dev/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 "${MCU_CAN2:-vcan_motor}" --can2-bus "${MCU_CAN2_BUS:-motor}" &
for _ in $(seq 150); do [[ -e "$XDG_RUNTIME_DIR/r80-mcu-uart" ]] && break; sleep 0.2; done
python3 "$R/hu/services/vehicled.py" &
python3 "$R/dev/media_tags.py" library "$XDG_RUNTIME_DIR/r80-hu/test-music"
# shellcheck disable=SC2086  # MEDIA_ARGS is a list of flags
python3 "$R/hu/services/mediad.py" --music-dir "$XDG_RUNTIME_DIR/r80-hu/test-music" \
  --cache-dir "$XDG_RUNTIME_DIR/r80-hu/media-cache" --state "$XDG_RUNTIME_DIR/r80-hu/media-state.json" \
  --usb session --bluetooth session --bt-audio none ${MEDIA_ARGS:-} &
python3 "$R/hu/services/audiod.py" --state "$XDG_RUNTIME_DIR/r80-hu/audio-state.json" &
# shellcheck disable=SC2086  # WARN_ARGS is a list of flags
python3 "$R/hu/services/warnd.py" ${WARN_ARGS:-} &
python3 "$R/hu/services/tripd.py" --state "$XDG_RUNTIME_DIR/r80-hu/trip-state.json" &
python3 "$R/hu/services/sysd.py" --state "$XDG_RUNTIME_DIR/r80-hu/settings.json" --log-dir /tmp/r80-dlt-state/trace &
python3 "$R/hu/services/navd.py" --socket "$XDG_RUNTIME_DIR/r80-hu/companion.sock" --bluetooth session &
python3 "$R/hu/services/phoned.py" --telephony session --bluez none --obex session --state-dir "$XDG_RUNTIME_DIR/r80-hu/phone" --call-audio none &
wait -n   # either one ending ends the DUT
echo "DUT: a process exited"
exit 1
