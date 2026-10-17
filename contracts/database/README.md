# 数据库契约与迁移规则

迁移文件进入 `contracts/database/migrations/`，命名为 `YYYYMMDDHHMM_<description>`。迁移必须可审查、向前兼容，并写清升级、数据回填和回滚策略。

核心表计划：tenant、user、role、project、document、document_section、review_task、graph_run、finding、evidence、human_review、report、rule_version、legal_source_version、model_call、audit_event。

所有业务表包含 `tenant_id`；外键、唯一键和查询索引必须包含租户边界。软删除不能代替数据保留策略。审计事件采用追加写入，业务更新不得覆盖历史证据。

## TASK-0004 已实现契约

首版迁移为 `migrations/202610131200_identity_core.py`，其中冻结DDL是数据库契约。表与字段类型、复合键、状态约束须先修改/追加迁移，再同步ORM。

| 表 | 边界与用途 |
|---|---|
| tenant | 租户ID、名称、启用状态；身份引导使用 |
| app_user | tenant_id+user_id复合主键、租户内用户名唯一、Argon2哈希、启用状态；角色为四值封闭枚举，无自定义权限表 |
| auth_session | 租户+会话ID、账号、过期时间、撤销状态；每次鉴权按复合键读取 |
| project | 租户+项目ID、完整JSON上下文、版本、创建人/时间；创建人复合外键 |
| project_version | 租户+项目+版本、不可覆盖快照、修改人/时间；只追加 |
| idempotency_record | 租户+操作者+键哈希、请求哈希、原始响应快照；事务内唯一占位 |
| document | 租户+文档ID、租户内项目FK、状态/哈希/对象引用；接入功能由TASK-0005实现 |
| review_task | 租户+任务ID、租户内项目FK、运行ID和状态；执行功能由TASK-0009实现 |
| audit_event | 租户+事件ID、操作者、动作、资源ID、请求ID、时间；无密码/Token/正文/异常消息字段 |

project、project_version、document、review_task、idempotency_record和audit_event在PostgreSQL启用并强制RLS；身份表不开放业务HTTP查询。SQLite与PostgreSQL均拒绝覆盖/删除历史和审计。其余计划表按后续任务增量创建；不存在的接口不能称为已实现。迁移与身份选择见ADR-0007，权限与升级/回滚步骤见identity-data-start.md。

## TASK-0005 增量契约

`202610131300_secure_ingestion.py` 在首版之上保留已有文档并增加格式、大小、解析/上下文版本、问题码及质量状态。新增 ingestion_job（幂等键、提交者、尝试数和租约）、document_section（不可覆盖自动片段）、section_revision（人工转录追加历史）、document_context_version（上下文追加快照）。所有关系使用租户复合外键，四张新表 FORCE RLS。修订/上下文快照拒绝修改删除，自动解析 payload 不可覆盖。

升级、受限角色权限和有损降级的备份要求见 docs/development/secure-ingestion-start.md。降级将已解析文档改为 failed，移除新表和属性，保留原始对象；不会自动恢复历史。冻结DDL为权威契约，不修改旧迁移。


## TASK-0006 检索运行增量契约

迁移202610141200_legal_retrieval_run.py在202610131300之上只新增legal_retrieval_run，不改旧表。tenant+run复合主键，tenant/project和tenant/actor复合外键，完整请求/上下文快照和输出分别存JSON及规范SHA-256。PostgreSQL FORCE RLS/WITH CHECK，运行角色仅GRANT SELECT, INSERT；追加写触发器拒绝UPDATE/DELETE，SQLite也有同等触发器。运行与审计同事务提交，按租户重新鉴权读取并验证两端哈希及关联字段。

部署需显式迁移，再由运维给已受限运行账号授予SELECT/INSERT ON legal_retrieval_run；不要用superuser/BYPASSRLS运行服务。旧数据不回填；降级会删除检索运行历史，必须备份并停止写入。没有global publication/current管理表，不把本地索引保存当作法规发布审批。

## TASK-0006 全局法规授权（D05）

202610141600新增legal_operator_grant（tenant/user复合FK、active、capabilities），与租户admin角色独立；运行角色只GRANT SELECT，FORCE RLS只读取当前tenant/user grant，没有运行写策略。数据库运维按真实身份配置全局权限，租户HTTP/模型均不能授予这些权限。每次操作复核会话与当前grant；不缓存授权。降级删除grant，须先备份，现有身份/项目/运行行不更改。


## TASK-0006 不可变核验与发布（D02）

202610141700新增legal_law_identity（标题规范键/稳定law_id，换来源及移出语料不丢身份）、legal_corpus_revision（完整manifest/index/原始与清洗字节/核验来源、SHA、父修订、可信actor、幂等请求）、legal_publication（追加发布/停用/回滚历史）、legal_corpus_state（唯一当前发布与独立核验头）。不限制相同正文hash产生新的核验修订，旧元数据/来源/条款/算法不漂移。发布要求expected_sequence与expected_draft_sequence；全局状态触发器检查对应新增历史/actor权限，不接受无日志移动指针。ingest不能插入verified修订，需verify能力。

