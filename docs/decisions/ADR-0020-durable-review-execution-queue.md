# ADR-0020：审查运行的持久调度与租约接管

- 状态：已采纳（产品交付规划 U04）
- 日期：2026-10-17
- 任务：TASK-0028 / U04

## 背景

`ReviewEngineRun` 已保存哈希固定的输入快照，LangGraph 使用 PostgreSQL Checkpoint；但 API 的创建、恢复与重试请求仍等待完整引擎调用。运行记录没有持久调度动作、领取租约或执行代次，部署重启后无法安全判断谁拥有执行权。U02 已冻结作业、身份、未知调用及报告语义。

## 决策

1. 继续复用 `review_engine_run` 作为运行记录和持久队列，不另建第二份审查账本。以 `action`（`start`/`resume`/`retry`）、`scheduled_at`、`lease_id`、`lease_until` 和单调递增的 `execution_generation` 增量登记调度与领取。
2. API 在完成鉴权、冻结并提交输入快照后只登记队列意图并返回；独立 worker 轮询活跃租户元数据，然后逐租户设置 RLS 上下文、原子领取一个到期动作。跨租户扫描只读取租户标识，不以 worker 角色读取跨租户项目/文档/运行内容。
3. worker 使用持久运行的原始 `actor_id` 作为审计主体；每次执行重新校验租户、账户、当前角色和项目/资源授权，不复用 JWT，也不伪造长期 HTTP Session。失效账户/租户或权限不足的动作失败关闭。
4. 每次租约领取增加执行代次；worker 和 LangGraph 写入前检查租约 ID/代次。被接管的旧 worker 不能覆盖状态或追加新执行产物。心跳仅续租当前持有的租约。
5. 旧快照、运行身份、Checkpoint 和已存储结果不重解释。迁移只新增调度列与索引并以原 `updated_at` 设定历史 `scheduled_at`。没有租约的旧 `running` 行不自动被新 worker 接管；部署/迁移前须按 U13 的停机顺序核对在途执行。
6. 持久调用登记在调用前写入确定调用身份；收到响应时先持久化响应引用和哈希。若 worker 在发送后、响应持久化前失去结果，调用标记/推导为 `unknown`，不自动补发；恢复从已写 Checkpoint/已存产物继续。供应商 exactly-once 不作假设。

## 后果

- API 执行路径可以在模型流程运行期间快速返回，worker 可在新进程中处理队列。
- 多 worker 依赖 PostgreSQL 原子领取、RLS 与执行代次 fencing；不能用 SQLite 并发试验替代 PostgreSQL 验收。
- `unknown` 调用不会被通用 retry 转成新供应商请求；如何在未知账务下人工结算/释放预算由 U05 冻结并实现。
- 迁移仅在本地/专项测试环境验证；生产应用、数据库迁移、真实模型/数据外发均须等待各自 D3/D4 决策。

## 备选方案

- API 内存队列：进程重启后丢失任务，并且多个 API 副本不能协调。
- Redis-only 消息身份：当前没有已验证的持久确认与 PostgreSQL 运行/Checkpoint 的原子边界。
- 以 HTTP JWT 作为后台身份：Token 会过期或撤销，且会把浏览器 Session 生命周期错误地带入后台执行。
