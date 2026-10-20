#!/usr/bin/env bash
# Boots 8ball: starts the API + viewer and opens it in your browser.
# Usage (Git Bash):  ./run.sh          (change the port with  PORT=8800 ./run.sh)
# Stop it with Ctrl+C in this window.
set -u
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}"
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Can't find the project's Python (.venv). Set it up first (see README.md)." >&2
  exit 1
fi

# Already running? Just open it.
if curl -s -o /dev/null "${URL}/api/health"; then
  echo "8ball is already running at ${URL}"
  cmd.exe //c start "" "${URL}" 2>/dev/null || xdg-open "${URL}" 2>/dev/null || open "${URL}" 2>/dev/null
  exit 0
fi

echo "Starting 8ball on ${URL} ..."
# Open the browser as soon as the server answers (in the background).
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "${URL}/api/health"; then
      cmd.exe //c start "" "${URL}" 2>/dev/null || xdg-open "${URL}" 2>/dev/null || open "${URL}" 2>/dev/null
      exit 0
    fi
    sleep 1
  done
) &

exec "$PY" -m eightball serve --port "${PORT}"
