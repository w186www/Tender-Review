# TASK-0004 身份与项目启动

关联 ADR-0007、SEC-001/002/007。数据库生产目标为 PostgreSQL；SQLite 只用于 development/test。迁移不会在 API 启动时自动执行。

## 本地可运行流程

先按 README 安装锁定环境。在仓库根目录执行：

```powershell
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite:///data/runtime/development.db'
New-Item -ItemType Directory -Path data/runtime -Force | Out-Null
$env:AUTH_SIGNING_KEY = & ./.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
./.venv/Scripts/python.exe scripts/manage_identity.py migrate
./.venv/Scripts/python.exe scripts/manage_identity.py bootstrap --tenant local --tenant-name '本地项目' --username reviewer --role reviewer
./scripts/start.ps1
```

引导命令交互输入并确认12至1024字符密码，终端不回显，命令行不接受密码。没有预设账号；用户名在租户内唯一。重复引导同名账号会失败，不覆盖原授权。runtime目录与.env被Git忽略。签名密钥若重生成，旧Token失效；需要持久使用时由本地未提交.env或秘密服务注入。

开发 `/docs` 中执行 `POST /api/v1/auth/token`，输入 tenant_id、username、password，得到短期 bearer JWT。在 Authorize 中设置返回 Token。不要在公共截图、聊天或终端日志中复制真实Token。

随后 `POST /api/v1/projects`，带16至200字符 Idempotency-Key，请求内容例如：

```json
{"name":"学校改造项目","procurement_type":"government","project_type":"works","region":"安徽省滁州市","industry":"教育","budget_amount":1000000,"applicable_system":"采购人内部制度版本号"}
```

接口返回租户、项目ID、版本1与创建时间。GET projects为带分页的本租户列表；GET projects/{projectId} 查询；PUT 同路径以完整上下文和 expected_version 更新，旧版本返回409；GET 后缀 /versions 返回历史。重复创建返回原始快照，复用同一幂等键但改变内容返回409。登出使用 POST auth/logout，此会话Token立即失效；不同登录会话分别撤销。

## 权限矩阵

| 角色 | 项目查询/历史 | 创建/更新项目 |
|---|---|---|
| reviewer | 是 | 是 |
| admin | 是 | 否 |
| auditor | 是 | 否 |
| operator | 是 | 否 |

认证和每个仓库调用绑定 Principal；租户来自校验后的JWT与当前数据库身份。请求body多传 tenant_id/user_id/role 被拒绝；X-Tenant-ID不参与授权。跨租户ID与不存在ID统一404。角色调整、账号或租户停用在下次请求立即生效。当前没有网页注册/角色变更接口，后续授权审批由安全工作流任务实现。

## PostgreSQL 部署和迁移

运维通过秘密管理配置迁移身份的 DATABASE_URL，运行同一 migrate 与 bootstrap 命令，然后切换到权限受限的 API DATABASE_URL 启动。不得使用超级用户或 BYPASSRLS 身份运行API，发现会关闭业务接口。

API数据库角色需要：schema USAGE；tenant/app_user SELECT；app_user仅password_hash列UPDATE（升级哈希）；auth_session和project SELECT/INSERT/UPDATE；project_version、idempotency_record、audit_event SELECT/INSERT。TASK-0005新增文档/作业/片段权限与202610131300迁移，详见secure-ingestion-start.md。TASK-0009迁移202610141800新增review_engine_run SELECT/INSERT/UPDATE、review_artifact/review_decision/review_result SELECT/INSERT，以及LangGraph Checkpoint表按租户线程前缀隔离的SELECT/INSERT/UPDATE/DELETE；人工决定/结果插入另受当前用户和reviewer角色约束，checkpoint_migrations仅需SELECT。运行角色无DDL权限；迁移由独立身份执行。

业务表 FORCE RLS，作用域由服务端事务内 set_config('app.tenant_id', tenant, true) 设置；事务结束自动清除，不允许客户端选择。复合外键阻止文档或任务关联其他租户项目。项目快照与审计触发器拒绝UPDATE/DELETE；API账户另只授予追加权限。完整运维防篡改存储、保留期、TLS和认证限流尚待TASK-0012/0013，不宣告生产全项验收。

初版迁移 `202610131200` 无数据回填。重复upgrade为无操作。downgrade base 会删除全部初版表：仅用于空库验证或停止服务、备份确认后的受控回滚；不提供自动启动回滚或日常删除命令。将来迁移必须增量追加，不修改已经部署的历史文件。

## 验证

`./scripts/verify.ps1` 包含所有原有门禁和新增真实进程登录/项目读写/撤销验证；测试库位于.verification，子服务完成后自动停止。GitHub postgres作业另用PostgreSQL16空库、非特权角色验证迁移、RLS、复合外键、并发幂等、乐观锁、追加触发器和升级回滚。

本机如具备独立临时PostgreSQL库，设置 POSTGRES_VERIFY_URL 指向数据库名 task0004_verification，然后运行 `.venv/Scripts/python.exe scripts/check_postgres.py`。该脚本拒绝其他库名和已有tenant表，不清空已有数据库；测试需具备临时库中的迁移/建角色权限。成功后库包含回迁的空表，重验须由运维创建新临时环境。
