#!/usr/bin/env bash
# BoAt smoke tests of the virtual headunit (hu-virtual/), the same way locally and in CI.
#
#   ci/run_boat_sil.sh              use the BoAt you have (BOAT_ROOT, default ~/BoAt; `boat` on PATH)
#   ci/run_boat_sil.sh --dut-arm64  run the DUT (mcu_emu + vehicled) in an aarch64 Debian Trixie
#                                   container (ci/dut/) instead of on the host; BoAt stays on the host.
#                                   Needs docker and QEMU binfmt for arm64 (CI: qemu-user-static).
#   ci/run_boat_sil.sh --install    first install BoAt $BOAT_VERSION into $R80_CI_OUT/boat:
#                                   the gateway, the BoAt source at that commit (restbus.py uses its
#                                   SDK and tools/dbc2boatjson.py) and a venv with boat-py and
#                                   boat-cli built from that source
#
# BOAT_VERSION (default: ci/boat.version) is either
#   - a release tag (v0.1.1): gateway from the release tarball, or
#   - a branch or commit (master): gateway from BoAt's CI image ci-<sha> (ci/fetch_boat_gateway.py).
#     BoAt only pushes that image after its CI passed, so the newest commit on the ref that has
#     one is used.
# $R80_CI_OUT/boat/tested.txt says which commit and which gateway were used.
#
# BoAt runs on the test PC (x86_64) only. The Raspberry Pi is the DUT and never runs BoAt
# (docs/bench-pi.md), so --install refuses other machines.
# Other env: BOAT_REPO (AlexTech-stack/BoAt), R80_CI_OUT (default: build/ci-boat, git-ignored).
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
  local dir="$OUT/boat" ver="${BOAT_VERSION#v}" arch sha="" note="" from
  arch=$(uname -m)
  [[ "$arch" == x86_64 ]] || { echo "BoAt runs on the x86_64 test PC, not on $arch: the Pi is the DUT (docs/bench-pi.md)"; return 1; }
  echo "== installing BoAt $BOAT_VERSION into $dir"
  rm -rf "$dir" && mkdir -p "$dir/bin"
  git clone -q --filter=blob:none --no-checkout "https://github.com/$BOAT_REPO.git" "$dir/src"
  local head; head=$(git -C "$dir/src" rev-parse --verify -q "origin/$BOAT_VERSION^{commit}" \
                     || git -C "$dir/src" rev-parse --verify "$BOAT_VERSION^{commit}") || return 1
  if [[ "$BOAT_VERSION" =~ ^v[0-9] ]]; then
    curl -fsSL "https://github.com/$BOAT_REPO/releases/download/$BOAT_VERSION/boat-platform-$ver-Linux-x86_64.tar.gz" \
      | tar xz -C "$dir" --strip-components=1
    sha=$head from="release tarball"
  else
    # The newest commit whose CI image exists (BoAt CI pushes it after it passed).
    local c rc n=20
    for c in $(git -C "$dir/src" rev-list --first-parent -n "$n" "$head"); do
      rc=0; python3 "$ROOT/ci/fetch_boat_gateway.py" "$c" "$dir/bin/boat_gateway" || rc=$?
      if ((rc == 0)); then sha=$c; break; fi
      ((rc == 2)) || return 1
    done
    [[ -n "$sha" ]] || { echo "no BoAt CI image for the last $n commit(s) of $BOAT_VERSION"; return 1; }
    [[ "$sha" == "$head" ]] || note=" (newest commit with a CI image; $BOAT_VERSION is at ${head:0:7})"
    from="CI image"
  fi
  git -C "$dir/src" -c advice.detachedHead=false checkout -q "$sha"
  echo "BoAt $BOAT_VERSION @ ${sha:0:7}$note, gateway from $from" | tee "$dir/tested.txt"
  python3 -m venv --system-site-packages "$dir/venv"
  "$dir/venv/bin/pip" install -q "$dir/src/boat-platform/sdk/python" "$dir/src/boat-platform/cli"
  export BOAT_ROOT="$dir/src" BOAT_GATEWAY="$dir/bin/boat_gateway" PATH="$dir/venv/bin:$PATH"
}

