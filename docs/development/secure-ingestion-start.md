# TASK-0005 安全文件接入启动与操作

实现依据为 ADR-0008、OpenAPI 0.4.0、config/ingestion.yaml 和数据库迁移 202610131300。先完成 identity-data-start.md 的环境、迁移、账号引导和登录步骤。API 不自动建表，也不在请求进程执行解析。

## 本地启动

需要 Python 3.12、锁定依赖、Docker Desktop Linux Engine 和 PowerShell 7。开发可以使用 SQLite 和本地私有对象目录；staging/production 必须使用 PostgreSQL 和 S3 适配器。

在仓库根目录构建固定解析镜像，并启动仅监听本机的 ClamAV 服务：

```powershell
docker build -f Dockerfile.parser -t bidding-parser:task0005 .
if ($LASTEXITCODE -ne 0) { throw 'Parser build failed' }
$env:PARSER_IMAGE = docker image inspect bidding-parser:task0005 --format '{{.Id}}'
docker run -d --name tender-dev-clamav -p 127.0.0.1:3310:3310 clamav/clamav:stable
$env:CLAMD_HOST = '127.0.0.1'
$env:CLAMD_PORT = '3310'
$env:OBJECT_STORAGE_MODE = 'local'
$env:OBJECT_STORAGE_ROOT = 'data/runtime/objects'
./.venv/Scripts/python.exe scripts/manage_identity.py migrate
./scripts/start.ps1
```

ClamAV 初次加载病毒库可能需要数分钟，可通过 `docker logs tender-dev-clamav` 检查服务启动；扫描器会核验版本与病毒库日期，过期超过七天或不可用时拒绝继续。不能通过配置关闭扫描。上面容器名由本说明创建；使用结束执行 `docker stop tender-dev-clamav`，需要移除时只移除该容器。已有同名容器应先核对其归属，不覆盖其他服务。

进程环境变量不会传给新终端。API 与独立 Worker 需要相同数据库、对象存储和扫描配置；签名密钥与数据库密码由本地未提交 .env 或秘密服务注入。Worker 无须处理用户密码或复制登录 Token。PARSER_IMAGE 必须是实际构建的 sha256 镜像 ID，不能填写可变标签。

生产 S3 配置需要 OBJECT_STORAGE_MODE=s3、OBJECT_STORAGE_ENDPOINT、OBJECT_STORAGE_BUCKET、OBJECT_STORAGE_ACCESS_ID、OBJECT_STORAGE_ACCESS_SECRET。私有桶由管理员预先建立；端点来自服务端配置，不能取自文档或请求。凭据使用仅访问该桶的业务身份，并配置 TLS、存储加密、保留与备份策略（完整部署验收属于 TASK-0012/0013）。本地模式在 staging/production 无法进行业务存储操作。健康接口仅表示进程存活。

## 从上传到可审查原文

开发 `/docs` 中用 reviewer 登录、Authorize 后创建项目。在 `POST /api/v1/projects/{projectId}/documents` 选择一个文件，提供 16 至 200 字符的 Idempotency-Key。支持 PDF、DOCX、PNG、JPEG；后缀、MIME、签名必须一致，最大 10 MiB。接口返回 202 和 document_id，初始状态 quarantined；相同键与相同文件返回同一文档，改文件复用该键返回 409。

在已配置相同环境的另一个终端执行实际 Worker：

```powershell
./.venv/Scripts/python.exe scripts/process_document.py --tenant local --document '<上传返回的document_id>'
```

tenant 是数据库作业的作用域，不能给予权限；Worker 从作业读取提交者，在处理前和发布前再次核对其当前租户与 reviewer 权限。作业有持久化状态、180 秒租约和最多三次尝试；重复领取或旧租约发布被拒绝。扫描不可用、解析超时等有限重试需重新执行此命令。首期提供独立单作业执行器；持续调度、队列服务管理与资源配额在后续任务交付。

| 状态 | 含义和下一步 |
|---|---|
| quarantined / parsing | 尚未获准使用原文，等待 Worker 或正在处理 |
| rejected | 恶意、非法结构、权限失效等被拒绝；不能人工解除 |
| failed | 技术失败；查看安全问题码，符合重试条件且预算未用尽时重试 |
| needs_review | 文本或 OCR 质量不足，先修正文段并复检 |
| needs_confirmation | 质量门禁已通过，需人工确认项目上下文 |
| ready | 文本与上下文可供后续审查模块使用，不代表合规审查完成 |

