#!/usr/bin/env bash
# sync-openclaw.sh — sync OpenClaw JSONL session logs to Azure Blob.
#
# Auth: prefer `azcopy login --identity` (VM Managed Identity); fallback to
#       `azcopy login` (device code) for VMs without MI.
#
# Inputs (env vars):
#   STORAGE_ACCOUNT  (required)
#   CONTAINER        (default: agent-sessions)
#   OPENCLAW_DIR     (default: $HOME/.openclaw/agents/main/sessions)

set -euo pipefail

: "${STORAGE_ACCOUNT:?STORAGE_ACCOUNT must be set}"
CONTAINER="${CONTAINER:-agent-sessions}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw/agents/main/sessions}"

HB=/tmp/openclaw-heartbeat.txt
BASE="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}"

if [[ ! -d "$OPENCLAW_DIR" ]]; then
    echo "[openclaw-sync] ERROR: sessions dir not found at $OPENCLAW_DIR" >&2
    exit 3
fi

echo "[openclaw-sync] Syncing $OPENCLAW_DIR -> $BASE/openclaw/sessions/"
# azcopy sync is incremental: only changed/new *.jsonl files are uploaded.
azcopy sync "$OPENCLAW_DIR" "$BASE/openclaw/sessions/" \
    --recursive \
    --include-pattern='*.jsonl'

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo -n "$TS" > "$HB"
echo "[openclaw-sync] Heartbeat $TS -> $BASE/heartbeats/openclaw.txt"
azcopy copy "$HB" "$BASE/heartbeats/openclaw.txt" --overwrite=true

echo "[openclaw-sync] OK"