INSTALL="" DUT_ARM64=""
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --dut-arm64) DUT_ARM64=1 ;;
    *) sed -n '2,25p' "$0"; exit 1 ;;
  esac
done

mkdir -p "$OUT"
[[ -n "$INSTALL" ]] && install_boat

echo "== BoAt: root ${BOAT_ROOT:-~/BoAt}, gateway ${BOAT_GATEWAY:-<hu-virtual.sh default>}, CLI $(command -v boat || echo missing)"
python3 -c "import boat, dbus, gi" || { echo "python3 cannot import boat, dbus and gi"; exit 1; }

# Fresh reports for this run only.
rm -rf "$RUN/reports" "$OUT/reports" "$OUT/logs"

run_local_dut() {
  # A private session bus, so vehicled never talks to (or collides with) a desktop session.
  dbus-run-session -- bash -c '
    cd "$1/hu-virtual"
    trap "./hu-virtual.sh down" EXIT
    ./hu-virtual.sh up && ./hu-virtual.sh test
  ' _ "$ROOT"
}

run_arm64_dut() {
  # BoAt on the host (the "test PC"), the DUT in an aarch64 container. They share the host
  # network (vcan), XDG_RUNTIME_DIR (UART link, MCU control socket) and a session bus whose
  # socket lives there too. The container runs as our user so D-Bus accepts it.
  local rt="${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR must be set}" image=r80-dut-arm64 name=r80-dut
  echo "== building the aarch64 DUT image"
  docker build -q --platform linux/arm64 -t "$image" "$ROOT/ci/dut" >/dev/null
  local bus_pid
  bus_pid=$(dbus-daemon --config-file="$ROOT/ci/dut/session-bus.conf" --fork --print-pid --address="unix:path=$rt/r80-bus")
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$rt/r80-bus"
  local rc=0
  arm64_dut_session "$rt" "$image" "$name" || rc=$?
  # Always: keep the DUT log, stop the container, the BoAt side and the bus.
  mkdir -p "$OUT/logs"
  docker logs "$name" >"$OUT/logs/dut-arm64.log" 2>&1 || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  (cd "$ROOT/hu-virtual" && ./hu-virtual.sh down) || true
  kill "$bus_pid" 2>/dev/null || true
  return $rc
}

arm64_dut_session() {
  local rt=$1 image=$2 name=$3
  (cd "$ROOT/hu-virtual" && HU_DUT=external ./hu-virtual.sh up) || return 1
  docker run -d --name "$name" --platform linux/arm64 --network host --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e XDG_RUNTIME_DIR="$rt" -e DBUS_SESSION_BUS_ADDRESS \
    -v "$rt:$rt" -v "$ROOT:$ROOT:ro" "$image" "$ROOT/ci/dut/start_dut.sh" "$ROOT/hu-virtual" >/dev/null
  echo "== waiting for the DUT (de.r80.Vehicle with the MCU link up)"
  python3 - <<'PY' || { docker logs "$name" | tail -20; return 1; }
import time, dbus
deadline = time.monotonic() + 120  # QEMU makes the first start slow
while time.monotonic() < deadline:
    try:
        props = dbus.SessionBus().get_object("de.r80.Vehicle", "/de/r80/Vehicle").GetAll(
            "de.r80.Vehicle1", dbus_interface="org.freedesktop.DBus.Properties")
        if props.get("LinkUp"):
            print(f"   DUT up after {120 - (deadline - time.monotonic()):.0f} s")
            raise SystemExit(0)
    except dbus.DBusException:
        pass
    time.sleep(1)
raise SystemExit("DUT did not come up within 120 s")
PY
  docker logs "$name" 2>&1 | grep '^DUT:' | sed 's/^/   /'
  (cd "$ROOT/hu-virtual" && ./hu-virtual.sh test)
}

set +e
if [[ -n "$DUT_ARM64" ]]; then run_arm64_dut; else run_local_dut; fi
rc=$?
set -e

cp -r "$RUN/reports" "$OUT/reports" 2>/dev/null || true
mkdir -p "$OUT/logs" && cp "$RUN"/*.log "$OUT/logs/" 2>/dev/null || true
echo
if ((rc)); then echo "BoAt smoke tests FAILED (exit $rc); reports and logs in $OUT"; else echo "BoAt smoke tests passed"; fi
exit $rc
