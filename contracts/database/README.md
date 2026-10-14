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
