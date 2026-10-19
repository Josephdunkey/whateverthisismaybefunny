@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY=.venv\Scripts\python.exe"
set "HPY=D:\hindsight\.venv\Scripts\python.exe"
set "WAIT=%PY% tools\wait_port.py"

echo [1/5] Ollama (11434)...
%WAIT% 11434 1
if errorlevel 1 (
  start "" /min ollama serve
  %WAIT% 11434 30
)
if errorlevel 1 echo [WARN] Ollama is not ready. Local memory/local reading will fail.

echo [2/5] Hindsight database (pg0:5432)...
%WAIT% 5432 1
if errorlevel 1 (
  "%HPY%" -c "import pg0; pg0.start('hindsight')"
  %WAIT% 5432 30
)
if errorlevel 1 echo [WARN] Hindsight database is not ready.

echo [3/5] Hindsight API (8888)...
%WAIT% 8888 1
if errorlevel 1 (
  start "" /min "%HPY%" "D:\hindsight\run_server.py"
  %WAIT% 8888 45
)
if errorlevel 1 echo [WARN] Hindsight API is not ready. See D:\hindsight\server.log.

echo [4/5] BookCompiler GUI (8765)...
%WAIT% 8765 1
if errorlevel 1 (
  start "" "%PY%" -m bookcompiler --db ".bookcompiler\library.db" gui --host 127.0.0.1 --port 8765 --open
  %WAIT% 8765 30
)
if errorlevel 1 echo [WARN] BookCompiler GUI is not ready.

echo [5/5] Hermes Agent...
if exist "D:\hermes agent\start-hermes.bat" (
  start "Hermes Agent" /D "D:\hermes agent" cmd /k "start-hermes.bat"
) else (
  echo [WARN] D:\hermes agent\start-hermes.bat not found.
)

echo.
echo All launchers started.
echo   BookCompiler GUI : http://127.0.0.1:8765
echo   Hindsight API    : http://127.0.0.1:8888/health
echo   Ollama           : http://127.0.0.1:11434
echo   Switch models    : switch-models.bat  (menu 8 = MiMo cloud reading + local Ollama memory)
echo.
timeout /t 8 >nul
endlocal