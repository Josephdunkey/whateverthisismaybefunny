@echo off
setlocal
cd /d "D:\hermes agent"
if not exist "bin\hermes.cmd" (
  echo [ERROR] Hermes launcher not found: D:\hermes agent\bin\hermes.cmd
  pause
  exit /b 1
)
echo Starting Hermes Agent...
call "D:\hermes agent\bin\hermes.cmd" chat
echo.
echo Hermes exited. Press any key to close.
pause >nul
