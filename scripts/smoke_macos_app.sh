#!/bin/sh
set -eu

APP_PATH="${1:?Usage: smoke_macos_app.sh APP_PATH}"
APP_EXECUTABLE="$APP_PATH/Contents/MacOS/research-memory-desktop"
CORE_EXECUTABLE="$APP_PATH/Contents/MacOS/research-memory-core"
LOG_PATH="$(mktemp "${TMPDIR:-/tmp}/research-memory-app-smoke.XXXXXX")"
APP_PID=""

test -x "$APP_EXECUTABLE"
test -x "$CORE_EXECUTABLE"

cleanup() {
  if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
    kill -TERM "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  for core_pid in $(pgrep -f "$CORE_EXECUTABLE --desktop" 2>/dev/null || true); do
    kill -TERM "$core_pid" 2>/dev/null || true
  done
  cleanup_attempt=0
  while [ "$cleanup_attempt" -lt 10 ] &&
    pgrep -f "$CORE_EXECUTABLE --desktop" >/dev/null 2>&1; do
    cleanup_attempt=$((cleanup_attempt + 1))
    sleep 1
  done
  for core_pid in $(pgrep -f "$CORE_EXECUTABLE --desktop" 2>/dev/null || true); do
    kill -KILL "$core_pid" 2>/dev/null || true
  done
  rm -f "$LOG_PATH"
}
trap cleanup EXIT INT TERM

"$APP_EXECUTABLE" >"$LOG_PATH" 2>&1 &
APP_PID=$!
attempt=0
while [ "$attempt" -lt 45 ]; do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    cat "$LOG_PATH" >&2
    echo "Packaged app exited before its private core became ready." >&2
    exit 1
  fi
  if grep -F "Uvicorn running on http://127.0.0.1:" "$LOG_PATH" >/dev/null; then
    printf 'Packaged app launched its authenticated core successfully.\n'
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

cat "$LOG_PATH" >&2
echo "Timed out waiting for the packaged app core." >&2
exit 1
