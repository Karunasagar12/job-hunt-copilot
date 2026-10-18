@echo off
cd /d "%~dp0"
docker compose pull
if errorlevel 1 exit /b 1
docker compose up -d
if errorlevel 1 exit /b 1
echo Updated.
pause
