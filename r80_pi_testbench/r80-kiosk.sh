#!/usr/bin/env bash
# R80 headunit kiosk for the Raspberry Pi: the MCU stand-in, the vehicle service
# and the media service, then the UI on Qt eglfs. r80-hu.service wraps this in
# dbus-run-session so all of them share one session bus.
#
# Override paths with R80_HU, R80_VENV and R80_MUSIC.
set -euo pipefail

VENV="${R80_VENV:-$HOME/r80-venv}"
HU="${R80_HU:-$HOME/Project_R80/hu-virtual}"
MUSIC="${R80_MUSIC:-$HOME/Music}"
PY="$VENV/bin/python"

[[ -x "$PY" ]] || { echo "python not found at $PY" >&2; exit 1; }
[[ -f "$HU/hu/ui/run_hu.py" ]] || { echo "headunit not found at $HU" >&2; exit 1; }

"$PY" "$HU/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 vcan_motor --can2-bus motor >/tmp/r80-mcu.log 2>&1 &
"$PY" "$HU/hu/vehicled.py" >/tmp/r80-vehicled.log 2>&1 &
"$PY" "$HU/hu/mediad.py" --music-dir "$MUSIC" >/tmp/r80-mediad.log 2>&1 &
sleep 1

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-eglfs}"
export QT_QPA_EGLFS_HIDECURSOR="${QT_QPA_EGLFS_HIDECURSOR:-1}"
exec "$PY" "$HU/hu/ui/run_hu.py" --fullscreen
