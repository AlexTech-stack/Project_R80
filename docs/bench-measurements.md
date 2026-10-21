# Bench measurements

Start-up time and memory of the headunit on the Raspberry Pi bench, against the targets
of the architecture (§5: UI visible < 8 s after ignition, audio resumes < 5 s). Measured
with `./r80 bench measure` (`bench/pi/measure.py`): boot times from systemd, the HU's
start from its DLT log (timestamps since boot; the UI logs when it drew its first frame),
memory as PSS from `/proc/<pid>/smaps_rollup`, CPU from `/proc/<pid>/stat`.

## 2026-10-21: Raspberry Pi 3 Model B (1 GB), Raspberry Pi OS desktop

Setup: Debian 13 based Raspberry Pi OS with the desktop (labwc, wayvnc, autologin),
SD card, the HU as the desktop unit (`r80-hu-desktop`: DLT daemon, MCU emulator, 8
services, UI), PySide6 6.x from pip, the tester panel on the PC sending ~170 CAN
frames/s through the tunnel.

### Cold boot (power on to the first frame)

| step | after power on |
|---|---|
| kernel done | 5.3 s |
| desktop session (user@1000) | 28.0 s |
| HU unit started (desktop autostart) | 33.5 s |
| DLT daemon | 34.3 s |
| services on D-Bus: navd, tripd, vehicled, phoned, audiod, sysd | 37.5 – 38.6 s |
| **UI: first frame** | **44.9 s** (the UI process took 11.3 s: Qt imported 6.3 s, backends 7.3 s, QML loaded 9.6 s) |
| mediad on D-Bus, then the music loaded | 47.3 s, 47.8 s |
| warnd on D-Bus | 48.0 s |

The 33.5 s before the HU starts are the desktop OS: NetworkManager (6.1 s), cloud-init
(4.7 s), the swap file resize (3.2 s), wayvnc (3.2 s), waiting for the network, the
desktop login. None of that is needed by the HU; a target image would not have it.

### HU restart (warm: everything in the page cache)

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| UI first frame after the restart | 5.8 s | 6.3 s | 5.5 s |
| ... inside the UI process: Qt imported / QML loaded / first frame | 3.9 / 5.2 / 5.7 s | 3.7 / 5.7 / 6.3 s | 3.7 / 5.0 / 5.5 s |
| music loaded after the restart | 3.3 s | 3.4 s | 3.4 s |

On their own (warm, nothing else starting) the pieces are much faster: Python 0.14 s,
dbus-python + GLib 0.9 s, GStreamer 0.8 s, PySide6 with Qt Quick 1.2 s. In the real start
9 processes start at once on 4 cores and slow each other down: the UI needs 3.7 s to
import Qt instead of 1.2 s.

**Experiment**: the services at a lower CPU priority (`nice -n 10`) and without the kiosk
script's fixed 1 s wait before the UI: first frame after **4.2 s and 4.1 s** (1.5 to 2 s
earlier; Qt imported after 1.6 s), the music loaded after 4.8 s (1.4 s later, still < 5 s).
Then the UI can draw before the services answer, and for that moment `Sim.qml` shows its
demo data (see the decisions below).

### Memory (PSS, MB; after the cold boot / after warm restarts)

| process | after boot | warm | notes |
|---|---|---|---|
| UI (PySide6, Qt Quick) | 100.6 | 115.1 | the biggest single part |
| mediad | 27.1 | 33.6 | GStreamer |
| warnd | 18.4 | 22.5 | GStreamer for the chimes |
| sysd, phoned, audiod, navd, tripd, vehicled | 8 – 12 each | 15 – 18 each | Python + dbus-python + GLib each |
| MCU emulator (bench only) | 4.4 | 8.5 | the real MCU does this |
| DLT daemon | 0.4 | 0.9 | |
| **headunit together** | **210** (+58 swapped out) | **277** | |

The desktop adds about 150 MB (panel, file manager, portals, labwc, PipeWire). After boot:
368 MB of 905 MB available, 97 MB in swap. CPU at idle with the CAN traffic: the HU
together 30 % of one core (vehicled 12 %, MCU emulator 8 %, UI 7 %); without CAN 8 %.

### What it means

- **UI < 8 s after ignition** is far off from a cold boot on this bench (45 s), but most
  of that is the desktop OS. The HU itself needs 11 s cold and 4 – 6 s warm. A trimmed
  image on the Pi 3 (kernel 5 s + a few seconds of userspace) plus the HU cold would be
  about 15 – 20 s: still over 8 s. Reaching 8 s needs one of: a faster board (D4), the HU
  not booting from cold at every ignition (kept in suspend-to-RAM or standby while the car
  is off: a power decision with the MCU), or both.
- **Audio < 5 s**: met warm (3.4 s), not cold (14 s after the HU starts: mediad's
  GStreamer start from the SD card).
- **Memory**: the HU takes 210 – 280 MB. On a board without the desktop, about 400 MB used
  in all: 1 GB is comfortable, 512 MB would be tight (the UI alone is 100+ MB).
- **PySide6** costs start time (1.2 s warm, more cold, 676 MB installed) and about 100 MB.
  A small C++ launcher would start Qt faster and save memory, but the backends
  (`hu/ui/backend.py`, dbus-python) would have to be rewritten in C++ (QtDBus): worth it
  only once the board is chosen.
