@echo off
cd /d "%~dp0"
echo === NexFlow backend launcher ===

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo Existing .venv is invalid. Recreating it ...
        rmdir /s /q .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment .venv ...
    python -m venv .venv
)

echo Installing/updating backend dependencies from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo Dependency install failed. See the error above.
    pause
    exit /b 1
)

echo.
echo Starting backend on http://localhost:8000 ...
".venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --port 8000

pause
