@echo off
REM Stock Pulse scheduled-task installer. ASCII only on purpose: cmd.exe
REM mis-parses batch files that mix codepages, so all localized output lives
REM in install-sync-task.ps1.
REM
REM   install-sync-task.bat           register (daily 07:10 and 17:10)
REM   install-sync-task.bat 09:00     register (daily, once, at that time)
REM   install-sync-task.bat remove    unregister
setlocal
title Stock Pulse - sync schedule

if not exist "%~dp0install-sync-task.ps1" (
  echo [X] install-sync-task.ps1 not found next to this file.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-sync-task.ps1" %1
exit /b %errorlevel%
