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
  in [`app/src/main/assets/maneuver_icons.json`](app/src/main/assets/maneuver_icons.json).
  That table is empty until it is built from captured drives (see Capture). Until
  then the HU gets maneuver `unknown` with distance and road, and shows a generic
  arrow.
- **Link to the HU:** for now over TCP to a PC running `hu-navd --tcp 47800`
  (development, trusted Wi-Fi only). Bluetooth RFCOMM to the real HU is the next
  step. The link reconnects by itself and runs as a foreground service, so
  Android keeps it alive during a drive.
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
4. Allow notifications when asked (the foreground service shows one).

Each CI build is signed with a new debug key, so a newer APK from CI cannot
update an installed one: uninstall first (the settings are lost).

## Try it with the virtual HU

On the PC (phone and PC in the same Wi-Fi; the PC's firewall must allow TCP 47800):

```bash
cd hu-virtual
NAV_ARGS="--tcp 47800" ./hu-virtual.sh up && ./hu-virtual.sh ui
```

In the app: enter `<PC's IP>:47800`, Connect, then start a route in Google Maps.
The HU's Navigation screen follows.

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
  MapsParser.kt           Google Maps notification text -> Guidance
  IconTable.kt            arrow image fingerprints -> maneuver
  MapsListenerService.kt  notification listener; capture hook
  LinkService.kt          foreground service holding the link
  Capture.kt              capture mode and export
  MainActivity.kt, Settings.kt, AppState.kt   screen, settings, shared state
app/src/main/assets/maneuver_icons.json        known arrows (built from captures)
app/src/test/                                  JVM unit tests
```
