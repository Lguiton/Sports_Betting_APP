@echo off
title EIVANTA Dashboard - Stopping
echo Stopping EIVANTA backend and frontend...

taskkill /FI "WINDOWTITLE eq EIVANTA Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq EIVANTA Frontend*" /T /F >nul 2>&1

REM Fallback: also stop by process/port in case the titled windows already
REM closed on their own but the servers are still bound to the ports.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

echo Done.
timeout /t 3 /nobreak >nul
exit
