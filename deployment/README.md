# AIDC public deployment (Windows + Tailscale Funnel)

This folder contains deployment-only automation. It does not change AIDC business code.

## Active architecture

```text
Internet client
  -> https://aidc-workbench.tail1e4e55.ts.net
  -> Tailscale Funnel relay
  -> encrypted outbound Tailscale connection
  -> http://127.0.0.1:8502
  -> AIDC Streamlit workbench
```

No router port-forwarding or Windows inbound firewall rule is required. AIDC remains bound to `127.0.0.1`.

## AIDC startup and recovery

Manual controls:

```text
deployment\start-aidc.bat
deployment\stop-aidc.bat
deployment\restart-aidc.bat
```

Install or repair automatic startup from an Administrator PowerShell:

```powershell
Set-Location "D:\Codex-AI Community Helper"
.\deployment\install-aidc-autostart.ps1
```

This registers the `AIDC Workbench` scheduled task as `SYSTEM` at Windows startup. The supervisor restarts the Dashboard child process after 10 seconds; Task Scheduler retries the supervisor every minute.

The installer also discovers the current `ae-cli.cmd` path and stores its absolute path in the
Git-ignored machine settings. This is required because the SYSTEM account does not inherit the
interactive user's global npm directory. To override discovery, pass
`-AeCliPath "C:\path\to\ae-cli.cmd"` when repairing the task.

## Tailscale Funnel configuration

The official Tailscale Windows client installs the `Tailscale` service. After signing in and approving Funnel for the tailnet, run this from an Administrator PowerShell:

```powershell
Set-Location "D:\Codex-AI Community Helper"
.\deployment\configure-tailscale-funnel.ps1
```

The script verifies that AIDC is healthy and loopback-only, configures HTTPS Funnel to proxy `http://127.0.0.1:8502`, sets the Tailscale service to Automatic, enables service recovery, and stores only non-secret machine settings in the Git-ignored `deployment\machine-settings.json`.

Funnel's background configuration persists across Windows and Tailscale restarts. The stable public URL is:

```text
https://aidc-workbench.tail1e4e55.ts.net/
```

Check or disable it from an Administrator terminal:

```powershell
& "C:\Program Files\Tailscale\tailscale.exe" funnel status
& "C:\Program Files\Tailscale\tailscale.exe" funnel --https=443 off
```

## End-to-end verification

```powershell
.\deployment\health-check.ps1 -RequireTunnel
```

Expected values include `LocalHealthy = True`, `LoopbackOnly = True`, `TunnelStatus = Running`, and `PublicHealthy = True`.

Useful Windows checks:

```powershell
Get-ScheduledTask -TaskName "AIDC Workbench"
Get-ScheduledTaskInfo -TaskName "AIDC Workbench"
Get-Service Tailscale
& "C:\Program Files\Tailscale\tailscale.exe" funnel status
netstat -ano -p TCP | findstr :8502
```

## Reboot troubleshooting order

1. Confirm Windows has internet access and the system time is correct.
2. Run `deployment\health-check.ps1`; AIDC must be healthy and loopback-only first.
3. Check the `AIDC Workbench` task and `logs\deployment\aidc-*.err.log`.
4. Check that the `Tailscale` service is Running and the device is signed in.
5. Run `tailscale funnel status` as Administrator; it must show `Funnel on` and the `127.0.0.1:8502` proxy.
6. Test `https://aidc-workbench.tail1e4e55.ts.net/_stcore/health` from a different network. Public DNS changes can take up to 10 minutes after first enabling Funnel.
7. After a Windows or Tailscale service restart, allow roughly two minutes for the Funnel relays to reconnect before treating the public check as failed.
8. If local health still works but public health remains unavailable, rerun `configure-tailscale-funnel.ps1`.

## Cloudflare rollback option

The previous remotely managed Cloudflare Tunnel and `deployment\install-cloudflare-service.ps1` are intentionally retained for rollback. Do not run Cloudflare and Tailscale as competing public routes unless both are deliberately managed. The Cloudflare service may be disabled after the Tailscale public URL is verified; no tunnel credentials are stored in this repository.

## Security notes

- Funnel makes the AIDC login page reachable by anyone who knows or discovers the URL. Keep `DASHBOARD_PASSWORD` strong and unique.
- Funnel is still a beta feature and has non-configurable bandwidth limits.
- The public certificate name is recorded in Certificate Transparency logs and cannot be removed from those logs.
- Funnel hides the local machine's public IP and does not require an inbound port rule.
- Never add authentication keys, API keys, tunnel tokens, certificates, credential JSON, or service registry exports to Git.
