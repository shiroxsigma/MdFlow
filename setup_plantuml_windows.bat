@echo off
setlocal
cd /d "%~dp0"

echo [MdFlow] PlantUML environment setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_plantuml_windows.ps1"
if errorlevel 1 goto :error

echo.
echo [MdFlow] Setup and rendering verification completed.
exit /b 0

:error
echo.
echo [MdFlow] PlantUML setup failed. See the error above.
pause
exit /b 1
