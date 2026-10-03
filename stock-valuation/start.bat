@echo off
chcp 65001 >nul
REM Starts the app on http://localhost:8000
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "" http://localhost:8000
python server.py
