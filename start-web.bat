@echo off
REM Stock Pulse launcher. ASCII only on purpose: cmd.exe mis-parses batch files
REM that mix codepages, so all localized output lives in start-web.ps1.
setlocal
title Stock Pulse

if not exist "%~dp0start-web.ps1" (
  echo [X] start-web.ps1 not found next to this file.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-web.ps1"
exit /b %errorlevel%
