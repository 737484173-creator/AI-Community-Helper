[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$AeCliPath,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-AidcAdministrator)) {
    throw "Administrator privileges are required. Reopen PowerShell as Administrator and run this script again."
}

$settings = Get-AidcSettings
$resolvedPython = Resolve-AidcPython -RequestedPath $PythonPath -Settings $settings
$resolvedAeCli = Resolve-AidcAeCli -RequestedPath $AeCliPath -Settings $settings
$machineSettings = @{ PythonPath = $resolvedPython }
if ($resolvedAeCli) {
    $machineSettings["AeCliPath"] = $resolvedAeCli
}
Save-AidcMachineSettings -Values $machineSettings

$runner = Join-Path $PSScriptRoot "run-aidc.ps1"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$encodedCommand = ConvertTo-AidcEncodedCommand -ScriptPath $runner
$taskArguments = "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encodedCommand"
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $taskArguments -WorkingDirectory (Get-AidcProjectRoot)
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $settings.ScheduledTaskName `
    -Description "Start the local-only AIDC Streamlit workbench and restart it after failures." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $taskSettings `
    -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $settings.ScheduledTaskName
}

Write-Host "Scheduled task installed: $($settings.ScheduledTaskName)"
Write-Host "Python runtime: $resolvedPython"
if ($resolvedAeCli) {
    Write-Host "AE CLI: $resolvedAeCli"
}
else {
    Write-Warning "AE CLI was not found. Dashboard startup will continue, but AE sync will be unavailable."
}
Write-Host "Startup: At system startup; dashboard recovery: 10 seconds; supervisor recovery: every 1 minute."
