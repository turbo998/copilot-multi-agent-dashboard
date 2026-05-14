# Copilot Multi-Agent Session Dashboard — Azure 部署方案

> **版本：v2（2026-05-14 review 后修订）**
> 修订点：SQLite WAL 一致性、SAS Token 管理、Easy Auth 单用户、冷启动、缓存、同步增量、可观测性、overrides GC、模板迁移预算、schema 漂移防护。

## 1. 目标与场景

把分散在三处的 agent 会话历史统一到一个 Azure 上的网页看板，单用户 + Entra ID 登录，本机电脑/手机浏览器查看。

| 源 | 主机 | 存储 |
|---|---|---|
| GitHub Copilot CLI | 本机 Windows | `%USERPROFILE%\.copilot\session-store.db` (SQLite + FTS5) |
| Hermes Agent | Azure VM (Linux) | `~/.hermes/state.db` (SQLite + FTS5, WAL) |
| OpenClaw | Azure VM (Linux) | `~/.openclaw/agents/main/sessions/*.jsonl` |

## 2. 架构

```
[Win本机]      [hermes-vm]     [openclaw-vm]
   │              │                │
   │ Task Scheduler│  cron 每30m   │  cron 每10m (jsonl增量)
   │ 每30m        │                │
   │              │                │
   │ ① sqlite .backup → snap.db    │  ① 直接 azcopy sync (append-only)
   │ ② azcopy sync (MD5 比对)      │  ② heartbeat 写 blob
   │ ③ heartbeat 写 blob           │
   └──────────────┴────────────────┘
                  ▼
       ┌──────────────────────────────┐
       │ Azure Storage Account (Blob) │
       │  container: agent-sessions    │
       │    ghcp/snap.db              │  ← .backup 出来的快照
       │    hermes/snap.db            │  ← .backup 出来的快照
       │    openclaw/sessions/*.jsonl │
       │    overrides/groups.json     │
       │    overrides/cats.json       │
       │    overrides/hidden.json     │
       │    heartbeats/{ghcp,hermes,openclaw}.txt │
       └──────────────┬───────────────┘
                      │ Managed Identity (读写)
       ┌──────────────▼───────────────┐
       │ Azure Container App (FastAPI)│
       │  • Entra ID Easy Auth        │
       │  • minReplicas=1 (无冷启动)  │
       │  • 磁盘缓存 /tmp + Blob ETag │
       │  • 三个 adapter → 统一模型   │
       │  • 首页显示 heartbeat 状态   │
       └──────────────┬───────────────┘
                      │ HTTPS
                  浏览器（任何地方）
```

## 3. 关键技术决策

| 项 | 选型 | 原因 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn | 原 `http.server` 不利于多源 + 上传 + 鉴权 |
| 计算 | Azure Container Apps，**minReplicas=1** | 单用户冷启动 15–25s 体验差；常驻一份每月 $5–8 可接受 |
| 存储 | Azure Blob Storage (单 Storage Account, 单 container) | 按源用前缀分目录 |
| 身份 | Container App 的 System-Assigned Managed Identity | 读写 Blob 不用密钥 |
| 鉴权 | Container Apps Built-in Auth (Easy Auth) + Entra ID 单租户 + Enterprise App **Assignment required=Yes** | 显式只放行自己 |
| 客户端鉴权 (推送侧) | Windows: `azcopy login` (Entra ID device code，一次)；Linux VM: Managed Identity 或 User Delegation SAS (7天有效期，脚本自动轮换) | 不留长效密钥 |
| SQLite 同步 | `sqlite3 src.db ".backup snap.db"` → `azcopy sync` | WAL 安全；MD5 比对避免无变化全量上传 |
| OpenClaw 同步 | `azcopy sync`（append-only 天然增量） | 简单 |
| 同步频率 | SQLite 30 min；jsonl 10 min | 控成本 + 控带宽 |
| IaC | Bicep + `azd up`，起手 `azd init --template` 找官方 container-app + storage + MI 模板 | 少走弯路 |

