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
