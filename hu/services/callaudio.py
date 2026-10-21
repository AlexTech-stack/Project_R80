"""Bluetooth sound on PipeWire: the thin layer between hu-phoned / hu-mediad and the audio stack.

Calls (hu-phoned) below; music from the phone (hu-mediad): music(address) finds the phone's
A2DP stream (kept at full volume, so the phone sends at full level) and the "R80 Bluetooth
music" stage (r80_bt_music_out), whose level mediad sets.

During a call PipeWire's Bluetooth hands-free backend opens two streams for the phone,
and WirePlumber links them like any other stream:

    bluez_input.<ADDR>.N   (Stream/Output/Audio)  the far end's voice -> the HU's output
    bluez_output.<ADDR>.N  (Stream/Input/Audio)   the HU's microphone -> the phone

This module finds them (pw-dump) and sets the far end's level (the phone volume from
hu-audiod, D9) and the microphone mute (wpctl, pw-cli). PipeWire passes the call stream's
volume on to the phone (AT+VGS), and the phone turns itself down on its own curve; so where
the "R80 call" stage exists (bench/pi/r80-pipewire.conf: WirePlumber routes the call into
it) the call stream stays at full volume, the phone sends at full level, and the level is
set on the stage's output instead (linear, above 1.0 for the call boost). With no microphone, WirePlumber
links the stream to the phone from the *monitor* of the HU's output (its best target when
there is no source), and the far end hears itself and the music: so the stream to the
phone is muted unless it is fed by a real microphone (an Audio/Source). Everything PipeWire-specific is
here; without PipeWire's tools it does nothing and says so (CI, the virtual HU).
Echo cancellation (car speakers + cabin microphone) is a PipeWire filter, not part of it.
"""
from __future__ import annotations

import json
import shutil
import subprocess


class CallAudio:
    def __init__(self, log=print, env: dict | None = None):
        self.log, self.env = log, env
        self.channels: dict[int, int] = {}
        self.ok = bool(shutil.which("pw-dump") and shutil.which("wpctl") and shutil.which("pw-cli"))
        if not self.ok:
            log("call audio: no pw-dump / wpctl / pw-cli here, level and microphone mute are not applied")

    def run(self, *args) -> str | None:
        try:   # pw-dump can take seconds on a busy Pi 3B during a call
            return subprocess.run(args, capture_output=True, text=True, timeout=5, env=self.env, check=True).stdout
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"call audio: {args[0]} failed: {e}")
            return None

    def streams(self, address: str) -> dict | None:
        """{"down": node id, "up": node id, "mic": bool, "stage": node id} of the phone's call
        streams that exist now (mic: the stream to the phone is fed by a real microphone;
        stage: the "R80 call" level stage); None if PipeWire could not be asked."""
        if not self.ok or not address:
            return {}
        out = self.run("pw-dump")
        if out is None:
            return None
        try:
            objects = json.loads(out)
        except ValueError:
            return None
        tag = address.replace(":", "_").upper()
        found = {}
        classes = {}
        for o in objects:
            if o.get("type") != "PipeWire:Interface:Node":
                continue
            props = (o.get("info") or {}).get("props") or {}
            name, kind = str(props.get("node.name", "")), str(props.get("media.class", ""))
            classes[o["id"]] = kind
            vols = [x.get("channelVolumes") for x in ((o.get("info") or {}).get("params") or {}).get("Props", [])
                    if isinstance(x, dict) and "channelVolumes" in x]
            self.channels[o["id"]] = len(vols[0]) if vols and vols[0] else 1
            if name == "r80_call_out":
                found["stage"] = o["id"]
            elif name.startswith(f"bluez_input.{tag}") and kind == "Stream/Output/Audio":
                found["down"] = o["id"]
            elif name.startswith(f"bluez_output.{tag}") and kind == "Stream/Input/Audio":
                found["up"] = o["id"]
        if "up" in found:
            feeds = [(o.get("info") or {}).get("output-node-id") for o in objects
                     if o.get("type") == "PipeWire:Interface:Link"
                     and (o.get("info") or {}).get("input-node-id") == found["up"]]
            found["mic"] = any(classes.get(n) == "Audio/Source" for n in feeds)
        return found

    def music(self, address: str) -> dict | None:
        """{"stream": the phone's A2DP stream, "stage": r80_bt_music_out}, as far as they
        exist; None if PipeWire could not be asked."""
        if not self.ok:
            return {}
        out = self.run("pw-dump")
        if out is None:
            return None
        try:
            objects = json.loads(out)
        except ValueError:
            return None
        tag = address.replace(":", "_").upper()
        found = {}
        for o in objects:
            if o.get("type") != "PipeWire:Interface:Node":
                continue
            props = (o.get("info") or {}).get("props") or {}
            name = str(props.get("node.name", ""))
            vols = [x.get("channelVolumes") for x in ((o.get("info") or {}).get("params") or {}).get("Props", [])
                    if isinstance(x, dict) and "channelVolumes" in x]
            self.channels[o["id"]] = len(vols[0]) if vols and vols[0] else 2
            if name == "r80_bt_music_out":
                found["stage"] = o["id"]
            elif (tag and name.startswith(f"bluez_input.{tag}") and props.get("media.class") == "Stream/Output/Audio"
                  and str(props.get("api.bluez5.profile", "")).startswith("a2dp")):
                found["stream"] = o["id"]
        return found

    def set_linear(self, node: int, value: float) -> bool:
        """Linear volume on all channels (pw-cli: no cubic scale, values above 1.0 allowed)."""
        vols = ", ".join([f"{max(0.0, min(value, 8.0)):.4f}"] * self.channels.get(node, 1))
        return self.ok and self.run("pw-cli", "set-param", str(node), "Props", f"{{ channelVolumes: [ {vols} ] }}") is not None

    def set_level(self, node: int, gain: float) -> bool:
        """gain: linear amplitude, as audiod computes it (mediad's GStreamer volume is linear too).
        wpctl takes the cubic scale of desktop volume sliders: linear = value ** 3."""
        value = max(0.0, min(gain, 1.0)) ** (1 / 3)
        return self.ok and self.run("wpctl", "set-volume", str(node), f"{value:.4f}") is not None

    def set_mute(self, node: int, muted: bool) -> bool:
        return self.ok and self.run("wpctl", "set-mute", str(node), "1" if muted else "0") is not None