## 4. 统一数据模型 `UnifiedSession`

```python
{
  "id": "<source>:<original-id>",      # e.g. "ghcp:9a25c038-..."
  "source": "ghcp" | "hermes" | "openclaw",
  "title": str,
  "created_at": ISO8601,
  "updated_at": ISO8601,
  "turns": int,
  "model": str | None,
  "cwd": str | None,
  "first_user_msg": str,                # ≤ 240 字符
  "body": str,                          # ≤ 8000 字符，用于搜索
  "cat": str,
  "group_id": str | None,
  "hidden": bool,                       # 来自 overrides/hidden.json
}
```

**Schema 漂移防护**：每个 adapter 启动时断言上游 schema 版本（GHCP/Hermes 的 `PRAGMA user_version` 或表结构 hash），不匹配就明确报错而不是静默崩。adapter 单元测试用固定 fixture。

## 5. 工作分解

### Phase 1 — Skeleton & Adapters（本地可运行）
- 建工程结构 `dashboard-azure/`
- 写 FastAPI 应用骨架 `app/main.py`
- 三个 adapter：`adapters/ghcp.py`、`adapters/hermes.py`、`adapters/openclaw.py`
- 每个 adapter 带 schema_version 断言 + pytest fixture
- `models.py` UnifiedSession
- **HTML 模板从 `http.server` 字符串迁移到 Jinja2**——预算 0.5 天，不要按"复用"估
- `templates/index.html` + `templates/space.html` + `templates/session.html`
- 增加 "来源" 过滤 chip（GHCP / Hermes / OpenClaw / 全部）
- **响应式布局**：手机浏览器要能用，单独留 0.5 天调
- 本地用 fake fixture 跑通

### Phase 2 — 存储与缓存层
- `storage.py`：从 Blob 拉 snapshot 到本地 `/tmp`，用 **Blob ETag/If-None-Match** 判断是否需要重新下载（替代固定 5 min TTL）
- 已解析的 `UnifiedSession` 列表缓存为 `/tmp/parsed-{source}.json`，源 blob 没变就直接复用，避免每次重新 parse SQLite
- `overrides.py`：read/write `groups.json` + `cats.json` + `hidden.json` 到 Blob
- 本地连真实 Storage Emulator (Azurite) 测试

### Phase 3 — 写操作改造（**第二迭代**，第一版可先只读 demo）
- `/delete` 改为：写入 `overrides/hidden.json`，下次同步不会再出现
- **GC 任务**：每次同步完成后扫 overrides，把"源里已不存在"的 id 从 hidden/cats/groups 清掉，避免长期膨胀
- `/resume` 改为：返回剪贴板友好的命令字符串（前端复制）
- `/rename`、`/recat`、`/groups/merge` 等：全部写到 Blob overrides

### Phase 4 — Azure 化
- 写 `Dockerfile`（python:3.12-slim + uvicorn）
- `infra/main.bicep`（**起手用 `azd init --template` 找官方模板**）：
  - Storage Account + container
  - Container Apps Environment
  - Container App，**minReplicas=1**（不 scale-to-zero）
  - System-Assigned Managed Identity
  - 角色分配：Storage Blob Data Contributor (App MI → Storage)
- `azure.yaml` + `azd up` 一键部署
- 部署后开启 Easy Auth（Entra ID 单租户）
- **Easy Auth 单用户 checklist（不要漏）**：
  1. App registration 创建后，去 **Enterprise applications → 该 App → Properties**
  2. **Assignment required = Yes**
  3. **Users and groups** 里只加自己
  4. 用别的账号验证一次会被拒

