# Companion link protocol, v1

How the R80 Companion app on the driver's Android phone talks to the headunit
(decision D11). The phone's navigation app does the routing; the companion app
sends its turn-by-turn guidance to the HU, which shows it in its own style.

The Python side is `hu/services/companion_link.py`. Keep it and this document in
step; the Android app (`companion-android/`, later) implements the same rules.

## Transport

- **Target:** Bluetooth Classic RFCOMM. The HU is the server and registers the
  service UUID `b4184390-fb7f-44db-9eaa-6985447914af` on RFCOMM channel 22; the phone
  (already paired for calls and music) looks the UUID up and connects to it.
- **Virtual environment and CI:** a local stream socket to the phone emulator.
- Both sides only see a byte stream, so framing and session rules are the same.

## Framing

- One JSON object per line, UTF-8, ending in `\n`. A `\r` before it is ignored.
- A line is at most 4096 bytes. A longer line is dropped up to its `\n`.
- Every object has a `"type"` (string).
- Numbers are plain JSON numbers. `NaN` and `Infinity` are not valid. `true`/`false` are not numbers.
- Strings longer than 200 characters are cut by the receiver.
- A line that is not valid is dropped. The receiver counts and logs it but keeps the link.
- **Forward compatibility:** a receiver ignores unknown types and unknown fields.
  A newer peer may therefore add both without changing the version. Changing or
  removing a field, or changing its meaning, needs a new `proto` version.

## Session

1. The phone connects and sends `hello` first.
2. The HU answers with its own `hello`, which carries `heartbeat_s`.
   - If the phone's `proto` differs from the HU's, the HU sends `bye` with a reason and closes.
   - The HU ignores anything other than `hello` that arrives before the phone's `hello`.
3. **Keepalive:** each side sends `heartbeat` whenever it has sent nothing for `heartbeat_s` seconds.
   - The link counts as lost when nothing has arrived for longer. The HU's timeout is in its config (`nav.ini`); the phone uses 3 × `heartbeat_s`.
4. Either side may send `bye` and close. A lost link is the same as `bye`, without a reason.
5. After a reconnect, the phone sends the current guidance again.

## Messages

### `hello` (both directions)

| Field | Type | | Meaning |
|---|---|---|---|
| `proto` | integer | required | protocol version, `1` |
| `app` | string | required | `r80-companion` or `r80-hu` |
| `version` | string | required | software version of the sender |
| `device` | string | optional | phone model, for logs |
| `caps` | list of strings | optional | what the sender takes part in. The phone: `guidance`, `weather`, `position` (it sends them), `car_status` (it wants them), `remote` (it wants `media` and `browse_result`, sends `media_cmd` and `browse`). The HU: `weather`, `position` (it wants them), `car_status` (it sends them), `remote` (the other side of it). Each side sends an optional message type only to a peer that lists it |
| `heartbeat_s` | number | HU only | heartbeat interval the phone has to keep |

### `heartbeat` (both directions)

No fields.

### `guidance` (phone → HU)

Every message is the **whole current state**, not a change. The phone sends one
whenever something shown would change, and once right after `hello`.

| Field | Type | | Meaning |
|---|---|---|---|
| `active` | boolean | required | `false`: no guidance (ended or cancelled); all other fields are left out |
| `source` | string | required if active | navigation app: `google_maps`, `osmand` |
| `maneuver` | object | required if active | the next maneuver, see below |
| `distance_m` | number ≥ 0 | optional | distance to that maneuver, metres, as the navigation app shows it |
| `street` | string | optional | street to turn into or follow |
| `text` | string | optional | the navigation app's own instruction text; shown when `maneuver.type` is `unknown` |
| `remaining_m` | number ≥ 0 | optional | distance to the destination, metres |
| `remaining_s` | number ≥ 0 | optional | time to the destination, seconds. The HU computes the arrival time with its own clock |

`maneuver`:

| Field | Values |
|---|---|
| `type` (required) | `depart`, `turn`, `continue`, `merge`, `fork`, `on_ramp`, `off_ramp`, `roundabout`, `uturn`, `arrive`, `unknown` |
| `modifier` (optional) | `straight`, `slight_left`, `left`, `sharp_left`, `slight_right`, `right`, `sharp_right`; for `roundabout` the direction of the exit, for `arrive` the side of the destination |
| `exit` (optional) | roundabout exit, integer 1–99 (Google Maps only shows the direction: `modifier`) |

"Keep left/right" is `fork` with `slight_left` / `slight_right`.

How the app derives these values from Google Maps' navigation notification or from
OsmAnd's interface is the app's business (step 4). The HU only sees this format.

### `weather` (phone → HU)

The weather where the phone is, from an internet weather service (the HU has no
internet). Every message is the whole current state; the phone sends one after `hello`
and whenever it fetched new data (about every 30 minutes). The HU shows it while it is
not older than a few hours, also after the link is gone.

