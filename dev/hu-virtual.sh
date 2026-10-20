#!/usr/bin/env bash
# Start / stop the virtual R80 headunit environment. Usually run as ./r80 virtual <command>.
#
#   ./hu-virtual.sh up          buses, BoAt gateway, MCU emulator, hu-vehicled, hu-mediad, hu-audiod, hu-warnd, hu-tripd, hu-navd, hu-sysd, hu-phoned
#   ./hu-virtual.sh drive       ... plus the BoAt restbus playing the drive cycle
#   ./hu-virtual.sh phone       phone emulator: plays a navigation route as the companion app would (D11)
#   ./hu-virtual.sh phonepanel  phone panel: a GUI that plays the phone (routes, any guidance, link loss)
#   ./hu-virtual.sh tunnel      CAN tunnel to the Raspberry Pi bench (PI_IP; also started by up when set)
#   ./hu-virtual.sh ui          start the UI (window) on top of a running env
#   ./hu-virtual.sh panel       tester panel: the restbus with a GUI to change signals and press HU keys
#   ./hu-virtual.sh test        run the BoAt test suite (env must be up; stops restbus, panels, phone and tunnel)
#   ./hu-virtual.sh status | logs | down
#
# Env overrides: BOAT_ROOT (~/BoAt), BOAT_PORT (50061), UI_ARGS (extra hu/ui/run.py arguments, e.g. --fullscreen),
#                HU_DUT=external (up starts only buses + gateway; the DUT, i.e. MCU emulator,
#                vehicled, mediad, audiod, warnd, tripd, navd, sysd and phoned, runs elsewhere, e.g. in a container: ci/run_boat_sil.sh --dut-arch=arm64),
#                MCU_CAN2 / MCU_CAN2_BUS (vcan_motor / motor; or vcan_comfort / comfort),
#                MUSIC_DIR (media library; unset = the test library in $RUN/test-music, dev/media_tags.py),
#                MEDIA_ARGS (extra hu/mediad.py arguments), MEDIA_USB (session: the tests' udisks2 stand-in, default;
#                system: this PC's real USB sticks),
#                AUDIO_ARGS (extra hu/audiod.py arguments; volumes are saved in $RUN/audio-state.json),
#                WARN_ARGS (extra hu/warnd.py arguments, e.g. --config my-warnings.ini),
#                TRIP_ARGS (extra hu/tripd.py arguments; trips are saved in $RUN/trip-state.json),
#                NAV_ARGS (extra hu/navd.py arguments, e.g. --tcp 47800), PHONE_ARGS (extra phone_emu/phone_emu.py arguments),
#                NAV_BLUETOOTH (session: BlueZ stand-in of the tests, default; system: this PC's real Bluetooth),
#                SYS_ARGS (extra hu/sysd.py arguments; settings are saved in $RUN/settings.json),
#                PI_IP (the Raspberry Pi bench: up/drive also start the CAN tunnel to it, docs/bench-pi.md).
# Settings that should stick can go into ~/.config/r80/hu-virtual.env (KEY=value lines, read first).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # dev/: the PC stand-ins
REPO="$(dirname "$HERE")"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/r80/hu-virtual.env"
# shellcheck disable=SC1090  # optional user settings, e.g. PI_IP=...
[[ -f "$CONF" ]] && { set -a; . "$CONF"; set +a; }
BOAT_ROOT="${BOAT_ROOT:-$HOME/BoAt}"
BOAT_PORT="${BOAT_PORT:-50061}"
GATEWAY="${BOAT_GATEWAY:-$BOAT_ROOT/boat-platform/build/debug/src/gateway/grpc_gateway/boat_gateway}"
RUN="${XDG_RUNTIME_DIR:-/tmp}/r80-hu"
BUSES=(vcan_motor vcan_info vcan_comfort)
mkdir -p "$RUN"

