@echo off
cd /d "%~dp0frontend"

REM Start Next.js frontend dev server
from sports_agent.graph import sports_agent_app
python -m backend.main
pause

