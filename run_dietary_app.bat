@echo off
REM Run DIETARY-APP using existing virtual environment
cd /d "%~dp0"
IF NOT EXIST .venv\Scripts\activate (
  echo Virtual environment not found. Run setup_dietary_app_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
python app.py
