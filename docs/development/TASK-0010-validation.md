# TASK-0010 本地验收记录

- 日期：2026-10-14
- 分支：`work/TASK-0010`
- 基线：TASK-0009归档提交 `50ee5b11ec850b24ed5dfcce36c8e86e45f06af7`
- 源码候选提交：`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`
- 任务状态：本地验收通过，远程源码 CI 与归档提交 CI 待执行。没有推送远端。

TASK-0010复用TASK-0009的 `ReviewEngineRun`、`ReviewArtifact`、`ReviewDecision`、`ReviewResult`、`publish_result` 和 LangGraph PostgreSQL Checkpoint。没有另建结果发布系统。法规支持绑定尚未批准，Evidence Checker现有门禁保持不变，人工决定不提升 `evidence_status`。

## TASK0010-001：人工复核与审计

`submit_decision` 对请求身份、租户、角色、run、冻结快照哈希、任务状态及Finding归属重新校验。接受、修改、驳回均保存不可变前后状态、原因、操作者、时间、请求幂等身份、request trace 和 run/snapshot 身份。可编辑字段使用白名单，不能通过修改正文伪造证据或引用。重复请求重放原决定；并发决定由数据库唯一约束裁决；非审核角色被拒绝并审计。

`approved_findings` 按已持久化的决定投影最终结果，保留独立证据状态；发布仍调用TASK-0009的幂等发布逻辑。空结果确认也保留决定事实。

证据：

- `tests/test_review_reports.py::test_task0010_human_projection_keeps_evidence_status_separate`：accept/modify/reject三种投影均保持原 `evidence_status` 并记录原因。
- `scripts/check_review_engine.py::verify_review_engine`（由 `scripts/check_legal_publications.py` 在真实PostgreSQL执行）：接受决定前后值、原因、snapshot绑定、请求幂等、并发审核员竞争、非审核角色拒绝/审计；同时验证TASK-0009人工中断恢复、Checkpoint、有限重试、取消、撤权和并发幂等发布。
- `scripts/check_postgres.py`：增量/重复迁移、ORM漂移、API、RLS、租户复合外键、并发和事务回滚通过。

## TASK0010-002：不可变报告、原文定位与导出

报告只从已发布 `ReviewResult` 及冻结run/snapshot生成。结构化报告内容以不可变 `ReviewReportContent` 固定，并由Word/PDF两个渲染器共用；输出文件存放在带SHA-256和snapshot哈希的不可变 `ReviewReport` 中。数据库唯一约束保护同结果/格式/模板的复用以及租户幂等身份。Word使用DOCX包，PDF使用内置CID中文字体映射，不依赖个人字体文件路径。

引用通过原始document ID、原始字节哈希、片段revision、locator、页码/坐标系统和摘录哈希绑定；服务端以冻结候选制品及历史片段修订精确重解析，失配则失败关闭，不以全文搜索猜测位置。报告导出重新校验当前身份、租户、角色、项目及内容哈希并记录审计。历史引用另有经授权的片段解析接口。

证据：

- `tests/test_review_reports.py::test_task0010_word_and_pdf_are_real_parseable_chinese_reports`：真实解析DOCX/PDF，检查中文、证据状态和源定位字段。
- `scripts/check_review_engine.py::verify_review_engine`（真实PostgreSQL）：两格式共享同一个结构化报告版本、DOCX/PDF可解析、幂等生成复用、冻结文档原文精确回查、授权导出及审计通过；租户管理员导出被拒绝且生成拒绝审计。
- `scripts/check_postgres.py`：迁移漂移、RLS及数据库约束通过。

## 验证结果

| 检查 | 结果 |
|---|---|
| `scripts/verify.ps1 -Mode Full`，运行于源码候选 `ab878ecd9f5df5d60ea4e27fe7edc451246ca75e` | 504 passed，0 failed/error/skipped；JUnit `.verification/pytest-result.xml` |
| Full 静态检查 | 契约与生成一致性、Ruff、Mypy 85源文件通过 |
| Full 真实启动检查 | 本机HTTP健康200/未知路径404/request ID匹配；登录、项目创建/读取/版本、注销撤权通过 |
| `scripts/check_postgres.py`，PostgreSQL 16 | 迁移、API、RLS、租户FK、并发和回滚通过 |
| `scripts/check_legal_publications.py`，PostgreSQL 16 | 法规生命周期及TASK-0009审查/恢复/证据门禁；TASK-0010决定、报告、回查、导出与权限并发通过 |

Full有两个既有 `pypdf.add_js` 弃用警告；不影响测试结果。所有测试使用合成数据、离线网关和一次性PostgreSQL容器，容器在退出时停止并移除。没有调用在线模型供应商，也没有使用真实招标文件或真实凭据。

## 限制与后续

- DEC-002仍未批准，模型生产路由保持关闭。`create_app`允许宿主显式注入已授权 `ReviewEngine`；默认不构造网关或执行模型调用。未注入时，resume API返回服务不可用。
- 源码候选尚无远程GitHub CI证据；TASK-0010仍为 `in_progress`。未得到本次远程写入授权，因此未推送。按项目流程，用户普通推送后应核验源码CI，再记录验收提交，并在归档提交CI通过后将任务移动到 `tasks/completed/`。
- 本任务未实现前端工作台；TASK-0011及后续任务未启动。

TASK-0011可复用 `ReviewReportContent` / `ReviewReport` 不可变制品、`report_content_id`、结果/snapshot/content哈希、现有报告生成与导出服务，以及授权历史片段解析接口。
