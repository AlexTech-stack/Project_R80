#!/usr/bin/env bash
# CI on a tag v<major>.<minor>.<patch>: the signed update file of the HU software as a GitHub
# Release (the R80 Companion app downloads it from there and sends it to the HU, D12).
# Needs the release key in R80_UPDATE_KEY (PEM) and GH_TOKEN; GITHUB_REF_NAME is the tag.
set -euo pipefail
cd "$(dirname "$0")/.."
tag="${GITHUB_REF_NAME:?the tag}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a release tag: $tag"; exit 1; }
[[ -n "${R80_UPDATE_KEY:-}" ]] || { echo "no release key (secret R80_UPDATE_KEY)"; exit 1; }
key="$(mktemp)"; trap 'rm -f "$key"' EXIT
printf '%s\n' "$R80_UPDATE_KEY" >"$key"
# the key must be the one the HUs trust
[[ "$(openssl pkey -in "$key" -pubout)" == "$(cat hu/update-keys/release.pem)" ]] \
  || { echo "R80_UPDATE_KEY is not the key of hu/update-keys/release.pem"; exit 1; }
out=build/release; rm -rf "$out"; mkdir -p "$out"
file="$(python3 ci/make_bundle.py --out "$out" --key "$key" --version "${tag#v}")"
python3 - "$file" <<'PY'
import sys; sys.path.insert(0, "hu/services"); import update
from pathlib import Path
m = update.verify(Path(sys.argv[1]), [Path("hu/update-keys/release.pem")])
print(f"verified: {m['version']}, {len(m['files'])} files")
PY
gh release create "$tag" "$file" --title "R80 HU ${tag#v}" --verify-tag \
  --notes "The HU software ${tag#v}: the R80 Companion app installs it over the phone link, or put the file into R80-update/ on a USB stick (docs/bench-pi.md)."
