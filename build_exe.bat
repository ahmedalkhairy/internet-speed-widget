@echo off
setlocal ENABLEDELAYEDEXPANSION

REM Build TrafficWidget.exe with PyInstaller (one-file, no console)
REM Requires Python 3.9+ on PATH.

REM Ensure dependencies
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt pyinstaller >nul 2>&1

REM If app is currently running, ask user to close it and wait
set _EXE_NAME=TrafficWidget.exe
echo Checking if %_EXE_NAME% is running...
:check_running
tasklist /FI "IMAGENAME eq %_EXE_NAME%" | findstr /I "%_EXE_NAME%" >nul
if not errorlevel 1 (
  echo.
  echo %_EXE_NAME% is running. Please close it before building.
  echo Close via the tray icon: Exit, or close the window.
  echo Then return here. Rechecking in 2 seconds... Press Ctrl+C to cancel.
  timeout /t 2 /nobreak >nul
  goto check_running
)

REM Double-check the file is not locked by attempting a temporary rename
if exist "dist\%_EXE_NAME%" (
  :check_locked
  >nul 2>&1 ren "dist\%_EXE_NAME%" "%_EXE_NAME%.tmp"
  if errorlevel 1 (
    echo %_EXE_NAME% still appears locked. Please ensure it is closed.
    timeout /t 2 /nobreak >nul
    goto check_locked
  ) else (
    ren "dist\%_EXE_NAME%.tmp" "%_EXE_NAME%" >nul 2>&1
  )
)

REM Build using module invocation to avoid PATH issues
python -m PyInstaller --noconfirm --clean ^
  --name TrafficWidget ^
  --onefile --noconsole ^
  --hidden-import=paramiko ^
  --hidden-import=pystray ^
  --hidden-import=PIL.Image --hidden-import=PIL.ImageDraw --hidden-import=PIL.ImageFont ^
  traffic_widget.py

echo.
echo Built EXE at dist\TrafficWidget.exe
endlocal
