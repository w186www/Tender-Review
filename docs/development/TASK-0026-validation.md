# TASK-0026 验证记录：Linux 单机容器化部署

基线：`work/TASK-0023` / `ca1c15d76150bc64c9ca8a3425fc65e7d416dcf1`，新工作树
`bidding-compliance-agent-TASK-0026`，分支 `work/TASK-0026`。
TASK-0019、TASK-0021、TASK-0022 工作树未写入。

本轮只新增编排与配置：`src/`、`contracts/`、`tests/`、`scripts/`、`knowledge/`、两份锁文件均未改动。

## 一、交付文件

| 文件 | 作用 |
|---|---|
| `docker-compose.demo.yml` | 六服务编排：postgres、minio、clamav、api、worker、nginx；四个显式命名卷；两个内部网络 |
| `Dockerfile.api` | API 与 worker 共用镜像；`python:3.12-slim-bookworm` + `requirements-dev.lock` + `docker:27-cli` 的 CLI 二进制 |
| `Dockerfile.api.dockerignore` | 该镜像的构建白名单，排除 `src/frontend`、密钥、验证数据 |
| `Dockerfile.web` | 两阶段构建 React 产物并由 `nginx:1.27-alpine` 托管；`VITE_REVIEW_MODE` 编译期开关 |
| `Dockerfile.web.dockerignore` | 该镜像的构建白名单 |
| `deploy/api_entry.py` | 容器入口：按 `DEPLOY_REVIEW_MODE` 选择仓库既有 app 装配（离线确定性 / 已授权真实模型），不自行实现审查逻辑 |
| `deploy/demo_init.py` | 一次性初始化：迁移、非超级用户 RLS 角色与授权、租户与账号、对象桶、ClamAV 就绪、法规快照发布；幂等 |
| `deploy/nginx-demo.conf`、`deploy/nginx-locations.inc`、`deploy/nginx-demo-tls.conf` | 单源反向代理：托管 React 静态产物 + 反代 `/api/`；HTTP 与 TLS 共用同一份 location 片段 |
| `deploy/demo.env.example` | 环境变量模板 |
| `deploy/bootstrap.sh` | 幂等引导：生成密钥、构建 parser 镜像并固化其镜像 ID、探测 Docker socket 属组、按序启动、初始化 |
| `deploy/backup.sh`、`deploy/restore.sh` | 备份与恢复；`--verify` 为非破坏性演练 |
| `deploy/verify_deployment.py` | 经公网反向代理驱动真实 API 的业务验收（合成标书全链路） |
| `deploy/verify_persistence.py` | 重启/重建前后的数据一致性核对 |
| `deploy/README-demo.md` | 部署、运维、HTTPS、备份恢复、模型授权与安全说明 |
| `deploy/docker-compose.tls.yml` | HTTPS 覆盖层 |
| `.gitignore` | 新增 `backups/`（备份含完整数据库与上传对象） |

`deploy/.env` 由脚本生成、权限 600、已被 `.gitignore` 覆盖，未入库。

## 二、实际执行的验证

全部在本机 Docker Linux 引擎（Docker Desktop 4.65.0 / Engine 29.2.1 / Compose v5.1.0）上真实执行。

### 2.1 镜像构建

| 镜像 | 体积 | 说明 |
|---|---|---|
| `tender-review-api:demo` | 772 MB | 含仓库锁定的全部依赖；`Dockerfile.api.dockerignore` 生效（构建日志中 `config/`、`contracts/`、`knowledge/`、`scripts/`、`deploy/` 均按预期 COPY） |
| `tender-review-web:demo` | 74.1 MB | npm ci + vite build 产物 |
| `tender-review-parser:demo` | 449 MB | Tesseract chi_sim + parser 锁文件 |
| `tender-review-minio:release-2025-09-07` | 416 MB | 由仓库 `Dockerfile.minio-verification` 从源码构建（校验和固定） |

解析镜像 ID 固化为 `sha256:857e33a3af72e847b89e69ada0bca47f8afb495ca5d1b3eda2fa30746ebd97de`，
写回 `deploy/.env` 的 `PARSER_IMAGE`；`docker run <该 ID>` 实测可启动并返回结构化结果。

### 2.2 服务启动

