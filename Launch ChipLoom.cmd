@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Install ChipLoom.cmd first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m tracker4agents gui %*
