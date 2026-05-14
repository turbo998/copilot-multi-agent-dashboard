# Copilot Multi-Agent Session Dashboard

Unified web dashboard aggregating session histories from:
- **GitHub Copilot CLI** (`%USERPROFILE%\.copilot\session-store.db`)
- **Hermes Agent** (`~/.hermes/state.db`)
- **OpenClaw** (`~/.openclaw/agents/main/sessions/*.jsonl`)

Hosted on Azure Container Apps, single-user with Entra ID auth. See `plan.md` for full design.

## Status
🚧 Under active development. See [plan.md](./plan.md) for architecture and roadmap.

## Quick links
- Architecture & decisions: [plan.md](./plan.md)
- Local dev: see `docs/local-dev.md` (TBD)
- Deploy: `azd up` from repo root (TBD)