start() {  # name, command...
  local name=$1; shift
  if [[ -f "$RUN/$name.pid" ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then
    echo "  $name already running"; return
  fi
  setsid "$@" >"$RUN/$name.log" 2>&1 < /dev/null &
  echo $! >"$RUN/$name.pid"
  echo "  $name started (log: $RUN/$name.log)"
}

stop() {
  local name=$1
  if [[ -f "$RUN/$name.pid" ]]; then
    local pid; pid=$(cat "$RUN/$name.pid")
    if kill "$pid" 2>/dev/null; then
      for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done  # let it free its port
      echo "  $name stopped"
    fi
    rm -f "$RUN/$name.pid"
  fi
}

buses_up() {
  if ! ip link show vcan_info &>/dev/null; then
    echo "creating virtual CAN buses (needs sudo)"
    sudo modprobe vcan
    for b in "${BUSES[@]}"; do sudo ip link add "$b" type vcan; done
  fi
  for b in "${BUSES[@]}"; do ip link show "$b" | grep -q ',UP' || sudo ip link set "$b" up; done
}

wait_gateway() {
  for _ in $(seq 50); do
    grep -q "listening" "$RUN/gateway.log" 2>/dev/null && return
    sleep 0.2
  done
  echo "gateway did not come up, see $RUN/gateway.log"; exit 1
}

up() {
  buses_up
  [[ -x "$GATEWAY" ]] || { echo "BoAt gateway not built at $GATEWAY"; exit 1; }
  start gateway env BOAT_CAN_INTERFACES="$(IFS=,; echo "${BUSES[*]}")" BOAT_GRPC_PORT="$BOAT_PORT" "$GATEWAY"
  wait_gateway
  [[ -z "${PI_IP:-}" || -n "${R80_NO_TUNNEL:-}" ]] || start tunnel env PI_IP="$PI_IP" "$REPO/bench/pi/pc-cannelloni.sh"
  if [[ "${HU_DUT:-}" == external ]]; then echo "  DUT is external: not starting mcu, vehicled, mediad, audiod, warnd, tripd, navd, sysd and phoned"; return; fi
  start mcu python3 "$HERE/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 "${MCU_CAN2:-vcan_motor}" --can2-bus "${MCU_CAN2_BUS:-motor}"
  sleep 0.5
  start vehicled python3 "$REPO/hu/services/vehicled.py"
  # Without MUSIC_DIR: the test library (tags, covers; dev/media_tags.py), which the tests expect.
  [[ -n "${MUSIC_DIR:-}" ]] || python3 "$HERE/media_tags.py" library "$RUN/test-music"
  # shellcheck disable=SC2086  # MEDIA_ARGS is a list of flags
  start mediad python3 "$REPO/hu/services/mediad.py" --music-dir "${MUSIC_DIR:-$RUN/test-music}" \
    --cache-dir "$RUN/media-cache" --state "$RUN/media-state.json" --usb "${MEDIA_USB:-session}" ${MEDIA_ARGS:-}
  # shellcheck disable=SC2086  # AUDIO_ARGS is a list of flags
  start audiod python3 "$REPO/hu/services/audiod.py" --state "$RUN/audio-state.json" ${AUDIO_ARGS:-}
  # shellcheck disable=SC2086  # WARN_ARGS is a list of flags
  start warnd python3 "$REPO/hu/services/warnd.py" ${WARN_ARGS:-}
  # shellcheck disable=SC2086  # TRIP_ARGS is a list of flags
  start tripd python3 "$REPO/hu/services/tripd.py" --state "$RUN/trip-state.json" ${TRIP_ARGS:-}
  # shellcheck disable=SC2086  # NAV_ARGS is a list of flags
  # shellcheck disable=SC2086  # SYS_ARGS is a list of flags
  start sysd python3 "$REPO/hu/services/sysd.py" --state "$RUN/settings.json" ${SYS_ARGS:-}
  start navd python3 "$REPO/hu/services/navd.py" --socket "$RUN/companion.sock" --bluetooth "${NAV_BLUETOOTH:-session}" ${NAV_ARGS:-}
  # calls: PipeWire's telephony stand-in of the tests / the phone panel on the session bus (PHONE_TELEPHONY=ADDRESS for a real one)
  start phoned python3 "$REPO/hu/services/phoned.py" --telephony "${PHONE_TELEPHONY:-session}" --bluez "${PHONE_BLUEZ:-none}"
}

case "${1:-status}" in
  up) up ;;
  drive) up; stop panel; start restbus python3 "$REPO/test/boat/restbus.py" --address "localhost:$BOAT_PORT" --drive ${RESTBUS_ARGS:-} ;;
  restbus) start restbus python3 "$REPO/test/boat/restbus.py" --address "localhost:$BOAT_PORT" ${RESTBUS_ARGS:-} ;;
  ui) start ui python3 "$REPO/hu/ui/run.py" ${UI_ARGS:-} ;;
  # shellcheck disable=SC2086  # PHONE_ARGS is a list of flags
  phone) start phone python3 "$HERE/phone_emu/phone_emu.py" --socket "$RUN/companion.sock" ${PHONE_ARGS:-} ;;
  phonepanel) stop phone; start phonepanel python3 "$HERE/phone_emu/phone_panel.py" --target "$RUN/companion.sock" ;;
  tunnel) start tunnel env PI_IP="${PI_IP:?set PI_IP (or put it into $CONF)}" "$REPO/bench/pi/pc-cannelloni.sh" ;;
  panel) stop restbus; start panel python3 "$REPO/test/boat/restbus_panel.py" --address "localhost:$BOAT_PORT" ;;
  test)
    stop restbus; stop panel; stop phone; stop phonepanel; stop tunnel    # the Pi's HU must not answer on the test buses
    cd "$REPO/test/boat"
    BOAT_HOST="localhost:$BOAT_PORT" boat test run manifest_hu_smoke.json --report-dir "$RUN/reports" "${@:2}"
    ;;
  down) for n in ui panel phonepanel phone restbus tunnel phoned sysd navd tripd warnd audiod mediad vehicled mcu gateway; do stop "$n"; done ;;
  status)
    for n in gateway tunnel mcu vehicled mediad audiod warnd tripd navd sysd phoned restbus phone phonepanel panel ui; do
      if [[ -f "$RUN/$n.pid" ]] && kill -0 "$(cat "$RUN/$n.pid")" 2>/dev/null; then s=running; else s=stopped; fi
      printf "  %-9s %s\n" "$n" "$s"
    done
    ip -br link show type vcan 2>/dev/null | sed 's/^/  /' || true
    ;;
  logs) tail -n 20 "$RUN"/*.log ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
