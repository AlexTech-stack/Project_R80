#!/usr/bin/env bash
# The headunit's DLT daemon: COVESA dlt-daemon with hu/services/dlt.conf.
#
#   dlt-daemon.sh STATE_DIR RUN_DIR [PORT]
#
# STATE_DIR keeps the log files (STATE_DIR/trace, a 16 MB ring) and stored log levels;
# RUN_DIR holds the daemon's pipes: the services need DLT_PIPE_DIR=RUN_DIR (and
# DLT_DAEMON_TCP_PORT=PORT if not 3490), see hu/services/dlt.py.
set -euo pipefail

STATE=${1:?state dir}
RUN=${2:?run dir}
PORT=${3:-3490}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v dlt-daemon >/dev/null || { echo "dlt-daemon not installed (apt install dlt-daemon)" >&2; exit 1; }
umask 077
mkdir -p "$STATE/trace" "$RUN"
# the daemon writes the files only in logging mode "both" (internal and external); it keeps the mode here
CFG="$STATE/dlt-runtime.cfg"
{ grep -v '^LoggingMode' "$CFG" 2>/dev/null || true; echo "LoggingMode = 3"; } >"$CFG.new" && mv "$CFG.new" "$CFG"
sed -e "s|@STATE@|$STATE|" -e "s|@TRACE@|$STATE/trace|" -e "s|@RUN@|$RUN|" "$HERE/dlt.conf" >"$RUN/dlt.conf"
exec dlt-daemon -c "$RUN/dlt.conf" -t "$RUN" -p "$PORT"
