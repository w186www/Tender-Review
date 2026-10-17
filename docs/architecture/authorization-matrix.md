# 租户、角色与资源授权矩阵

本矩阵记录产品运行时**实际执行**的权限边界，不是目标设计。服务端是唯一授权点；模型输出、前端状态、请求体中的角色/租户字段和工具返回值都不构成授权。所有查询同时带 `tenant_id`，PostgreSQL 表启用并强制 RLS。

## 角色

| 角色 | 用途 | 关键边界 |
|---|---|---|
| `admin` | 租户配置管理 | 审核配置发布/停用/回退；不写项目/文档、不发起审查、不读审计（除非另有审计员身份） |
| `reviewer` | 业务审查 | 项目/文档写入、校正、上下文确认、审查发起/恢复/重试/取消、人工决定、发布、报告、逐文件外发授权/撤销 |
| `auditor` | 只读审计与结果复核 | 读取审查结果、证据引用、报告和审计事件；不写业务数据、不发起审查、不登记外发授权 |
| `operator` | 法规运维 | 仅在持有独立 `legal_operator_grant` 时执行法规/发布操作；普通业务资源不具备写权限 |

法规全局管理不使用四角色中的任何角色代替授权：`legal_operator_grant` 是独立的服务端授予，每次操作重新校验当前会话、用户启用状态和 grant。

## 资源矩阵

| 资源/操作 | admin | reviewer | auditor | operator | 执行点 |
|---|---|---|---|---|---|
| 登录、读取自身身份 | 是 | 是 | 是 | 是 | `services/identity.py` |
| 列出/读取本项目、文档、审查状态 | 是 | 是 | 是 | 是 | `services/projects.py`、`documents.py`、`review_management.py`（租户内） |
| 创建/更新项目、上传文档、校正、确认上下文 | 否 | 是 | 否 | 否 | `services/projects.py::require_write`、`documents.py::require_reviewer` |
| 发起/恢复/重试/取消审查 | 否 | 是 | 否 | 否 | `review_management.authorize_review_control` |
| 提交人工决定、发布结果、生成报告 | 否 | 是 | 否 | 否 | `review_persistence.submit_decision`、`review_management.publish_review`、`reports.create_report` |
| 读取审查结果、引用、报告导出 | 是 | 是 | 是 | 是（仅已授予的只读接口） | `review_management._require_result_read`、`reports.export_report` |
| 登记逐文件外发授权 | 否 | 是 | 否 | 否 | `execution_authorization.approve_document` |
| 撤销逐文件外发授权 | 否 | 是 | 否 | 否 | `execution_authorization.revoke_document` |
| 读取审计事件 | 否 | 否 | 是 | 否 | `services/audit.list_events` |
| 发布/停用/回退审核配置 | 是 | 否 | 否 | 否 | `review_configurations` |
| 法规草稿/核验/发布/回退 | 否 | 否 | 否 | 需 grant | `legal_authorization.require_legal_operation` |

## 后端执行身份

后台 Worker 不伪造长期登录 Session。领取运行时，Worker 从数据库重新读取租户、原执行者、启用状态和 reviewer 角色，构造 `Principal(background_worker=True, execution_lease_id=..., execution_generation=...)`。每次写入运行/制品/决定前：

1. 租户和用户仍启用；
2. 用户角色仍是 reviewer；
3. 运行 `status='running'`、lease 标识和执行代次与 Worker 身份一致。

用户被停用、角色被移除或运行被接管后，旧 Worker 的后续写入被拒绝；已发出的供应商请求不能撤回，但不会继续产生新的副作用。

## 外发授权判定顺序

1. 认证会话或 Worker 执行身份有效；
2. 机构策略启用，供应商和用途在允许集合内，授权期限不超过策略上限；
3. 当前文档版本存在活动授权，且 `document_sha256`、`parse_version` 与冻结快照一致；
4. 文档当前哈希仍等于冻结哈希；
5. 撤销优先：`state='revoked'` 或已过期的行不进入允许集合；
6. 每次出站最小化前重新查询，不用进程启动时的快照。

产品模式没有环境变量哈希白名单；JSONL 注册表只属于本地验证装配。前端展示的授权状态来自服务端，前端不能自行推断授权成功。
