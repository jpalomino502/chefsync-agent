@echo off
REM ============================================================
REM  ChefSync Agent — Start the HTTP API + Supabase poller
REM
REM  Starts the Flask agent on http://localhost:5321 with:
REM    - /health, /printers, /print, /print/test, /config/*
REM    - Supabase poller (claim jobs, heartbeat, registration)
REM    - Virtual printer file sink writes to %TEMP%\chefsync-virtual-jobs
REM
REM  Environment variables (optional):
REM    CHEFSYNC_HOST             - bind address (default: localhost)
REM    CHEFSYNC_PORT             - bind port (default: 5321)
REM    CHEFSYNC_LOG_LEVEL        - DEBUG, INFO, WARNING, ERROR
REM    CHEFSYNC_PRINT_SINK_DIR   - virtual printer output directory
REM
REM  The agent reads Supabase config from:
REM    1. Environment variables (CHEFSYNC_SUPABASE_URL, _KEY, _LOCATION_ID)
REM    2. Config file: %APPDATA%\ChefSync\config.json
REM ============================================================

cd /d "%~dp0"

echo.
echo  ============================================
echo   ChefSync Agent
echo  ============================================
echo.

REM Check Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found in PATH.
    echo  Install Python 3.10+ and add it to PATH.
    echo  https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check for virtual environment
if exist ".venv\Scripts\python.exe" (
    echo  Using .venv\Scripts\python.exe
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    echo  Using venv\Scripts\python.exe
    set "PYTHON=venv\Scripts\python.exe"
) else (
    echo  Using system python
    set "PYTHON=python"
)

echo.
echo  Starting agent...
echo  HTTP:   http://%CHEFSYNC_HOST%=localhost:%CHEFSYNC_PORT%=5321
echo  Config: %APPDATA%\ChefSync\config.json
echo  Sink:   %CHEFSYNC_PRINT_SINK_DIR%=%TEMP%\chefsync-virtual-jobs
echo.
echo  Press Ctrl+C to stop.
echo.

"%PYTHON%" run_local_agent.py

pause