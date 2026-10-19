@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
echo This stops BookCompiler, Hindsight and the Hermes Dashboard.
echo PostgreSQL and Ollama are left running.
echo Use: python tools\stop.py all   to stop every process recorded by the launcher.
echo.
"%PY%" "%~dp0tools\stop.py" bookcompiler hindsight hermes-dashboard
pause
endlocal
