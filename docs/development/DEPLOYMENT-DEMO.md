# 面试演示部署方案（单台 Linux）

本轮为**部署前审计与方案设计**，未购买服务器、未开放公网、未调用任何供应商 API。
所有资源数字都给出可核对依据；无法确认的项目明确标注。

## 一、组件与依赖清单

| 组件 | 形态 | 依赖 | 备注 |
|---|---|---|---|
| API（FastAPI + uvicorn） | 宿主进程或容器 | PostgreSQL、MinIO、ClamAV、Parser 镜像 | 入口 `python -m bidding_compliance.api`；`scripts/start.ps1` 仅 Windows，Linux 需等价命令 |
| 前端（React + Vite） | 静态产物 | 无 | 构建产物 `dist/`：JS 348 KB + CSS 18 KB，可由 nginx 直接托管 |
| PostgreSQL 16 | 容器 | 数据卷 | 业务数据 + Alembic 迁移 + **LangGraph checkpoint**（`AsyncPostgresSaver`，`review_engine.py:345` 明确要求 PostgreSQL） |
| MinIO | 容器 | 数据卷 | 上传对象存储（S3 兼容） |
| ClamAV | 容器 | 病毒库更新 | 装配时显式 `--memory=3g`（`run_task0011_e2e.py:517`） |
| 隔离 Parser | 一次性容器 | `bidding-parser:<tag>` 镜像 | `python:3.12-slim` + tesseract(chi_sim) + 15 个解析依赖；**无数据库/模型密钥** |
| 模型网关 | API 内 | 无（默认关闭） | 演示若不开真实模型，则不需要任何供应商凭据 |

## 二、资源测算（含依据）

**内存是唯一硬约束**，依据是各进程/容器的实际需求：

| 项目 | 内存 | 依据 |
|---|---|---|
| ClamAV | **3 GB** | 仓库装配代码显式限制 `--memory=3g`；官方镜像加载病毒库到内存 |
| PostgreSQL 16 | ~300 MB | 演示数据量（单项目、几十 KB 标书） |
| MinIO | ~150 MB | 单桶、单对象 |
| FastAPI（含 LangGraph） | ~400 MB | 单进程 Python + 编排图 |
| 操作系统 + Docker 引擎 | ~600 MB | 典型最小发行版 |
| **合计（同时常驻）** | **≈ 4.45 GB** | |

**结论**：

- **最低配置：2 vCPU / 6 GB RAM / 40 GB SSD**。4 GB **不足**（ClamAV 一项即 3 GB，加上其余组件已超过 4 GB，会触发 OOM 杀掉解析或数据库）。
- **推荐配置：2 vCPU / 8 GB RAM / 60 GB SSD**，理由：解析大文件时 Parser 容器与 ClamAV 同时占用峰值；留出 30% 余量避免 OOM。
- **并发演示（2–3 人同时操作）：4 vCPU / 8 GB**。CPU 只在解析与 PDF 渲染时短暂打满，2 vCPU 可用但会排队。

**磁盘依据**：镜像合计约 3 GB（slim ~150 MB、postgres:16 ~400 MB、minio ~200 MB、clamav ~1.5 GB、parser ~800 MB）；数据与日志在演示规模下 < 1 GB。40 GB 可用，60 GB 更稳妥。**未实测**各镜像在本机的确切层大小，因此按官方镜像典型值估算，部署时可用 `docker system df` 核对。

## 三、数据卷与重启恢复（当前缺口）

**现状核实**：`run_task0011_e2e.py` 的容器装配**没有挂载任何卷**，数据写在容器可写层。这意味着**容器删除即数据丢失**（TASK-0023 的真实运行数据库正是这样丢失的）。

**部署必须补齐的卷**：

| 卷 | 挂载点 | 作用 |
|---|---|---|
| `pgdata` | `/var/lib/postgresql/data` | 业务数据 + 迁移 + **checkpoint** |
| `miniodata` | `/data` | 上传对象 |
| `clamdb` | `/var/lib/clamav` | 病毒库（避免每次重启重新下载） |
| `api-runtime` | 宿主目录 | 对象存储本地根、模型账本与审计（若使用） |

**重启恢复能力**：

- PostgreSQL / MinIO / ClamAV：有卷即自动恢复 ✓
- **LangGraph checkpoint 在 PostgreSQL 内** → 中断的审查可在同一 `run_id` 继续（TASK-0023 已验证 resume 行为）✓
- **无卷时**：重启后除镜像外一切丢失，包括已迁移的表结构与已上传标书 ✗
- **未验证**：卷的备份/恢复演练与崩溃一致性（本轮不做，列为实施步骤）

## 四、短期面试演示的安全配置

