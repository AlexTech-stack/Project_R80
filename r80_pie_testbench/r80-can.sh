#!/usr/bin/env bash
# Raspberry Pi side of the R80 CAN tunnel: create the vcan interfaces and start
# one cannelloni client per bus. Needs root; normally run by r80-can.service,
# which supplies PC_IP/BASE_PORT from /etc/r80-bench.conf.
#
#   sudo PC_IP=192.168.1.10 ./r80-can.sh
#
# Env: PC_IP (required), BASE_PORT (default 20000), IFACES (default below).
set -euo pipefail

: "${PC_IP:?set PC_IP (see r80-bench.conf.example)}"
BASE_PORT="${BASE_PORT:-20000}"
IFACES=(${IFACES:-vcan_info vcan_motor vcan_comfort})

modprobe vcan
for i in "${!IFACES[@]}"; do
  iface="${IFACES[$i]}"
  ip link show "$iface" &>/dev/null || ip link add "$iface" type vcan
  ip link set "$iface" up
  port=$((BASE_PORT + i))
  echo "cannelloni: $iface <-> $PC_IP:$port"
  cannelloni -I "$iface" -R "$PC_IP" -r "$port" -l "$port" -t 1000 &
done
wait
