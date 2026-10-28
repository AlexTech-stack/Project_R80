#!/usr/bin/env bash
# The voice assistant's speech on the bench (hu-assistd, hu/services/speech.py; measured in
# docs/bench-measurements.md): sherpa-onnx in the HU's venv, Debian's espeak-ng (the Piper voice's
# phonemes, run as a program of its own: GPL-3.0), and the two models in $XDG_DATA_HOME/r80/speech:
#   Moonshine tiny English, int8 (MIT)            speech to text
#   Piper voice en_US kathleen low (CC0)          text to speech
# About 200 MB of models and 250 MB of Python packages. Run again: only what is missing is fetched.
#   ./r80 bench speech
set -euo pipefail
VENV="${R80_VENV:-$HOME/r80-venv}"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/r80/speech"
BASE="https://github.com/k2-fsa/sherpa-onnx/releases/download"
MODELS=("asr-models/sherpa-onnx-moonshine-tiny-en-int8" "tts-models/vits-piper-en_US-kathleen-low")

command -v espeak-ng >/dev/null || sudo apt-get install -y espeak-ng
"$VENV/bin/python" -c "import sherpa_onnx" 2>/dev/null || "$VENV/bin/pip" install "sherpa-onnx>=2.0,<3" numpy
mkdir -p "$DIR" "$DIR.part"
for m in "${MODELS[@]}"; do
  name="${m#*/}"
  if [[ -d "$DIR/$name" ]]; then echo "have $name"; continue; fi
  echo "fetching $name"
  curl -fsSL "$BASE/$m.tar.bz2" | tar xj -C "$DIR.part"
  mv "$DIR.part/$name" "$DIR/$name"
done
rm -rf "$DIR.part"
du -sh "$DIR"/*
echo "done: restart the HU (./r80 bench restart) to load them"
