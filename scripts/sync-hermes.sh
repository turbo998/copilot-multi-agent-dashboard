#!/usr/bin/env bash
# sync-hermes.sh — snapshot Hermes state.db and upload to Azure Blob.
#
# Auth: prefer `azcopy login --identity` (VM Managed Identity); fallback to
#       `azcopy login` (device code) for VMs without MI.
#
# Inputs (env vars):
#   STORAGE_ACCOUNT  (required) — e.g. agentdashstg
#   CONTAINER        (default: agent-sessions)
#   HERMES_DB        (default: $HOME/.hermes/state.db)

set -euo pipefail

: "${STORAGE_ACCOUNT:?STORAGE_ACCOUNT must be set}"
CONTAINER="${CONTAINER:-agent-sessions}"
HERMES_DB="${HERMES_DB:-$HOME/.hermes/state.db}"

SNAP=/tmp/hermes-snap.db
HB=/tmp/hermes-heartbeat.txt
BASE="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}"

if [[ ! -f "$HERMES_DB" ]]; then
    echo "[hermes-sync] ERROR: Hermes DB not found at $HERMES_DB" >&2
    exit 3
fi

echo "[hermes-sync] Snapshotting $HERMES_DB -> $SNAP"
sqlite3 "$HERMES_DB" ".backup '$SNAP'"

echo "[hermes-sync] Uploading snapshot to $BASE/hermes/snap.db"
azcopy copy "$SNAP" "$BASE/hermes/snap.db" --overwrite=ifSourceNewer

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo -n "$TS" > "$HB"
echo "[hermes-sync] Heartbeat $TS -> $BASE/heartbeats/hermes.txt"
azcopy copy "$HB" "$BASE/heartbeats/hermes.txt" --overwrite=true

echo "[hermes-sync] OK"
