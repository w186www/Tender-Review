# 文档入口与权威性

## 开发依据

| 内容 | 文件 | 何时必须更新 |
|---|---|---|
| 当前项目状态 | `PROJECT_STATE.md` | 每个任务结束前 |
| 功能需求 | `requirements/functional.md` | 行为范围变化时 |
| 安全需求 | `requirements/security.md` | 信任边界、权限、数据处理变化时 |
| 非功能需求 | `requirements/non-functional.md` | 性能、可靠性、运维指标变化时 |
| 验收标准 | `requirements/acceptance.md` | 交付判定口径变化时 |
| 系统架构 | `architecture/system.md` | 模块、依赖或部署边界变化时 |
| LangGraph | `architecture/langgraph.md` | State、节点、路由和恢复变化时 |
| 数据流与溯源 | `architecture/data-flow.md` | 数据引用、发布或关联ID变化时 |
| 部署架构 | `architecture/deployment.md` | 环境或服务边界变化时 |
| 模型适配 | `architecture/model-gateway.md` | 模型调用协议或路由变化时 |
| 安全架构 | `architecture/security.md` | 威胁、控制或审计方式变化时 |
| 架构决策 | `decisions/` | 出现长期、跨模块选择时 |
| 里程碑与依赖 | `development/roadmap.yaml`、`development/roadmap.md` | 任务或验收阶段改变时 |
| 接口与数据 | `../contracts/` | 编码前，且与实现同步 |
| 身份与数据库启动 | `development/identity-data-start.md` | 认证、权限、迁移、引导与数据库部署变化时 |
| 安全文件接入启动 | `development/secure-ingestion-start.md`、`development/ingestion-support-matrix.md` | 上传、扫描、解析、OCR、质量信号、支持范围、人工校正和容量前检变化时 |
| 单写入者开发与验证 | `development/development-workflow.md`、`development/testing-standard.md` | 实施、验证档位与验收规则变化时 |
| 法规摄取与检索 | `development/legal-retrieval-start.md` | 来源核验、有效区间、范围、快照和检索算法变化时 |
| 前端工作台 | `development/frontend-workbench.md`、`development/TASK-0011-validation.md` | 前端启动、契约客户端和 TASK-0011 验收状态变化时 |
| 面试演示 Demo | `development/TASK-0020-demo-gap-assessment.md`、`development/TASK-0020-validation.md` | 本地离线演示启动、前端状态标识或完整浏览器流程验收变化时 |
| 合成数据真实 Qwen 在线演示 | `development/model-gateway-online-demo.md`、`decisions/DEC-002-qwen-demo-authorization.md`、`decisions/ADR-0017-bailian-qwen-chat-adapter.md` | 百炼 Chat 适配、在线路由、合成数据外发授权、模型预算与审计发生变化时 |
| 真实文件离线诊断与待批 Qwen 外发提案 | `development/TASK-0022-validation.md`、`decisions/DEC-005-real-tender-qwen-evaluation-authorization.md` | 单个经授权本地招标文件的安全解析、离线规则/法规/证据检查及其独立在线授权时 |
| 离线检索评测、Mock-only云Embedding与Tesseract OCR | `development/TASK-0018-validation.md`、`decisions/ADR-0015-offline-retrieval-ocr-provenance.md`、`decisions/ADR-0016-task-0018-cloud-embedding-contract.md` | 法规召回、云Provider接口、隔离OCR基线或运行版本追溯变化时 |
| 产品租户执行授权与预算 | `decisions/ADR-0021-tenant-execution-authorization-and-budget.md`、`architecture/authorization-matrix.md`、`development/product-contract-baseline.md` | 产品模式供应商/用途策略、逐文件外发授权/撤销、PostgreSQL 预算或历史账本导入变化时 |
| 本地准备与真实阻塞 | `development/local-preparation-status.md` | 判断哪些离线实现可继续、哪些需要 D1—D4/U03 资产时 |

产品交付新增的状态与兼容语义见 [产品契约基线](development/product-contract-baseline.md)，FR/SEC/NFR/AC 至实施单元及 G3 记录的映射见 [产品交付追踪表](development/product-delivery-traceability.yaml)。

产品评测样本分区、候选标注状态和复用边界见 [产品评测数据基线与标签协议](development/product-evaluation-protocol.md)。

## 需求追踪规则

TASK-0023 真实 Qwen 业务验收已完成（DEC-006 在正式网页完成审查→复核→发布→Word/PDF 闭环），TASK-0024 已完成法规检索解阻、参考候选展示与三案例排名评测；详情见 [TASK-0023 验证记录](development/TASK-0023-validation.md)、[TASK-0024 验证记录](development/TASK-0024-validation.md) 与 [三案例检索证据摘要](development/TASK-0024-case-evidence.md)，公开/私有演示入口见 [演示指南](DEMO.md)。

TASK-0025 已完成证据分类加固、账本连续性防护与 CI 超时修复，Full CI 全绿。

