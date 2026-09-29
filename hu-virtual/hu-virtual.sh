#!/usr/bin/env bash
# Start / stop the virtual R80 headunit environment.
#
#   ./hu-virtual.sh up          buses, BoAt gateway, MCU emulator, hu-vehicled
#   ./hu-virtual.sh drive       ... plus the BoAt restbus playing the drive cycle
#   ./hu-virtual.sh ui          start the UI (window) on top of a running env
#   ./hu-virtual.sh panel       tester panel: the restbus with a GUI to change signals and press HU keys
#   ./hu-virtual.sh test        run the BoAt test suite (env must be up, no restbus running)
#   ./hu-virtual.sh status | logs | down
#
# Env overrides: BOAT_ROOT (~/BoAt), BOAT_PORT (50061), R80_MOCKUP (mockup dir),
#                MCU_CAN2 / MCU_CAN2_BUS (vcan_motor / motor; or vcan_comfort / comfort).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
  start mcu python3 "$HERE/mcu_emu/mcu_emu.py" --can1 vcan_info --can2 "${MCU_CAN2:-vcan_motor}" --can2-bus "${MCU_CAN2_BUS:-motor}"
  sleep 0.5
  start vehicled python3 "$HERE/hu/vehicled.py"
}

case "${1:-status}" in
  up) up ;;
  drive) up; stop panel; start restbus python3 "$HERE/boat/restbus.py" --address "localhost:$BOAT_PORT" --drive ${RESTBUS_ARGS:-} ;;
  restbus) start restbus python3 "$HERE/boat/restbus.py" --address "localhost:$BOAT_PORT" ${RESTBUS_ARGS:-} ;;
  ui) start ui python3 "$HERE/hu/ui/run_hu.py" ${UI_ARGS:-} ;;
  panel) stop restbus; start panel python3 "$HERE/boat/restbus_panel.py" --address "localhost:$BOAT_PORT" ;;
  test)
    stop restbus; stop panel
    cd "$HERE"
    BOAT_HOST="localhost:$BOAT_PORT" boat test run boat/manifest_hu_smoke.json --report-dir "$RUN/reports" "${@:2}"
    ;;
  down) for n in ui panel restbus vehicled mcu gateway; do stop "$n"; done ;;
  status)
    for n in gateway mcu vehicled restbus panel ui; do
      if [[ -f "$RUN/$n.pid" ]] && kill -0 "$(cat "$RUN/$n.pid")" 2>/dev/null; then s=running; else s=stopped; fi
      printf "  %-9s %s\n" "$n" "$s"
    done
    ip -br link show type vcan 2>/dev/null | sed 's/^/  /' || true
    ;;
  logs) tail -n 20 "$RUN"/*.log ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
