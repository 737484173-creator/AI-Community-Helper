[CmdletBinding()]
param(
    [string]$CloudflaredPath,
    [string]$PublicHostname,
    [switch]$UseClipboard
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-AidcAdministrator)) {
    throw "Administrator privileges are required. Reopen PowerShell as Administrator and run this script again."
}

$settings = Get-AidcSettings
if (-not (Test-AidcLocalHealth -Settings $settings)) {
    throw "AIDC must be healthy at $(Get-AidcLocalHealthUri -Settings $settings) before installing the tunnel service."
}
$addresses = @(Get-AidcListenerAddresses -Port ([int]$settings.Port))
if (-not (Test-AidcLoopbackOnly -Addresses $addresses)) {
    throw "AIDC is not loopback-only (listeners: $($addresses -join ', ')). Restart it with deployment\restart-aidc.bat first."
}

if ([string]::IsNullOrWhiteSpace($CloudflaredPath)) {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($command) {
        $CloudflaredPath = $command.Source
    }
    else {
        $projectCopy = Join-Path (Get-AidcProjectRoot) "tools\cloudflared.exe"
        if (Test-Path -LiteralPath $projectCopy) {
            $CloudflaredPath = $projectCopy
        }
    }
}
if ([string]::IsNullOrWhiteSpace($CloudflaredPath) -or -not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
    throw "cloudflared.exe was not found. Install it or pass -CloudflaredPath."
}

$existingService = Get-Service -Name $settings.CloudflaredService -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "The cloudflared service already exists; preserving its Tunnel registration."
}

if (-not $existingService) {
    $clipboardText = $null
    if ($UseClipboard) {
        $clipboardText = Get-Clipboard -Raw
        if ($clipboardText -notmatch '(?<![A-Za-z0-9._-])(eyJ[A-Za-z0-9._-]+)') {
            throw "The clipboard does not contain a Cloudflare Tunnel Token."
        }
        $secureToken = ConvertTo-SecureString $Matches[1] -AsPlainText -Force
    }
    else {
        Write-Host "Paste only the eyJ... Tunnel Token from Cloudflare. Input is hidden and is never written to this project."
        $secureToken = Read-Host "Tunnel Token" -AsSecureString
    }
    $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        if ([string]::IsNullOrWhiteSpace($plainToken)) {
            throw "Tunnel Token cannot be empty."
        }
        & $CloudflaredPath service install $plainToken
        if ($LASTEXITCODE -ne 0) {
            throw "cloudflared service install failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        if ($tokenPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
        }
        Remove-Variable plainToken -ErrorAction SilentlyContinue
        Remove-Variable secureToken -ErrorAction SilentlyContinue
        if ($UseClipboard) {
            Set-Clipboard -Value " "
            Remove-Variable clipboardText -ErrorAction SilentlyContinue
        }
    }
}
elseif ($UseClipboard) {
    Set-Clipboard -Value " "
}

Set-Service -Name $settings.CloudflaredService -StartupType Automatic
& sc.exe failure $settings.CloudflaredService "reset=" 86400 "actions=" "restart/5000/restart/15000/restart/60000" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure cloudflared service recovery."
}
& sc.exe failureflag $settings.CloudflaredService 1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enable cloudflared recovery actions."
}
Start-Service -Name $settings.CloudflaredService

if (-not [string]::IsNullOrWhiteSpace($PublicHostname)) {
    $normalizedHost = $PublicHostname -replace '^https?://', '' -replace '/.*$', ''
    Save-AidcMachineSettings -Values @{ PublicHostname = $normalizedHost }
}

$service = Get-Service -Name $settings.CloudflaredService
Write-Host "cloudflared Windows Service installed. Status: $($service.Status); Startup: Automatic."
