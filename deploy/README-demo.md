# 单机部署说明（面试演示）

本目录只包含**编排与配置**。业务代码（`src/`）、契约（`contracts/`）、法规库（`knowledge/`）、
测试与锁文件均未修改；容器里跑的就是仓库当前这份 Tender-Review。

## 一、这套东西在做什么

```
浏览器 ──HTTP(S)──> nginx ──/api/──> api（FastAPI + LangGraph）
                      └──> React 静态产物
api / worker ──> postgres（业务数据 + 迁移 + LangGraph checkpoint）
             ──> minio   （上传文件对象）
             ──> clamav  （强制病毒扫描）
worker       ──> docker 守护进程 ──> 一次性隔离 parser 容器（DOCX/PDF + Tesseract OCR）
```

两个刻意的边界：

- **只有 nginx 对外发布端口**。PostgreSQL、MinIO、ClamAV、API、Worker 全部只在内网。
- **API 容器不挂载 Docker Socket**。文件解析只发生在 ingestion worker 进程里，
  而 worker 没有对外端口。公网可达的进程不持有容器运行时权限。

## 二、前置条件

- Linux（阿里云 ECS / 本机 Docker Desktop 均可），Docker 24+ 与 `docker compose` 插件。
- 能拉取以下镜像（或已配置可用镜像源）：
  `postgres:16`、`clamav/clamav:stable`、`python:3.12-slim-bookworm`、`docker:27-cli`、
  `golang:1.24.6-bookworm`（构建 MinIO）、`node:22-bookworm-slim`、`nginx:1.27-alpine`。
- 内存 ≥ 6 GB（ClamAV 单独就要 3 GB），推荐 8 GB。
- 出网能力：ClamAV 首次启动要下载病毒特征库（约 250 MB）；镜像构建要访问 npm 与 PyPI。

## 三、首次部署

```bash
git clone https://github.com/w186www/Tender-Review.git
cd Tender-Review
git checkout work/TASK-0026          # 部署分支（含本目录）

./deploy/bootstrap.sh init
```

`init` 依次完成，每一步都可重复执行：

1. 生成 `deploy/.env`（随机密码、签名密钥、MinIO 凭据；文件权限 600，且已在 `.gitignore` 里）。
2. 构建**隔离 parser 镜像**，把 `docker image inspect` 得到的固定镜像 ID 写入 `PARSER_IMAGE`。
   Worker 只接受 `sha256:...` 形式的镜像 ID，不接受可被替换的标签。
3. 构建 api 与 web 镜像。
4. 拉起 PostgreSQL、MinIO、ClamAV。
5. 执行 `deploy/demo_init.py storage`：跑迁移 → 创建**非超级用户、NOBYPASSRLS** 的应用角色并授权 →
   建租户与账号 → 建对象桶 → 等待 ClamAV 病毒库可用。
6. 拉起 api、worker、nginx，再执行 `deploy/demo_init.py legal`：
   通过真实鉴权 API 发布初始法规快照。
7. 打印演示账号。

启动完成后浏览器访问 `http://<主机>/`。

## 四、演示账号

`./deploy/bootstrap.sh credentials` 可随时打印。默认三个账号（租户 `tenant-a`）：

| 用户名 | 角色 | 用途 |
|---|---|---|
| `reviewer` | reviewer | **主演示账号**：建项目、上传、发起审查、人工复核、下载报告 |
| `admin` | admin | 法规管理与发布（需要 `legal_operator_grant`，初始化时已授予） |
| `auditor` | auditor | 只读审计视角 |

密码为随机生成，只存在于 `deploy/.env`。演示结束后应删除账号或销毁实例。

> 角色边界来自仓库既有 RBAC：`reviewer` 才能写项目与做复核决定（`domain/identity.py`），
> 所以不要用 admin 走演示主流程。

## 五、日常运维命令