`deploy/bootstrap.sh up` 幂等执行通过，输出：

```
migrations: up to date
runtime role: updated
accounts created: none (already present)
bucket: present
ClamAV: ready with a valid virus database
legal publication: already active (1856e2f4-55cb-43c7-ba29-520d7b0110b3)
```

六服务状态：api、worker、nginx `Up`；postgres、minio、clamav `healthy`。
只有 nginx 发布端口（本机映射 8080）。

连通性实测：`/api/v1/health` 经 nginx 返回 200 `{"status":"ok","version":"0.1.0"}`；
`/` 返回 200 `text/html`；React Router 深链 `/projects` 回退 200；未知 API 路径 404。

### 2.3 合成标书全链路（经反向代理，真实 API）

`deploy/verify_deployment.py --base-url http://127.0.0.1:8080` 结果 `status: passed`：

| 步骤 | 实测结果 |
|---|---|
| 登录 | `reviewer` / 角色 `reviewer` |
| 创建项目 | `b99ad41a-fffa-4031-ac70-ef2b5b55e61f` |
| 上传 | 37088 字节，服务端 `sha256` 与本地一致 |
| 安全扫描 + 隔离解析 | 状态 `quarantined` → `needs_confirmation`（ClamAV 强制扫描 + 一次性 parser 容器） |
| 上下文确认 | 状态 `ready`，`parse_version=1`、`context_version=2` |
| 发起审查 | 任务 `d5997d20-4d1e-5bac-9585-baab98fcd069`，批次 `bdff45bb-d937-5d7e-9f85-acb80cc61905` |
| 审查完成 | `waiting_human`，`model_runtime.execution_mode=offline-deterministic`、`provider=offline-verification`、`model=synthetic-protocol-adapter` |
| 风险与证据 | 1 项，`evidence_status=insufficient_evidence`，规则 `TASK0007.QUAL.LOCAL-REGISTRATION`，原文定位 `ooxml/body/3/paragraph` |
| 人工复核 | 1 项决定已记录，历史含审核人与理由 |
| 结果发布 | `result_id=bc756a9e-8088-4b89-9fff-c987039e8983` |
| Word 报告 | 40294 字节，下载字节 SHA-256 `6086323a…` 与服务端 `content_hash` 一致 |
| PDF 报告 | 6765 字节，下载字节 SHA-256 `5fc7a4d7…` 与服务端 `content_hash` 一致 |

报告正文实测包含：证据状态、原文摘录与定位、"本条结果未包含可引用的法规条款，不补造条文"、
以及「语义分析使用 OfflineReviewGateway（offline-verification / synthetic-protocol-adapter）；
本次未调用真实 LLM」。**模型身份如实标注，未伪装成真实 AI 结论。**

### 2.4 浏览器验收（真实前端）

经 ZCode 内置浏览器访问 `http://127.0.0.1:8080/`：

- 登录页正常渲染，顶部「离线确定性演示」提示可见（`VITE_REVIEW_MODE=offline-deterministic` 编译期注入）。
- `reviewer` 登录成功，顶栏显示角色「审核员」。
- 项目工作台列出全部项目；打开项目显示文档状态「可用于审查」、`P1`/`C2`、SHA-256 前缀。
- 审查任务页显示「实际 AI 运行记录：模式 offline-deterministic · 供应商 offline-verification ·
  模型 synthetic-protocol-adapter · 已验证调用 1 次 · 估算费用 ¥0.000000」。
- 风险卡片、原因与建议、原文摘录、文档与法规证据引用、人工决定历史、报告列表（DOCX/PDF + 内容哈希）均正常。
- 点击「下载报告」浏览器下载事件已触发。
- 「待复核任务」页正常（当前无待复核项，与全部已复核一致）。

### 2.5 数据持久化

显式命名卷：`tender-review-pgdata`、`-miniodata`、`-clamdb`、`-modelstate`。

- `docker compose down`（删除全部容器与网络，保留卷）后 `up -d`：
  项目、文档（`ready`，同一 SHA-256）、审查任务（`result_published`，同一 `result_id`）、
  两份报告（字节 SHA-256 与重建前完全一致）全部保留。
