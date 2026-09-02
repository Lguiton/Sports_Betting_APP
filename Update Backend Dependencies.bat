@echo off
setlocal
cd /d "%~dp0"
title Updating backend dependencies

echo ============================================
echo   Updating backend Python dependencies
echo   (adds curl_cffi -- needed to get past
echo   ESPN's bot-mitigation)
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv\Scripts\python.exe -- run start_backend.bat
    echo once first to set up the environment, then try this again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo pip install failed -- see the error above.
    pause
    exit /b 1
)

echo.
echo Done. You can close this window and use the EIVANTA Dashboard
echo shortcut normally -- it will pick up the update next time it starts
echo the backend.
echo.
pause