```bash
cd <repo>
D="docker compose --env-file deploy/.env -f docker-compose.demo.yml"

$D ps                        # 状态
$D logs -f --tail=200 api    # API 日志（换 worker / nginx / clamav / postgres / minio）
$D restart api worker        # 只重启应用进程，数据不动
$D stop                      # 停止全部容器（数据卷保留）
$D up -d                     # 重新启动
$D down                      # 删除容器与网络，**数据卷保留**
$D down -v                   # 删除容器与数据卷 —— 只有确实要清空演示数据时才用
```

更新代码后：

```bash
git pull
./deploy/bootstrap.sh parser          # 解析逻辑或解析依赖变化时才需要
$D build api nginx
$D up -d
$D run --rm --no-deps --entrypoint python api deploy/demo_init.py storage   # 有新迁移时会补跑
```

## 六、数据持久化

| 卷（默认前缀 `tender-review`） | 内容 | 丢了会怎样 |
|---|---|---|
| `-pgdata` | 业务数据、迁移版本、**LangGraph checkpoint** | 项目/文档/审查任务/复核结论全部丢失，未完成的审查无法恢复 |
| `-miniodata` | 上传的原始文件对象 | 已入库文档的正文永久缺失，无法重新解析 |
| `-clamdb` | ClamAV 病毒特征库 | 仅影响下次启动时间（需重新下载） |
| `-modelstate` | 模型预算账本与审计（`dec005-budget.sqlite3`、`dec007-budget.sqlite3`、`*-audit.jsonl`）、逐文件授权注册表、预构建的法规向量索引 | 真实模型授权的额度记录、逐文件授权与预构建索引丢失，属于审计缺口；索引需重新付费预构建 |

卷名在 `deploy/.env` 里由 `VOLUME_PREFIX` 决定，可用 `docker volume ls` 核对。

**重建容器不会丢数据**：`docker compose down` 后再 `up -d`，项目、文件、审查任务、报告都还在。
只有 `down -v` 或手工 `docker volume rm` 才会删除。

### 备份与恢复

```bash
./deploy/backup.sh                    # 输出到 ./backups/<UTC 时间戳>/
./deploy/backup.sh /srv/backups/x     # 指定目录

./deploy/restore.sh ./backups/20261016T031500Z --confirm   # 破坏性，必须显式确认
```

备份内容：PostgreSQL 自定义格式转储、MinIO 数据卷、模型状态卷，以及带 SHA-256 的 manifest。
ClamAV 特征库不备份（可重新下载，不是业务数据）。

## 七、HTTPS 与域名（阿里云 ECS）

1. **安全组**：只放行 `443`（HTTPS）与 `80`（仅用于跳转或申请证书时）。
   `22` 限制到你的出口 IP。**不要**放行 5432 / 9000 / 3310 / 8000。
2. **域名**：把 `demo.example.com` 解析到 ECS 公网 IP。
3. **证书**：用 certbot 的 webroot 或 DNS 方式签发，然后：
   - 把证书放到宿主机（例如 `/etc/letsencrypt/live/<域名>/`）；
   - 用 TLS 覆盖文件启动 nginx：
     ```bash
     $D -f docker-compose.demo.yml -f deploy/docker-compose.tls.yml up -d nginx
     ```
     （`deploy/docker-compose.tls.yml` 会把证书只读挂进 nginx，并把 443 映射到 8443。）
   - 或保持本仓库默认：在 ECS 前面挂一个阿里云负载均衡/SLB 终结 TLS，后端仍指向 80。
4. 改完 `deploy/.env` 里的 `PUBLIC_BASE_URL=https://demo.example.com` 后 `$D up -d api`。

> 未配置 HTTPS 时不要把演示地址公开到互联网：登录口令会在明文 HTTP 上传输。

## 八、真实 Qwen 审查：现在的状态与启用条件

默认 `DEPLOY_REVIEW_MODE=offline`。此时走的是仓库既有的**离线确定性网关**：
LangGraph 全流程、法规检索、证据核验、人工复核、Word/PDF 报告都是真的，
**但模型分析输出是协议一致性样本，不是语义审查结论**。工作台会显示
「离线确定性演示」横幅说明这一点（`VITE_REVIEW_MODE=offline-deterministic` 编译期开关）。

