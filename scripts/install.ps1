#Requires -Version 5.1
<#
.SYNOPSIS
  Install claude-close-guard: venv, deps, MCP registration, AHK auto-start.

.DESCRIPTION
  Run from the repository root after `git clone`. Idempotent — safe to re-run
  to upgrade. Does not download the embedding model; that happens on first
  `ccg search` / `ccg-mcp` call.
#>

param(
    [switch]$NoMcp,
    [switch]$NoStartup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$ConfigDir  = Join-Path $env:USERPROFILE '.claude-close-guard'
$VenvDir    = Join-Path $ConfigDir '.venv'
$PythonExe  = Join-Path $VenvDir 'Scripts\python.exe'
$PythonwExe = Join-Path $VenvDir 'Scripts\pythonw.exe'

Write-Host "==> Installing claude-close-guard" -ForegroundColor Cyan
Write-Host "    repo:   $RepoRoot"
Write-Host "    config: $ConfigDir"

# 1) python venv
if (-not (Test-Path $PythonExe)) {
    Write-Host "==> Creating venv at $VenvDir" -ForegroundColor Cyan
    $sysPython = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $sysPython) { throw "python is not on PATH. Install Python >= 3.10 first." }
    & $sysPython.Source -m venv $VenvDir
}

Write-Host "==> Installing project (pip install -e)" -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip wheel setuptools | Out-Null

# Install CPU-only torch first (default PyPI torch is the CUDA build, ~2.5 GB).
# If the user wants GPU, they can `pip install torch --index-url ...` themselves.
$haveTorch = (& $PythonExe -c "import importlib, sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" 2>$null; $LASTEXITCODE -eq 0)
if (-not $haveTorch) {
    Write-Host "    installing CPU-only torch (~200 MB)..." -ForegroundColor DarkGray
    & $PythonExe -m pip install --index-url https://download.pytorch.org/whl/cpu torch
}

& $PythonExe -m pip install -e $RepoRoot

# 2) write default config + ahk.cfg
if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }
$DefaultConfig = Join-Path $ConfigDir 'config.yaml'
if (-not (Test-Path $DefaultConfig)) {
    Copy-Item (Join-Path $RepoRoot 'config.example.yaml') $DefaultConfig
    Write-Host "    wrote $DefaultConfig"
}
Set-Content -Path (Join-Path $ConfigDir 'ahk.cfg') -Value $PythonwExe -Encoding UTF8

# 3) MCP registration (best effort — only if `claude` is on PATH)
if (-not $NoMcp) {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        Write-Host "==> Registering MCP server (ccg-memory)" -ForegroundColor Cyan
        $ccgMcp = Join-Path $VenvDir 'Scripts\ccg-mcp.exe'
        if (-not (Test-Path $ccgMcp)) { $ccgMcp = "$PythonExe -m claude_close_guard.mcp_server" }
        try {
            & $claude.Source mcp remove ccg-memory 2>&1 | Out-Null
        } catch { }
        & $claude.Source mcp add ccg-memory --scope user -- $ccgMcp
    } else {
        Write-Host "    (skipped — 'claude' CLI not on PATH; register the MCP server manually later)" -ForegroundColor Yellow
    }
}

# 4) AHK auto-start (only if AHK v2 present)
if (-not $NoStartup) {
    $ahkExe = $null
    foreach ($p in @(
        "$env:ProgramFiles\AutoHotkey\v2\AutoHotkey.exe",
        "$env:ProgramFiles\AutoHotkey\AutoHotkey.exe",
        "$env:LOCALAPPDATA\Programs\AutoHotkey\v2\AutoHotkey.exe"
    )) {
        if (Test-Path $p) { $ahkExe = $p; break }
    }

    if ($ahkExe) {
        Write-Host "==> Registering AHK script for auto-start" -ForegroundColor Cyan
        $ahkScript = Join-Path $RepoRoot 'ahk\close_guard.ahk'
        $startup   = [Environment]::GetFolderPath('Startup')
        $shortcut  = Join-Path $startup 'claude-close-guard.lnk'
        $wsh = New-Object -ComObject WScript.Shell
        $sc = $wsh.CreateShortcut($shortcut)
        $sc.TargetPath = $ahkExe
        $sc.Arguments  = "`"$ahkScript`""
        $sc.WorkingDirectory = (Split-Path -Parent $ahkScript)
        $sc.Save()
        Write-Host "    wrote $shortcut"
        # Start it now too
        Start-Process -FilePath $ahkExe -ArgumentList "`"$ahkScript`""
    } else {
        Write-Host "    (skipped — AutoHotkey v2 not found; install from https://www.autohotkey.com)" -ForegroundColor Yellow
    }
}

# 5) ccg-claude shim on PATH (both .ps1 and .cmd so it works from anywhere)
$BinDir = Join-Path $ConfigDir 'bin'
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }
Copy-Item (Join-Path $RepoRoot 'powershell\ccg-claude.ps1') (Join-Path $BinDir 'ccg-claude.ps1') -Force
Copy-Item (Join-Path $RepoRoot 'powershell\ccg-claude.cmd') (Join-Path $BinDir 'ccg-claude.cmd') -Force

$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable('Path', "$UserPath;$BinDir", 'User')
    Write-Host "==> Added $BinDir to user PATH (open a new terminal to pick it up)" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "==> Done." -ForegroundColor Green
Write-Host "    - Use Alt+F4 in your terminal → blocking confirm popup."
Write-Host "    - Use 'ccg-claude' (instead of 'claude') to enable X-button post-close popup."
Write-Host "    - 'ccg list' / 'ccg search <q>' to browse the memory store."
Write-Host "    - Memory dir: $((& $PythonExe -m claude_close_guard.cli path))"
