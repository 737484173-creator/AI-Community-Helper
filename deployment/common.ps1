Set-StrictMode -Version Latest

function Get-AidcProjectRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Get-AidcSettings {
    $settingsPath = Join-Path $PSScriptRoot "settings.json"
    $settingsObject = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $settings = @{}
    foreach ($property in $settingsObject.PSObject.Properties) {
        $settings[$property.Name] = $property.Value
    }
    $machineSettingsPath = Join-Path $PSScriptRoot "machine-settings.json"

    if (Test-Path -LiteralPath $machineSettingsPath) {
        $machineSettings = Get-Content -LiteralPath $machineSettingsPath -Raw | ConvertFrom-Json
        foreach ($property in $machineSettings.PSObject.Properties) {
            $settings[$property.Name] = $property.Value
        }
    }

    return $settings
}

function Save-AidcMachineSettings {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Values
    )

    $machineSettingsPath = Join-Path $PSScriptRoot "machine-settings.json"
    $current = @{}
    if (Test-Path -LiteralPath $machineSettingsPath) {
        $existing = Get-Content -LiteralPath $machineSettingsPath -Raw | ConvertFrom-Json
        foreach ($property in $existing.PSObject.Properties) {
            $current[$property.Name] = $property.Value
        }
    }
    foreach ($key in $Values.Keys) {
        if ($null -eq $Values[$key] -or [string]::IsNullOrWhiteSpace([string]$Values[$key])) {
            $current.Remove($key)
        }
        else {
            $current[$key] = $Values[$key]
        }
    }

    $current | ConvertTo-Json | Set-Content -LiteralPath $machineSettingsPath -Encoding UTF8
}

function Test-AidcAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-AidcEncodedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    $escapedPath = $ScriptPath.Replace("'", "''")
    $command = "& '$escapedPath'"
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
}

function Repair-AidcPathEnvironment {
    $pathKeys = @(
        [Environment]::GetEnvironmentVariables().Keys |
            Where-Object { [string]$_ -ieq "Path" }
    )
    if ($pathKeys.Count -le 1) {
        return
    }

    # Some agent shells inherit both PATH and Path. Windows PowerShell 5.1
    # cannot launch a child process until the duplicate key is normalized.
    $pathValue = $env:PATH
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

function Resolve-AidcPython {
    param(
        [string]$RequestedPath,
        [hashtable]$Settings = (Get-AidcSettings)
    )

    $projectRoot = Get-AidcProjectRoot
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @(
        $RequestedPath,
        $env:AIDC_PYTHON,
        (Join-Path $projectRoot ".venv\Scripts\python.exe"),
        $Settings["PythonPath"]
    )) {
        if (-not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            $candidates.Add([string]$candidate)
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notlike "*\WindowsApps\python.exe") {
        $candidates.Add($pythonCommand.Source)
    }

    $runtimeRoot = Join-Path $env:SystemDrive "Users\Administrator\.cache\codex-runtimes"
    if (Test-Path -LiteralPath $runtimeRoot) {
        Get-ChildItem -LiteralPath $runtimeRoot -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\dependencies\python\python.exe" } |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        try {
            & $candidate -c "import streamlit" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
        catch {
            continue
        }
    }

    throw "No Python runtime with Streamlit was found. Pass -PythonPath to install-aidc-autostart.ps1."
}

function Resolve-AidcAeCli {
    param(
        [string]$RequestedPath,
        [hashtable]$Settings = (Get-AidcSettings)
    )

    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @(
        $RequestedPath,
        $env:AIDC_AE_CLI,
        $Settings["AeCliPath"]
    )) {
        if (-not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            $candidates.Add([string]$candidate)
        }
    }

    foreach ($commandName in @("ae-cli.cmd", "ae-cli.exe", "ae-cli.bat")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $candidates.Add([string]$command.Source)
        }
    }

    # The dashboard normally runs as SYSTEM, whose APPDATA and USERPROFILE do
    # not point at the interactive user's global npm directory. Discover the
    # standard per-user npm shim locations once and persist the absolute path.
    $usersRoot = Join-Path $env:SystemDrive "Users"
    if (Test-Path -LiteralPath $usersRoot -PathType Container) {
        Get-ChildItem -LiteralPath $usersRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                foreach ($filename in @("ae-cli.cmd", "ae-cli.exe", "ae-cli.bat")) {
                    $candidates.Add((Join-Path $_.FullName "AppData\Roaming\npm\$filename"))
                }
            }
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($candidate in $candidates) {
        if (-not $seen.Add($candidate)) {
            continue
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Get-AidcLogDirectory {
    param([hashtable]$Settings = (Get-AidcSettings))

    $path = Join-Path (Get-AidcProjectRoot) $Settings.LogDirectory
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    return $path
}

function Get-AidcPidFile {
    param([hashtable]$Settings = (Get-AidcSettings))

    return Join-Path (Get-AidcLogDirectory -Settings $Settings) $Settings.PidFileName
}

function Write-AidcPidFileSafely {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [hashtable]$Record
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporaryPath = Join-Path $directory (".{0}.{1}.tmp" -f ([System.IO.Path]::GetFileName($Path)), [guid]::NewGuid().ToString("N"))
    try {
        $Record | ConvertTo-Json | Set-Content -LiteralPath $temporaryPath -Encoding UTF8 -ErrorAction Stop
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force -ErrorAction Stop
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Remove-AidcPidFileSafely {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Nullable[int]]$ExpectedProcessId
    )

    try {
        if ($PSBoundParameters.ContainsKey("ExpectedProcessId")) {
            $record = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if (-not ($record.PSObject.Properties.Name -contains "ProcessId")) {
                throw "PID file does not contain ProcessId: $Path"
            }
            if ([int]$record.ProcessId -ne [int]$ExpectedProcessId) {
                return $false
            }
        }

        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        return $true
    }
    catch {
        # Stop/restart controls and the supervisor may race to remove the same
        # PID file. A file that is already gone is the desired end state.
        if (-not (Test-Path -LiteralPath $Path)) {
            return $true
        }
        throw
    }
}

function Get-AidcLocalHealthUri {
    param([hashtable]$Settings = (Get-AidcSettings))

    return "http://$($Settings.ListenAddress):$($Settings.Port)$($Settings.HealthPath)"
}

function Test-AidcLocalHealth {
    param(
        [hashtable]$Settings = (Get-AidcSettings),
        [int]$TimeoutSec = 4
    )

    try {
        $response = Invoke-WebRequest -Uri (Get-AidcLocalHealthUri -Settings $Settings) -UseBasicParsing -TimeoutSec $TimeoutSec
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Get-AidcListenerAddresses {
    param([int]$Port)

    try {
        return @(
            Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
                Select-Object -ExpandProperty LocalAddress -Unique
        )
    }
    catch {
        $pattern = "^\s*TCP\s+(\S+):$Port\s+\S+\s+LISTENING\s+\d+\s*$"
        return @(
            netstat.exe -ano -p TCP |
                ForEach-Object {
                    if ($_ -match $pattern) { $Matches[1].Trim('[', ']') }
                } |
                Where-Object { $_ } |
                Sort-Object -Unique
        )
    }
}

function Test-AidcLoopbackOnly {
    param([string[]]$Addresses)

    if (-not $Addresses -or $Addresses.Count -eq 0) {
        return $false
    }
    foreach ($address in $Addresses) {
        if ($address -eq "::1" -or $address -like "127.*") {
            continue
        }
        return $false
    }
    return $true
}
