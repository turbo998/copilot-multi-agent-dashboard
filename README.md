# Copilot Multi-Agent Session Dashboard

聚合 GHCP CLI (Win)、Hermes (Azure VM)、OpenClaw (Azure VM) 三源会话快照，FastAPI + Jinja 看板，部署在 Azure Container Apps（新加坡）。

## 架构

```
[GHCP Win]  ──sync-ghcp.ps1──┐
[Hermes VM] ──sync-hermes.sh─┼──> Azure Blob (agent-sessions/)
[OpenClaw]  ──sync-openclaw.sh┘                │
                                               │ pull on startup + 60s
                                               ▼
                                   FastAPI (Container Apps SG)
                                               │
                                               │ Easy Auth (Entra ID)
                                               ▼
                                       https://agentdash-app...
```

- **存储**：Azure Storage Blob，container `agent-sessions/`，按 source 分目录。
- **同步**：客户端脚本带 `.backup` 防破坏，`azcopy sync` 增量上传，写 `heartbeat/<source>.json`。
- **运行**：Container App 启动时从 Blob 拉快照到本地，每 60s 增量重拉；用户请求走本地缓存。
- **Auth**：System-assigned Managed Identity → Storage Blob Data Reader（Bicep 已配）。

## 当前部署

- RG: `rg-agent-dashboard-sg` @ southeastasia
- ACR: `acragentdash50568.azurecr.io`
- Storage: `stagentdashvofwui` / container `agent-sessions`
- App URL: https://agentdash-app.proudplant-8d61f177.southeastasia.azurecontainerapps.io

## 部署流程

```bash
# 1. 准备 RG + ACR（一次性）
az group create -n rg-agent-dashboard-sg -l southeastasia
ACR=acragentdash$(date +%s | tail -c 6)
az acr create -g rg-agent-dashboard-sg -n $ACR -l southeastasia --sku Basic --admin-enabled true

# 2. Build & push 镜像
az acr build -r $ACR --image dashboard:v1 --file Dockerfile .

# 3. Bicep 部署其余资源
az deployment group create -g rg-agent-dashboard-sg -n main2 \
  -f infra/main.bicep \
  -p prefix=agentdash acrName=$ACR \
     containerImage=$ACR.azurecr.io/dashboard:v1 \
     minReplicas=1 maxReplicas=2
```

## 配置 Easy Auth（必须手动，需 Entra ID 管理员或开放注册）

VM 的 Managed Identity 没有 Graph 权限创建 App Registration，请在浏览器完成：

1. **Azure Portal → Entra ID → App registrations → New registration**
   - Name: `AgentDashboard-EasyAuth`
   - Supported account types: Accounts in this organizational directory only (Single tenant)
   - Redirect URI: Web → `https://agentdash-app.proudplant-8d61f177.southeastasia.azurecontainerapps.io/.auth/login/aad/callback`
   - 创建后，记下 **Application (client) ID**
2. **Certificates & secrets → New client secret** → 记下 **Value**（只显示一次）
3. **Enterprise applications → AgentDashboard-EasyAuth → Properties**
   - Assignment required = **Yes**
   - **Users and groups** → 加你自己（实现单用户）
4. **回到 Container App `agentdash-app` → Authentication → Add identity provider**
   - Provider: Microsoft
   - App registration: 选 existing → 填上面的 client ID + secret
   - Restrict access: **Require authentication**
   - Unauthenticated requests: HTTP 302 redirect → Microsoft

## 同步脚本

见 `docs/sync.md`。三源各自一个脚本，跑在数据所在主机：

- **Win + GHCP**：定时任务跑 `scripts/sync-ghcp.ps1`
- **Hermes VM**：cron 跑 `scripts/sync-hermes.sh`
- **OpenClaw VM**：cron 跑 `scripts/sync-openclaw.sh`

每个脚本都会写 `heartbeat/<source>.json`，看板首页状态条会显示 lag。

## 本地开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                                   # 49 tests
AGENTDASH_AUTOSTART=1 AGENTDASH_LOCAL_STORE=./local-data \
  uvicorn app.main:app --reload
```

## 测试

49 个单元 + 集成测试（pytest）。
