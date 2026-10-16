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
| `caps` | list of strings | optional | what the sender offers; phone v1: `["guidance"]` |
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

Ideas the format leaves room for: lane hints, the phone's position and other
sensors, and extending the HU's UI from the phone. They become new message types
or fields, announced through `caps`.