### 8.1 启用条件（DEC-007 完整能力）

要换成真实 Qwen，需要**全部**满足下列条件，缺一不可：

1. 阿里云百炼 API Key 与 Workspace ID（`DASHSCOPE_API_KEY`、`BAILIAN_WORKSPACE_ID`），
   只写入服务器 `deploy/.env`（600、已 gitignore），不进镜像与前端。
2. **独立的 DEC-007 授权**：`DEC007_AUTHORIZATION_ID=DEC-007-2026-10-16`。
   仓库里的 `DEC-005` / `DEC-006` 有各自额度账本且已消耗，不能复用，也不会被重置；
   DEC-007 有独立账本 `dec007-budget.sqlite3`（LLM 300 次 / Embedding 800 批 / ¥30）。
3. **预构建全量法规向量索引**（服务端不会临时建库）。在 api 容器内执行一次：
   ```bash
   $D exec api python scripts/prebuild_legal_vectors.py \
       --dry-run                    # 先看计划：3120 条 → 3112 条可嵌入、8 条超长、312 批
   $D exec api python scripts/prebuild_legal_vectors.py \
       --publication-id <id> --revision-id <id>   # 真实构建（付费，支持断点续建）
   ```
   `publication_id` / `revision_id` 取当前法规发布版本（见第八节末尾的查询命令）。
   索引文件、账本与注册表都在 `-modelstate` 持久卷里，`down && up -d` 不会丢。
   **缺索引、索引未完成或校验失败时，API 会直接拒绝该次审查**（零供应商调用），
   不会在面试官点击审查时同步跑几百批 Embedding。
4. **逐文件外发授权**：未登记的文件一律拒绝（见 8.2）。
5. 设置 `DEPLOY_REVIEW_MODE=authorized-real`，并用 `VITE_REVIEW_MODE=dec007-real-qwen`
   重新构建前端（`$D build nginx`），保证页面提示与实际执行一致。
6. 额度与预算限制仍然生效：单次调用前**全额预留**，账本只增不减。批次到 800 拒绝；
   累计费用到 ¥30 拒绝（即使批次还有余额）；失败或用量未知的预留继续占用额度且不自动补发。
   本地账本**不是**生产级防回滚方案（审计与账本被整体回滚无法检测），演示期间不要宣称有防回滚能力。
7. **首次真实调用前**先跑一次受控验证轮（独立镜像 + 收紧上限 4 次 LLM / 322 批 / 累计 ¥2，
   含账本基线核对与三步顺序）：见 8.4。

未满足上述条件时，真实审查入口保持关闭并如实报错，**不会**回退成 Mock 冒充成功。
`docker-compose.demo.yml` 把上述真实模型变量（`DASHSCOPE_*`、`BAILIAN_*`、`DEC007_*`、
`DEC005_*`）**只注入 api 服务**，worker 与其他服务不持有任何供应商凭据；全部留空时
`DEPLOY_REVIEW_MODE=offline` 仍可正常启动。

### 8.2 逐文件授权的运维步骤（approve / list / revoke）

授权登记是**追加式 JSONL 审计文件**，只记录文件 SHA-256、文档标识、理由、时间与操作人，
从不读写文件内容。它必须与 `DEC007_AUTHORIZATION_REGISTRY`、同一个 `-modelstate` 卷共用。

```bash
cd <repo>
D="docker compose --env-file deploy/.env -f docker-compose.demo.yml"

# 1) 看当前状态：有效白名单 + 全部审计行
$D exec api python deploy/manage_authorization.py list
$D exec api python deploy/manage_authorization.py list --json

# 2) 登记一个文件（面试官上传的合成样本）；--actor 省略时取 DEC007_AUTHORIZATION_ACTOR
$D exec api python deploy/manage_authorization.py approve \
    --sha256 <64 位小写 hex> --document <document-id> --reason "面试演示合成样本"

# 3) 收回授权（文件、法务或演示范围变化时）
$D exec api python deploy/manage_authorization.py revoke \
    --sha256 <64 位小写 hex> --reason "演示结束收回"
```

