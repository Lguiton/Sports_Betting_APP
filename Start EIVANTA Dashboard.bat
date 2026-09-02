@echo off
setlocal
cd /d "%~dp0"
title EIVANTA Dashboard Launcher

echo ============================================
echo   Starting EIVANTA Analytics Terminal...
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Could not find the Python environment at .venv\Scripts\python.exe
    echo Run start_backend.bat once first to set it up, then try this again.
    pause
    exit /b 1
)
if not exist "frontend\node_modules" (
    echo Could not find frontend\node_modules.
    echo Run "npm install" inside the frontend folder once first, then try this again.
    pause
    exit /b 1
)
if not exist "frontend\node_modules\.bin\next.cmd" (
    echo.
    echo frontend\node_modules exists but is missing next.cmd -- this usually
    echo means it was installed by something other than Windows npm (Linux/WSL,
    echo for example^), so Windows cannot run it.
    echo.
    echo Run "Reinstall Frontend Dependencies.bat" once to fix this, then try
    echo this launcher again.
    pause
    exit /b 1
)

echo Clearing out anything already using ports 8000/3001 from an earlier run...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

echo Starting backend (port 8000)...
start "EIVANTA Backend" /min "%~dp0_launcher\run_backend.bat"

echo Starting frontend (port 3001)...
start "EIVANTA Frontend" /min "%~dp0_launcher\run_frontend.bat"

echo.
echo Waiting for the backend to respond (up to 40 seconds)...
set /a _tries=0
:waitloop
set /a _tries+=1
curl -s -o nul -w "%%{http_code}" http://localhost:8000/docs > "%TEMP%\eivanta_check.txt" 2>nul
set /p _code=<"%TEMP%\eivanta_check.txt"
if "%_code%"=="200" goto backend_ready
if %_tries% GEQ 20 goto backend_timeout
timeout /t 2 /nobreak >nul
goto waitloop

:backend_timeout
echo.
echo   WARNING: backend did not respond at http://localhost:8000/docs after 40 seconds.
echo   Opening the dashboard anyway -- check the minimized "EIVANTA Backend"
echo   window (click it in your taskbar) for the actual error.
echo.

:backend_ready
start "" "http://localhost:3001"

echo.
echo ============================================
echo   EIVANTA is running.
echo   Backend and frontend windows are minimized
echo   in your taskbar. To stop everything, run
echo   "Stop EIVANTA Dashboard.bat" or just close
echo   the two minimized "EIVANTA Backend" /
echo   "EIVANTA Frontend" windows.
echo ============================================
echo.
echo This window will close in 10 seconds...
timeout /t 10 /nobreak >nul
exit
