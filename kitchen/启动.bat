@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "F:\Clip\venv\Scripts\python.exe" (
  "F:\Clip\venv\Scripts\python.exe" -u app.py
) else (
  python -u app.py
)
if errorlevel 1 pause
