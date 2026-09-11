#!/bin/bash
# Start backend + frontend on macOS. Opens the app in your browser.
# Skips launching a second copy if ports 8000 / 5173 are already in use.

set -e
cd "$(dirname "$0")"

echo ""
echo "=== Research Intelligence Tool — macOS start ==="
echo ""

fail() {
  echo ""
  echo "Start failed: $1"
  echo "Fix the error above, then try again."
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
}

VENV_PY="backend/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  fail "backend/.venv not found.
Run setup_mac.command once before starting the app."
fi

if [ ! -f "backend/.env" ]; then
  fail "backend/.env is missing.
Run setup_mac.command once before starting the app."
fi

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

BACKEND_UP=0
FRONTEND_UP=0
port_in_use 8000 && BACKEND_UP=1
port_in_use 5173 && FRONTEND_UP=1

if [ "$BACKEND_UP" -eq 1 ] && [ "$FRONTEND_UP" -eq 1 ]; then
  echo "App appears to be already running."
  echo "Opening http://localhost:5173/ in your browser ..."
  open "http://localhost:5173/"
  echo ""
  read -r -p "Press Enter to close..."
  exit 0
fi

if [ "$BACKEND_UP" -eq 1 ]; then
  echo "WARNING: Port 8000 is already in use. Not starting another backend."
fi
if [ "$FRONTEND_UP" -eq 1 ]; then
  echo "WARNING: Port 5173 is already in use. Not starting another frontend."
fi

# --- Safe migrations before start ---
echo "Applying database migrations (safe / idempotent) ..."
(cd backend && .venv/bin/python -m alembic upgrade head) \
  || fail "Database migration failed."
echo "[OK] Database is up to date"
echo ""

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Stopping servers..."
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if [ "$BACKEND_UP" -eq 0 ]; then
  echo "Starting backend on http://127.0.0.1:8000 ..."
  (cd backend && .venv/bin/python -m uvicorn app.main:app --reload) &
  BACKEND_PID=$!
else
  echo "Backend already running — skipping."
fi

if [ "$FRONTEND_UP" -eq 0 ]; then
  echo "Starting frontend on http://localhost:5173 ..."
  (cd frontend && npm run dev) &
  FRONTEND_PID=$!
else
  echo "Frontend already running — skipping."
fi

echo "Waiting a few seconds for the app to come up ..."
sleep 4

echo "Opening http://localhost:5173/ in your browser ..."
open "http://localhost:5173/"
echo ""
echo "App is running. Press Ctrl+C in this window to stop."
echo ""

# Keep Terminal open while servers run.
if [ -n "$BACKEND_PID" ] && [ -n "$FRONTEND_PID" ]; then
  wait "$BACKEND_PID" "$FRONTEND_PID"
elif [ -n "$BACKEND_PID" ]; then
  wait "$BACKEND_PID"
elif [ -n "$FRONTEND_PID" ]; then
  wait "$FRONTEND_PID"
else
  read -r -p "Press Enter to close..."
fi
