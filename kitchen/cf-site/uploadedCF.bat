@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "F:\Clip\venv\Scripts\python.exe" (
  "F:\Clip\venv\Scripts\python.exe" uploadedCF.py %*
) else (
  python uploadedCF.py %*
)
if errorlevel 1 pause
