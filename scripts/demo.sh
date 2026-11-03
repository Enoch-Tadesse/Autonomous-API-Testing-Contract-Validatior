#!/usr/bin/env bash
# Start the web demo: target API on :9000 and the agent service + UI on :8000.
#   scripts/demo.sh            build the UI if needed, then start both servers
#   scripts/demo.sh --rebuild  force a fresh UI build first
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "No .venv found. Run: python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }

if [ "${1:-}" = "--rebuild" ] || [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null || { echo "npm is needed to build the UI (Node 18+)."; exit 1; }
  echo "Building the web UI..."
  (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build)
fi

cleanup() { kill "${TARGET_PID:-}" "${SERVICE_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" -m uvicorn target_api.main:app --port 9000 --log-level warning &
TARGET_PID=$!
"$PY" -m uvicorn app.main:app --port 8000 --log-level warning &
SERVICE_PID=$!

for _ in $(seq 50); do
  curl -s -o /dev/null http://localhost:8000/health && curl -s -o /dev/null http://localhost:9000/docs && break
  sleep 0.2
done
echo
echo "  Demo ready:   http://localhost:8000"
echo "  Target API:   http://localhost:9000/docs"
echo "  Ctrl+C to stop."
echo
wait
