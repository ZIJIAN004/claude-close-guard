@echo off
rem Wrapper that bypasses pip's console_scripts launcher (which can deadlock
rem subprocess spawn on Windows with sentence-transformers/multiprocessing).
"%USERPROFILE%\.claude-close-guard\.venv\Scripts\python.exe" -m claude_close_guard.cli %*