**生效语义**：

- `approve` / `revoke` 立即对**正在运行的 API 生效**：注册表按文件 mtime/size 重读，
  引擎的冻结/调用门禁与出站最小化器在**每次判定**时重新读取有效白名单，
  撤销后**下一次外发即被拒绝**，无需重启容器。
- 只有注册表**路径或授权身份**变化才需要重启 api（例如改 `DEC007_AUTHORIZATION_REGISTRY`）。
- 审计行只增不改：某个哈希的**最后一条**记录（approve/revoke）决定它当前是否被授权。
- 注册表损坏或不可读时**失败关闭**（不降级为"全部授权"或"全部拒绝后继续放行"）。

**与账本 scope 的关系**：

- 账本 scope（`scope_sha256`）只绑定**静态**部分：授权 ID、租户、环境变量白名单、
  供应商/模型/embedding 身份，以及注册表**文件路径**。
- 逐文件 approve/revoke **不改变** scope，因此**永远不会重置或作废**已有账本
  （否则唯一的"修复"办法就是删账本，正好是 DEC-007 禁止的额度重置）。
- 反过来，改环境变量白名单或换注册表路径会改变 scope，与旧账本冲突并报
  `existing DEC ledger has a different scope`；这正是需要新授权 ID 的场景。

### 8.3 供应商外发范围与不可宣称项

- DEC-007 仅授权逐文件登记过的**合成**文件与脱敏分段外发；真实商业标书仍不外发。
- 全量索引不等于"法规已核验"：可确认适用的法规依据依然来自确定性核验链，
  向量相似度不能提升证据等级，未核验法条不能成为确认违法的依据。
- 8 条超长条款（>8192 字节）无法嵌入，只能由 BM25 覆盖。

查询当前法规发布版本（预构建参数）：

```bash
$D exec postgres psql -U postgres -d bidding_compliance -c \
    "select publication_id, revision_id from legal_publication order by sequence desc limit 1"
```

### 8.4 本轮受控验证：独立镜像 + 收紧上限（LLM 4 / Embedding 322 / 累计 ¥2）

线上 `authorized-real` 用的是 DEC-007 授权额度本身（LLM 300 / Embedding 800 / ¥30）。
**首次真实调用之前**先跑一轮受控验证：仍是 TASK-0027 最新代码、仍然是同一个
`-modelstate` 命名卷（读写挂载）、同一法规发布/修订、同一 embedding 身份与同一授权 scope，
但本轮上限在**装配层代码里固定**（`scripts/task0027_real_ai_validation_app.py`）：

| 项 | 本轮上限 | 说明 |
|---|---|---|
| LLM | **4 次** | 一次合成样本审查约 2 次（发现 + 语义），留余量 |
| Embedding | **322 批** | 312 批已用于预构建索引，本轮最多再新增 **10 批**查询 |
| 费用 | 累计 **¥2** | **含**已结算的 ¥0.1035070，不是额外新增额度 |

- 三个值都是脚本里的常量：**环境变量、命令行参数、普通演示账号都无法提高**。
- 启动时还会拒绝"不比 DEC-007 授权更严"的取值；`AUTHORIZATION_LIMITS[DEC-007]` 的
  300/800/¥30 **保持不变**，只作构造期上界。
- 计数是**同一账本文件、同一 authorization_id 的累计值**（硬限制，不是预估）；
  失败或用量未知的预留继续占用额度且不自动补发。

#### 三步顺序（不可颠倒）

**第一步：门禁与测试通过（尚未有任何外发）**

```bash
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Focused \
  -TestPaths @('tests/test_task0027_round_limits.py','tests/test_task0027_validation_entry.py', \
               'tests/test_task0027_budget_boundaries.py','tests/test_task0027_per_file_authorization.py') \
  -PythonExecutable <venv python>"
```

**第二步：登记冻结 DOCX 的 SHA-256**（只写追加式注册表，**不写环境变量白名单**）