| Field | Type | | Meaning |
|---|---|---|---|
| `source` | string | required | the weather service, e.g. `open-meteo` |
| `time` | integer | required | when the service made this data, unix seconds |
| `now` | object | required | `temp_c` (number, °C), `code` (integer, WMO weather code 0–99) |
| `days` | list of objects | optional | today first, at most 7: `date` (`YYYY-MM-DD`, the phone's local date), `code` (WMO 0–99), `max_c`, `min_c` (numbers, °C) |

WMO weather codes (the meaning the HU uses for its icons): 0 clear; 1–2 partly cloudy;
3 overcast; 45, 48 fog; 51–57 drizzle; 61–67, 80–82 rain; 71–77, 85–86 snow; 95–99
thunderstorm.

### `position` (phone → HU)

What the HU shows from the phone's position: the altitude. The phone never sends its
coordinates (the HU does not need them). Sent after `hello` and about once a minute
while the phone has a position.

| Field | Type | | Meaning |
|---|---|---|---|
| `time` | integer | required | when the phone measured it, unix seconds |
| `alt_m` | number | optional | altitude above sea level, metres (−500 to 9000) |
| `accuracy_m` | number ≥ 0 | optional | how far off the altitude may be, metres |
| `heading_deg` | number | optional | direction of travel, 0–360° (0 = north), when moving |

### `car_status` (HU → phone)

How the car is, for the app to show while the driver is away from it. Every message is
the whole current state: one right after `hello`, then about once a minute, and a last
one with `final: true` when the ignition goes off. Values the HU does not know (a stale
or missing CAN signal) are left out.

| Field | Type | | Meaning |
|---|---|---|---|
| `time` | integer | required | when the HU sent it, unix seconds |
| `final` | boolean | required | `true`: the ignition went off, this is how the car was parked |
| `fuel_pct` | number 0–100 | optional | fuel level, % of the tank |
| `range_km` | number ≥ 0 | optional | remaining range |
| `odometer_km` | number ≥ 0 | optional | total distance |
| `battery_v` | number ≥ 0 | optional | battery voltage |
| `outside_c` | number | optional | outside temperature, °C |
| `service_km`, `service_days` | number | optional | until the next service; negative = overdue |
| `trip` | object | optional | the trip since the last start: `km`, `minutes`, `avg_kmh` (numbers ≥ 0) |
| `warnings` | list of objects | optional | the active warnings, most severe first, at most 10: `severity` (`warning`, `information`, `notice`), `text` |
| `accent` | string | optional | the HU's accent colour setting (`signal_red`, `amber`, `arctic_white`, `ice_blue`), so the app looks the same |

### `media` (HU → phone)

The remote (a passenger with the driver's phone): what plays and the volume. Every message
is the whole current state: one after `hello`, then whenever something shown changes (at
most about twice a second). The position is sent with the time it was measured; while
`playing`, the phone counts on by itself. Sent again when the position jumps (a seek).

| Field | Type | | Meaning |
|---|---|---|---|
| `allowed` | boolean | required | the HU takes commands from the phone (its setting "Allow the phone to control the HU"); `false`: show only |
| `status` | string | required | `playing`, `paused`, `stopped` |
| `source`, `sources` | string, list of strings | optional | the current source and all there are (`Library`, sticks, `Bluetooth`) |
| `title`, `artist`, `album` | string | optional | the current track |
| `duration_s`, `position_s` | number ≥ 0 | optional | the track's length and position, seconds |
| `time` | number | optional | when `position_s` was measured, unix seconds (with fractions) |
| `shuffle`, `repeat` | boolean | optional | |
| `track`, `tracks` | integer | optional | the position in the queue (0 = first) and its length |
| `queue` | string | optional | the queue's name (an album, "All tracks", …) |
| `up_next` | list of objects | optional | the next tracks in play order, at most 5: `title`, `artist` |
| `volume`, `volume_max` | integer | optional | the HU's master volume |
| `muted` | boolean | optional | |

### `media_cmd` (phone → HU)

A command of the remote. The HU ignores it while `allowed` is `false`; the next `media`
shows what happened.

| `cmd` | Further fields |
|---|---|
| `play`, `pause`, `next`, `previous` | — |
| `seek` | `value`: position, seconds |
| `shuffle`, `repeat`, `mute` | `value`: true / false |
| `volume` | `value`: master volume, integer 0 … `volume_max` |
| `source` | `value`: one of `sources` |
| `play_from` | `path` (a list of the browse tree), `index` (its track to start with): that list becomes the queue |

### `browse` (phone → HU) and `browse_result` (HU → phone)

The HU's media library as the HU's own Browse screen shows it, one page at a time. The phone
asks with an `id` of its choice; the answer carries the same `id`.

`browse`: `id` (integer, required), `path` (string, `""` = the top: folders, artists,
albums, all tracks), `offset` (integer, default 0), `count` (integer 1–20, default 20).

`browse_result`: `id`, `path`, `title` (of the list), `total` (entries in the whole list;
-1: there is no such list), `offset`, `entries`: list of `kind` (`menu`, `folder`,
`artist`, `album`, `track`), `id` (the path to browse into; `""` for a track), `title`,
`subtitle` (both at most 60 characters), `index` (a track's position in the list, for
`play_from`; -1 otherwise). A page may have fewer entries than asked for, so that it fits
into a line; the phone asks for the next one from `offset` + their number.

### `bye` (both directions)

| Field | Type | | Meaning |
|---|---|---|---|
| `reason` | string | optional | why, for logs (`user`, `protocol 1 expected`, …) |

## Example

```
phone → {"type":"hello","proto":1,"app":"r80-companion","version":"0.1.0","device":"Redmi Note 12 Pro 5G","caps":["guidance"]}
HU    → {"type":"hello","proto":1,"app":"r80-hu","version":"0.1","caps":[],"heartbeat_s":2.0}
phone → {"type":"guidance","active":true,"source":"google_maps","maneuver":{"type":"turn","modifier":"right"},"distance_m":350,"street":"Hauptstraße","remaining_m":8300,"remaining_s":720}
phone → {"type":"heartbeat"}
phone → {"type":"guidance","active":true,"source":"google_maps","maneuver":{"type":"roundabout","exit":2},"distance_m":120,"street":"B27","remaining_m":7900,"remaining_s":680}
phone → {"type":"guidance","active":false}
```

## Not in v1

Ideas the format leaves room for: lane hints, other sensors of the phone, and
extending the HU's UI from the phone. They become new message types
or fields, announced through `caps`.
