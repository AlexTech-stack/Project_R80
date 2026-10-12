#!/usr/bin/env bash
# BoAt smoke tests of the virtual headunit (hu-virtual/), the same way locally and in CI.
#
#   ci/run_boat_sil.sh              use the BoAt you have (BOAT_ROOT, default ~/BoAt; `boat` on PATH)
#   ci/run_boat_sil.sh --install    first install the BoAt release pinned in ci/boat.version into
#                                   $R80_CI_OUT/boat: gateway from the release tarball, the BoAt source
#                                   at that tag (restbus.py uses its SDK and tools/dbc2boatjson.py)
#                                   and a venv with boat-py and boat-cli built from that source
#
# Env: BOAT_VERSION (default: ci/boat.version), BOAT_REPO (AlexTech-stack/BoAt),
#      R80_CI_OUT (default: build/ci-boat, git-ignored).
# Needs: Linux with the vcan module, sudo (hu-virtual.sh creates the buses), dbus-run-session,
#        python3 >= 3.11 with the dbus and gi modules (Debian/Ubuntu: python3-dbus python3-gi).
#
# The verdict is the exit code of `boat test run`. BoAt's report.junit.xml is not used:
# it is empty for script tests (AlexTech-stack/BoAt#50).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${R80_CI_OUT:-$ROOT/build/ci-boat}"
BOAT_VERSION="${BOAT_VERSION:-$(tr -d '[:space:]' < "$ROOT/ci/boat.version")}"
BOAT_REPO="${BOAT_REPO:-AlexTech-stack/BoAt}"
RUN="${XDG_RUNTIME_DIR:-/tmp}/r80-hu"   # hu-virtual.sh keeps its pids, logs and reports here

install_boat() {
  local dir="$OUT/boat" ver="${BOAT_VERSION#v}"
  echo "== installing BoAt $BOAT_VERSION into $dir"
  rm -rf "$dir" && mkdir -p "$dir"
  curl -fsSL "https://github.com/$BOAT_REPO/releases/download/$BOAT_VERSION/boat-platform-$ver-Linux-x86_64.tar.gz" \
    | tar xz -C "$dir" --strip-components=1
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$BOAT_VERSION" "https://github.com/$BOAT_REPO.git" "$dir/src"
  python3 -m venv --system-site-packages "$dir/venv"
  "$dir/venv/bin/pip" install -q "$dir/src/boat-platform/sdk/python" "$dir/src/boat-platform/cli"
  export BOAT_ROOT="$dir/src" BOAT_GATEWAY="$dir/bin/boat_gateway" PATH="$dir/venv/bin:$PATH"
}

mkdir -p "$OUT"
[[ "${1:-}" == "--install" ]] && install_boat

echo "== BoAt: root ${BOAT_ROOT:-~/BoAt}, gateway ${BOAT_GATEWAY:-<hu-virtual.sh default>}, CLI $(command -v boat || echo missing)"
python3 -c "import boat, dbus, gi" || { echo "python3 cannot import boat, dbus and gi"; exit 1; }

# Fresh reports for this run only.
rm -rf "$RUN/reports" "$OUT/reports" "$OUT/logs"

# A private session bus, so vehicled never talks to (or collides with) a desktop session.
set +e
dbus-run-session -- bash -c '
  cd "$1/hu-virtual"
  trap "./hu-virtual.sh down" EXIT
  ./hu-virtual.sh up && ./hu-virtual.sh test
' _ "$ROOT"
rc=$?
set -e

cp -r "$RUN/reports" "$OUT/reports" 2>/dev/null || true
mkdir -p "$OUT/logs" && cp "$RUN"/*.log "$OUT/logs/" 2>/dev/null || true
echo
if ((rc)); then echo "BoAt smoke tests FAILED (exit $rc); reports and logs in $OUT"; else echo "BoAt smoke tests passed"; fi
exit $rc
