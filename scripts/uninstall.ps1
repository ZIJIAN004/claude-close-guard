#Requires -Version 5.1
<#
.SYNOPSIS
  Remove claude-close-guard's auto-start, MCP registration, and PATH entry.
  Memory dir (~/.claude-close-guard/memory) is preserved.
#>

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$ConfigDir = Join-Path $env:USERPROFILE '.claude-close-guard'
$BinDir    = Join-Path $ConfigDir 'bin'

Write-Host "==> Uninstalling claude-close-guard" -ForegroundColor Cyan

# Stop running AHK
Get-Process AutoHotkey* -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -like '*close_guard*' -or
    $_.Path -like '*claude-close-guard*'
} | ForEach-Object {
    Write-Host "    stopping AHK pid $($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

# Remove startup shortcut
$Startup = [Environment]::GetFolderPath('Startup')
$Shortcut = Join-Path $Startup 'claude-close-guard.lnk'
if (Test-Path $Shortcut) {
    Remove-Item $Shortcut -Force
    Write-Host "    removed $Shortcut"
}

# MCP removal
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    & $claude.Source mcp remove ccg-memory 2>&1 | Out-Null
    Write-Host "    removed MCP server ccg-memory"
}

# PATH cleanup
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath -like "*$BinDir*") {
    $newPath = ($UserPath -split ';' | Where-Object { $_ -ne $BinDir }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "    removed $BinDir from PATH"
}

# Tell the user about the data we did NOT delete
Write-Host ""
Write-Host "Preserved (delete manually if you want):" -ForegroundColor Yellow
Write-Host "    $ConfigDir"
Write-Host "      ├─ memory/        your saved memories (markdown)"
Write-Host "      ├─ vectors.sqlite vector index"
Write-Host "      ├─ config.yaml"
Write-Host "      └─ .venv/         Python venv"
Write-Host ""
Write-Host "==> Done." -ForegroundColor Green
