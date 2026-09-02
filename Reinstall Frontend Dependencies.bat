@echo off
setlocal
cd /d "%~dp0frontend"
title Reinstalling frontend dependencies

echo ============================================
echo   Reinstalling frontend dependencies
echo   (fixes "'next' is not recognized" errors)
echo ============================================
echo.
echo This removes frontend\node_modules and reinstalls it fresh using
echo YOUR machine's npm, so Windows gets the .cmd launchers it needs
echo (the previous install looks like it was created on Linux/WSL, which
echo only creates Unix-style symlinks that Windows cmd cannot run).
echo.
echo If OneDrive is not already paused: right-click the OneDrive cloud
echo icon in your system tray -^> Pause syncing -^> 2 hours.
echo.
pause

if exist node_modules (
    echo Removing old node_modules (attempt 1: rmdir^)...
    rmdir /s /q node_modules >nul 2>&1
)

if exist node_modules (
    echo Still present -- retrying with PowerShell (attempt 2^)...
    powershell -NoProfile -Command "Remove-Item -LiteralPath 'node_modules' -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
)

if exist node_modules (
    echo Still present -- retrying with robocopy (attempt 3^).
    echo This handles the very long file paths node_modules is prone to,
    echo which is the single most common reason rmdir/PowerShell can't
    echo fully clear it on Windows even with nothing else locking it...
    if exist "%TEMP%\eivanta_empty" rmdir /s /q "%TEMP%\eivanta_empty" >nul 2>&1
    mkdir "%TEMP%\eivanta_empty"
    robocopy "%TEMP%\eivanta_empty" node_modules /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >nul
    rmdir /s /q node_modules >nul 2>&1
    rmdir /s /q "%TEMP%\eivanta_empty" >nul 2>&1
)

if exist node_modules (
    echo.
    echo   Still could not fully remove node_modules after three different
    echo   methods. Something has an actual open handle on a file in there
    echo   -- most likely a leftover node.exe process from an earlier run,
    echo   or an editor/antivirus with it open. Two things to try:
    echo     1^) Open Task Manager, end any "Node.js" / "node.exe" processes,
    echo        then run this script again.
    echo     2^) If that doesn't work, restart your PC (this always clears
    echo        file locks^) and run this script again right after.
    echo.
    pause
    exit /b 1
)

echo node_modules fully removed.
echo.
echo Running npm install (this can take a few minutes)...
call npm install
if errorlevel 1 (
    echo.
    echo npm install failed -- see the error above.
    echo If it is another EPERM/copyfile error, something is still locking
    echo files in this folder -- see the suggestions above.
    pause
    exit /b 1
)

echo.
if exist "node_modules\.bin\next.cmd" (
    echo Success -- node_modules\.bin\next.cmd now exists.
    echo You can close this window and use the EIVANTA Dashboard shortcut normally.
    echo (You can resume OneDrive syncing now if you paused it.^)
) else (
    echo Reinstall finished, but next.cmd still was not created.
    echo Something is unusual about this npm/Node setup -- let me know what
    echo printed above and I will take a closer look.
)
echo.
pause
