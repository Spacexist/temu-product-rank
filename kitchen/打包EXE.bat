@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "F:\Clip\venv\Scripts\python.exe" (
  set PY=F:\Clip\venv\Scripts\python.exe
) else (
  set PY=python
)
"%PY%" -m pip install -q customtkinter pyinstaller
"%PY%" -m PyInstaller --noconfirm --windowed --name 厨房收纳 --add-data "words;words" --add-data "cf-site;cf-site" --add-data "pipeline;pipeline" --add-data "screener;screener" app.py
echo EXE 在 dist\厨房收纳\
pause
