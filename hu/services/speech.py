"""Speech for the voice assistant (hu-assistd): speech to text, text to speech, and when the
driver has finished talking. No GStreamer and no D-Bus here; assistd brings the audio in and out.

Engines (measured on the bench Pi in docs/bench-measurements.md):
  recognizer  moonshine   Moonshine tiny (int8) through sherpa-onnx (Apache-2.0; the model is MIT)
              transcript  tests and the virtual HU: the text that comes with the recorded speech
  voice       piper       a Piper voice (VITS) through sherpa-onnx. Piper voices need espeak-ng to turn
                          text into phonemes; espeak-ng is GPL-3.0, so it runs as a program of its own
                          (Debian's espeak-ng) and never inside the HU's services
              silent      tests and the virtual HU: silence as long as the text would take to say

The models live in the speech folder (default $XDG_DATA_HOME/r80/speech, installed on the bench by
`./r80 bench speech`). They are loaded once (25 s on a Pi 3): loading them at the button press would
be far too slow.

Audio in and out is 16-bit signed mono PCM (bytes), at the rate given with it.
"""
from __future__ import annotations

import array
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

RATE = 16000                      # what the microphone delivers and the recognizer takes


@dataclass
class Utterance:
    pcm: bytes                    # S16LE mono
    rate: int
    transcript: str | None = None  # only from recorded test speech (the transcript recognizer)

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.rate


def read_wav(path: Path) -> Utterance:
    """Recorded speech (16-bit mono WAV) and, for the transcript recognizer, its text from
    <name>.txt next to it."""
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{path.name}: needs 16-bit mono, not {w.getsampwidth() * 8}-bit x {w.getnchannels()}")
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    txt = path.with_suffix(".txt")
    return Utterance(pcm, rate, txt.read_text().strip() if txt.is_file() else None)


