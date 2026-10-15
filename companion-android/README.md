# R80 Companion (Android app)

The app on the driver's phone (decision D11): the phone navigates, the headunit
displays. The app reads the turn-by-turn guidance of Google Maps' navigation
notification and sends it to the HU over the companion link
([`../docs/companion-protocol.md`](../docs/companion-protocol.md)).

Android 14 or newer, Kotlin, no Google Play services, MIT like the rest of R80.

## What it does

- **Reads Google Maps:** distance to the next maneuver, road, and remaining time
  and distance are text in the notification. The maneuver itself is only in the
  arrow image. The app turns that image into a small fingerprint and looks it up
  in [`app/src/main/assets/maneuver_icons.json`](app/src/main/assets/maneuver_icons.json):
  19 Google Maps arrows (turns of every strength, U-turn, forks, motorway exit,
  merge, roundabout right / straight / left, destination and its side), built from
  captured virtual drives in Pforzheim, Stuttgart and Karlsruhe. Only fingerprints
  are stored, never Google's images. An arrow that is not in the table yet reaches
  the HU as maneuver `unknown` with distance and road (generic arrow); capture
  mode records it, so it can be added.
- **Link to the HU:** Bluetooth RFCOMM to the paired HU (hu-navd registers the
  companion service with BlueZ and only accepts paired phones). For development
  also Wi-Fi: TCP to a PC running `hu-navd --tcp 47800` (trusted network only, no
  authentication). The link reconnects by itself and runs as a foreground
  service, so Android keeps it alive during a drive.
- **Capture (development):** records every Google Maps notification (all text
  fields, the arrow's fingerprint) and each different arrow image once. "Export
  to Downloads" saves a zip. The recording contains the streets of the drive and
  stays on the phone until you export or delete it.

## Install and set up

1. Get the APK: CI job `android`, artifact `r80-companion`
   (`r80-companion-debug.apk`), or build it yourself (below).
2. Install it on the phone (allow installing from that source).
3. Open the app → "Open notification access" → enable R80 Companion. Android 13+
   greys this out for apps not installed from a store: App info → ⋮ → "Allow
   restricted settings", then try again.
4. Allow notifications and "Nearby devices" when asked (the foreground service
   shows a notification; "Nearby devices" lets the app list the paired HU).

Each CI build is signed with a new debug key, so a newer APK from CI cannot
update an installed one: uninstall first (the settings are lost).

## Try it with the virtual HU

**Over Bluetooth** (the PC plays the HU; it needs a Bluetooth adapter):

1. Pair the phone with the PC (the PC's Bluetooth settings, or `bluetoothctl`).
2. Start the virtual HU with the PC's real Bluetooth:
   ```bash
   cd hu-virtual
   NAV_BLUETOOTH=system ./hu-virtual.sh up && ./hu-virtual.sh ui
   ```
   `$XDG_RUNTIME_DIR/r80-hu/navd.log` should say "companion service registered with BlueZ".
3. In the app: Bluetooth, choose the PC, Connect, then start a route in Google Maps.

**Over Wi-Fi** (phone and PC in the same network; the PC's firewall must allow TCP 47800):

```bash
cd hu-virtual
NAV_ARGS="--tcp 47800" ./hu-virtual.sh up && ./hu-virtual.sh ui
```

In the app: Wi-Fi (development), enter `<PC's IP>:47800`, Connect.

Either way the HU's Navigation screen follows the route.

## Build

```bash
ci/build_android.sh          # unit tests + debug APK into build/ci/android/
```

Needs JDK 21, Gradle 9.8 and the Android SDK (`ANDROID_HOME`); Android Studio
brings the SDK and can open `companion-android/` directly. The unit tests run on
the PC (no phone): the protocol against
[`../docs/companion-protocol-examples.jsonl`](../docs/companion-protocol-examples.jsonl)
(the HU checks the same file in TC_HU_020), the Maps parser, the arrow
fingerprints, and the link against a fake HU.

## Files

```
app/src/main/java/de/r80/companion/
  Protocol.kt             companion link protocol v1 (phone side)
  Link.kt                 session: hello, guidance, heartbeats, reconnect; TCP transport
  BluetoothTransport.kt   RFCOMM to the paired HU
  MapsParser.kt           Google Maps notification text -> Guidance
  IconTable.kt            arrow image fingerprints -> maneuver
  MapsListenerService.kt  notification listener; capture hook
  LinkService.kt          foreground service holding the link
  Capture.kt              capture mode and export
  MainActivity.kt, Settings.kt, AppState.kt   screen, settings, shared state
app/src/main/assets/maneuver_icons.json        known arrows (built from captures)
app/src/test/                                  JVM unit tests
```
