@echo off
cd /d "%~dp0frontend"
echo === NexFlow frontend launcher ===
echo Starting Next.js dev server on port 3001 ...

if exist "C:\Program Files\nodejs\npm.cmd" set "PATH=C:\Program Files\nodejs;%PATH%"

where npm >nul 2>&1
if not errorlevel 1 (
    call npm run dev
) else (
    echo Windows npm was not found. Using WSL Node.js ...
    for /f "tokens=1" %%i in ('wsl.exe hostname -I') do set WSL_IP=%%i
    echo Frontend URL: http://%WSL_IP%:3001
    wsl.exe --cd /mnt/c/Users/Guito/OneDrive/Documents/Sports_Betting_App/frontend npm run dev
)
pause
