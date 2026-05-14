# Agent Session Sync

The dashboard reads aggregated session data from an Azure Blob container
(`agent-sessions`). Each agent host pushes its own snapshot on a schedule.
The dashboard app itself uses Managed Identity to **read** these blobs.

| Agent     | Source                                                  | Blob path                           |
|-----------|---------------------------------------------------------|-------------------------------------|
| GHCP      | `%USERPROFILE%\.copilot\session-store.db` (Win)         | `ghcp/snap.db`                      |
| Hermes    | `~/.hermes/state.db` (Linux)                            | `hermes/snap.db`                    |
| OpenClaw  | `~/.openclaw/agents/main/sessions/*.jsonl` (Linux)      | `openclaw/sessions/*.jsonl`         |
| (any)     | last-run timestamp                                      | `heartbeats/{ghcp,hermes,openclaw}.txt` |

All three scripts use SQLite's online-safe `.backup` (where applicable) plus
`azcopy` so they can run while the underlying agent is live.

---

## 1. Authentication

### Windows laptop (GHCP)

No Managed Identity available on a personal laptop, so use Entra ID interactive
login. One-time setup:

```powershell
winget install Microsoft.Azure.AzCopy.10
winget install SQLite.SQLite        # provides sqlite3.exe
azcopy login                        # device-code flow, grants user token
```

The signed-in user must have **Storage Blob Data Contributor** on the storage
account (or at least the container).

### Linux VM (Hermes / OpenClaw)

Preferred: enable a **system-assigned Managed Identity** on the VM and grant it
**Storage Blob Data Contributor**. Then:

```bash
azcopy login --identity
```

Fallback (no MI, e.g. dev box): `azcopy login` (device code) or generate a
short-lived **User Delegation SAS** and append it to the destination URL.

Install:

```bash
# azcopy
curl -sL https://aka.ms/downloadazcopy-v10-linux | tar -xz --strip-components=1 -C /usr/local/bin azcopy_linux_amd64_*/azcopy
# sqlite3 (Hermes only)
sudo apt-get install -y sqlite3
```

---

## 2. Scheduling

### Windows — Task Scheduler (every 30 min)

One-line registration:

```powershell
schtasks /Create /SC MINUTE /MO 30 /TN "AgentDash\SyncGHCP" /TR `
    "powershell -NoProfile -ExecutionPolicy Bypass -File C:\agentdash\sync-ghcp.ps1 -StorageAccount agentdashstg" `
    /RL LIMITED /F
```

Equivalent XML (`schtasks /Create /XML sync-ghcp-task.xml /TN ...`):

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Repetition>
        <Interval>PT30M</Interval>
      </Repetition>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File C:\agentdash\sync-ghcp.ps1 -StorageAccount agentdashstg</Arguments>
    </Exec>
  </Actions>
</Task>
```

### Linux — cron (every 30 min)

```cron
*/30 * * * * STORAGE_ACCOUNT=agentdashstg /home/azureuser/sync-hermes.sh   >> /var/log/agentdash-sync.log 2>&1
*/30 * * * * STORAGE_ACCOUNT=agentdashstg /home/azureuser/sync-openclaw.sh >> /var/log/agentdash-sync.log 2>&1
```

Make sure `/var/log/agentdash-sync.log` is writable by the cron user, or write
to `~/agentdash-sync.log` instead.

---

## 3. Troubleshooting

**`azcopy: command not found` / `sqlite3.exe was not recognized`**
Installer didn't put the binary on PATH. Re-open the shell after `winget`, or
add `C:\Program Files\AzCopy` (Win) / `/usr/local/bin` (Linux) to PATH.

**`AuthorizationPermissionMismatch` / `403 AuthenticationFailed`**
Token is valid but the principal lacks **Storage Blob Data Contributor** on the
container. Run `azcopy login status`. On Linux MI, confirm with
`curl -H Metadata:true 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://storage.azure.com/'`.
On Windows, re-run `azcopy login` (token may have expired).

**`database is locked`**
Should not happen — we use `sqlite3 .backup` which is online-safe and works
against a live WAL-mode database. If it does occur, the writing agent likely
holds an exclusive transaction; retry in a few seconds. Do **not** copy
`state.db` directly with `cp`/`azcopy` — always go through `.backup`.

**Heartbeat stale on dashboard**
Dashboard considers an agent "down" when `heartbeats/<agent>.txt` is older than
~2× the cron interval. Check the cron/Task Scheduler log first; then re-run
the script manually to confirm auth still works.

**OpenClaw JSONL not appearing**
`azcopy sync` only re-uploads files whose mtime/size changed. If JSONL files
are append-only, mtime updates on append, so they will sync. Verify with
`azcopy sync ... --dry-run`.
