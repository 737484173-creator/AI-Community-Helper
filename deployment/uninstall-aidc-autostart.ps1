[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-AidcAdministrator)) {
    throw "Administrator privileges are required."
}

$settings = Get-AidcSettings
$task = Get-ScheduledTask -TaskName $settings.ScheduledTaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -InputObject $task
    }
    Unregister-ScheduledTask -TaskName $settings.ScheduledTaskName -Confirm:$false
    Write-Host "Scheduled task removed: $($settings.ScheduledTaskName)"
}
else {
    Write-Host "Scheduled task is not installed."
}
