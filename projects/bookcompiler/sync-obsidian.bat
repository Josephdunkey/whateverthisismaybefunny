@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m bookcompiler --db .bookcompiler\library.db obsidian-sync-all %*
if "%~1"=="" pause
