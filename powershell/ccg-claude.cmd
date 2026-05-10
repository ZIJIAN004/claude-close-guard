@echo off
rem Shim so `ccg-claude` works from cmd.exe and PowerShell (where .PS1 isn't in PATHEXT).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ccg-claude.ps1" %*
