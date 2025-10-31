@echo off
REM =============================================================
REM  DIETARY-APP Windows Quick Setup
REM  - Creates a virtual environment in .venv
REM  - Upgrades pip
REM  - Installs dependencies (from requirements.txt if present)
REM  - Runs the app (python app.py)
REM =============================================================

SETLOCAL ENABLEDELAYEDEXPANSION

REM ----- Move to the folder where this script lives -----
cd /d "%~dp0"

echo.
echo [1/6] Checking Python...
where python >nul 2>nul
IF ERRORLEVEL 1 (
  echo ERROR: Python is not on PATH. Please install Python 3.12+ from https://www.python.org/downloads/ and check "Add Python to PATH".
  pause
  exit /b 1
)

for /f "tokens=2 delims== " %%v in ('python -c "import sys; print(f'py{sys.version_info.major}.{sys.version_info.minor}')"') do set PYVER=%%v
echo Found Python !PYVER!

echo.
echo [2/6] Creating virtual environment (.venv)...
python -m venv .venv
IF ERRORLEVEL 1 (
  echo ERROR: Failed to create virtual environment.
  pause
  exit /b 1
)

echo.
echo [3/6] Activating virtual environment...
call .venv\Scripts\activate
IF ERRORLEVEL 1 (
  echo ERROR: Could not activate virtual environment.
  pause
  exit /b 1
)

echo.
echo [4/6] Upgrading pip...
python -m pip install --upgrade pip
IF ERRORLEVEL 1 (
  echo ERROR: pip upgrade failed. Try running this window as Administrator.
  pause
  exit /b 1
)

echo.
echo [5/6] Installing dependencies...
IF EXIST requirements.txt (
  echo Using requirements.txt
  pip install -r requirements.txt
) ELSE (
  echo requirements.txt not found. Installing core packages: Flask, Jinja2, and Pandas (optional).
  pip install Flask Jinja2 pandas
)

IF ERRORLEVEL 1 (
  echo ERROR: One or more packages failed to install.
  pause
  exit /b 1
)

echo.
echo [6/6] Launching the app...
IF NOT EXIST app.py (
  echo WARNING: app.py was not found in this folder. Place this script inside your DIETARY-APP project folder where app.py lives.
  echo Exiting without running.
  pause
  exit /b 0
)

python app.py
echo.
echo If the browser does not open automatically, visit: http://127.0.0.1:5000/
echo Press Ctrl+C to stop the server.
pause