- 上传原件经 `GET …/documents/{id}/original` 取回 37088 字节，SHA-256 与上传一致 → MinIO 卷持久化有效。
- 卷实测占用：pgdata 68M、miniodata 632K、clamdb 168M、modelstate 4K。

### 2.6 备份与恢复演练

`deploy/backup.sh` 产出 PostgreSQL 自定义转储、MinIO 卷归档、模型状态卷归档与 SHA-256 manifest。

`deploy/restore.sh <dir> --verify`（非破坏性，未删除任何现有数据）实测：

```
live     : tenant=1 app_user=3 project=3 document=3 ingestion_job=3 review_task=1
           review_result=1 review_report=2 review_report_content=1 audit_event=49
restored : 同上，逐表一致
miniodata: archive files=27 live files now=27 checksum=ok
modelstate: archive files=0 live files now=0 checksum=ok
database: passed   volumes: passed
```

演练结束后复核线上数据：`project=3`、`review_report=2`，未被修改。

### 2.7 资源实测（空闲稳态）

| 服务 | 实测内存 | 说明 |
|---|---|---|
| api | 417.8 MiB | 单进程 Python + LangGraph |
| clamav | 964.7 MiB | 上限 3 GiB 是装配硬约束；加载特征库后的稳态实测值 |
| postgres | 94.9 MiB | 演示数据量 |
| minio | 89.25 MiB | |
| worker | 59.94 MiB | 上限 1 GiB |
| nginx | 13.8 MiB | |
| **合计** | **≈ 1.64 GiB** | 空闲稳态，不含解析峰值 |

隔离解析实测：合成 DOCX 解析 41 ms，进程峰值 RSS 65,323,008 字节（62 MiB），
容器峰值 49,901,568 字节（48 MiB）。

> 与 `DEPLOYMENT-DEMO.md` 中"合计 ≈ 4.45 GB"的估算相比，实测显著更低：
> 该估算按 ClamAV 上限 3 GB 计入，而实测稳态约 965 MiB。上界仍需按 3 GB 保留，
> 因为装配中的 `--memory=3g` 是审查过的硬约束，不得下调。

## 三、明确未验证 / 未执行

- **未在目标 Linux 主机上部署**：本轮全部为本机 Docker Linux 引擎上的验证。
- **未配置 HTTPS**：TLS 覆盖层与 nginx TLS 配置已编写，但未签发证书、未实际启用。
- **未做真实 Qwen 在线调用**：本轮零供应商调用；离线模式的选择与其如实标注见第四节。
- **未执行破坏性恢复**：只做了 `--verify` 演练；`--confirm` 全量恢复路径未实际跑过。
- **未验证并发多用户**、未做性能压测、未验证磁盘写满等故障场景。

## 四、真实 Qwen 的阻断与所需条件

现状核查（代码与决策记录为准）：

- 模型网关有**两份独立且已消耗的本地授权**：`DEC-005-2026-10-15`（30 次 LLM / 200 批 embedding / ¥20）
  与 `DEC-006-2026-10-15`（15 次 LLM / 0 embedding / ¥5），定义在
  `model_gateway/authorized_runtime.py`。TASK-0023 已用掉 DEC-006 的 10/15 次。
- 账本按**授权 ID 分账**，只增不减，新授权不会重置旧额度。
- 外发前按**文档 SHA-256 白名单**过滤（`AuthorizedTenderMinimizer`），
  白名单以 `scope_sha256` 绑定账本；未列入的文档分段一律拒绝。
- 单次调用前**全额预留**预算；`DELETE`/exec 类容器接口与供应商调用均受审计。
- 数据策略为 `CONFIDENTIAL`，供应商限定 `bailian`。

**结论：新上传的演示文件当前无法获得真实 Qwen 审查。** 使其可用需要以下全部条件，
且均需用户单独批准：新增一条独立授权（新的授权 ID、调用次数上限与费用上限）、
在授权中登记演示文件的 SHA-256、注入百炼 API Key 与 Workspace ID、并设置
`DEPLOY_REVIEW_MODE=authorized-real` 与匹配的 `VITE_REVIEW_MODE=dec005-real-qwen`。

本轮未解除任何门禁、未新增模型调用、未把密钥写入仓库或镜像。
密钥只经环境变量注入，`deploy/.env` 权限 600 且不入库。

## 五、已知限制与风险

