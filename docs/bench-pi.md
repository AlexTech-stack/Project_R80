# R80 bench: Raspberry Pi 3B prototype

How to run the headunit software, especially the Media application, on a
Raspberry Pi 3B. The car is still simulated on the test PC (BoAt + restbus);
only the CAN buses are tunnelled to the Pi with
[cannelloni](https://github.com/mguentner/cannelloni) (GPL-2.0). BoAt itself
never runs on the Pi.

Everything the Pi runs under `hu/` is target software; `mcu_emu/` stands in for
the not-yet-existing vehicle MCU. The restbus and the tester panel stay on the
test PC.

```
 TEST PC (= "the car")                              Raspberry Pi 3B (= the headunit)
 ┌───────────────────────────────┐                  ┌──────────────────────────────┐
 │ BoAt gateway :50061           │                  │ cannelloni x3 (UDP)          │
 │ restbus.py / restbus_panel.py │                  │   |                          │
 │ vcan_info/motor/comfort       │◄── cannelloni ──►│ vcan_info/motor/comfort      │
 │ (the gateway writes frames)   │   (UDP, LAN)     │   |                          │
 └───────────────────────────────┘                  │ mcu_emu.py (MCU stand-in)    │
        ▲ panel + tests = PC only                    │   | (mcu_link UART)          │
        │                                            │ hu/vehicled.py -> D-Bus      │
        │                                            │ hu/mediad.py   -> D-Bus      │
                                                     │ hu/ui/run_hu.py (eglfs)      │
                                                     └──────────────────────────────┘
```

Ports are UDP and the same on both ends: `vcan_info` 20000, `vcan_motor` 20001,
`vcan_comfort` 20002 (`-t 1000`, i.e. 1 ms aggregation, for a snappier UI).

The ready-made files live in `r80_pi_testbench/`:

| File | Runs on | Purpose |
|---|---|---|
| `pc-cannelloni.sh` | test PC | starts the three cannelloni servers |
| `r80-can.sh` | Pi | creates the vcans and starts the three cannelloni clients |
| `r80-can.service` | Pi | systemd unit for `r80-can.sh` |
| `r80-kiosk.sh` | Pi | starts mcu emu + vehicled + mediad + the UI |
| `r80-hu.service` | Pi | systemd unit for `r80-kiosk.sh` (eglfs kiosk) |
| `r80-bench.conf.example` | Pi | `PC_IP`/ports for the can service |

> These files are on `master`. The Media service is on the `Media_Application`
> branch until it is merged. Check out `master` on the Pi once the branch is
> merged, or copy `r80_pi_testbench/` onto a `Media_Application` checkout
> meanwhile.

## 1. Hardware

Pi 3B, 5 V/2.5 A supply, microSD >= 16 GB (A1/A2), heatsink (the 3B throttles
under sustained Qt + GStreamer load), HDMI monitor, USB keyboard and mouse,
speakers/headphones on the 3.5 mm jack. PC and Pi on the same LAN.

## 2. Operating system

Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager. Use the current
Debian 13 "Trixie" image: the 64-bit image supports the 3B, and its glibc (>= 2.39)
is new enough for the latest PySide6 `aarch64` wheel. Set user, Wi-Fi, locale,
timezone and enable SSH in Imager. Then:

```bash
sudo apt update && sudo apt full-upgrade -y
uname -m          # must be aarch64
ldd --version     # glibc >= 2.39 for PySide6 6.11
python3 --version # must be 3.10 - 3.14
```

## 3. Dependencies

```bash
sudo apt install -y python3-venv python3-dbus python3-gi gir1.2-glib-2.0 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly gstreamer1.0-tools \
  gstreamer1.0-alsa libegl1 libgles2 libgbm1 libdrm2 libinput10 \
  libxkbcommon0 libfontconfig1 libxcb-cursor0 libxkbcommon-x11-0 \
  can-utils cmake build-essential

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
git checkout master                 # after Media_Application is merged
# or: git checkout Media_Application  # until then
```

## 5. Music and 3.5 mm audio

```bash
mkdir -p ~/Music                    # copy mp3/ogg/flac/wav here
```

Enable the headphone jack with `sudo raspi-config` -> System Options -> Audio ->
Headphones, then test with `speaker-test -t sine -c 1` or
`gst-play-1.0 ~/Music/<file>`. Under PipeWire use `wpctl status` /
`wpctl set-default <id>`; otherwise select the output in `alsamixer`.

## 6. CAN tunnel (test PC)

Keep the normal PC environment running (`./hu-virtual.sh drive` brings up the
gateway and the three vcans, plus the restbus). Then start the tunnel:

```bash
cd ~/Project_R80/hu-virtual
./hu-virtual.sh drive                                  # your usual PC env
PI_IP=<raspberry-ip> ~/Project_R80/r80_pi_testbench/pc-cannelloni.sh
candump -a vcan_info                                   # frames the Pi should see
```

Keep the PC's own mcu/vehicled/mediad running: the tester panel's knob/keys and
the six BoAt tests still drive that PC headunit. Allow UDP 20000-20002 through
the PC firewall.

## 7. CAN tunnel (Pi)

Copy `r80-bench.conf.example` to `/etc/r80-bench.conf` and set `PC_IP`. Install
the two units (once the repo is at `~/Project_R80`):

```bash
sudo cp ~/Project_R80/r80_pi_testbench/r80-can.service /etc/systemd/system/
sudo cp ~/Project_R80/r80_pi_testbench/r80-hu.service  /etc/systemd/system/
sudo cp ~/Project_R80/r80_pi_testbench/r80-bench.conf.example /etc/r80-bench.conf
sudo nano /etc/r80-bench.conf                          # set PC_IP
sudo chmod +x ~/Project_R80/r80_pi_testbench/*.sh
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
cd ~/Project_R80/hu-virtual
~/r80-venv/bin/python mcu_emu/mcu_emu.py --can1 vcan_info --can2 vcan_motor --can2-bus motor &
~/r80-venv/bin/python hu/vehicled.py &
gdbus call --session -d de.r80.Vehicle -o /de/r80/Vehicle \
  -m org.freedesktop.DBus.Properties.Get de.r80.Vehicle1 VehicleSpeed
```

## 9. First UI run (windowed, on the desktop)

Validate before the kiosk, so the desktop owns the display:

```bash
cd ~/Project_R80/hu-virtual
~/r80-venv/bin/python hu/mediad.py --music-dir ~/Music &
~/r80-venv/bin/python hu/ui/run_hu.py
```

Expected: live Vehicle/Drive screens (from the tunnel) and real media playback.
Headless check: `run_hu.py --screenshot /tmp/hu.png`.

## 10. eglfs kiosk

Disable the desktop and grant device access:

```bash
sudo systemctl set-default multi-user.target
sudo systemctl disable --now lightdm 2>/dev/null || true
sudo usermod -aG video,render,input,audio $USER
```

`r80-kiosk.sh` starts mcu emu, `vehicled` and `mediad`, then execs the UI with
`QT_QPA_PLATFORM=eglfs`. `r80-hu.service` wraps it in `dbus-run-session` so the
services and the UI share one session bus (`de.r80.Vehicle` / `de.r80.Media`),
and requires `r80-can.service`:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now r80-can.service r80-hu.service
```

Edit the paths in `r80-kiosk.sh` and the units if the repo, venv or music live
somewhere other than `~/Project_R80`, `~/r80-venv` and `~/Music`; `r80-kiosk.sh`
also honours `R80_HU`, `R80_VENV` and `R80_MUSIC`.

## 11. Verify

- `journalctl -u r80-can -u r80-hu -f` and `cat /tmp/r80-*.log`.
- `candump -a vcan_info` on the Pi mirrors the PC.
- `gdbus` reads `de.r80.Vehicle` / `de.r80.Media`; transport buttons change the
  track and position advances.
- `vcgencmd measure_temp` under load; add cooling if it throttles.

## 12. Troubleshooting

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
  with `~/r80-venv/bin/python hu/mediad.py --sink alsasink`.
- **Out of memory:** the 3B has only 1 GB; use a leaner image or reduce what runs
  beside the UI.

## Known limitations

- The tester panel's knob/button controls drive the **PC** headunit
  (`restbus_panel.py` -> the PC `mcu_emu` socket); the Pi is controlled by its
  own keyboard. The panel's CAN-signal editing does reach the Pi over the tunnel.
- The BoAt tests still validate the PC's `vehicled`; testing the Pi's D-Bus
  remotely is separate future work.
- UDP can lose and reorder frames. If that matters, lower `-t` further or switch
  cannelloni to TCP (`-C s` / `-C c`) or SCTP.
- No BoAt, `mcu_emu` or `boat` imports under `hu/`: the Pi runs the target
  software unchanged, plus the PC-only stand-ins as separate processes
  (AGENTS.md section 8).
