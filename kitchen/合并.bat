@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "F:\Clip\venv\Scripts\python.exe" (
  set PY=F:\Clip\venv\Scripts\python.exe
) else (
  set PY=python
)
if "%~1"=="" (
  echo 用法: 合并.bat 文件1.csv 文件2.csv 文件3.csv
  echo 或: python pipeline\merge_csv.py --dir C:\Users\ZFGJ-WCH\Downloads --n 3
  pause
  exit /b 1
)
"%PY%" -u pipeline\merge_csv.py %*
if errorlevel 1 pause