```bash
cd <repo>
D="docker compose --env-file deploy/.env -f docker-compose.demo.yml"
$D exec api python deploy/manage_authorization.py approve \
    --sha256 <冻结 DOCX 的 64 位小写 hex> --document <document-id> \
    --reason "TASK-0027 受控验证合成样本"
```

不要用改 `DEC005_ALLOWED_DOCUMENT_SHA256` 的方式放行文件：环境变量白名单是账本 scope 的一部分，
改了会与既有账本冲突（`existing DEC ledger has a different scope`），唯一的"修复"办法就成了删账本 ——
正是 DEC-007 禁止的额度重置。逐文件注册表**不参与 scope**，所以 approve/revoke 永远不会作废账本。

**第三步：才发起真实调用**（本轮上限生效，命令见下）。未完成前两步、未获批准前不要执行。

#### 独立镜像标签与运行命令（不影响线上容器与 offline 模式）

```bash
cd <repo>
D="docker compose --env-file deploy/.env -f docker-compose.demo.yml"

# 0) 启动前人工确认：线上仍是离线模式、且没有第二个 authorized-real 实例
$D exec api printenv DEPLOY_REVIEW_MODE          # 必须输出 offline
$D ps

# 1) 用独立标签构建验证镜像（绝不覆盖线上 tender-review-api:demo）
IMAGE_TAG=task0027-validation $D build api

# 2) 只读核对账本基线（不创建、不修改、不重置账本）
IMAGE_TAG=task0027-validation $D run --rm --no-deps api \
    python scripts/task0027_ledger_baseline.py

# 3) 预检查（零供应商调用、零写入、零预留；缺索引/基线不符/公网 API 不可达即拒绝）
IMAGE_TAG=task0027-validation $D run --rm --no-deps api \
    python scripts/task0027_real_ai_validation_app.py --preflight \
    --publication-id <id> --revision-id <id> --online-api-offline-verified

# 4) 起一次性验证实例：只在宿主机回环发布端口
IMAGE_TAG=task0027-validation $D run --rm --no-deps -p 127.0.0.1:8123:8000 api \
    python scripts/task0027_real_ai_validation_app.py \
    --publication-id <id> --revision-id <id> --online-api-offline-verified
```

- `run --rm --no-deps` 只创建一个**一次性容器**：复用 api 服务的环境变量、网络与 `-modelstate`
  读写挂载，**不重启、不改动线上 api / worker / nginx**，也不改 `DEPLOY_REVIEW_MODE`。
- 容器内验证实例监听 `0.0.0.0:8000`（否则 `-p` 无法转发到它），但**只发布到宿主机回环**
  `127.0.0.1:8123`；容器自身只挂在 compose 内网，没有对外端口。
- `IMAGE_TAG=...` 只作用于该条命令；`$D up -d` 仍解析为 `tender-review-api:demo`，线上镜像不被替换。
- 上传与隔离解析仍走线上栈（worker 是离线解析，不外发）；本轮审查请求打到
  `127.0.0.1:8123` 上的验证实例。验证实例的日志（stderr）含预检查报告与生效上限。
- `--preflight` 的 `--publication-id/--revision-id` 取自第八节末尾的 SQL；给出后会在启动前
  用 `require_prebuilt_vector_index` 本地校验预构建索引（零供应商调用）。不给出时该项显示为
  "not pinned"，服务端仍在审查时拒绝建库（`allow_build=False`）。
- 验证实例需要**至少一个已登记文件**才能启动（出站最小化器拒绝空白名单），所以第二步必须在前。
- 服务端（API 侧）只允许**逐文件登记 + 本轮收紧上限**两条同时成立；缺一即拒绝且零外发。

#### 账本基线核对（执行前必须做）

期望值：**LLM 0 次 / Embedding 312 批 / 累计 ¥0.1035070 / 未结算 0**。

```bash
IMAGE_TAG=task0027-validation $D run --rm --no-deps api \
    python scripts/task0027_ledger_baseline.py
```

