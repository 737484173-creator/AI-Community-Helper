[CmdletBinding()]
param(
    [string]$PublicHostname,
    [switch]$RequireTunnel,
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "common.ps1")

$settings = Get-AidcSettings
if ([string]::IsNullOrWhiteSpace($PublicHostname) -and $settings.ContainsKey("PublicHostname")) {
    $PublicHostname = [string]$settings.PublicHostname
}
$publicProvider = if ($settings.ContainsKey("PublicProvider")) {
    [string]$settings.PublicProvider
}
else {
    "Tailscale Funnel"
}

$localUri = Get-AidcLocalHealthUri -Settings $settings
$localHealthy = Test-AidcLocalHealth -Settings $settings
$listenerAddresses = @(Get-AidcListenerAddresses -Port ([int]$settings.Port))
$loopbackOnly = Test-AidcLoopbackOnly -Addresses $listenerAddresses

$tunnelServiceName = if ($publicProvider -eq "Cloudflare Tunnel") {
    [string]$settings.CloudflaredService
}
else {
    [string]$settings.TailscaleService
}
$service = Get-Service -Name $tunnelServiceName -ErrorAction SilentlyContinue
$tunnelInstalled = $null -ne $service
$tunnelRunning = $tunnelInstalled -and $service.Status -eq "Running"

$publicChecked = -not [string]::IsNullOrWhiteSpace($PublicHostname)
$publicHealthy = $false
$publicStatus = $null
if ($publicChecked) {
    $normalizedHost = $PublicHostname -replace '^https?://', '' -replace '/.*$', ''
    try {
        $publicResponse = Invoke-WebRequest -Uri "https://$normalizedHost$($settings.HealthPath)" -UseBasicParsing -TimeoutSec 12
        $publicStatus = $publicResponse.StatusCode
        $publicHealthy = $publicStatus -eq 200
    }
    catch {
        # curl.exe is a useful fallback on Windows when Invoke-WebRequest's
        # Schannel negotiation fails during initial certificate propagation.
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            $curlStatus = & $curl.Source `
                --fail `
                --silent `
                --show-error `
                --location `
                --max-time 20 `
                --output NUL `
                --write-out "%{http_code}" `
                "https://$normalizedHost$($settings.HealthPath)" 2>$null
            if ($LASTEXITCODE -eq 0 -and [string]$curlStatus -eq "200") {
                $publicStatus = 200
                $publicHealthy = $true
            }
            else {
                $publicStatus = $_.Exception.Message
            }
        }
        else {
            $publicStatus = $_.Exception.Message
        }
    }
}

$result = [pscustomobject]@{
    CheckedAt         = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    LocalUrl          = $localUri
    LocalHealthy      = $localHealthy
    ListenerAddresses = @($listenerAddresses)
    LoopbackOnly      = $loopbackOnly
    TunnelProvider    = $publicProvider
    TunnelService     = $tunnelServiceName
    TunnelInstalled   = $tunnelInstalled
    TunnelStatus      = if ($tunnelInstalled) { [string]$service.Status } else { "NotInstalled" }
    PublicHostname    = $PublicHostname
    PublicChecked     = $publicChecked
    PublicHealthy     = $publicHealthy
    PublicStatus      = $publicStatus
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 4
}
else {
    $result | Format-List
}

$failed = -not $localHealthy -or -not $loopbackOnly
if ($RequireTunnel -and -not $tunnelRunning) {
    $failed = $true
}
if ($publicChecked -and -not $publicHealthy) {
    $failed = $true
}
if ($failed) { exit 1 }
exit 0