`GET .../sections` 返回 automatic 和 effective 片段、原文件哈希、文本哈希、定位及修订号。PDF 使用原始页码与 PDF 点坐标；图片使用像素坐标；DOCX 使用 OOXML 结构路径和表格行列，无渲染页码。PNG/JPEG 与扫描 PDF 使用中英文 Tesseract OCR。DOCX 页眉、页脚、脚注、嵌套表格保留结构文本；内嵌图片目前保留空 OCR 定位并进入 needs_review，需要人工转录，不能视为已自动识别。

`POST .../corrections` 提交 expected_parse_version、reason 和 corrections（section_id、text）。修正追加版本，自动原文不覆盖；重新验证质量、增加 parse_version，并使既有上下文确认失效。空 OCR 页不能靠其他页长文本掩盖。恶意文件没有可用片段，修正接口不能绕过安全拒绝。

`GET .../context` 返回带置信度与来源的自动候选；它们是启发式提取，不自动成为事实。`POST .../context` 提交 expected_version、reason 和完整 context（name、procurement_type、project_type、region，以及可选 industry、budget_amount、applicable_system）。版本过期返回 409，成功追加人工确认版本并进入 ready。

`GET .../original` 经租户和项目鉴权后复验原文件哈希，以附件下载。文件仍是原始上传内容，不执行其中指令；不返回存储路径。reviewer 可以上传、修正和确认；其他三种角色只能读取本租户已通过扫描的文档。跨租户 ID 与不存在 ID 均返回 404。

当前严格文件策略拒绝加密/主动内容/附件 PDF、DOCX 宏与所有外部关系（包括外部超链接）、路径穿越、压缩炸弹和多帧图片。需要兼容其他格式或外部超链接时，必须先修改版本化安全策略与 ADR 并提供回归证据。

## 迁移与权限

在停止业务写入并备份后，独立迁移身份执行升级至 202610131300。已有 document 记录保留，新增属性采用默认值；新增 ingestion_job、document_section、section_revision、document_context_version。迁移身份与 API/Worker 身份分离。

PostgreSQL 业务角色新增 document、ingestion_job 的 SELECT/INSERT/UPDATE；document_section 的 SELECT/INSERT 和 revision 列 UPDATE；section_revision、document_context_version 的 SELECT/INSERT。原 TASK-0004 权限继续保留。四张新增表 FORCE RLS，修订和上下文快照触发器阻止覆盖/删除，自动解析 payload 不可覆盖。API 与 Worker 拒绝超级用户或 BYPASSRLS 角色。

降级至 202610131200 会删除新增解析历史和作业表、移除新增属性，已经解析的文档改为 failed；原始对象文件保留。必须先备份数据库和对象，停止 API/Worker，按受控回滚执行，不将降级作为日常修复。重新升级不会恢复被删除的历史。

## 可复现验证

```powershell
./scripts/verify.ps1
$env:PARSER_VERIFY_IMAGE = docker image inspect bidding-parser:task0005 --format '{{.Id}}'
./.venv/Scripts/python.exe scripts/check_parser_sandbox.py
./.venv/Scripts/python.exe scripts/check_ingestion_containers.py
```

后两个脚本要求 Docker Linux Engine、已构建解析镜像和本机缓存的 minio/minio:latest、clamav/clamav:stable（首次可用 docker pull 获取）。真实验证创建自己的随机服务、随机秘密和合成样本，检查 S3、杀毒、OCR、HTTP、租户隔离及资源限制，最后清理自己的容器与服务。CI 对这些步骤单独设必过作业，没有不可用时跳过的分支。

单元测试使用明确标注的扫描/OCR替身；实际容器验证另提供真实证据，两者不能互相冒充。PostgreSQL 验证继续使用 identity-data-start.md 中的独立空测试库。真实学校招标文件和用户法规未用于本任务的测试；扫描准确率、中文复杂版面和生产安全总体验收另按黄金集及里程碑执行。
