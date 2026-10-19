@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found in this folder.
  echo Create it first with: py -m venv .venv
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo Starting BookCompiler GUI...
echo The browser will open automatically. Keep this window open while you use it.
echo.
".venv\Scripts\python.exe" -m bookcompiler --db ".bookcompiler\library.db" gui --host 127.0.0.1 --port 8765 --open
echo.
echo BookCompiler GUI stopped. Press any key to close.
pause >nul