TASK-0026 已完成单机容器化部署的编排、持久化、反向代理与本地端到端验收（未改业务代码）；部署与运维见 [`deploy/README-demo.md`](../deploy/README-demo.md)，实测证据、资源数据与真实 Qwen 阻断见 [TASK-0026 验证记录](development/TASK-0026-validation.md)；上云前的审计与测算保留在[面试演示部署方案](development/DEPLOYMENT-DEMO.md)。目标 ECS 上尚未部署。

TASK-0027 第七轮实现、Full、CI 及经单独授权的公网真实路径已有记录，但正式 TASK 仍为 `in_progress`：零候选执行缺口与外发授权端点的 OpenAPI 漂移仍须按产品路线收尾，不以一次真实运行证明产品质量达标。见 [TASK-0027 验证记录](development/TASK-0027-validation.md)。

2026-10-18 最终状态：公网产品验收已跑通（真实 DOCX、派生真实文本 PDF、真实模型、人工复核、Word/PDF），服务器已切换到 product-postgres（PostgreSQL 为唯一授权/预算权威源，历史 460 条 reservation 已导入，真实文本 PDF 新增 17 次 LLM 全部 settled），撤销门禁 403、回退 authorized-real 再切回均验证。正式法律支持仍为 0（无独立核验、无人工规则—法规签署），扫描/图片 OCR 实测后因 LOW_CONFIDENCE_NUMERIC/碎片化转人工检查，用户独立验收未发生。U01/U02/U04/U05 已完成；U03/U07/U10 进行中；U06/U08/U09/U11/U12 有真实证据但正式单元仍待 U03/D2/完整矩阵。法规采用按 [DEC-009](decisions/DEC-009-legal-library-adoption-20261018.md) 与 [ADR-0022](decisions/ADR-0022-legal-adoption-citation-semantics.md)；D1—D4 按 [DEC-008](decisions/DEC-008-product-delivery-d1-d4-authorization-20261018.md)；专家标签仍为 0，precision/recall 未测量。U06 支持范围由[摄取支持矩阵](development/ingestion-support-matrix.md)和 tests/test_task0029_support_scope.py 覆盖；真实 DOCX 41 条风险/v3.2 报告，真实文本 PDF 13 条风险/17 次 LLM/50 饱和/1423 拒绝/0 未提交。U13/U14 新备份 20261017T213903Z 隔离恢复通过、TLS 叠加层与容量 smoke 完成，外部告警未配置。机读映射见 [`roadmap.yaml`](development/roadmap.yaml)，逐单元证据见[产品交付验证记录](development/product-delivery-validation.md)，运行状态以 `PROJECT_STATE.md` 为准。单一 planned/completed 字段不代替真实内容签署、效果验收或用户独立验收。

接续修正：上段真实文本 PDF 的“1423 拒绝”是旧字段 `rejected_units` 的 partial 批次 section_count 总和，可能重复，不是候选拒绝数。旧 DOCX 的 503 同理。当前代码改为分别保存候选拒绝数/原因/唯一原文单元/恢复结果。2026-10-18 收口状态：最终代码候选 `89766d8` 官方 Full 958 passed/0 failed/0 skipped、push/PR CI run `39107901768`/`39107907712` 全绿；仅构建并发布 api/review-worker/worker/nginx（`task0029-89766d8`），服务器 `staging/product-postgres`、迁移 `202610172000`、TLS overlay、health 200，admin/reviewer/auditor 登录均 200（历史 401 未复现）；部署前备份 `20261018T074713Z` 的隔离恢复校验通过，账本 spent ¥1.41978080/reserved 0 未变；镜像内新验证器重放既有文本 PDF 响应 29/18→34/13、恢复 5 条空白差异引用、新增模型调用 0。四组公网浏览器结果产生于上一候选 `33a7e81`，最终候选差异由镜像内重放覆盖；用户独立网页验收仍未发生。生产安全回退只允许兼容的 product-postgres 候选或 offline，旧 `authorized-real` 仅限 development/test。详情见 [PROJECT_STATE.md](../PROJECT_STATE.md) 与 [本轮验证记录](development/product-delivery-validation.md)。

- 功能：`FR-###`
- 安全：`SEC-###`
- 非功能：`NFR-###`
- 验收：`AC-###`
- 架构决策：`ADR-####`
- 开发任务：`TASK-####`

任务必须引用至少一个需求或验收 ID。代码提交和 PR 描述应列出任务 ID。关键测试名称或注释应引用被验证的 ID。

任务的 related_requirements/related_acceptance 表示关联范围；acceptance_checks 是该任务的实际验收项，完成时逐项填写evidence。关联AC不能因任务结束而自动标为完成。全局验收和发布门禁见里程碑文件。

当前法规生命周期、并发发布、全局授权及HTML/PDF来源映射决策见[ADR-0012](decisions/ADR-0012-legal-lifecycle-and-provenance.md)，历史ADR-0010长期生产方案未自动批准。

## 正式方案

完整开发与交付方案见 [reference/README.md](reference/README.md)。该 Word 文档用于正式评审和交付；若与版本化契约或已批准 ADR 不一致，应更新 Word 文档或在发布说明中列出差异。

