@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe run.py
if errorlevel 1 goto failed
exit /b
:failed
pause
