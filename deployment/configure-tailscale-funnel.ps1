[CmdletBinding()]
param(
    [string]$TailscalePath,
    [string]$PublicHostname
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-AidcAdministrator)) {
    throw "Administrator privileges are required. Reopen PowerShell as Administrator and run this script again."
}

$settings = Get-AidcSettings
if (-not (Test-AidcLocalHealth -Settings $settings)) {
    throw "AIDC must be healthy at $(Get-AidcLocalHealthUri -Settings $settings) before enabling Funnel."
}

$addresses = @(Get-AidcListenerAddresses -Port ([int]$settings.Port))
if (-not (Test-AidcLoopbackOnly -Addresses $addresses)) {
    throw "AIDC is not loopback-only (listeners: $($addresses -join ', ')). Restart it with deployment\restart-aidc.bat first."
}

if ([string]::IsNullOrWhiteSpace($TailscalePath)) {
    if ($settings.ContainsKey("TailscalePath") -and (Test-Path -LiteralPath $settings.TailscalePath -PathType Leaf)) {
        $TailscalePath = [string]$settings.TailscalePath
    }
    else {
        $tailscaleCommand = Get-Command tailscale.exe -ErrorAction SilentlyContinue
        if ($tailscaleCommand) {
            $TailscalePath = $tailscaleCommand.Source
        }
    }
}
if ([string]::IsNullOrWhiteSpace($TailscalePath) -or -not (Test-Path -LiteralPath $TailscalePath -PathType Leaf)) {
    throw "tailscale.exe was not found. Install the official Windows client or pass -TailscalePath."
}

$service = Get-Service -Name $settings.TailscaleService -ErrorAction SilentlyContinue
if (-not $service) {
    throw "The Tailscale Windows Service is not installed."
}
Set-Service -Name $settings.TailscaleService -StartupType Automatic
if ($service.Status -ne "Running") {
    Start-Service -Name $settings.TailscaleService
}

& sc.exe failure $settings.TailscaleService "reset=" 86400 "actions=" "restart/5000/restart/15000/restart/60000" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure Tailscale service recovery."
}
& sc.exe failureflag $settings.TailscaleService 1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enable Tailscale service recovery actions."
}

$localTarget = "http://$($settings.ListenAddress):$($settings.Port)"
$funnelOutput = & $TailscalePath funnel --bg $localTarget 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enable Tailscale Funnel: $($funnelOutput -join ' ')"
}

$statusOutput = (& $TailscalePath funnel status 2>&1) -join "`n"
if ($statusOutput -notmatch "Funnel on") {
    throw "Tailscale did not report an active Funnel."
}

if ([string]::IsNullOrWhiteSpace($PublicHostname) -and $statusOutput -match 'https://([^/\s]+)') {
    $PublicHostname = $Matches[1]
}
if (-not [string]::IsNullOrWhiteSpace($PublicHostname)) {
    $PublicHostname = $PublicHostname -replace '^https?://', '' -replace '/.*$', ''
}

Save-AidcMachineSettings -Values @{
    PublicProvider = "Tailscale Funnel"
    PublicHostname = $PublicHostname
    TailscalePath  = $TailscalePath
}

Write-Host "Tailscale Funnel is active and forwards HTTPS to $localTarget."
if (-not [string]::IsNullOrWhiteSpace($PublicHostname)) {
    Write-Host "Public URL: https://$PublicHostname/"
}
Write-Host "The Funnel configuration and Tailscale Windows Service persist across reboots."
