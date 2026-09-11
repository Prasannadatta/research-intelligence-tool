#!/bin/bash
# First-time macOS setup: tools check, venv, deps, .env, DB, frontend install.
# Never deletes or overwrites an existing database or backend/.env.

set -e
cd "$(dirname "$0")"

echo ""
echo "=== Research Intelligence Tool — macOS setup ==="
echo ""

fail() {
  echo ""
  echo "Setup failed: $1"
  echo "Fix the error above, then run setup_mac.command again."
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
}

# --- Check required tools ---
if ! command -v git >/dev/null 2>&1; then
  fail "Git was not found.
Install Git from: https://git-scm.com/downloads
(or install Xcode Command Line Tools: xcode-select --install)
Then close and reopen Terminal, and run setup again."
fi
echo "[OK] Git found"

if ! command -v python3 >/dev/null 2>&1; then
  fail "Python 3 was not found.
Install Python 3 from: https://www.python.org/downloads/
Then close and reopen Terminal, and run setup again."
fi
echo "[OK] Python found"

if ! command -v node >/dev/null 2>&1; then
  fail "Node.js was not found.
Install Node.js LTS from: https://nodejs.org/
Then close and reopen Terminal, and run setup again."
fi
echo "[OK] Node.js found"

if ! command -v npm >/dev/null 2>&1; then
  fail "npm was not found (usually installed with Node.js).
Install Node.js LTS from: https://nodejs.org/
Then close and reopen Terminal, and run setup again."
fi
echo "[OK] npm found"
echo ""

# --- Backend virtualenv ---
if [ ! -x "backend/.venv/bin/python" ]; then
  echo "Creating backend/.venv ..."
  (cd backend && python3 -m venv .venv) || fail "Failed to create backend/.venv"
  echo "[OK] Created backend/.venv"
else
  echo "[OK] Reusing existing backend/.venv"
fi

# --- Backend Python packages ---
echo "Installing backend requirements ..."
backend/.venv/bin/python -m pip install -r backend/requirements.txt \
  || fail "Failed to install backend requirements."
echo "[OK] Backend requirements installed"
echo ""

# --- .env (create only if missing; never overwrite) ---
if [ -f "backend/.env" ]; then
  echo "[OK] backend/.env already exists — leaving it unchanged"
else
  if [ ! -f "backend/.env.example" ]; then
    fail "backend/.env.example is missing. Cannot create backend/.env"
  fi
  echo "Creating backend/.env from backend/.env.example ..."
  cp backend/.env.example backend/.env \
    || fail "Failed to create backend/.env"
  echo "[OK] Created backend/.env"
  echo "     Edit backend/.env later to add API keys if needed."
fi

# --- Database migrations (safe; does not delete existing DB) ---
echo "Running database migrations (alembic upgrade head) ..."
(cd backend && .venv/bin/python -m alembic upgrade head) \
  || fail "Database migration failed."
echo "[OK] Database is up to date"
echo ""

# --- Frontend packages ---
echo "Installing frontend npm packages ..."
(cd frontend && npm install) \
  || fail "npm install failed in frontend."
echo "[OK] Frontend dependencies installed"
echo ""

echo "Setup complete."
echo "Next: double-click start_mac.command (or run it from this folder)."
echo ""
read -r -p "Press Enter to close..."
exit 0
