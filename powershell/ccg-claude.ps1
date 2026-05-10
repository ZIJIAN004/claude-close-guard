#Requires -Version 5.1
<#
.SYNOPSIS
  Drop-in replacement for `claude` that registers a Console-Ctrl handler so the
  X-button / "close window" path triggers the post-close memory popup.
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = 'Stop'

$ConfigDir = Join-Path $env:USERPROFILE '.claude-close-guard'
$ConfigFile = Join-Path $ConfigDir 'ahk.cfg'
if (-not (Test-Path $ConfigFile)) {
    Write-Error "claude-close-guard: missing $ConfigFile. Run install.ps1 first."
    exit 1
}
$PythonExe = (Get-Content -LiteralPath $ConfigFile -Encoding UTF8 | Select-Object -First 1).Trim()
if (-not (Test-Path $PythonExe)) {
    Write-Error "claude-close-guard: pythonw.exe not found at $PythonExe"
    exit 1
}

$ClaudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $ClaudeCmd) {
    Write-Error "claude-close-guard: 'claude' is not on PATH. Install Claude Code first."
    exit 1
}

# Register a SetConsoleCtrlHandler that fires on CTRL_CLOSE_EVENT (X button,
# task-bar Close Window, end-task) and detaches a popup process. Windows
# gives us ~5 s before SIGKILL, but we only need a few ms to spawn detached.
$signature = @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class CcgCloseHandler {
    public delegate bool HandlerRoutine(uint dwCtrlType);

    [DllImport("Kernel32", SetLastError = true)]
    public static extern bool SetConsoleCtrlHandler(HandlerRoutine handler, bool add);

    public const uint CTRL_C_EVENT = 0;
    public const uint CTRL_BREAK_EVENT = 1;
    public const uint CTRL_CLOSE_EVENT = 2;
    public const uint CTRL_LOGOFF_EVENT = 5;
    public const uint CTRL_SHUTDOWN_EVENT = 6;

    public static string PythonExe;

    private static HandlerRoutine _handler;

    public static void Install(string pythonExe) {
        PythonExe = pythonExe;
        _handler = new HandlerRoutine(OnCtrl);
        SetConsoleCtrlHandler(_handler, true);
    }

    private static bool OnCtrl(uint type) {
        if (type != CTRL_CLOSE_EVENT && type != CTRL_LOGOFF_EVENT && type != CTRL_SHUTDOWN_EVENT)
            return false;  // let Ctrl+C / Ctrl+Break propagate
        try {
            int pid = Process.GetCurrentProcess().Id;
            // Use ShellExecute (UseShellExecute=true) so the new process is
            // launched via the shell and does NOT inherit our console session
            // group — otherwise it gets the same CTRL_CLOSE_EVENT and dies
            // with us. Hidden window keeps it invisible until tkinter pops up.
            var psi = new ProcessStartInfo {
                FileName = PythonExe,
                Arguments = string.Format(
                    "-m claude_close_guard.close_handler --pid {0} --post-close", pid),
                UseShellExecute = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            Process.Start(psi);
        } catch {
            // best-effort; never block close
        }
        return false;  // continue default handling → process exits and window closes
    }
}
'@

if (-not ('CcgCloseHandler' -as [type])) {
    Add-Type -TypeDefinition $signature -Language CSharp
}

[CcgCloseHandler]::Install($PythonExe)

# Forward all args to the real claude CLI.
& $ClaudeCmd.Source @ClaudeArgs
exit $LASTEXITCODE
