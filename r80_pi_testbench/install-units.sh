#!/usr/bin/env bash
# Installs the bench's systemd units for the current user and this checkout:
# fills in @USER@, @UID@ and @REPO@ in r80-can.service / r80-hu.service, copies them
# to /etc/systemd/system and creates /etc/r80-bench.conf (from the example) if missing.
# Does not enable or start anything.
#
#   r80_pi_testbench/install-units.sh [PC_IP]    # PC_IP goes into a new /etc/r80-bench.conf
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(dirname "$HERE")"
USER_NAME="$(id -un)"
USER_ID="$(id -u)"
[[ "$USER_NAME" != root ]] || { echo "run as the user the HU should run as, not root (sudo is used inside)"; exit 1; }

for unit in r80-can.service r80-hu.service; do
  sed -e "s|@USER@|$USER_NAME|g" -e "s|@UID@|$USER_ID|g" -e "s|@REPO@|$REPO|g" "$HERE/$unit" \
    | sudo tee "/etc/systemd/system/$unit" >/dev/null
  echo "installed /etc/systemd/system/$unit (user $USER_NAME, repo $REPO)"
done
if [[ ! -f /etc/r80-bench.conf ]]; then
  sudo cp "$HERE/r80-bench.conf.example" /etc/r80-bench.conf
  [[ -z "${1:-}" ]] || sudo sed -i "s/^PC_IP=.*/PC_IP=$1/" /etc/r80-bench.conf
  echo "created /etc/r80-bench.conf$([[ -n "${1:-}" ]] && echo " with PC_IP=$1")"
fi
chmod +x "$HERE"/*.sh
sudo systemctl daemon-reload
echo "now: sudo systemctl enable --now r80-can.service (and r80-hu.service for the kiosk)"
