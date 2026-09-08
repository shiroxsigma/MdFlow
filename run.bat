@echo off
setlocal
cd /d "%~dp0"

set "MDFLOW_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%MDFLOW_PYTHON%" (
    echo [MdFlow] Creating the Python virtual environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.12 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto :error

)

"%MDFLOW_PYTHON%" -c "import nicegui, pptx, yaml" >nul 2>&1
if errorlevel 1 (
    echo [MdFlow] Installing dependencies...
    "%MDFLOW_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo [MdFlow] Starting...
"%MDFLOW_PYTHON%" -m mdflow
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [MdFlow] Failed to start. See the error above.
pause
exit /b 1
