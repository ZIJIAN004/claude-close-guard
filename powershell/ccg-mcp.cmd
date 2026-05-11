@echo off
rem Wrapper that bypasses pip's console_scripts launcher (see ccg.cmd for why).
"%USERPROFILE%\.claude-close-guard\.venv\Scripts\python.exe" -m claude_close_guard.mcp_server %*
