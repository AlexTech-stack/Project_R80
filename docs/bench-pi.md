# R80 bench: Raspberry Pi 3B prototype

How to run the headunit software (vehicle, media, audio, warnings, trip computer,
navigation and the UI) on a Raspberry Pi 3B. The car is still simulated on the test PC (BoAt + restbus);
only the CAN buses are tunnelled to the Pi with
[cannelloni](https://github.com/mguentner/cannelloni) (GPL-2.0). BoAt itself
never runs on the Pi.

This is the `bench` run mode (`./r80 bench <command>`, `./r80 --help`).
Everything the Pi runs under `hu/` is target software; `dev/mcu_emu/` stands in for
the not-yet-existing vehicle MCU. The restbus and the tester panel stay on the
test PC. The driver's phone pairs with the Pi over Bluetooth and sends its
navigation guidance with the R80 Companion app (decision D11).

```
 TEST PC (= "the car")                              Raspberry Pi 3B (= the headunit)
 ┌───────────────────────────────┐                  ┌──────────────────────────────┐
 │ BoAt gateway :50061           │                  │ cannelloni x3 (UDP)          │
 │ restbus.py / restbus_panel.py │                  │   |                          │
 │ vcan_info/motor/comfort       │◄── cannelloni ──►│ vcan_info/motor/comfort      │
 │ (the gateway writes frames)   │   (UDP, LAN)     │   |                          │
 └───────────────────────────────┘                  │ mcu_emu.py (MCU stand-in)    │
        ▲ panel + tests = PC only                    │   | (mcu_link UART)          │
        │                                            │ vehicled.py    -> D-Bus      │
        │                                            │ mediad.py      -> D-Bus      │
        │                                            │ audiod.py      -> D-Bus      │
        │                                            │ warnd.py       -> D-Bus      │
        │                                            │ tripd.py       -> D-Bus      │
        │                                            │ sysd.py        -> D-Bus      │
        │                                            │ navd.py        -> D-Bus      │◄── Bluetooth ── phone
                                                     │ hu/ui/run.py (eglfs)         │    (R80 Companion app)
                                                     └──────────────────────────────┘
```

Ports are UDP and the same on both ends: `vcan_info` 20000, `vcan_motor` 20001,
`vcan_comfort` 20002 (`-t 1000`, i.e. 1 ms aggregation, for a snappier UI).

The ready-made files live in `bench/pi/`:

| File | Runs on | Purpose |
|---|---|---|
| `pc-cannelloni.sh` | test PC | starts the three cannelloni servers |
| `r80-can.sh` | Pi | creates the vcans and starts the three cannelloni clients |
| `r80-can.service` | Pi | systemd unit for `r80-can.sh` |
| `r80-kiosk.sh` | Pi | starts mcu emu + vehicled + mediad + audiod + warnd + tripd + navd + sysd + the UI |
| `r80-hu.service` | Pi | systemd unit for `r80-kiosk.sh` (eglfs kiosk) |
| `r80-media.rules` | Pi | polkit rule: the HU may mount USB sticks (and set up test-stick images) |
| `r80-bench.conf.example` | Pi | `PC_IP`/ports for the can service |
| `install-units.sh` | Pi | installs both units (and with `--desktop` the desktop unit) for the current user and checkout; `./r80 bench install` |
| `pc-share-internet.sh` | test PC | shares the PC's internet with the Pi over the cable (NAT) |

## 1. Hardware

Pi 3B, 5 V/2.5 A supply, microSD >= 16 GB (A1/A2), heatsink (the 3B throttles
under sustained Qt + GStreamer load), HDMI monitor, USB keyboard and mouse,
speakers/headphones on the 3.5 mm jack. PC and Pi on the same LAN. The Pi's
built-in Bluetooth is the link to the phone; keep it enabled. For the
navigation test an Android 14+ phone with Google Maps and the R80 Companion app.

## 2. Operating system

Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager. Use the current
Debian 13 "Trixie" image with desktop (not Lite: section 9 runs the UI in a
window first; section 11 switches the desktop off). The 64-bit image supports the
3B, and its glibc (>= 2.39) is new enough for the latest PySide6 `aarch64` wheel.
Set user, locale, timezone and enable SSH in Imager (any user name; the units
are filled in for it in section 7).

**Network.** The bench uses a direct cable between PC and Pi (static addresses,
e.g. PC 200.200.0.101, Pi 200.200.0.102) for SSH, VNC and the CAN tunnel. The Pi
also needs internet for the steps below. The Pi 3B only does 2.4 GHz Wi-Fi; on a
crowded 2.4 GHz channel it was unusable here (seconds of delay, most packets
lost, `brcmf ... status -110` in `dmesg`). Reliable instead: the PC shares its
internet over the cable.

```bash
# test PC (once; persistent; undo: see the script's header)
./r80 bench share-internet enp0s31f6 200.200.0.0/24
# Pi: gateway = the PC, public DNS, Wi-Fi off
sudo nmcli con modify <cable connection> ipv4.gateway 200.200.0.101 ipv4.dns "1.1.1.1 8.8.8.8" ipv4.ignore-auto-dns yes
sudo nmcli dev reapply eth0
sudo nmcli radio wifi off
```

**Screen without a monitor.** Make the Pi behave as if a 1280 x 768 display were
connected (the HU's design size; it also gives eglfs a display later), and turn on
its VNC server:

```bash
sudo sed -i '1 s/$/ video=HDMI-A-1:1280x768M@60D/' /boot/firmware/cmdline.txt
sudo raspi-config nonint do_vnc 0
sudo reboot
```

On the PC: `vncviewer <pi address>` (TigerVNC), log in with the Pi's user and
password. On a bench where only the PC can reach the Pi, the login can go: in
`/etc/wayvnc/config` set `enable_auth=false` and bind it to the cable address
(`address=<pi address on the cable>`), then `sudo systemctl restart wayvnc`. Screenshots over SSH: `XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0 grim shot.png`.

Then:

```bash
sudo apt update && sudo apt full-upgrade -y
uname -m          # must be aarch64
ldd --version     # glibc >= 2.39 for PySide6 6.11
python3 --version # must be 3.10 - 3.14
bluetoothctl show # an adapter, "Powered: yes" (BlueZ comes with Raspberry Pi OS)
```

## 3. Dependencies

```bash
sudo apt install -y python3-venv python3-dbus python3-gi gir1.2-glib-2.0 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly gstreamer1.0-tools \
  gstreamer1.0-alsa libegl1 libgles2 libgbm1 libdrm2 libinput10 \
  libxkbcommon0 libfontconfig1 libxcb-cursor0 libxkbcommon-x11-0 \
  can-utils cmake build-essential dlt-daemon dlt-tools

python3 -m venv --system-site-packages ~/r80-venv
~/r80-venv/bin/pip install --upgrade pip
~/r80-venv/bin/pip install PySide6          # fallback: "PySide6==6.7.*" on older glibc
```

`--system-site-packages` is what lets the venv see apt's `gi` (GStreamer) and
`dbus`. pip only installs PySide6 into the venv; Raspberry Pi OS Python is
externally managed.

cannelloni is usually built from source:

```bash
cannelloni --help >/dev/null 2>&1 || {
  git clone https://github.com/mguentner/cannelloni ~/cannelloni
  cmake -B ~/cannelloni/build -S ~/cannelloni -DCMAKE_BUILD_TYPE=Release -DSCTP_SUPPORT=OFF
  cmake --build ~/cannelloni/build
  sudo cmake --install ~/cannelloni/build
}
```

Sanity checks:

```bash
~/r80-venv/bin/python -c "import gi; gi.require_version('Gst','1.0'); from gi.repository import Gst; Gst.init(None); print(Gst.version_string())"
~/r80-venv/bin/python -c "import dbus, dbus.mainloop.glib; import PySide6; print('dbus + PySide6', PySide6.__version__)"
```

## 4. Code

```bash
git clone git@github.com:AlexTech-stack/Project_R80.git ~/Project_R80
cd ~/Project_R80
```

Use `master`. To update later: `./r80 bench update` (`git pull`, then restart the HU).
After a change to the units or to paths, run `./r80 bench install --desktop` again.

Optional, a USB stick for repo, venv and music (saves the SD card; on a Pi 3B it
is not faster, USB and Ethernet share one USB 2.0 bus). Format it ext4, mount it
by UUID in `/etc/fstab` (e.g. at `/mnt/r80`, with `nofail`), put the three folders
there and link them, so every path in this guide stays the same:

```bash
ln -s /mnt/r80/Project_R80 ~/Project_R80
ln -s /mnt/r80/r80-venv ~/r80-venv
ln -s /mnt/r80/Music ~/Music
```

## 5. Music and 3.5 mm audio

```bash
mkdir -p ~/Music                    # the Library: copy mp3/ogg/flac/wav here
```

USB sticks are a second source: mediad (`--usb system`) sees them through udisks2,
mounts them read-only, names them after their label and plays one as soon as it is
plugged in. The HU runs outside the desktop session, so udisks2 needs the polkit rule
`r80-media.rules`, installed by `./r80 bench install` (section 9). The bench's own
storage stick (`/mnt/r80`, in `/etc/fstab`) is never a source.

Without a spare stick, a disk image attached by the bench user plays the stick
(`sudo apt install dosfstools mtools` once):

```bash
truncate -s 64M /mnt/r80/teststick.img && /usr/sbin/mkfs.vfat -n R80STICK /mnt/r80/teststick.img
mcopy -i /mnt/r80/teststick.img ~/Music/*.mp3 ::/       # some music onto it
udisksctl loop-setup -f /mnt/r80/teststick.img           # "plug in" (the desktop mounts it)
udisksctl loop-delete -b /dev/loopN && udisksctl unmount -b /dev/loopN   # "pull" (this order: else mediad mounts it again)
```

A big test stick for scan and browse speed (2000 short tagged tones, 100 albums):

```bash
python3 ~/Project_R80/dev/media_tags.py big-library /mnt/r80/bigstick
truncate -s 160M /mnt/r80/bigstick.img && /usr/sbin/mkfs.vfat -n BIGSTICK /mnt/r80/bigstick.img
mcopy -s -i /mnt/r80/bigstick.img /mnt/r80/bigstick/* ::/
```

Which source played, where in which track, and whether it played is kept in
`~/.local/state/r80/media.json` (saved on a source change, before a shutdown and when
systemd stops the HU) and restored at start; a stick is waited for 15 s.

`dtparam=audio=on` in `/boot/firmware/config.txt` (the default) gives the jack as
ALSA card `bcm2835 Headphones`. The HU's services play through PipeWire's default
output, so make the jack the default and give the volume to the HU (audiod, D9):
PipeWire at 0 dB on the jack. At 100 % the Pi's analog output runs at +4 dB and
distorts loud tracks.

```bash
wpctl status                        # under Sinks: the "Built-in Audio" whose card is bcm2835 Headphones
wpctl inspect <id> | grep -E "alsa.pcm.card|node.name"
wpctl set-default <id>              # stored by name, survives reboots and HDMI audio appearing
wpctl set-volume <id> 0.86          # = 0 dB on the jack (amixer -c 1 sget PCM)
```

While the HU plays, `wpctl status` lists a `python` stream going to
`bcm2835 Headphones`. Test without the HU: `speaker-test -t sine -c 2 -l 1`.

## 6. CAN tunnel (test PC)

Keep the normal PC environment running (`./r80 virtual drive` brings up the
gateway and the three vcans, plus the restbus). Then start the tunnel:

Put the Pi's address into `~/.config/r80/hu-virtual.env` once; from then on
`./r80 virtual up` / `drive` also start the tunnel (`tunnel` in `status`), and
`down` stops it. `./r80 virtual test` and `ci/run_boat_sil.sh` keep it off, so
the Pi's headunit cannot answer on the test buses.

```bash
mkdir -p ~/.config/r80 && echo "PI_IP=<raspberry-ip>" >> ~/.config/r80/hu-virtual.env
cd ~/Project_R80
./r80 bench rbs                                        # the rest of the car for the Pi, with the tester panel
./r80 bench rbs drive                                  # ... or with the drive cycle
./r80 bench rbs stop                                   # all of it down again
candump -a vcan_info                                   # frames the Pi should see
```

`./r80 bench rbs` starts only what the Pi needs from the PC: the buses, the BoAt
gateway, the tunnel and the restbus (panel or drive cycle). No headunit runs on the
PC then, so the Pi's is the only one on the buses. The panel's knob, keys and dimming
override reach the Pi's MCU emulator: `rbs` forwards its control socket over SSH
(`./r80 virtual mcufwd`; needs a key login to the Pi, `PI_USER` if your login there differs).
For a PC headunit next to the Pi (the BoAt tests), use
`./r80 virtual drive` (or `up` + `panel`) instead: it starts the tunnel too, and
`./r80 bench tunnel` adds it to a running environment. Allow UDP 20000-20002
through the PC firewall.

## 7. CAN tunnel (Pi)

Install the two units for your user and checkout (as that user, not root). It
fills in user, UID and repo path, and creates `/etc/r80-bench.conf` with `PC_IP`
(the PC's address on the link to the Pi) if it does not exist yet:

```bash
~/Project_R80/r80 bench install <PC_IP>
```

To bring the tunnel up manually first:

```bash
sudo modprobe vcan
for b in vcan_info vcan_motor vcan_comfort; do
  sudo ip link add "$b" type vcan 2>/dev/null || true
  sudo ip link set "$b" up
done
cannelloni -I vcan_info    -R <PC_IP> -r 20000 -l 20000 -t 1000 &
cannelloni -I vcan_motor   -R <PC_IP> -r 20001 -l 20001 -t 1000 &
cannelloni -I vcan_comfort -R <PC_IP> -r 20002 -l 20002 -t 1000 &
candump -a vcan_info        # must mirror the PC
```

Debug a broken tunnel with `cannelloni -d cut`.

## 8. Pi vehicle stack (manual bring-up)

Only Infotainment and the MCU's CAN 2 are consumed by `mcu_emu`; the third bus is
tunnelled for completeness and later use.

```bash
cd ~/Project_R80
~/r80-venv/bin/python dev/mcu_emu/mcu_emu.py --can1 vcan_info --can2 vcan_motor --can2-bus motor &
~/r80-venv/bin/python hu/services/vehicled.py &
gdbus call --session -d de.r80.Vehicle -o /de/r80/Vehicle \
  -m org.freedesktop.DBus.Properties.Get de.r80.Vehicle1 VehicleSpeed
```

## 9. First UI run (windowed, on the desktop)

Validate before the kiosk, so the desktop owns the display:

```bash
cd ~/Project_R80
~/r80-venv/bin/python hu/services/mediad.py --music-dir ~/Music &
~/r80-venv/bin/python hu/services/audiod.py &
~/r80-venv/bin/python hu/services/warnd.py &
~/r80-venv/bin/python hu/services/tripd.py &
~/r80-venv/bin/python hu/services/sysd.py &
~/r80-venv/bin/python hu/services/navd.py --bluetooth system &
~/r80-venv/bin/python hu/ui/run.py
```

Without a monitor (VNC, section 2), the same as one command that survives logging
out of SSH: everything `r80-kiosk.sh` starts, with the UI full screen on the desktop
instead of eglfs:

```bash
systemd-run --user --unit=r80-hu-window --collect -E QT_QPA_PLATFORM=wayland -E WAYLAND_DISPLAY=wayland-0 \
  dbus-run-session -- ~/Project_R80/bench/pi/r80-kiosk.sh
systemctl --user stop r80-hu-window      # stop it again; logs in /tmp/r80-*.log
```

To start it with the desktop at every boot (the Pi logs in automatically), install
it once as a user service with an autostart entry, and enable the tunnel:

```bash
~/Project_R80/r80 bench install --desktop
sudo systemctl enable --now r80-can.service
./r80 bench status                                     # the unit restarts the HU if it crashes
./r80 bench restart | stop | start | logs
```

Expected: live Vehicle/Drive screens (from the tunnel), real media playback, and
Navigation saying "No phone connected" until the phone is paired and connected
(section 10). navd prints "companion service registered with BlueZ" at start.
Headless check: `hu/ui/run.py --screenshot /tmp/hu.png`.

## 10. Phone (R80 Companion app, calls, contacts, music)

Pair once; afterwards the app connects by itself whenever it is started.

1. Install the app on the phone and set it up as in
   [`../companion-android/README.md`](../companion-android/README.md) (APK from the
   CI job `android`, notification access, permissions).
2. Make the Pi visible and accept pairings without a prompt. `bluetoothctl`'s own
   agent cannot register while the desktop runs one, so use `bt-agent`:
   ```bash
   sudo apt install -y bluez-tools
   bt-agent -c NoInputNoOutput &                 # accepts pairings; stop it afterwards
   bluetoothctl discoverable-timeout 600
   bluetoothctl discoverable on
   ```
3. On the phone: Settings → Bluetooth → under available devices "Refresh", tap
   the Pi (its hostname), confirm "Pair".
4. On the Pi: trust the phone (reconnects without asking), hide the Pi again,
   stop the agent:
   ```bash
   bluetoothctl devices Paired                   # the phone's address
   bluetoothctl trust <phone address>
   bluetoothctl discoverable off
   kill %1                                       # bt-agent
   ```
5. In the app: Bluetooth → choose the Pi → Connect. Start a route in Google Maps.
   The HU's Navigation screen shows the guidance; `Phone.via` says "Bluetooth":
   ```bash
   gdbus call --session -d de.r80.Nav -o /de/r80/Nav \
     -m org.freedesktop.DBus.Properties.Get de.r80.Nav1 Phone
   ```

Without a phone: the phone panel on the PC (`./r80 virtual phonepanel`,
see `dev/README.md`) reaches the Pi's navd over the cable once navd has a TCP
port. For the desktop service: `systemctl --user edit r80-hu-desktop`, add
`[Service]` / `Environment="R80_NAV_ARGS=--tcp 47800"` (with the quotes), restart it, then connect the
panel to `tcp:<pi-ip>:47800` (no authentication: only on the cable to the PC).

navd only accepts paired phones (BlueZ checks that before navd sees the
connection). Pair while the desktop is still on, before the kiosk takes over.

Xiaomi / HyperOS phones: allow the app "Autostart" and set its battery saver to
"No restrictions" (App info), or Android may not start its notification listener
(the app then shows "No navigation running" although Maps navigates).

### Weather, car status and the remote (the app)

With the link up the app also sends the weather and the altitude (Clock & Weather on the
HU; the app needs location), gets the car's status (its Car tab; set the ignition to Off in
the tester panel to see the final one and "Parked here") and works as a remote (its Remote
tab; on the HU Settings → Phone → "Remote from the app" switches that off):

```bash
gdbus call --session -d de.r80.Nav -o /de/r80/Nav \
  -m org.freedesktop.DBus.Properties.Get de.r80.Nav1 Weather
```

### Calls, contacts and music from the phone (D13)

The paired phone also does hands-free calls, contacts and music; hu-phoned and hu-mediad
use PipeWire and BlueZ on the desktop's session bus (`r80-kiosk.sh`). `./r80 bench install`
puts the settings in place:

| File | Installed to | What |
|---|---|---|
| `r80-telephony.conf` | `~/.config/wireplumber/wireplumber.conf.d/80-r80-telephony.conf` | PipeWire's call control on D-Bus (`org.pipewire.Telephony`); calls into the "R80 call" stage, phone music into "R80 Bluetooth music" |
| `r80-pipewire.conf` | `~/.config/pipewire/pipewire.conf.d/80-r80.conf` | the two stages (loopbacks) where the HU sets the levels |
| `r80-bt-sco.service` / `.sh` | `/etc/systemd/system/` | call audio of the Pi's built-in Bluetooth over HCI (see below); enable it: `sudo systemctl enable --now r80-bt-sco.service` |

- **Calls:** ringing, answer, end, dial work from the HU. A USB headset (or USB
  microphone) is the HU's microphone; without one the stream to the phone stays muted
  and the call popup says "No microphone".
- **Level:** PipeWire passes a Bluetooth stream's volume on to the phone (AT+VGS, AVRCP
  absolute volume), so the phone's streams stay at full level and the HU sets the level
  on its stages: calls at the phone volume plus `call_boost_db` (audio.ini, +12 dB),
  phone music at the media volume.
- **Contacts:** the HU asks the first time; then the phone has to share them. HyperOS
  shows no prompt and refuses (`OBEX Connect failed with 0x53`, shown under Settings →
  Phone): on the phone, Settings → Bluetooth → the Pi → switch on **Contact sharing**,
  then Settings → Phone → Sync now on the HU.
- **Music:** start music on the phone; the HU switches to the Bluetooth source while
  nothing else plays. If the phone only connected for calls,
  `bluetoothctl connect <phone> 0000110a-0000-1000-8000-00805f9b34fb` adds A2DP.

**The Pi 3B's built-in Bluetooth (BCM43438 on a UART) is too weak for this.** It sends
call audio (SCO) to its PCM pins by default (silent calls; `r80-bt-sco.service` switches
it to HCI with a Broadcom vendor command at every bluetooth start), and under call or
music traffic the UART link loses frames (`dmesg`: "Frame reassembly failed", "link tx
timeout, killing stalled connection"): calls look stuck until the link drops, A2DP drops
after a while, the chip may hang until a reboot. Use a USB Bluetooth adapter for calls
and phone music: a **TP-Link UB500** (Realtek RTL8761BU, firmware in `firmware-realtek`)
or a genuine **CSR8510 A10** (e.g. Plugable USB-BT4LE; avoid no-name "CSR 4.0" clones).
Then switch the built-in one off (`dtoverlay=disable-bt` in `/boot/firmware/config.txt`,
reboot) and pair the phone again (new address); `r80-bt-sco.sh` does nothing on a USB
adapter. The copies of the contacts are per phone and stay.

## 11. eglfs kiosk (with a monitor)

Only with a monitor on the Pi: eglfs takes the display from the desktop, so VNC
shows nothing any more. Without a monitor use the desktop mode of section 9.

Disable the desktop and grant device access:

```bash
sudo systemctl set-default multi-user.target
sudo systemctl disable --now lightdm 2>/dev/null || true
sudo usermod -aG video,render,input,audio $USER
```

`r80-kiosk.sh` starts the DLT daemon, mcu emu, `vehicled`, `mediad`, `audiod`, `warnd`, `tripd`, `sysd`, `navd`
(`--bluetooth system`), `phoned` and `syslogd`, then execs the UI with
`QT_QPA_PLATFORM=eglfs`. `r80-hu.service` wraps it in `dbus-run-session` so the
services and the UI share one session bus (`de.r80.Vehicle` / `de.r80.Media`),
and requires `r80-can.service`:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now r80-can.service r80-hu.service
```

Edit the paths in `r80-kiosk.sh` and the units if the repo, venv or music live
somewhere other than `~/Project_R80`, `~/r80-venv` and `~/Music`; `r80-kiosk.sh`
also honours `R80_REPO`, `R80_VENV` and `R80_MUSIC`. `./r80 bench run` starts it in
the foreground, for debugging.

### The log (DLT, D14)

`r80-kiosk.sh` starts the HU's DLT daemon first (`hu/services/dlt-daemon.sh`; Debian's own
`dlt` units are disabled by `./r80 bench install`, they would hold the port). Its files: a
16 MB ring in `~/.local/state/r80/dlt/trace/` (`dlt-convert -a <file>`). From the PC, DLT
Viewer or `dlt-receive -a <PI_IP>` read it live on port 3490. On the HU: Settings →
Diagnostics (warnings and errors per service, log level per service), and Export to USB
writes the files and a `summary.txt` onto the stick in `R80-logs/<date_time>/` (the music
from that stick stops for a few seconds).

The system's own log is in it too: `hu/services/syslogd.py` follows the journal and writes the
kernel's, BlueZ's, PipeWire's, NetworkManager's and the `r80-*` units' lines, cleaned
(`hu/services/syslog.ini`), as the DLT application `OS` (contexts `KERN BT PW NET UNIT SYSD`).
Reading the system journal needs the user in the group `adm` (Raspberry Pi OS: already) or
`systemd-journal`. It keeps its place in `~/.local/state/r80/syslog.cursor`; the first start
reads the whole boot. The Pi 3B's built-in Bluetooth shows up there as
`Bluetooth: hci0: Frame reassembly failed` (lost data on its UART), hundreds of times per call
or music session.

## 12. Verify

`./r80 bench measure` reports the start-up times and the memory; `--restart` restarts the HU
and times that start. Results: [bench-measurements.md](bench-measurements.md).

- `journalctl -u r80-can -u r80-hu -f` and `cat /tmp/r80-*.log`.
- `candump -a vcan_info` on the Pi mirrors the PC.
- `gdbus` reads `de.r80.Vehicle` / `de.r80.Media`; transport buttons change the
  track and position advances.
- `/tmp/r80-navd.log` says "companion service registered with BlueZ"; with the
  app connected, "phone hello: <phone model>".
- `/tmp/r80-sysd.log` says "saver registered: audiod / tripd / mediad"; Settings → System on
  the HU lists 7 of 7 services running. The settings are kept in
  `~/.local/state/r80/settings.json`.
- `dlt-receive -a localhost` shows the services' lines (ECU `R80`) and the system's (`OS`);
  Settings → Diagnostics lists every service as running, and "System log (journal)".
- `vcgencmd measure_temp` under load; add cooling if it throttles.

## 13. Troubleshooting

- **eglfs blank or fails:** try `QT_QPA_EGLFS_INTEGRATION=eglfs_kms`, then
  `QT_QPA_EGLFS_ALWAYS_SET_MODE=1`; check `dmesg` for the `v3d` driver. Last
  resort `QT_QUICK_BACKEND=software` (slower but reliable on a 3B).
- **Keyboard/mouse dead under eglfs:** ensure `libinput10` is installed and the
  user is in the `input` group.
- **No services on D-Bus:** both `vehicled`/`mediad` and the UI must run under the
  same `dbus-run-session`; start them before the UI.
- **Tunnel one-way or empty:** `cannelloni -d cut`, check firewall/ports, and that
  `ip -br link` shows the vcans `UP`.
- **No sound:** `gst-inspect-1.0 | grep -E 'alsa|pulse|pipewire'`; force the sink
  with `~/r80-venv/bin/python hu/services/mediad.py --sink alsasink`.
- **navd: "BlueZ refused the companion service":** add the user to the
  `bluetooth` group (`sudo usermod -aG bluetooth $USER`, log in again) and check
  `systemctl status bluetooth`.
- **App stays at "connecting" over Bluetooth:** the phone must be paired with the
  Pi (section 10) and navd running with `--bluetooth system`; `bluetoothctl info
  <phone address>` should show `Paired: yes` and `Trusted: yes`. Removing and
  re-pairing on both sides fixes most cases.
- **Out of memory:** the 3B has only 1 GB; use a leaner image or reduce what runs
  beside the UI.

## Known limitations

- The tester panel's knob/button controls drive the **PC** headunit
  (`restbus_panel.py` -> the PC `mcu_emu` socket); the Pi is controlled by its
  own keyboard. The panel's CAN-signal editing does reach the Pi over the tunnel.
- The BoAt tests still validate the PC's `vehicled`; testing the Pi's D-Bus
  remotely is separate future work.
- Hands-free calls and phone music on the Pi 3B's built-in Bluetooth are unreliable
  (section 10); a USB adapter fixes that. No echo cancellation yet (a headset does not
  need it; the car's speakers and microphone will).
- UDP can lose and reorder frames. If that matters, lower `-t` further or switch
  cannelloni to TCP (`-C s` / `-C c`) or SCTP.
- No BoAt, `mcu_emu` or `boat` imports under `hu/`: the Pi runs the target
  software unchanged, plus the PC-only stand-ins as separate processes
  (AGENTS.md section 8).
