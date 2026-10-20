#!/usr/bin/env bash
# R80 headunit kiosk for the Raspberry Pi: the MCU stand-in, the vehicle, media, audio,
# warning, trip, navigation, system and phone service, then the UI on Qt eglfs. r80-hu.service wraps this in
# dbus-run-session so all of them share one session bus.
#
# Override paths with R80_REPO, R80_VENV and R80_MUSIC; extra navd flags with R80_NAV_ARGS.
set -euo pipefail

VENV="${R80_VENV:-$HOME/r80-venv}"
R="${R80_REPO:-$HOME/Project_R80}"
MUSIC="${R80_MUSIC:-$HOME/Music}"
PY="$VENV/bin/python"

[[ -x "$PY" ]] || { echo "python not found at $PY" >&2; exit 1; }
[[ -f "$R/hu/ui/run.py" ]] || { echo "headunit not found at $R" >&2; exit 1; }

"$PY" "$R/dev/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 vcan_motor --can2-bus motor >/tmp/r80-mcu.log 2>&1 &
"$PY" "$R/hu/services/vehicled.py" >/tmp/r80-vehicled.log 2>&1 &
"$PY" "$R/hu/services/mediad.py" --music-dir "$MUSIC" --usb system >/tmp/r80-mediad.log 2>&1 &
"$PY" "$R/hu/services/audiod.py" >/tmp/r80-audiod.log 2>&1 &
"$PY" "$R/hu/services/warnd.py" >/tmp/r80-warnd.log 2>&1 &
"$PY" "$R/hu/services/tripd.py" >/tmp/r80-tripd.log 2>&1 &
"$PY" "$R/hu/services/sysd.py" >/tmp/r80-sysd.log 2>&1 &
# shellcheck disable=SC2086  # R80_NAV_ARGS: extra navd flags, e.g. --tcp 47800 for the phone panel on the PC
"$PY" "$R/hu/services/navd.py" --bluetooth system ${R80_NAV_ARGS:-} >/tmp/r80-navd.log 2>&1 &
# calls: PipeWire's telephony service runs in the desktop's session bus (WirePlumber, r80-telephony.conf)
"$PY" "$R/hu/services/phoned.py" --telephony "unix:path=/run/user/$(id -u)/bus" --bluez system >/tmp/r80-phoned.log 2>&1 &
sleep 1

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-eglfs}"
export QT_QPA_EGLFS_HIDECURSOR="${QT_QPA_EGLFS_HIDECURSOR:-1}"
exec "$PY" "$R/hu/ui/run.py" --fullscreen