输出示例（口径为"该 authorization_id 在账本文件里的累计值"）：

```
llm_calls: 0 (expected 0)
embedding_batches: 312 (expected 312)
charged_or_reserved_cny: 0.1035070 (expected 0.1035070)
unsettled_requests: 0 (expected 0)
PASS: the ledger matches the documented pre-round baseline.
```

**不一致时停止并上报**（退出码 2）：先记录观测值与期望值的差异，再决定本轮是否继续；
**不得删除、替换或重置账本**。`--expect-*` 只用于如实记录已知漂移，不是修复手段。
`--json` 可输出机器可读结果（含各授权 ID 的历史计数，用于确认 DEC-005/006 未被触碰）。

#### 本轮的边界（必须如实说明，不得宣称超出）

- 账本文件只存**计数**，上限是**进程内参数**：若另一个进程被显式以 300/800/¥30 打开同一账本，
  账本本身不会阻止它（选项 A 的已知边界）。因此本轮**必须确保只有一个真实模型验证实例在运行**，
  运维不得并行启动宽上限进程；本方案**不提供**跨任意进程的全局收紧锁（选项 C 的账本内租约锁未实现）。
- 收紧上限**不写入账本**，也不改表结构：本轮结束后 300/800/¥30 仍可用，继续累计使用**原有账本**。
- 门禁在**任何**供应商请求之前生效：拒绝时 transport 零调用、账本计数不增加。
- 本地账本**不是**生产级防回滚方案；本轮结束不得以删除账本的方式恢复额度。

## 九、安全说明与已知限制

- 应用进程使用非超级用户、`NOBYPASSRLS` 的角色连接数据库，租户隔离由行级安全策略强制。
- 上传先经 ClamAV 扫描，再在 `--network=none --read-only --cap-drop=ALL --memory=512m`
  的一次性容器里解析；解析器无数据库与模型凭据。
- 密钥只存在于 `deploy/.env`（权限 600）与容器环境变量，不进镜像、不进仓库、不进日志。
- **Worker 持有 Docker Socket**：这是仓库既有解析设计所要求的（`ingestion/sandbox.py`
  通过 `docker run -i` 启动解析容器并与之交互）。挂载 socket 等价于宿主 root，这是本方案
  剩余的主要风险面。已做的收敛：API 容器不持有 socket、worker 不发布端口、
  `cap_drop: ALL`、`no-new-privileges`、只读根文件系统、非 root 用户、内存上限，
  并且 socket 的属组由 `bootstrap.sh` 探测后用 `group_add` 精确授予。
- **已实测：受限 Docker API 代理当前不可用**。在 worker 与 socket 之间加一层只放行容器生命周期
  的代理（`tecnativa/docker-socket-proxy:0.2.0`）后，解析会在 60 秒后 `PARSE_TIMEOUT`：
  代理不转发 `docker run -i` 依赖的 HTTP 劫持式 attach，容器收不到 stdin、也不回传 stdout。
  因此该加固无法在不修改 `src/bidding_compliance/ingestion/sandbox.py` 的前提下启用，
  本轮未交付该叠加层。要真正收缩这一面，需要把解析调用改成不依赖交互式 attach 的形式
  （例如经文件或对象存储传递载荷），那属于业务代码变更，需单独决策与授权。
- MinIO 目标桶由初始化脚本用根凭据创建，应用也使用同一凭据（与仓库既有验收装配一致）。
  这是已知的最小权限缺口；演示数据无害，但生产化时应改为桶级受限的 MinIO 用户。
  （尝试引入 `minio/mc` 创建受限账号时，该镜像在当前镜像源返回 403 无法拉取，故未采用。）
- 演示只放**合成标书**。不要上传真实商业标书或个人身份信息。

## 十、演示结束后的清理

```bash
$D down            # 保留数据，便于复盘
$D down -v         # 清空演示数据卷
# 阿里云控制台：停止或释放 ECS 实例；如用弹性公网 IP，一并释放以免继续计费
```
