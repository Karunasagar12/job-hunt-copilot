@echo off
cd /d "%~dp0"
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop isn't running. Open Docker Desktop, wait until it says "Engine running", then double-click start.bat again.
  pause
  exit /b 1
)
if not exist data mkdir data
docker compose pull
docker compose up -d
if errorlevel 1 (
  echo Could not start Job Hunt Copilot. See docs\TROUBLESHOOTING.md
  pause
  exit /b 1
)
echo Starting Job Hunt Copilot...
for /l %%i in (1,1,60) do (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/health ^| Out-Null; exit 0 } catch { exit 1 }" && goto ready
  timeout /t 1 >nul
)
echo It's taking longer than usual. Open http://127.0.0.1:8080 in your browser in a minute.
pause
exit /b 0
:ready
start "" http://127.0.0.1:8080
