@echo off
setlocal EnableExtensions

REM Start backend + frontend on Windows. Opens the app in your browser.
REM Skips launching a second copy if ports 8000 / 5173 are already in use.

cd /d "%~dp0"
echo.
echo === Research Intelligence Tool — Windows start ===
echo.

set "VENV_PY=backend\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo ERROR: backend\.venv not found.
  echo Run setup_windows.bat once before starting the app.
  goto :fail
)

if not exist "backend\.env" (
  echo ERROR: backend\.env is missing.
  echo Run setup_windows.bat once before starting the app.
  goto :fail
)

REM --- Detect if already running ---
set "BACKEND_UP=0"
set "FRONTEND_UP=0"
netstat -ano 2>nul | findstr /R /C:":8000 .*LISTENING" >nul && set "BACKEND_UP=1"
netstat -ano 2>nul | findstr /R /C:":5173 .*LISTENING" >nul && set "FRONTEND_UP=1"

if "%BACKEND_UP%"=="1" if "%FRONTEND_UP%"=="1" (
  echo App appears to be already running.
  echo Opening http://localhost:5173/ in your browser ...
  start "" "http://localhost:5173/"
  echo.
  pause
  exit /b 0
)

if "%BACKEND_UP%"=="1" (
  echo WARNING: Port 8000 is already in use. Not starting another backend.
) 
if "%FRONTEND_UP%"=="1" (
  echo WARNING: Port 5173 is already in use. Not starting another frontend.
)

REM --- Safe migrations before start ---
echo Applying database migrations ^(safe / idempotent^) ...
pushd backend
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo ERROR: Database migration failed.
  popd
  goto :fail
)
popd
echo [OK] Database is up to date
echo.

REM --- Start processes that are not already up ---
if "%BACKEND_UP%"=="0" (
  echo Starting backend on http://127.0.0.1:8000 ...
  start "Research Intelligence Backend" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload"
) else (
  echo Backend already running — skipping.
)

if "%FRONTEND_UP%"=="0" (
  echo Starting frontend on http://localhost:5173 ...
  start "Research Intelligence Frontend" /D "%~dp0frontend" cmd /k "npm run dev"
) else (
  echo Frontend already running — skipping.
)

echo Waiting a few seconds for the app to come up ...
timeout /t 4 /nobreak >nul

echo Opening http://localhost:5173/ in your browser ...
start "" "http://localhost:5173/"
echo.
echo Backend and frontend are running in separate windows.
echo Close those windows ^(or press Ctrl+C in them^) when you are finished.
echo.
pause
exit /b 0

:fail
echo.
echo Start failed. Fix the error above, then try again.
echo.
pause
exit /b 1
