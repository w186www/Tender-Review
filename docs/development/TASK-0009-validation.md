# TASK-0009 验收与归档记录

- 日期：2026-10-14
- 分支：`work/TASK-0009`
- 基线：TASK-0008 归档提交 `c51eec293de47226ea271e599ddc2d773f43ea1c`
- 源码提交：`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`
- 任务状态：本地归档候选。TASK0009-001/002本地验收通过；用户确认源码提交及本地验证记录提交的必要远程CI通过。只有本归档提交的远程所有适用作业及`verify-required`成功后，才正式宣布`completed`。

## 正式验收

### TASK0009-001：模型分析接收法规结果，缺证据只能降级

本地通过。`scripts/check_review_engine.py` 通过真实业务图运行 TASK-0007 确定性候选发现、TASK-0006 已发布法规检索及离线 `ModelGateway`。离线网关断言模型请求包含真实候选、法规检索结果和逐候选法律证据；图边依赖保证候选发现先于法规检索、法规检索先于语义分析。模型不调用供应商 SDK，也不能提供 Evidence Checker 的可信状态。

`src/bidding_compliance/services/evidence_checker.py` 独立重定位并核对文档版本、片段修订、原文哈希及冻结法规发布/修订/检索结果。`tests/test_evidence_checker.py` 覆盖有效/篡改文档引用、有效法规引用、未核实法规、法律证据缺失和结论降级。当前没有批准的规则到法规绑定，故即使文档和已核实法律文本各自有效，也只标为 `suspected`；缺失支持为 `insufficient_evidence`，不输出 `confirmed`。集成链路断言模型输出不能越过独立门禁。

### TASK0009-002：Worker 重启、中断恢复和重复投递不重复发布结果

本地真实 PostgreSQL 通过。`ReviewEngine` 使用 LangGraph `AsyncPostgresSaver`，Checkpoint 的线程身份绑定 tenant、review task 和 run；恢复入口重新验证身份、租户、任务、输入快照及持久化人工决定。专项测试包括：

- 新建子进程从 PostgreSQL Checkpoint 恢复人工中断并完成发布，恢复时不再次调用模型；重复投递返回持久结果。
- 两个独立 Worker 实例通过各自 PostgreSQL 连接并发恢复同一 run（并发调用在一个测试进程内）。只允许一个发布；检查最终运行状态、由新调用重新读取的持久 Checkpoint 状态、唯一结果记录、制品数和人工决定数，并用 `NoCallGateway` 证明恢复没有重新执行模型副作用。独立子进程恢复另由前一用例覆盖。
- 人工决定缺失时发布被拒；已撤销身份不能恢复；冻结项目上下文变化时拒绝旧 run。
- PostgreSQL 触发器在事务提交前拒绝 `review_result` 插入；回滚后结果数为 0，run 仍为 `waiting_human`。
- 提交确认丢失通过包装真实 `Session.commit()` 注入：先执行数据库真实提交，再在返回调用方前抛出连接错误。新会话确认结果和 `result_published` 状态已持久化，随后重试返回相同 `result_id`，持久化结果仍恰好一条。
- 另有真实 PostgreSQL 并发重复发布、持久化决定、有限重试、取消、Checkpoint RLS 和重复图投递检查。

## 验证

| 检查 | 结果 |
|---|---|
| Focused：证据门禁、法规证据、候选发现 | 13 passed；Quick、契约/生成、秘密扫描、Ruff、Mypy 80 个源码文件通过 |
| 最终 Full：`scripts/verify.ps1 -Mode Full` | 500 passed，0 failed/error/skipped；JUnit `.verification/pytest-result.xml` |
| Full 静态与启动检查 | 契约/生成、Ruff、Mypy 80 文件、真实 HTTP 健康/404/请求 ID、登录/项目/版本/注销撤权通过 |
| PostgreSQL 16：`scripts/check_postgres.py` | 迁移、API、RLS、租户 FK、并发及回滚通过 |
| PostgreSQL 16：`scripts/check_legal_publications.py` | 法规生命周期及 TASK-0009 图、恢复、身份、快照、并发、发布故障注入通过 |
| 工程记录归档 Quick | 本次归档记录变更后通过；仓库、契约、生成状态与秘密扫描通过；不运行时测试、不重复 Full |

Full 有两条既有 `pypdf.add_js` 弃用警告，不影响结果。测试使用合成数据、离线网关和本机一次性 PostgreSQL 容器；容器已清理。没有访问 OpenAI/Anthropic，也没有使用真实招标文件或真实凭据。

## 里程碑门禁与远端状态

M2 的正式退出检查可由先前已完成任务的验收证据核验：TASK-0007 候选 provenance 与稳定定位、TASK-0006 法规范围过滤和快照证据、TASK-0008 两家适配器合规测试均有本地及对应远程 CI 证据。因此 M2 退出检查已满足，roadmap 标记 M2 `completed`、M3 `in_progress`。TASK-0009 本身依赖的 TASK-0005 至 TASK-0008 均已完成；M3 整体仍未完成。

远端为 `https://github.com/w186www/Tender-Review.git`。本地 `origin/work/TASK-0009` 跟踪引用指向`99ce00f7b7bef09285e280b9b909143022c847b4`，且源码提交`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`是其祖先；用户确认源码提交和验证记录提交已推送，必要远程CI通过。当前环境调用GitHub API返回“未知主机”，`gh` CLI不可用，因此无法取得上述运行的独立运行ID与逐作业页面；可在[该分支的 GitHub Actions 运行列表](https://github.com/w186www/Tender-Review/actions?query=branch%3Awork%2FTASK-0009)查看。

本地归档候选已将`tasks/active/TASK-0009-langgraph-engine.yaml`移入`tasks/completed/`并更新状态。归档提交仍须普通推送，且其对应远程所有适用作业和`verify-required`成功后，任务才满足仓库完成定义。本次不得强推或覆盖远端改动；若本机网络仍不可用，保留该本地提交供用户手动推送，并保持项目总体状态为待远程归档CI确认。

本地归档候选提交在远端分支为其祖先时，使用普通非强制推送：

```powershell
git push -u origin work/TASK-0009
```

不得使用 force push。若推送因远端已有提交而拒绝，应先核对远端历史，不覆盖它。归档提交的CI状态目前待运行/核验。

## 剩余生产限制

- DEC-002 尚未批准，生产模型路由继续禁用；真实 OpenAI/Anthropic 在线调用尚未执行。
- TASK-0008 预算账本仅保证单进程一致性；本任务没有声称多进程生产预算安全，也不将它作为本任务离线局部验收的替代条件。
- 规则到法律条款的充分支持绑定尚未批准，当前有效文档/法规支持最多为 `suspected`，需要人工审查；无有效证据只能降级。
- TASK-0010 人工复核管理、TASK-0011 报告/前端及 M3 端到端退出检查尚未完成。本轮未启动 TASK-0010。
