<#
.SYNOPSIS
    Snapshot GitHub Copilot session-store.db and upload to Azure Blob.

.DESCRIPTION
    Uses sqlite3 .backup (online-safe) to produce a consistent snapshot of
    %USERPROFILE%\.copilot\session-store.db, then uses azcopy to upload it
    plus a heartbeat file to the agent-sessions container.

.PARAMETER StorageAccount
    Azure Storage account name (e.g. 'agentdashstg'). May also be supplied
    via $env:STORAGE_ACCOUNT.

.PARAMETER Container
    Blob container name. Defaults to 'agent-sessions'.

.NOTES
    Auth: run `azcopy login` (Entra ID device-code) once on the machine.
    Requires sqlite3.exe in PATH (winget install SQLite.SQLite) and azcopy
    in PATH (winget install Microsoft.Azure.AzCopy.10).
#>

[CmdletBinding()]
param(
    [string]$StorageAccount = $env:STORAGE_ACCOUNT,
    [string]$Container = $(if ($env:CONTAINER) { $env:CONTAINER } else { 'agent-sessions' })
)

$ErrorActionPreference = 'Stop'

if (-not $StorageAccount) {
    Write-Error "StorageAccount not provided (param or `$env:STORAGE_ACCOUNT)."
    exit 2
}

$srcDb     = Join-Path $env:USERPROFILE '.copilot\session-store.db'
$snapDb    = Join-Path $env:TEMP       'ghcp-snap.db'
$heartbeat = Join-Path $env:TEMP       'ghcp-heartbeat.txt'
$base      = "https://$StorageAccount.blob.core.windows.net/$Container"

if (-not (Test-Path $srcDb)) {
    Write-Error "Copilot session DB not found at $srcDb"
    exit 3
}

Write-Host "[ghcp-sync] Snapshotting $srcDb -> $snapDb"
& sqlite3.exe $srcDb ".backup '$snapDb'"
if ($LASTEXITCODE -ne 0) {
    Write-Error "sqlite3 .backup failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host "[ghcp-sync] Uploading snapshot to $base/ghcp/snap.db"
& azcopy copy $snapDb "$base/ghcp/snap.db" --overwrite=ifSourceNewer
if ($LASTEXITCODE -ne 0) {
    Write-Error "azcopy copy (snap.db) failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Set-Content -Path $heartbeat -Value $ts -NoNewline
Write-Host "[ghcp-sync] Heartbeat $ts -> $base/heartbeats/ghcp.txt"
& azcopy copy $heartbeat "$base/heartbeats/ghcp.txt" --overwrite=true
if ($LASTEXITCODE -ne 0) {
    Write-Error "azcopy copy (heartbeat) failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host "[ghcp-sync] OK"
exit 0
