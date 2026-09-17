[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$settings = Get-AidcSettings
$projectRoot = Get-AidcProjectRoot
$pythonPath = Resolve-AidcPython -Settings $settings
$aeCliPath = Resolve-AidcAeCli -Settings $settings
$logDirectory = Get-AidcLogDirectory -Settings $settings
$pidFile = Get-AidcPidFile -Settings $settings
$supervisorLog = Join-Path $logDirectory "aidc-supervisor.log"
$supervisorProcess = Get-Process -Id $PID

$env:STREAMLIT_SERVER_ADDRESS = [string]$settings.ListenAddress
$env:STREAMLIT_SERVER_PORT = [string]$settings.Port
$env:STREAMLIT_SERVER_HEADLESS = "true"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
if ($aeCliPath) {
    $env:AE_CLI_PATH = $aeCliPath
}
Repair-AidcPathEnvironment

$arguments = @(
    "manage.py",
    "dashboard",
    "--port",
    [string]$settings.Port
)

while ($true) {
    if (Test-AidcLocalHealth -Settings $settings) {
        throw "AIDC is already healthy at $(Get-AidcLocalHealthUri -Settings $settings)."
    }

    $startedAt = Get-Date
    $logStamp = $startedAt.ToString("yyyyMMdd-HHmmss")
    $stdoutLog = Join-Path $logDirectory "aidc-$logStamp.out.log"
    $stderrLog = Join-Path $logDirectory "aidc-$logStamp.err.log"

    $process = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    @{
        ProcessId                      = $process.Id
        ProcessStartedAtFileTimeUtc    = $process.StartTime.ToFileTimeUtc()
        SupervisorId                   = $PID
        SupervisorStartedAtFileTimeUtc = $supervisorProcess.StartTime.ToFileTimeUtc()
        SupervisorPath                 = $supervisorProcess.Path
        PythonPath                     = $pythonPath
        StartedAtUtc                   = $process.StartTime.ToUniversalTime().ToString("o")
        Port                           = [int]$settings.Port
    } | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

    Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
        "{0} child PID {1} started on {2}:{3}." -f (Get-Date -Format "s"), $process.Id, $settings.ListenAddress, $settings.Port
    )

    $process.WaitForExit()
    $process.Refresh()
    $exitCode = $process.ExitCode
    $exitDisplay = if ($null -eq $exitCode) { "unavailable" } else { [string]$exitCode }
    if (Test-Path -LiteralPath $pidFile) {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        if ([int]$record.ProcessId -eq $process.Id) {
            Remove-Item -LiteralPath $pidFile -Force
        }
    }

    Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
        "{0} child PID {1} exited with code {2}; restarting in 10 seconds." -f (Get-Date -Format "s"), $process.Id, $exitDisplay
    )
    Start-Sleep -Seconds 10
}
