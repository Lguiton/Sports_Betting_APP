@echo off
setlocal
cd /d "%~dp0"
title Push to GitHub

echo ============================================
echo   Pushing today's commit to GitHub
echo ============================================
echo.
echo Repo: %cd%
echo.

git status
echo.
echo About to push branch "main" to origin (github.com/Lguiton/Sports_Betting_APP).
echo If this is the first push from this machine in a while, Git may open a
echo browser window asking you to sign in to GitHub -- that's normal.
echo.
pause

git push origin main
if errorlevel 1 (
    echo.
    echo Push failed -- see the error above. Common causes: not signed in
    echo to GitHub yet (a browser window may have opened -- finish signing
    echo in there and run this again^), or someone else pushed to main
    echo since your last pull.
    pause
    exit /b 1
)

echo.
echo Done -- pushed to GitHub successfully.
echo.
pause
