@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Lance d'abord Installer interface Windows.cmd dans ce dossier.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m tracker4agents gui %*
