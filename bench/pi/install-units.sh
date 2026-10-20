#!/usr/bin/env bash
# Installs the bench's systemd units for the current user and this checkout:
# fills in @USER@, @UID@ and @REPO@ in r80-can.service / r80-hu.service, copies them
# to /etc/systemd/system and creates /etc/r80-bench.conf (from the example) if missing.
# Also the polkit rule r80-media.rules (USB sticks for hu-mediad, test-stick images) and the
# WirePlumber setting r80-telephony.conf (PipeWire's call control for hu-phoned).
# Does not enable or start them.
# --desktop: also the HU on the desktop (no monitor, VNC): r80-hu-desktop.service as a user
# unit, started by the desktop's autostart at every login (the Pi logs in automatically).
#
#   bench/pi/install-units.sh [--desktop] [PC_IP]    # PC_IP goes into a new /etc/r80-bench.conf
set -euo pipefail
DESKTOP=""
[[ "${1:-}" == --desktop ]] && { DESKTOP=1; shift; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/../.." && pwd -P)"
USER_NAME="$(id -un)"
USER_ID="$(id -u)"
[[ "$USER_NAME" != root ]] || { echo "run as the user the HU should run as, not root (sudo is used inside)"; exit 1; }

for unit in r80-can.service r80-hu.service; do
  sed -e "s|@USER@|$USER_NAME|g" -e "s|@UID@|$USER_ID|g" -e "s|@REPO@|$REPO|g" "$HERE/$unit" \
    | sudo tee "/etc/systemd/system/$unit" >/dev/null
  echo "installed /etc/systemd/system/$unit (user $USER_NAME, repo $REPO)"
done
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cp "$HERE/r80-telephony.conf" ~/.config/wireplumber/wireplumber.conf.d/80-r80-telephony.conf
systemctl --user try-restart wireplumber.service 2>/dev/null || true
echo "installed ~/.config/wireplumber/wireplumber.conf.d/80-r80-telephony.conf (PipeWire call control for hu-phoned)"
sed -e "s|@USER@|$USER_NAME|g" "$HERE/r80-media.rules" | sudo tee /etc/polkit-1/rules.d/50-r80-media.rules >/dev/null
echo "installed /etc/polkit-1/rules.d/50-r80-media.rules (user $USER_NAME may mount sticks, set up loop devices)"
if [[ ! -f /etc/r80-bench.conf ]]; then
  sudo cp "$HERE/r80-bench.conf.example" /etc/r80-bench.conf
  [[ -z "${1:-}" ]] || sudo sed -i "s/^PC_IP=.*/PC_IP=$1/" /etc/r80-bench.conf
  echo "created /etc/r80-bench.conf$([[ -n "${1:-}" ]] && echo " with PC_IP=$1")"
fi
chmod +x "$HERE"/*.sh
sudo systemctl daemon-reload
if [[ -n "$DESKTOP" ]]; then
  mkdir -p ~/.config/systemd/user ~/.config/autostart
  sed -e "s|@REPO@|$REPO|g" "$HERE/r80-hu-desktop.service" > ~/.config/systemd/user/r80-hu-desktop.service
  cp "$HERE/r80-hu-desktop.desktop" ~/.config/autostart/r80-hu-desktop.desktop
  systemctl --user daemon-reload
  echo "installed r80-hu-desktop.service (user) + desktop autostart: the HU starts with the desktop"
  echo "  now: systemctl --user start r80-hu-desktop   (or log in again / reboot)"
fi
echo "now: sudo systemctl enable --now r80-can.service (and r80-hu.service for the kiosk)"
