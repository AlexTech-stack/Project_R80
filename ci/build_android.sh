#!/usr/bin/env bash
# Builds and unit-tests the R80 Companion app (companion-android/, decision D11).
#   ci/build_android.sh
# Needs JDK 21, the Android SDK (ANDROID_HOME) and Gradle 9.8 on PATH; in CI they come
# from actions/setup-java and gradle/actions/setup-gradle (the runner has the SDK).
# Output: build/ci/android/r80-companion-debug.apk and the unit test reports.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${R80_CI_OUT:-$ROOT/build/ci}/android"
command -v gradle >/dev/null || { echo "gradle not found (needs Gradle 9.8, JDK 21 and the Android SDK)"; exit 2; }
[[ -n "${ANDROID_HOME:-}" ]] || { echo "ANDROID_HOME is not set (Android SDK)"; exit 2; }

rm -rf "$OUT"; mkdir -p "$OUT"
status=0
gradle --no-daemon -p "$ROOT/companion-android" testDebugUnitTest assembleDebug || status=$?
cp -r "$ROOT/companion-android/app/build/reports/tests" "$OUT/test-reports" 2>/dev/null || true
cp "$ROOT/companion-android/app/build/outputs/apk/debug/app-debug.apk" "$OUT/r80-companion-debug.apk" 2>/dev/null || true
if [[ $status -ne 0 ]]; then echo "Android build or unit tests FAILED (exit $status); reports in $OUT"; exit $status; fi
echo "Android build and unit tests passed: $OUT/r80-companion-debug.apk"
