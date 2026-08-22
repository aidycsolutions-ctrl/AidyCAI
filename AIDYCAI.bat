@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m aidycai gui
) else (
  py -m aidycai gui
)
if errorlevel 1 pause
endlocal