- **Worker 持有 Docker Socket**：这是仓库既有解析设计所要求的（`ingestion/sandbox.py` 通过
  `docker run -i` 启动解析容器）。挂载 socket 等价宿主 root。已收敛：API 容器不持有 socket、
  worker 不发布端口、`cap_drop: ALL`、`no-new-privileges`、只读根文件系统、非 root（uid 65532）、
  socket 属组经探测后精确 `group_add`。
- **受限 Docker API 代理实测不可用**：加装 `tecnativa/docker-socket-proxy:0.2.0` 并只放行容器生命周期后，
  解析在 60 秒后 `PARSE_TIMEOUT` —— 该代理不转发 `docker run -i` 依赖的 HTTP 劫持式 attach。
  因此该加固在不修改业务代码的前提下无法启用，本轮未交付该叠加层。这是实测结论，不是推测。
- **MinIO 最小权限缺口**：目标桶由初始化脚本用根凭据创建，应用亦使用同一凭据（与仓库既有验收装配一致）。
  尝试引入 `minio/mc` 创建桶级受限账号时，该镜像在当前镜像源返回 403 无法拉取，故未采用。
- 模型账本**防整体回滚未实现**（需外部不可变存储）；演示期不应宣称生产级防回滚。
- 42 个法规版本仍未核验，报告保持 `insufficient_evidence` 与"不计入已核验证据"的表述。

## 六、提交与 CI

分支 `work/TASK-0026`（自 `ca1c15d` 创建）：

| 提交 | 内容 | CI |
|---|---|---|
| `5edf0df` | 部署文件与验证记录 | [Run 38778969436](https://github.com/w186www/Tender-Review/actions/runs/38778969436) `impact`✓ `postgres`✓ `ingestion`✓ `baseline`✗ |
| `70515d0` | 上云运行手册与 DEC-007 申请草案 | [Run 38779172680](https://github.com/w186www/Tender-Review/actions/runs/38779172680) `baseline`✗（同一原因） |
| `11bf78f` | 修复任务登记与证据路径 | [Run 38779974720](https://github.com/w186www/Tender-Review/actions/runs/38779974720) **全部适用作业 success** |

**第一次 Full 的失败原因与修复**：`scripts/verify_contracts.py` 要求 `acceptance_checks.evidence`
必须是**已存在的纯文件路径**（写入中文说明与 Markdown 锚点会被判为路径不存在），
且每个任务必须登记到 `docs/development/roadmap.yaml` 的某个里程碑。两处均已修复，
修复后本地 `verify_contracts.py` 与 `verify_repo.py` 均 PASS。

> 说明：`11bf78f` 因只改文档与任务元数据，仓库自带的 `verification_impact.py` 将其判为 Quick，
> 因此 `postgres`/`ingestion`/`baseline` 按文档条件合法 skipped。**Full 模式未在这三个提交上重跑**；
> 唯一失败过的 baseline 作业其失败原因是上述契约问题，已修复并在本地复验。

### 本地测试复核

`ruff check src scripts tests` 全部通过；`mypy src` 104 个源文件无错误；
`verify_contracts.py`、`verify_repo.py` PASS。

`pytest` 全量在仓库约定的项目内临时目录下运行（`--basetemp=.verification/...`）：
仅 `tests/test_verification_modes.py::test_quick_mode_preserves_existing_full_test_evidence` 失败。
**该失败与本任务无关**：在基线提交 `ca1c15d` 上同样失败（并额外报出 4 个错误），
根因是本机 Git Bash 下 PowerShell 子进程输出按 UTF-8 解码时的 `UnicodeDecodeError`
（Windows 控制台代码页），属既有环境问题。CI 在 Linux 上不受影响。

## 七、结论

在本机 Docker Linux 引擎上，**完整 Tender-Review 系统已可容器化运行并完成端到端业务闭环**，
包括隔离解析、ClamAV 扫描、LangGraph 审查、证据核验、人工复核与 Word/PDF 报告导出，
且数据在容器删除重建后完整保留、备份可演练恢复。

面向真实服务器的部署脚本、反向代理、持久化与备份方案均已就绪并实测；
**尚未在目标 ECS 上执行**，也未启用 HTTPS 与真实 Qwen。
