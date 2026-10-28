@echo off
cd /d "%~dp0"
echo ==== Building Sky Plane SMP launcher ====
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this again.
  pause
  exit /b 1
)
py -m pip install --upgrade pip
py -m pip install portablemc==5.0.6 pillow pyinstaller
if errorlevel 1 (
  echo Install failed. Check your internet connection.
  pause
  exit /b 1
)
py -m PyInstaller --noconfirm --clean --onefile --noconsole --name SkyPlaneSMP --icon assets\icon.ico --add-data "assets;assets" --collect-all portablemc launcher.py
if errorlevel 1 (
  echo Build failed. Copy the red text above and send it to me.
  pause
  exit /b 1
)
echo.
echo DONE. Your launcher is at: dist\SkyPlaneSMP.exe
pause
