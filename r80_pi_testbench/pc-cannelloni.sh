#!/usr/bin/env bash
# Test-PC side of the R80 CAN tunnel: one cannelloni server per vcan, so the
# Raspberry Pi sees the same buses the BoAt gateway writes. Start the PC
# environment first (hu-virtual/hu-virtual.sh drive) so the vcans exist.
#
#   PI_IP=192.168.1.42 ./pc-cannelloni.sh
#
# Env: PI_IP (required), BASE_PORT (default 20000), IFACES (default below).
set -euo pipefail

: "${PI_IP:?set PI_IP to the Raspberry Pi address}"
BASE_PORT="${BASE_PORT:-20000}"
IFACES=(${IFACES:-vcan_info vcan_motor vcan_comfort})

for i in "${!IFACES[@]}"; do
  iface="${IFACES[$i]}"
  port=$((BASE_PORT + i))
  ip link show "$iface" &>/dev/null || echo "warning: $iface not found; start the PC environment first" >&2
  echo "cannelloni: $iface <-> $PI_IP:$port"
  cannelloni -I "$iface" -R "$PI_IP" -r "$port" -l "$port" -t 1000 &
done
wait
