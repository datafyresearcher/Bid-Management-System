# Register the scheduled task that runs the capture bridge every four hours.
#
# The action runs capture.py under the venv's pythonw.exe: a GUI-subsystem
# interpreter, so no console window opens on the desktop at 4-hourly runs.
# stdout does not exist under pythonw, which is why capture.py logs to
# bridge.log instead of the console.
#
# An earlier revision routed the run through cmd.exe /c run-capture-task.cmd
# to dodge a schtasks /create quoting trap — the bridge folder's path contains
# spaces ("BID Management System") and schtasks mangles quoted paths at exactly
# that space. The ScheduledTasks module used here has no quoting traps, and any
# cmd.exe in the action would open a console window, so the interpreter is the
# action's whole command line. Re-running this script replaces the task. Run
# from any shell:
#
#     powershell -ExecutionPolicy Bypass -File tools\ppra-bridge\register-task.ps1

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe not found in the bridge venv: $pythonw"
}
$script = Join-Path $PSScriptRoot 'capture.py'
if (-not (Test-Path $script)) {
    throw "capture.py not found next to this script: $script"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}"' -f $script)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 4)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName 'AHTE-PPRA-capture' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered AHTE-PPRA-capture: runs every 4 hours, first run in ~5 minutes."
Write-Host "Action: $pythonw $script"
