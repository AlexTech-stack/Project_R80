#!/usr/bin/env bash
# Static checks for R80: the same script runs locally and in GitHub Actions.
#
#   ci/check_static.sh            all checks
#   SKIP_UI=1 ci/check_static.sh  without the QML screenshots (no PySide6 / no GL libs)
#
# Needs: python3 with PySide6, cantools, python-can (AGENTS.md section 3).
# Output (screenshots, logs) goes to $R80_CI_OUT (default: build/ci, git-ignored).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${R80_CI_OUT:-$ROOT/build/ci}"
PY="${PYTHON:-python3}"
cd "$ROOT"
rm -rf "$OUT" && mkdir -p "$OUT"

failed=()
step() {  # name, command...
  local name=$1; shift
  echo "== $name"
  if "$@"; then echo "   ok"; else echo "   FAILED: $name"; failed+=("$name"); fi
}

py_compile_all() {
  local files; mapfile -t files < <(git ls-files '*.py')
  PYTHONPYCACHEPREFIX="$OUT/pycache" "$PY" -m py_compile "${files[@]}"
}

dbc_up_to_date() {
  "$PY" hu-can/tools/make_dbc.py "$OUT/r80_test.dbc" >/dev/null || return 1
  diff -u hu-can/r80_test.dbc "$OUT/r80_test.dbc" || {
    echo "   r80_test.dbc does not match make_dbc.py: regenerate it and commit both"; return 1; }
}

sim_log() {
  "$PY" hu-can/tools/r80_can_sim.py --log "$OUT/drive.log" || return 1
  cmp -s "$OUT/drive.log" hu-can/sample_drive_60s.log || {
    echo "   r80_can_sim.py output differs from hu-can/sample_drive_60s.log: regenerate the sample and commit it"
    return 1; }
}

screenshots() {
  local shots="$OUT/screenshots"
  "$PY" hu-mockup/run.py --screenshots "$shots" || return 1
  local n; n=$(find "$shots" -name '*.png' -size +1k | wc -l)
  echo "   $n screenshots in $shots"
  [[ $n -ge 11 ]] || { echo "   expected 11 PNGs (10 screens + overview.png)"; return 1; }
}

step "py_compile"        py_compile_all
step "repo rules"        "$PY" ci/check_rules.py
step "DBC up to date"    dbc_up_to_date
step "simulator log"     sim_log
if [[ -n "${SKIP_UI:-}" ]]; then echo "== UI screenshots: skipped (SKIP_UI)"; else
step "UI screenshots"    screenshots
fi

echo
if ((${#failed[@]})); then echo "FAILED: ${failed[*]}"; exit 1; fi
echo "all static checks passed"
