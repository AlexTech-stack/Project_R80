#!/usr/bin/env bash
# Test PC: share this PC's internet with the Raspberry Pi on the direct cable (NAT), for
# when the Pi has no usable network of its own (the Pi 3B only does 2.4 GHz Wi-Fi).
# Installs, and starts:
#   /etc/sysctl.d/60-r80-pi-share.conf     IPv4 forwarding
#   /usr/local/sbin/r80-pi-share           adds / removes the NAT and FORWARD rules (iptables)
#   r80-pi-share.service                   runs it at boot
# Undo: sudo systemctl disable --now r80-pi-share.service, then delete those three files.
# On the Pi: gateway = this PC's cable address, DNS e.g. 1.1.1.1 (docs/bench-pi.md section 2).
#
#   bench/pi/pc-share-internet.sh <cable interface> [<cable network>]
#   bench/pi/pc-share-internet.sh enp0s31f6 200.200.0.0/24
set -euo pipefail
LAN_IF="${1:?cable interface towards the Pi, e.g. enp0s31f6 (ip -br addr)}"
NET="${2:-200.200.0.0/24}"
ip link show "$LAN_IF" >/dev/null

sudo tee /etc/sysctl.d/60-r80-pi-share.conf >/dev/null <<CONF
# R80 bench: this PC routes the Raspberry Pi ($NET on $LAN_IF) to the internet.
# Together with r80-pi-share.service (NAT). Remove both to undo.
net.ipv4.ip_forward = 1
CONF
sudo tee /usr/local/sbin/r80-pi-share >/dev/null <<SCRIPT
#!/bin/sh
# R80 bench: NAT the Pi's cable network ($NET) out through whatever interface
# carries this PC's internet. Idempotent. Usage: r80-pi-share start|stop
NET=$NET
LAN_IF=$LAN_IF
rules() {
  iptables "\$1" FORWARD -s "\$NET" -i "\$LAN_IF" -j ACCEPT
  iptables "\$1" FORWARD -d "\$NET" -o "\$LAN_IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  iptables -t nat "\$1" POSTROUTING -s "\$NET" ! -o "\$LAN_IF" -j MASQUERADE
}
case "\$1" in
  start) rules -C 2>/dev/null || rules -I ;;
  stop)  rules -D 2>/dev/null || true ;;
  *) echo "usage: \$0 start|stop"; exit 2 ;;
esac
SCRIPT
sudo chmod 755 /usr/local/sbin/r80-pi-share
sudo tee /etc/systemd/system/r80-pi-share.service >/dev/null <<UNIT
[Unit]
Description=R80 bench: share this PC's internet with the Raspberry Pi on the cable (NAT)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/r80-pi-share start
ExecStop=/usr/local/sbin/r80-pi-share stop

[Install]
WantedBy=multi-user.target
UNIT
sudo sysctl -q -p /etc/sysctl.d/60-r80-pi-share.conf
sudo systemctl daemon-reload
sudo systemctl enable --now r80-pi-share.service
echo "sharing internet with $NET on $LAN_IF"
