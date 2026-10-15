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
echo Installation terminee. Lance maintenant Lancer tracker4agents.cmd.
echo FFmpeg avec libopenmpt doit etre disponible dans le PATH pour l'ecoute.
pause
exit /b 0
:failed
echo Installation interrompue. Python 3.12 ou plus recent est requis.
pause
exit /b 1
