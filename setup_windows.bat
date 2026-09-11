@echo off
setlocal EnableExtensions

REM First-time Windows setup: tools check, venv, deps, .env, DB, frontend install.
REM Never deletes or overwrites an existing database or backend\.env.

cd /d "%~dp0"
echo.
echo === Research Intelligence Tool — Windows setup ===
echo.

REM --- Check required tools ---
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git was not found.
  echo Install Git from: https://git-scm.com/downloads
  echo Then close and reopen this window, and run setup again.
  goto :fail
)
echo [OK] Git found

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python was not found.
  echo Install Python 3 from: https://www.python.org/downloads/
  echo During install, check "Add Python to PATH".
  echo Then close and reopen this window, and run setup again.
  goto :fail
)
echo [OK] Python found

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js was not found.
  echo Install Node.js LTS from: https://nodejs.org/
  echo Then close and reopen this window, and run setup again.
  goto :fail
)
echo [OK] Node.js found

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm was not found ^(usually installed with Node.js^).
  echo Install Node.js LTS from: https://nodejs.org/
  echo Then close and reopen this window, and run setup again.
  goto :fail
)
echo [OK] npm found
echo.

REM --- Backend virtualenv ---
if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend\.venv ...
  pushd backend
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create backend\.venv
    popd
    goto :fail
  )
  popd
  echo [OK] Created backend\.venv
) else (
  echo [OK] Reusing existing backend\.venv
)

REM --- Backend Python packages ---
echo Installing backend requirements ...
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 (
  echo ERROR: Failed to install backend requirements.
  goto :fail
)
echo [OK] Backend requirements installed
echo.

REM --- .env (create only if missing; never overwrite) ---
if exist "backend\.env" (
  echo [OK] backend\.env already exists — leaving it unchanged
) else (
  if not exist "backend\.env.example" (
    echo ERROR: backend\.env.example is missing. Cannot create backend\.env
    goto :fail
  )
  echo Creating backend\.env from backend\.env.example ...
  copy /Y "backend\.env.example" "backend\.env" >nul
  if errorlevel 1 (
    echo ERROR: Failed to create backend\.env
    goto :fail
  )
  echo [OK] Created backend\.env
  echo      Edit backend\.env later to add API keys if needed.
)

REM --- Database migrations (safe; does not delete existing DB) ---
echo Running database migrations ^(alembic upgrade head^) ...
pushd backend
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
  echo ERROR: Database migration failed.
  popd
  goto :fail
)
popd
echo [OK] Database is up to date
echo.

REM --- Frontend packages ---
echo Installing frontend npm packages ...
pushd frontend
call npm install
if errorlevel 1 (
  echo ERROR: npm install failed in frontend.
  popd
  goto :fail
)
popd
echo [OK] Frontend dependencies installed
echo.

echo Setup complete.
echo Next: double-click start_windows.bat ^(or run it from this folder^).
echo.
pause
exit /b 0

:fail
echo.
echo Setup failed. Fix the error above, then run setup_windows.bat again.
echo.
pause
exit /b 1
