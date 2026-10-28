#!/usr/bin/env bash
# R80 headunit kiosk for the Raspberry Pi: the DLT daemon, the MCU stand-in, the vehicle, media, audio,
# warning, trip, navigation, system and phone service, the system log reader, the voice assistant, then the UI on Qt eglfs.
# r80-hu.service wraps this in dbus-run-session so all of them share one session bus.
#
# Override paths with R80_REPO, R80_VENV and R80_MUSIC; extra navd flags with R80_NAV_ARGS.
# Start-up (docs/bench-measurements.md): the services that are not on the audio path run at a lower
# CPU priority (R80_SERVICE_NICE, default 10), so the UI gets the CPU first and shows its first
# frame about 1.5 s earlier; until a service answers, the UI shows "–" for its values.
set -euo pipefail

VENV="${R80_VENV:-$HOME/r80-venv}"
R="${R80_REPO:-$HOME/Project_R80}"
MUSIC="${R80_MUSIC:-$HOME/Music}"
PY="$VENV/bin/python"
LOW=(nice -n "${R80_SERVICE_NICE:-10}" "$PY")          # not on the audio path: the UI first

[[ -x "$PY" ]] || { echo "python not found at $PY" >&2; exit 1; }
[[ -f "$R/hu/ui/run.py" ]] || { echo "headunit not found at $R" >&2; exit 1; }

# Which HU software starts (D12, hu/services/update.py): an installed release from
# R80_RELEASES (an update becomes current here; one that never got healthy is given up), else
# this checkout. "checkout" in ~/.config/r80/run-from (./r80 bench run-from) or R80_RUN_FROM=checkout
# always starts the checkout (development).
RELEASES="${R80_RELEASES:-${XDG_DATA_HOME:-$HOME/.local/share}/r80/releases}"
RUN_FROM="${R80_RUN_FROM:-$(cat "${XDG_CONFIG_HOME:-$HOME/.config}/r80/run-from" 2>/dev/null || echo release)}"
HU="$R"
if [[ "$RUN_FROM" != checkout ]]; then
  REL="$("$PY" "$R/hu/services/update.py" select "$RELEASES" 2>>/tmp/r80-update.log)" || REL=""
  [[ -n "$REL" && -f "$REL/hu/ui/run.py" ]] && HU="$REL"
fi
echo "starting the HU software from $HU" >>/tmp/r80-update.log

# the DLT log of the services and the UI (hu/services/dlt-daemon.sh): files in ~/.local/state/r80/dlt/trace
# (16 MB ring), DLT Viewer / dlt-receive on port 3490
export DLT_PIPE_DIR="${XDG_RUNTIME_DIR:-/tmp}/r80-dlt"
"$HU/hu/services/dlt-daemon.sh" "${XDG_STATE_HOME:-$HOME/.local/state}/r80/dlt" "$DLT_PIPE_DIR" >/tmp/r80-dlt.log 2>&1 &
"${LOW[@]}" "$R/dev/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 vcan_motor --can2-bus motor >/tmp/r80-mcu.log 2>&1 &
"${LOW[@]}" "$HU/hu/services/vehicled.py" >/tmp/r80-vehicled.log 2>&1 &
"$PY" "$HU/hu/services/mediad.py" --music-dir "$MUSIC" --usb system --bluetooth system >/tmp/r80-mediad.log 2>&1 &
"$PY" "$HU/hu/services/audiod.py" >/tmp/r80-audiod.log 2>&1 &
"${LOW[@]}" "$HU/hu/services/warnd.py" >/tmp/r80-warnd.log 2>&1 &
"${LOW[@]}" "$HU/hu/services/tripd.py" >/tmp/r80-tripd.log 2>&1 &
# updates: the bench trusts development keys (~/.config/r80/update-keys); the desktop unit can restart
# the HU (R80_RESTART) for "Restart now" and a rollback, the kiosk unit only at the next start
"${LOW[@]}" "$HU/hu/services/sysd.py" --releases "$RELEASES" --allow-dev-key \
  --restart-command "${R80_RESTART:-}" >/tmp/r80-sysd.log 2>&1 &
# shellcheck disable=SC2086  # R80_NAV_ARGS: extra navd flags, e.g. --tcp 47800 for the phone panel on the PC
"${LOW[@]}" "$HU/hu/services/navd.py" --bluetooth system ${R80_NAV_ARGS:-} >/tmp/r80-navd.log 2>&1 &
# calls and contacts: PipeWire's telephony service (WirePlumber, r80-telephony.conf) and obexd run on
# the desktop's session bus
DESKTOP_BUS="unix:path=/run/user/$(id -u)/bus"
"${LOW[@]}" "$HU/hu/services/phoned.py" --telephony "$DESKTOP_BUS" --obex "$DESKTOP_BUS" --bluez system >/tmp/r80-phoned.log 2>&1 &
# the system's own log (kernel, BlueZ, PipeWire, ...: the journal, cleaned) into DLT; reading the
# system journal needs the user in the group adm (or systemd-journal)
"${LOW[@]}" "$HU/hu/services/syslogd.py" >/tmp/r80-syslogd.log 2>&1 &
# the voice assistant: speech on the HU (./r80 bench speech installs the models); R80_ASSIST_ARGS, e.g.
# --mic-files DIR for recorded speech while the bench has no microphone
# shellcheck disable=SC2086  # R80_ASSIST_ARGS is a list of flags
"${LOW[@]}" "$HU/hu/services/assistd.py" ${R80_ASSIST_ARGS:-} >/tmp/r80-assistd.log 2>&1 &

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-eglfs}"
export QT_QPA_EGLFS_HIDECURSOR="${QT_QPA_EGLFS_HIDECURSOR:-1}"
exec "$PY" "$HU/hu/ui/run.py" --fullscreen
