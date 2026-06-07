@echo off
REM ============================================================
REM  ChefSync Virtual Printer — Start the thermal printer viewer
REM
REM  Starts the tkinter GUI that:
REM    - Watches %TEMP%\chefsync-virtual-jobs for .prn files
REM    - Renders ESC/POS receipts on screen
REM    - Runs an LPD server on port 5515 (for CUPS/lpd clients)
REM    - Runs a raw port 9100 server (for direct JetDirect clients)
REM
REM  The virtual printer reads files from the same directory the agent
REM  writes to (%TEMP%\chefsync-virtual-jobs by default), so it
REM  displays anything the agent prints to the "virtual" printer.
REM
REM  Environment variables (optional):
REM    CHEFSYNC_PRINT_SINK_DIR   - shared sink directory (same as agent)
REM    CHEFSYNC_VP_WIDTH_PX      - paper width in pixels (default: 576)
REM    CHEFSYNC_VP_LEFT_MARGIN   - left margin in pixels (default: 16)
REM    CHEFSYNC_VP_RIGHT_MARGIN  - right margin in pixels (default: 16)
REM ============================================================

cd /d "%~dp0"

echo.
echo  ============================================
echo   ChefSync Virtual Printer Viewer
echo  ============================================
echo.

REM Check Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found in PATH.
    echo  Install Python 3.10+ and add it to PATH.
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
echo  Virtual printer sink directory:
echo    %CHEFSYNC_PRINT_SINK_DIR%
echo  (default: %TEMP%\chefsync-virtual-jobs)
echo.
echo  LPD server:  port 5515
echo  RAW server:    port 9100
echo.
echo  Close the viewer window to stop.
echo.

"%PYTHON%" -m virtual_printer.viewer

pause