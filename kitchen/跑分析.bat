@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "F:\Clip\venv\Scripts\python.exe" (
  set PY=F:\Clip\venv\Scripts\python.exe
) else (
  set PY=python
)
if "%~1"=="" (
  echo 用法: 跑分析.bat 筛选后的.html
  echo 会写入 data_cache\日期\
  pause
  exit /b 1
)
"%PY%" -u pipeline\daily.py --bundle %*
if errorlevel 1 pause
