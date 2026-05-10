#Requires AutoHotkey v2.0
#SingleInstance Force

; claude-close-guard — Alt+F4 interceptor for terminal windows.
;
; Reads its config from %USERPROFILE%\.claude-close-guard\ahk.cfg (a single
; line: full path to pythonw.exe inside the project venv). install.ps1
; writes that file.

ConfigDir   := EnvGet("USERPROFILE") . "\.claude-close-guard"
ConfigFile  := ConfigDir . "\ahk.cfg"
LogFile     := ConfigDir . "\ahk.log"

PythonExe := ""
if FileExist(ConfigFile) {
    PythonExe := Trim(FileRead(ConfigFile, "UTF-8"))
}
if (!PythonExe || !FileExist(PythonExe)) {
    MsgBox("claude-close-guard: cannot locate pythonw.exe.`n`nMissing or invalid: " . ConfigFile,
           "claude-close-guard", 0x10)
    ExitApp 1
}

; Window classes we intercept Alt+F4 on. install.ps1 may rewrite this list
; from config.yaml, but the defaults cover Windows Terminal + conhost.
TargetClasses := Map(
    "CASCADIA_HOSTING_WINDOW_CLASS", true,
    "ConsoleWindowClass", true,
)

LogLine(line) {
    try {
        FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") . " " . line . "`n",
                   LogFile, "UTF-8")
    }
}

IsTargetWindow(hwnd) {
    if (!hwnd)
        return false
    cls := ""
    try {
        cls := WinGetClass("ahk_id " . hwnd)
    } catch {
        return false
    }
    return TargetClasses.Has(cls)
}

InterceptClose(hwnd) {
    pid := 0
    try {
        pid := WinGetPID("ahk_id " . hwnd)
    } catch {
        LogLine("WinGetPID failed for hwnd=" . hwnd)
        return 0
    }
    cmd := Format('"{1}" -m claude_close_guard.close_handler --pid {2} --hwnd {3}',
                  PythonExe, pid, hwnd)
    LogLine("intercept hwnd=" . hwnd . " pid=" . pid)
    exitCode := 0
    try {
        exitCode := RunWait(cmd, , "Hide")
    } catch as e {
        LogLine("RunWait failed: " . e.Message)
        return 0
    }
    LogLine("python exited " . exitCode)
    return exitCode
}

#HotIf IsTargetWindow(WinExist("A"))

!F4:: {
    hwnd := WinExist("A")
    code := InterceptClose(hwnd)
    if (code = 0) {
        try WinClose("ahk_id " . hwnd)
    }
}

#HotIf

LogLine("claude-close-guard AHK started; python=" . PythonExe)
