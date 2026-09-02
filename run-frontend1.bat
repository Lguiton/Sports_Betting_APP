@echo off
cd /d "%~dp0frontend"

REM Start Next.js frontend dev server
call npm run dev
pause
