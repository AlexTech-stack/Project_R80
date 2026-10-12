#!/usr/bin/env bash
# BoAt smoke tests of the virtual headunit (hu-virtual/), the same way locally and in CI.
#
#   ci/run_boat_sil.sh              use the BoAt you have (BOAT_ROOT, default ~/BoAt; `boat` on PATH)
#   ci/run_boat_sil.sh --install    first install BoAt $BOAT_VERSION into $R80_CI_OUT/boat:
#                                   the gateway, the BoAt source at that commit (restbus.py uses its
#                                   SDK and tools/dbc2boatjson.py) and a venv with boat-py and
#                                   boat-cli built from that source
#
# BOAT_VERSION (default: ci/boat.version) is either
#   - a release tag (v0.1.1): gateway from the release tarball on x86_64; on other machines
#     (aarch64) from BoAt's multi-arch CI image of the tag's commit, or
#   - a branch or commit (master): gateway from BoAt's CI image ci-<sha> (ci/fetch_boat_gateway.py).
#     BoAt only pushes that image after its CI passed, so the newest commit on the ref that has
#     one is used.
# $R80_CI_OUT/boat/tested.txt says which commit and which gateway were used.
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
  echo "== installing BoAt $BOAT_VERSION ($arch) into $dir"
  rm -rf "$dir" && mkdir -p "$dir/bin"
  git clone -q --filter=blob:none --no-checkout "https://github.com/$BOAT_REPO.git" "$dir/src"
  local head; head=$(git -C "$dir/src" rev-parse --verify -q "origin/$BOAT_VERSION^{commit}" \
                     || git -C "$dir/src" rev-parse --verify "$BOAT_VERSION^{commit}") || return 1
  if [[ "$BOAT_VERSION" =~ ^v[0-9] && "$arch" == x86_64 ]]; then
    # Releases ship an x86_64 tarball only.
    curl -fsSL "https://github.com/$BOAT_REPO/releases/download/$BOAT_VERSION/boat-platform-$ver-Linux-x86_64.tar.gz" \
      | tar xz -C "$dir" --strip-components=1
    sha=$head from="release tarball"
  else
    # BoAt's CI images are multi-arch. A release must use its own commit; a branch may
    # fall back to the newest commit whose image exists (BoAt CI pushes it after it passed).
    local c rc n=20
    [[ "$BOAT_VERSION" =~ ^v[0-9] ]] && n=1
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
  echo "BoAt $BOAT_VERSION @ ${sha:0:7}$note, $arch gateway from $from" | tee "$dir/tested.txt"
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