def level_db(frame: bytes) -> float:
    """RMS level of S16LE samples in dB below full scale (-120 for silence)."""
    a = array.array("h")
    a.frombytes(frame[: len(frame) // 2 * 2])
    if not a:
        return -120.0
    rms = math.sqrt(sum(x * x for x in a) / len(a))
    return 20 * math.log10(rms / 32768) if rms > 0 else -120.0


class Endpointer:
    """When the driver has finished talking: speech starts with a frame above speech_level_db and
    ends after end_silence_ms below it (or after max_speech_s). Nothing above the level for
    no_speech_s: nothing was said. feed() returns "waiting", "speech", "done" or "nothing"."""

    def __init__(self, rate: int, speech_level_db: float, end_silence_ms: int, max_speech_s: float, no_speech_s: float):
        self.rate, self.level = rate, speech_level_db
        self.end_silence = end_silence_ms / 1000
        self.max_speech, self.no_speech = max_speech_s, no_speech_s
        self.pcm = bytearray()
        self.t = 0.0                  # seconds of audio fed
        self.started = None           # when speech began
        self.last_loud = None
        self.lead = 0.3               # keep this much audio from before the speech began

    def feed(self, frame: bytes) -> str:
        dur = len(frame) / 2 / self.rate
        loud = level_db(frame) >= self.level
        self.t += dur
        self.pcm += frame
        if self.started is None:
            if loud:
                self.started = self.last_loud = self.t
                keep = int((dur + self.lead) * self.rate) * 2
                del self.pcm[: max(0, len(self.pcm) - keep)]
                return "speech"
            if self.t >= self.no_speech:
                return "nothing"
            keep = int(self.lead * self.rate) * 2           # the waiting audio is not kept
            del self.pcm[: max(0, len(self.pcm) - keep)]
            return "waiting"
        if loud:
            self.last_loud = self.t
        if self.t - self.last_loud >= self.end_silence or self.t - self.started >= self.max_speech:
            return "done"
        return "speech"

    def utterance(self) -> Utterance:
        return Utterance(bytes(self.pcm), self.rate)


def phrases(text: str) -> list[str]:
    """The answer cut into phrases at punctuation, so the first can play while the next is made.
    Pieces of one or two words join the next one (they sound choppy alone)."""
    parts = [p.strip() for p in re.split(r"(?<=[,.;:!?])\s+", text.strip()) if p.strip()]
    out = []
    for p in parts:
        if out and len(out[-1].split()) <= 2:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def _to_pcm(samples) -> bytes:
    import numpy as np
    return (np.asarray(samples, dtype=np.float32) * 32767).clip(-32768, 32767).astype(np.int16).tobytes()


class TranscriptRecognizer:
    name = "transcript"

    def recognize(self, utt: Utterance) -> str:
        return utt.transcript or ""


class MoonshineRecognizer:
    name = "moonshine"

    def __init__(self, folder: Path, threads: int):
        import sherpa_onnx
        for f in ("preprocess.onnx", "encode.int8.onnx", "uncached_decode.int8.onnx", "cached_decode.int8.onnx", "tokens.txt"):
            if not (folder / f).is_file():
                raise FileNotFoundError(f"speech model incomplete: {folder / f} is missing")
        self.r = sherpa_onnx.OfflineRecognizer.from_moonshine(
            preprocessor=str(folder / "preprocess.onnx"), encoder=str(folder / "encode.int8.onnx"),
            uncached_decoder=str(folder / "uncached_decode.int8.onnx"),
            cached_decoder=str(folder / "cached_decode.int8.onnx"), tokens=str(folder / "tokens.txt"),
            num_threads=threads)

    def recognize(self, utt: Utterance) -> str:
        import numpy as np
        st = self.r.create_stream()
        st.accept_waveform(utt.rate, np.frombuffer(utt.pcm, np.int16).astype(np.float32) / 32768)
        self.r.decode_stream(st)
        return st.result.text.strip()


class SilentVoice:
    name = "silent"
    rate = RATE

    def say(self, text: str, speed: float = 1.0) -> bytes:
        seconds = max(0.3, 0.06 * len(text)) / speed
        return bytes(int(seconds * self.rate) * 2)


class PiperVoice:
    """A Piper voice through sherpa-onnx; the phonemes come from espeak-ng run as its own program."""
    name = "piper"
    ENDS = ",.;:!?"

    def __init__(self, folder: Path, threads: int, espeak: str = "espeak-ng", espeak_voice: str = "en-us"):
        import sherpa_onnx
        models = sorted(folder.glob("*.onnx"))
        if not models or not (folder / "tokens.txt").is_file():
            raise FileNotFoundError(f"speech voice incomplete: no .onnx or tokens.txt in {folder}")
        self.espeak, self.espeak_voice = espeak, espeak_voice
        self.phonemes("test")                                 # espeak-ng there? fail now, not at the first answer
        self.tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(models[0]), tokens=str(folder / "tokens.txt")),
            num_threads=threads)))
        self.rate = self.tts.sample_rate

    def phonemes(self, text: str) -> str:
        try:
            r = subprocess.run([self.espeak, "-q", "-v", self.espeak_voice, "--ipa"], input=text,
                               capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            raise FileNotFoundError(f"{self.espeak} not found (Debian: apt install espeak-ng)") from None
        if r.returncode != 0:
            raise RuntimeError(f"{self.espeak} failed: {r.stderr.strip()}")
        p = " ".join(r.stdout.split())
        end = text.strip()[-1:]
        return p + end if end and end in self.ENDS else p    # the voice knows punctuation: intonation

    def say(self, text: str, speed: float = 1.0) -> bytes:
        import sherpa_onnx
        c = sherpa_onnx.GenerationConfig()
        c.speed = speed
        c.phoneme_codepoints = [[ord(ch) for ch in self.phonemes(text)]]
        return _to_pcm(self.tts.generate(text, c).samples)


def load(recognizer: str, voice: str, model_dir: Path, recognizer_model: str, voice_model: str, threads: int):
    """The engines named in assistant.ini (or on assistd's command line). Raises on a missing
    model, package or program, with a message for the driver's diagnostics."""
    if recognizer == "transcript":
        rec = TranscriptRecognizer()
    elif recognizer == "moonshine":
        rec = MoonshineRecognizer(model_dir / recognizer_model, threads)
    else:
        raise ValueError(f"unknown recognizer {recognizer!r}")
    if voice == "silent":
        out = SilentVoice()
    elif voice == "piper":
        out = PiperVoice(model_dir / voice_model, threads)
    else:
        raise ValueError(f"unknown voice {voice!r}")
    return rec, out
