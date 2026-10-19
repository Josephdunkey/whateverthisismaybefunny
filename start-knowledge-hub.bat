@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  pause
  exit /b 1
)
echo ============================================================
echo  Knowledge Hub - one click launcher
echo ============================================================
"%PY%" "%~dp0tools\launch.py" all
if errorlevel 1 (
  echo.
  echo [WARN] Some services did not start. Open the Services tab or inspect:
  echo        D:\knowledge-hub\logs
)
echo.
echo Opening Knowledge Hub...
start "" "http://127.0.0.1:9119/knowledge-hub"
echo.
echo   Unified console : http://127.0.0.1:9119/knowledge-hub
echo   BookCompiler    : http://127.0.0.1:8765
echo   Hindsight       : http://127.0.0.1:8888/health
echo   Ollama          : http://127.0.0.1:11434
echo.
timeout /t 6 >nul
endlocal
