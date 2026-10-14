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
$observingHealthyEndpoint = $false

$env:STREAMLIT_SERVER_ADDRESS = [string]$settings.ListenAddress
$env:STREAMLIT_SERVER_PORT = [string]$settings.Port
$env:STREAMLIT_SERVER_HEADLESS = "true"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
if ($aeCliPath) {
    $env:AE_CLI_PATH = $aeCliPath
}
Repair-AidcPathEnvironment

$arguments = @(
    "-m",
    "streamlit",
    "run",
    "app/dashboard/streamlit_app.py",
    "--server.port",
    [string]$settings.Port,
    "--server.address",
    [string]$settings.ListenAddress,
    "--server.headless",
    "true",
    "--server.runOnSave",
    "true",
    "--server.fileWatcherType",
    "poll",
    "--browser.gatherUsageStats",
    "false"
)

try {
while ($true) {
    if (Test-AidcLocalHealth -Settings $settings) {
        if (-not $observingHealthyEndpoint) {
            Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
                "{0} found an existing healthy endpoint; waiting to take ownership if it stops." -f (Get-Date -Format "s")
            )
            $observingHealthyEndpoint = $true
        }
        Start-Sleep -Seconds 10
        continue
    }
    if ($observingHealthyEndpoint) {
        Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
            "{0} existing endpoint stopped; starting a managed child." -f (Get-Date -Format "s")
        )
        $observingHealthyEndpoint = $false
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

    $pidRecord = @{
        ProcessId                      = $process.Id
        ProcessStartedAtFileTimeUtc    = $process.StartTime.ToFileTimeUtc()
        SupervisorId                   = $PID
        SupervisorStartedAtFileTimeUtc = $supervisorProcess.StartTime.ToFileTimeUtc()
        SupervisorPath                 = $supervisorProcess.Path
        PythonPath                     = $pythonPath
        StartedAtUtc                   = $process.StartTime.ToUniversalTime().ToString("o")
        Port                           = [int]$settings.Port
    }
    Write-AidcPidFileSafely -Path $pidFile -Record $pidRecord

    Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
        "{0} child PID {1} started on {2}:{3}." -f (Get-Date -Format "s"), $process.Id, $settings.ListenAddress, $settings.Port
    )

    $process.WaitForExit()
    $process.Refresh()
    $exitCode = $process.ExitCode
    $exitDisplay = if ($null -eq $exitCode) { "unavailable" } else { [string]$exitCode }
    try {
        $pidRemoved = Remove-AidcPidFileSafely `
            -Path $pidFile `
            -ExpectedProcessId $process.Id
        if (-not $pidRemoved) {
            Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
                "{0} kept PID file because ownership changed after child PID {1} exited." -f (Get-Date -Format "s"), $process.Id
            )
        }
    }
    catch {
        Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
            "{0} PID cleanup failed after child PID {1}: {2}; supervisor will continue." -f (Get-Date -Format "s"), $process.Id, $_.Exception.Message
        )
    }

    Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
        "{0} child PID {1} exited with code {2}; restarting in 10 seconds." -f (Get-Date -Format "s"), $process.Id, $exitDisplay
    )
    Start-Sleep -Seconds 10
}
}
catch {
    try {
        Add-Content -LiteralPath $supervisorLog -Encoding UTF8 -Value (
            "{0} supervisor is exiting after an unexpected error: {1}" -f (Get-Date -Format "s"), $_.Exception.Message
        )
    }
    catch {
        # Preserve the original failure even if the diagnostic log is unavailable.
    }
    throw
}
