#!/usr/bin/env bash
#
# One bounded load run: build a fresh plan, start one server on a loopback port,
# drive it, stop it, and leave nothing behind.
#
#   tests/load/run.sh <scenario> <seconds> <writers> <readers> <rtt_ms> [port] [gap_s]
#
# The plan is built into a temporary directory and deleted on the way out, so
# nothing here can reach seed/ or anybody's plan. The server is killed by a trap
# on EXIT, INT and TERM — a load harness that leaves a uvicorn holding a flock
# is the one thing worse than no measurement.
set -euo pipefail

SCENARIO="${1:-spread}"
SECONDS_="${2:-60}"
WRITERS="${3:-20}"
READERS="${4:-10}"
RTT="${5:-0}"
PORT="${6:-8931}"
GAP="${7:-2.0}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"

WORK="$(mktemp -d -t openproj-load)"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM PIPE HUP

"$PY" "$HERE/corpus.py" "$WORK/plan.git" 40 10 60 60 >/dev/null
git clone --bare --quiet "$WORK/plan.git" "$WORK/remote.git"
git --git-dir="$WORK/plan.git" remote add origin "file://$WORK/remote.git" 2>/dev/null || true

"$PY" "$HERE/server.py" "$WORK/plan.git" "$WORK/remote.git" "$PORT" "$RTT" \
  >"$WORK/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" >/dev/null || {
  echo "server never came up; log:" >&2
  cat "$WORK/server.log" >&2
  exit 1
}

if [[ "$SCENARIO" == "herd" ]]; then
  "$PY" "$HERE/herd.py" 127.0.0.1 "$PORT" "$WRITERS"
elif [[ "$SCENARIO" == "rooms" ]]; then
  # The co-editing path, which commits on the event loop rather than on a thread.
  "$PY" "$HERE/rooms.py" 127.0.0.1 "$PORT" "$WRITERS" "$SECONDS_" "$GAP"
else
  "$PY" "$HERE/drive.py" "http://127.0.0.1:$PORT" "$SCENARIO" "$SECONDS_" "$WRITERS" "$READERS" "$GAP"
fi

echo "--- server log tail ---" >&2
tail -5 "$WORK/server.log" >&2 || true

# What actually landed on the remote, which is the only question that matters
# for durability: a commit that is only in plan.git is a commit Cloud Run loses.
LOCAL="$(git --git-dir="$WORK/plan.git" rev-list --count refs/heads/main)"
REMOTE="$(git --git-dir="$WORK/remote.git" rev-list --count refs/heads/main)"
echo "commits: local=$LOCAL remote=$REMOTE unpushed=$((LOCAL - REMOTE))" >&2
