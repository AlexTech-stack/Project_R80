"""The sound of a call, on PipeWire: the thin layer between hu-phoned and the audio stack.

During a call PipeWire's Bluetooth hands-free backend opens two streams for the phone,
and WirePlumber links them like any other stream:

    bluez_input.<ADDR>.N   (Stream/Output/Audio)  the far end's voice -> the HU's output
    bluez_output.<ADDR>.N  (Stream/Input/Audio)   the HU's microphone -> the phone

This module finds them (pw-dump) and sets the far end's level (the phone volume from
hu-audiod, D9) and the microphone mute on them (wpctl). Everything PipeWire-specific is
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
        self.ok = bool(shutil.which("pw-dump") and shutil.which("wpctl"))
        if not self.ok:
            log("call audio: no pw-dump / wpctl here, level and microphone mute are not applied")

    def run(self, *args) -> str | None:
        try:   # pw-dump can take seconds on a busy Pi 3B during a call
            return subprocess.run(args, capture_output=True, text=True, timeout=5, env=self.env, check=True).stdout
        except (OSError, subprocess.SubprocessError) as e:
            self.log(f"call audio: {args[0]} failed: {e}")
            return None

    def streams(self, address: str) -> dict | None:
        """{"down": node id, "up": node id} of the phone's call streams that exist now;
        None if PipeWire could not be asked (keep what was known)."""
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
        for o in objects:
            if o.get("type") != "PipeWire:Interface:Node":
                continue
            props = o.get("info", {}).get("props", {})
            name, kind = str(props.get("node.name", "")), str(props.get("media.class", ""))
            if name.startswith(f"bluez_input.{tag}") and kind == "Stream/Output/Audio":
                found["down"] = o["id"]
            elif name.startswith(f"bluez_output.{tag}") and kind == "Stream/Input/Audio":
                found["up"] = o["id"]
        return found

    def set_level(self, node: int, gain: float) -> bool:
        """gain: linear amplitude, as audiod computes it (mediad's GStreamer volume is linear too).
        wpctl takes the cubic scale of desktop volume sliders: linear = value ** 3."""
        value = max(0.0, min(gain, 1.0)) ** (1 / 3)
        return self.ok and self.run("wpctl", "set-volume", str(node), f"{value:.4f}") is not None

    def set_mute(self, node: int, muted: bool) -> bool:
        return self.ok and self.run("wpctl", "set-mute", str(node), "1" if muted else "0") is not None