### Phase 5 — 同步脚本
- `scripts/sync-ghcp.ps1`（Windows 本机）
  - `sqlite3 $env:USERPROFILE\.copilot\session-store.db ".backup $env:TEMP\ghcp-snap.db"`
  - `azcopy sync $env:TEMP\ghcp-snap.db https://...blob.../ghcp/snap.db`（首次 `azcopy login`）
  - 写 heartbeat：`azcopy copy <时间戳文件> .../heartbeats/ghcp.txt`
- `scripts/sync-hermes.sh`（hermes VM）
  - `sqlite3 ~/.hermes/state.db ".backup /tmp/hermes-snap.db"`
  - `azcopy sync /tmp/hermes-snap.db https://...blob.../hermes/snap.db`
  - 优先用 VM Managed Identity；否则 User Delegation SAS（7 天，cron 自动轮换）
  - 写 heartbeat
- `scripts/sync-openclaw.sh`（openclaw VM）
  - `azcopy sync ~/.openclaw/agents/main/sessions/ https://...blob.../openclaw/sessions/`（append-only，天然增量）
  - 写 heartbeat
- 三个脚本都要有 `set -e` / `$ErrorActionPreference='Stop'`，失败要么 exit code 非零让 Task Scheduler/cron 报警，要么写一个 `errors/{source}.txt`
- README 中给出 Task Scheduler / cron 配置示例

### Phase 6 — 文档与可观测性
- 顶层 `README.md`：5 分钟部署、3 个源各自配置同步、故障排查
- 一张架构图
- **首页面板顶部显示三源 heartbeat**：读 `heartbeats/{source}.txt`，超过阈值（SQLite 源 >2h，jsonl 源 >30min）标红
- 部署完后跑一次"端到端冒烟"：本机产生一条新对话 → 等下次同步 → 看板能搜到

## 6. 风险与开放问题

- **Hermes/OpenClaw VM 的 SSH 接入信息我目前没有** → 同步脚本写好后用户自己上传并配 cron
- **写操作的"冲突"**：用户改了云端分类，但下次同步只覆盖 DB，不覆盖 overrides。`overrides/*.json` 永远以云端为准；GC 负责清理孤儿条目
- **冷启动**：`minReplicas=1` 已规避；如果后续要省钱再降到 0
- **SAS Token 安全**：Windows 优先 `azcopy login` 不用 SAS；Linux VM 优先 Managed Identity；只在不得已时用 User Delegation SAS + 短有效期 + 脚本轮换

## 7. 目录结构（最终交付）

```
dashboard-azure/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── models.py            # UnifiedSession + schema 断言
│   ├── storage.py           # Blob 拉取 + ETag 缓存 + parsed-cache
│   ├── overrides.py         # 分类/分组/隐藏覆盖 + GC
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── ghcp.py
│   │   ├── hermes.py
│   │   └── openclaw.py
│   ├── templates/
│   │   ├── index.html       # 经典看板（含 heartbeat 状态条）
│   │   ├── session.html     # 详情页
│   │   └── space.html       # 作战空间
│   └── static/              # 含响应式 CSS
├── tests/
│   ├── fixtures/            # 三源各一份固定样本
│   └── test_adapters.py     # schema 漂移检测
├── scripts/
│   ├── sync-ghcp.ps1
│   ├── sync-hermes.sh
│   └── sync-openclaw.sh
├── infra/
│   ├── main.bicep
│   └── main.parameters.json
├── Dockerfile
├── requirements.txt
├── azure.yaml
└── README.md
```

## 8. 修订后优先级（按砍范围顺序）

1. ✅ **Phase 1**（adapters + UnifiedSession + Jinja 模板 + 本地跑通）— 不可砍
2. ✅ **Phase 2 + 4**（Blob + Container App + Easy Auth + minReplicas=1）— 不可砍
3. 🔴 **Phase 5**（`.backup` + `azcopy sync` + heartbeat）— 不可砍
4. 🟡 **Phase 3**（写操作 + overrides + GC）— 第二迭代再做，第一版只读
5. 🟢 **Phase 6**（移动端打磨 + README）— 最后补