显式迁移后运行角色仅SELECT legal_operator_grant；SELECT/INSERT legal_law_identity、legal_corpus_revision、legal_publication；SELECT/UPDATE legal_corpus_state。无grant或历史表UPDATE/DELETE权限；全部新表PostgreSQL FORCE RLS，全局写入依实际tenant/user grant；追加写触发器也拒绝特权历史修改（不声称防御数据库管理员拆除触发器）。原租户项目/运行/audit复合FK和RLS不改。

降级先停止写入、备份全局修订/来源/发布/授权及租户运行。1700删除全局管理记录，1600删除grant；既有tenant/project/legal_retrieval_run不改写。新旧结果不静默升级，旧历史需原消费者版本，回滚当前发布是新publication而非删表。无生产数据，无自动迁移。

## TASK-0028 持久审查调度与模型调用结果

`migrations/202610171000_task0028_durable_review_queue.py` 在 `202610151000` 后追加 `review_engine_run.action`、`scheduled_at`、`lease_id`、`lease_until`、`execution_generation`，并增加租户/状态/调度时间索引。旧行的调度时间回填为原 `updated_at`；不回填 lease，不自动接管没有 lease 的旧 `running` 行。PostgreSQL 领取使用行锁与 `SKIP LOCKED`；SQLite 迁移用批量重建并显式保留既有检查约束。

新增 `review_model_call`，以 tenant+call 复合主键绑定运行、原执行者、调用节点/尝试、请求哈希、输入文档哈希、结果引用/哈希和执行代次。正文与模型响应只存内容寻址 `review_artifact`；PostgreSQL FORCE RLS 按租户隔离，插入策略要求当前 reviewer 身份。运行角色需经部署运维显式授予 `SELECT, INSERT, UPDATE ON review_model_call`。调用先登记为 `dispatched`；持久响应转 `succeeded`，发送后结果未知则转 `unknown` 并禁止自动重放。调用身份不可变，状态只允许从 `dispatched` 完结。

迁移不操作生产数据，也不迁入历史 JSONL/SQLite 账本。部署前应按 U13 停止领取并核对在途作业；降级会删除调用历史与响应指针，须先备份并确认不再需要这些审计/恢复记录。真实供应商调用与内容外发按 D3 单独授权。

## TASK-0028 U05 租户执行授权与预算权威源

`migrations/202610172000_task0028_execution_authorization.py` 在 `202610171000` 后只新增五张表，不改既有业务表、历史账本或注册表：

| 表 | 边界 |
|---|---|
| `model_execution_policy` | 每租户唯一：允许的供应商/用途、预算上限、单次调用/Embedding 批次上限、授权最长有效期、启用状态、更新人/时间 |
| `document_external_authorization` | tenant+authorization 复合主键；绑定项目、文档、原始 SHA-256、parse_version、用途、供应商、策略版本、授权人/时间、到期时间、撤销人/时间/理由；活动行按文件版本+用途+供应商唯一 |
| `model_budget_account` | tenant+authorization 复合主键；`reserved_cny + spent_cny <= limit_cny`；每租户只有一个产品预算账户 |
| `model_budget_reservation` | tenant+reservation 复合主键；调用/Embedding 预留、结算、未知、释放状态；`call_id` 唯一；身份不可变，状态只能前进，结算只能一次 |
| `ledger_import` | 历史 SQLite/JSONL 导入的来源摘要、计数、金额、报告摘要和导入人；追加写 |

PostgreSQL 全部启用并强制 RLS。授权表还有数据库级 restrictive 策略：插入必须由当前 `app.user_id`（启用的 reviewer）作为 `approved_by`，更新必须由当前 reviewer 作为 `revoked_by`；授权身份字段不可变，仅允许 `active → revoked`。预算账户和预留拒绝 DELETE；预留在 `reserved → dispatched → settled/unknown` 或 `reserved → settled/unknown/released` 之外的变化被拒绝，`released` 只能带零费用。

运行角色由部署运维显式授予 `SELECT, INSERT, UPDATE ON document_external_authorization`、`SELECT, UPDATE ON model_budget_account`、`SELECT, INSERT, UPDATE ON model_budget_reservation`、`SELECT ON model_execution_policy`、`SELECT, INSERT ON ledger_import`；策略写入与账户 provisioning 由运维 CLI 使用受控管理连接完成，运行角色不获得策略写权限。服务不得以 superuser/BYPASSRLS 运行。

产品模式（`DEPLOY_REVIEW_MODE=product-postgres`）只使用这些表，拒绝同时配置 DEC-007/DEC-005 SQLite 账本。历史账本由 `scripts/migrate_execution_ledgers.py` 只读导入：保留来源请求 ID，`reserved` 映射为 `unknown` 并按上限计费，异常整批失败，重复运行幂等。真实迁移、切换和线上操作需 D3/D4 单独批准。降级删除五张新表；须先备份并停止外发，既有历史账本不受影响。
