@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0preparar_aidycai.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo preparar AIDYCAI. Revisa el mensaje anterior.
  pause
)
endlocal
