[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop", "Restart")]
    [string]$Action,

    [int]$WaitSeconds = 30
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$settings = Get-AidcSettings
$pidFile = Get-AidcPidFile -Settings $settings

function Get-AidcScheduledTask {
    try {
        return Get-ScheduledTask -TaskName $settings.ScheduledTaskName -ErrorAction Stop
    }
    catch [Microsoft.Management.Infrastructure.CimException] {
        if (-not (Test-AidcAdministrator)) {
            throw "Unable to inspect the AIDC scheduled task without Administrator privileges. Reopen PowerShell as Administrator."
        }
        return $null
    }
    catch [System.UnauthorizedAccessException] {
        throw "Unable to inspect the AIDC scheduled task without Administrator privileges. Reopen PowerShell as Administrator."
    }
}

function Wait-AidcHealth {
    param([bool]$ExpectedHealthy)

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        $healthy = Test-AidcLocalHealth -Settings $settings
        if ($healthy -eq $ExpectedHealthy) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-AidcProcessTree {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return
    }

    try {
        $record = Get-Content -LiteralPath $pidFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        if (-not (Test-Path -LiteralPath $pidFile)) {
            return
        }
        throw
    }
    $useSupervisor = $record.PSObject.Properties.Name -contains "SupervisorStartedAtFileTimeUtc"
    $processId = if ($useSupervisor) { [int]$record.SupervisorId } else { [int]$record.ProcessId }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process -and $useSupervisor) {
        # Stop-ScheduledTask may end the supervisor before its Streamlit child.
        # Fall back to the recorded child instead of abandoning an orphan.
        $useSupervisor = $false
        $processId = [int]$record.ProcessId
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    }
    if (-not $process) {
        Remove-AidcPidFileSafely -Path $pidFile | Out-Null
        return
    }

    if ($useSupervisor) {
        $sameStart = [math]::Abs($process.StartTime.ToFileTimeUtc() - [int64]$record.SupervisorStartedAtFileTimeUtc) -lt 30000000
        $expectedPath = [string]$record.SupervisorPath
    }
    elseif ($record.PSObject.Properties.Name -contains "ProcessStartedAtFileTimeUtc") {
        $sameStart = [math]::Abs($process.StartTime.ToFileTimeUtc() - [int64]$record.ProcessStartedAtFileTimeUtc) -lt 30000000
        $expectedPath = [string]$record.PythonPath
    }
    else {
        $recordedStart = [datetime]::Parse(
            [string]$record.StartedAtUtc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        $actualStart = $process.StartTime.ToUniversalTime()
        $sameStart = [math]::Abs(($actualStart - $recordedStart).TotalSeconds) -lt 3
        $expectedPath = [string]$record.PythonPath
    }
    $sameExecutable = $false
    try {
        $sameExecutable = [System.IO.Path]::GetFullPath($process.Path) -eq [System.IO.Path]::GetFullPath($expectedPath)
    }
    catch {
        $sameExecutable = if ($useSupervisor) {
            $process.ProcessName -in @("powershell", "pwsh")
        }
        else {
            $process.ProcessName -in @("python", "pythonw")
        }
    }

    if (-not ($sameStart -and $sameExecutable)) {
        throw "PID file validation failed. Refusing to stop PID $processId because it may no longer belong to AIDC."
    }

    & taskkill.exe /PID $processId /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to stop AIDC process tree $processId. Run this script as Administrator."
    }
    Remove-AidcPidFileSafely -Path $pidFile | Out-Null
}

function Start-Aidc {
    $task = Get-AidcScheduledTask
    if ($task) {
        if ($task.State -ne "Running") {
            Start-ScheduledTask -InputObject $task
        }
    }
    elseif (-not (Test-AidcLocalHealth -Settings $settings)) {
        $runner = Join-Path $PSScriptRoot "run-aidc.ps1"
        $encodedCommand = ConvertTo-AidcEncodedCommand -ScriptPath $runner
        $argumentList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedCommand)
        $logDirectory = Get-AidcLogDirectory -Settings $settings
        Repair-AidcPathEnvironment
        Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList $argumentList `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logDirectory "manual-launch.out.log") `
            -RedirectStandardError (Join-Path $logDirectory "manual-launch.err.log") | Out-Null
    }

    if (Test-AidcLocalHealth -Settings $settings) {
        Write-Host "AIDC is already online and its supervisor is running: $(Get-AidcLocalHealthUri -Settings $settings)"
        return
    }

    if (-not (Wait-AidcHealth -ExpectedHealthy $true)) {
        throw "AIDC did not become healthy within $WaitSeconds seconds. Check logs\deployment."
    }
    Write-Host "AIDC is online: http://$($settings.ListenAddress):$($settings.Port)"
}

function Stop-Aidc {
    $task = Get-AidcScheduledTask
    if ($task -and $task.State -eq "Running") {
        Stop-ScheduledTask -InputObject $task
        Start-Sleep -Seconds 2
    }

    if (Test-Path -LiteralPath $pidFile) {
        Stop-AidcProcessTree
    }

    if (-not (Wait-AidcHealth -ExpectedHealthy $false)) {
        throw "AIDC is still answering on port $($settings.Port)."
    }
    Write-Host "AIDC is stopped."
}

switch ($Action) {
    "Start" { Start-Aidc }
    "Stop" { Stop-Aidc }
    "Restart" {
        Stop-Aidc
        Start-Aidc
    }
}