| 项目 | 建议 |
|---|---|
| **演示数据** | 只用**合成标书**（`scripts/generate_demo_fixture.py`，SHA 已登记）。**不上传任何真实标书**；真实天津地铁文件仅留在开发机私有目录 |
| **演示账号** | 由 `manage_identity.py` 引导创建一次性账号，密码随机、演示后删除；不共用管理员账号 |
| **HTTPS** | 反代终结 TLS（Caddy 自动证书最省事，或 nginx + Let's Encrypt）。**API 与 UI 都只监听 127.0.0.1，由反代对外** |
| **访问限制** | 四层：云安全组仅开 443（+ 临时 22 限本人 IP）；反代加 Basic Auth 或一次性令牌；应用层登录鉴权；`APP_ENV` 非 development |
| **供应商调用** | **默认关闭真实模型**。若不设 `DASHSCOPE_API_KEY`／`BAILIAN_WORKSPACE_ID`，真实路由装配即失败关闭，不会产生任何外部调用与费用 |
| **不发送** | 不上传真实招标文件、个人信息、密钥；`.env` 不入库，仅通过环境变量注入 |
| **审计** | 保留 `model-audit.jsonl` 与账本（若启用真实模型）；页面不暴露内部路径 |
| **演示后** | 关闭实例或停止容器、删除演示账号、清理演示数据 |

## 五、合成标书端到端可演示性

**已在本机验证过的链路**（TASK-0023／TASK-0024）：上传 → ClamAV 扫描 → 隔离解析 → 质量检查 →
上下文确认 → Skills → 风险发现 → 融合 → 法规检索 → 证据核验 → 人工复核 → 结果发布 → Word/PDF 生成与下载。
下载文件的 SHA-256 与服务端 `content_hash` 一致。

**部署后需要重新确认的两点**：

1. **Parser 镜像必须随部署一起构建**（`Dockerfile.parser`，固定基础镜像 digest），否则解析步骤会因缺镜像失败。
2. **ClamAV 病毒库必须可更新**：`CLAMD_MAX_DATABASE_AGE_SECONDS=604800` 会拒绝过期病毒库；离线环境需预置病毒库或允许出网更新，否则上传会被拒。

**未验证**：本轮未在目标 Linux 主机上跑过全流程，因此"合成标书可完整展示"目前是**本机证据 + 前置条件清单**，不是新环境的实测结论。

## 六、阻断项（必须在开放演示前解决）

| 级别 | 项目 | 说明 |
|---|---|---|
| **P0** | 容器无数据卷 | 当前装配无卷，重启即丢数据；部署必须补卷（第三节） |
| **P0** | ClamAV 病毒库时效 | 病毒库过期会导致上传被拒绝；需联网更新或预置 |
| **P1** | 模型账本**防整体回滚**未实现 | 现有防护只能检测"账本缺失/不可读而审计存在"。**审计与账本被协同回滚无法检测**，需要外部不可变存储（WORM）或 KMS 签名计数。**不宣称生产级防回滚**；演示若不启用真实模型，该风险不触发 |
| **P1** | 前端无生产托管配置 | 目前靠 Vite dev/preview；需 nginx 或静态托管 + 反代 |
| **P1** | Linux 启动脚本缺位 | `start.ps1` 仅 Windows；需要等价 systemd unit 或容器入口 |
| **P2** | 未做备份/恢复演练 | 卷的备份与恢复未验证 |

## 七、最低成本、最少代码修改的部署方案

**原则：不改业务代码，只加编排与配置。**

```
单台 Linux VM（2 vCPU / 8 GB / 60 GB SSD）
└── Docker Compose
    ├── postgres:16        + 卷 pgdata
    ├── minio              + 卷 miniodata
    ├── clamav             + 卷 clamdb（含病毒库更新策略）
    ├── api（宿主 Python 或容器）  环境变量注入，监听 127.0.0.1:8000
    ├── web（nginx 托管 dist/ + 反代 /api）监听 443，TLS 终结
    └── parser 镜像本地构建（不常驻，按需启动）
```

**新增文件（不触碰业务代码）**：`docker-compose.demo.yml`、`deploy/nginx.conf`（或 `Caddyfile`）、
`deploy/demo.env.example`、`deploy/README-demo.md`。

**成本量级**：2 vCPU / 8 GB 通用型云主机，按量计费约 ¥0.5–1.5/小时；演示数天即可，无需包月。

**明确不做**：不引入 Kubernetes、不引入托管数据库（成本更高）、不做多副本、不改 LangGraph 与法规检索。

## 八、实施顺序

1. **合并 main 前置**：TASK-0025 归档 → PR #1 评审合并（见交付说明）。
2. 补 `docker-compose.demo.yml` + 卷 + 反代配置（不改业务代码）。
3. 在目标机拉起 PostgreSQL / MinIO / ClamAV，跑 `migrate()`，确认迁移与病毒库可用。
4. 构建 parser 镜像，跑一次**合成标书**全流程，记录新环境的 run 证据。
5. 配置 HTTPS 与访问限制，创建一次性演示账号。
6. 演练重启恢复（`docker compose restart` 后数据仍在）。
7. 演示前一天复测；演示后销毁账号与数据。

## 九、明确不宣称

- 不宣称具备生产级防回滚、备份、监控、SLA 或多租户隔离能力。
- 不宣称在目标主机上已完成全流程实测（尚未部署）。
- 演示默认**不启用**真实 Qwen／Embedding；如启用，须遵循既有授权与账本约束。
