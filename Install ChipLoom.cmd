@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -e ".[desktop]"
if errorlevel 1 goto failed
echo.
echo Installed. Run Launch ChipLoom.cmd.
echo Playback requires FFmpeg with libopenmpt on PATH.
pause
exit /b 0
:failed
echo Installation failed. Python 3.12 or newer is required.
pause
exit /b 1
