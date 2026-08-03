@echo off
REM Stock Pulse data sync. ASCII only on purpose: cmd.exe mis-parses batch files
REM that mix codepages, so all localized output lives in sync-data.ps1.
REM
REM   sync-data.bat        discard local data/ artifacts, pull the bot's latest
REM   sync-data.bat push   commit and push the locally generated data/ instead
setlocal
title Stock Pulse - data sync

if not exist "%~dp0sync-data.ps1" (
  echo [X] sync-data.ps1 not found next to this file.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-data.ps1" %1
exit /b %errorlevel%
