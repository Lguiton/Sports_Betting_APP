@echo off
REM Create and activate native Windows virtual environment, install deps, and run backend server

REM Create venv
python -m venv .venv_win

REM Activate venv
call .\.venv_win\Scripts\activate.bat

REM Install requirements
pip install --upgrade pip
pip install -r requirements.txt

REM Run backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pause
