# Register the scheduled task that runs the capture bridge every four hours.
#
# The bridge folder's path contains spaces ("BID Management System"), and
# schtasks /create mangles quoted paths at exactly that space — the task ends
# up trying to execute "C:\...\BID" as a program and every run fails with
# 0x80070002 before the capture starts. The ScheduledTasks module has no
# quoting traps, so the task is registered here instead. Run from any shell:
#
#     powershell -ExecutionPolicy Bypass -File tools\ppra-bridge\register-task.ps1
#
# Re-running it replaces the existing task.

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$wrapper = Join-Path $PSScriptRoot 'run-capture-task.cmd'
if (-not (Test-Path $wrapper)) {
    throw "run-capture-task.cmd not found next to this script: $wrapper"
}

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$wrapper`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 4)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName 'AHTE-PPRA-capture' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered AHTE-PPRA-capture: runs every 4 hours, first run in ~5 minutes."
Write-Host "Action: cmd.exe /c $wrapper"
