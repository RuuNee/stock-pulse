@echo off
REM Stock Pulse stopper. ASCII only on purpose: cmd.exe mis-parses batch files
REM that mix codepages, so all localized output lives in stop-web.ps1.
setlocal
title Stock Pulse - stop

if not exist "%~dp0stop-web.ps1" (
  echo [X] stop-web.ps1 not found next to this file.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-web.ps1"
exit /b %errorlevel%
