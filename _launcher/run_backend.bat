@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
REM --reload watches for .py file changes and restarts automatically,
REM scoped to just the source folders so editing data/duckdb files or
REM node_modules never triggers a spurious backend restart.
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend --reload-dir sports_agent
