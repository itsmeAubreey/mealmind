DIETARY-APP — Windows Quickstart
=================================

1) Put these files in the ROOT of your project folder (same level as app.py):
   - setup_dietary_app_windows.bat
   - run_dietary_app.bat
   - requirements.txt

2) Right-click **setup_dietary_app_windows.bat** → Run as administrator.
   This will:
     • Create .venv
     • Upgrade pip
     • Install dependencies
     • Run `python app.py`

3) Next time, just double-click **run_dietary_app.bat**.

4) Open http://127.0.0.1:5000 in your browser.
   Test users (per your guide):
     - dietitian / 1234
     - cook / 1234
     - supervisor / 1234

Troubleshooting
---------------
• Python not found:
  Reinstall Python 3.12+ from https://www.python.org/downloads/
  Make sure to check "Add Python to PATH".

• Permission errors installing packages:
  Right-click the BAT file → Run as administrator.

• Port already in use:
  Change the port in app.py (e.g., app.run(port=5001)) or close the other app.

• Virtual environment issues:
  Delete the `.venv` folder and run the setup script again.
