@echo off
cd /d "%~dp0"

REM Activate Windows native Python virtual environment
call .\.venv\Scripts\activate.bat

REM Start FastAPI backend server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pause

