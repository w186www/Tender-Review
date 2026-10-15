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
| 安全文件接入启动 | `development/secure-ingestion-start.md` | 上传、扫描、解析、OCR、存储和人工确认变化时 |
| 单Codex开发与验证 | `development/development-workflow.md`、`development/testing-standard.md` | 实施、验证档位与验收规则变化时 |
| 法规摄取与检索 | `development/legal-retrieval-start.md` | 来源核验、有效区间、范围、快照和检索算法变化时 |
| 前端工作台 | `development/frontend-workbench.md`、`development/TASK-0011-validation.md` | 前端启动、契约客户端和 TASK-0011 验收状态变化时 |
| 面试演示 Demo | `development/TASK-0020-demo-gap-assessment.md`、`development/TASK-0020-validation.md` | 本地离线演示启动、前端状态标识或完整浏览器流程验收变化时 |
| 合成数据真实 Qwen 在线演示 | `development/model-gateway-online-demo.md`、`decisions/DEC-002-qwen-demo-authorization.md`、`decisions/ADR-0017-bailian-qwen-chat-adapter.md` | 百炼 Chat 适配、在线路由、合成数据外发授权、模型预算与审计发生变化时 |
| 真实文件离线诊断与待批 Qwen 外发提案 | `development/TASK-0022-validation.md`、`decisions/DEC-005-real-tender-qwen-evaluation-authorization.md` | 单个经授权本地招标文件的安全解析、离线规则/法规/证据检查及其独立在线授权时 |
| 离线检索评测、Mock-only云Embedding与Tesseract OCR | `development/TASK-0018-validation.md`、`decisions/ADR-0015-offline-retrieval-ocr-provenance.md`、`decisions/ADR-0016-task-0018-cloud-embedding-contract.md` | 法规召回、云Provider接口、隔离OCR基线或运行版本追溯变化时 |

## 需求追踪规则

TASK-0023 真实 Qwen 业务验收已完成（DEC-006 在正式网页完成审查→复核→发布→Word/PDF 闭环），TASK-0024 已完成法规检索解阻、参考候选展示与三案例排名评测；详情见 [TASK-0023 验证记录](development/TASK-0023-validation.md)、[TASK-0024 验证记录](development/TASK-0024-validation.md) 与 [三案例检索证据摘要](development/TASK-0024-case-evidence.md)，公开/私有演示入口见 [演示指南](DEMO.md)。

TASK-0025 已完成证据分类加固、账本连续性防护与 CI 超时修复，Full CI 全绿。

TASK-0026 已完成单机容器化部署的编排、持久化、反向代理与本地端到端验收（未改业务代码）；部署与运维见 [`deploy/README-demo.md`](../deploy/README-demo.md)，实测证据、资源数据与真实 Qwen 阻断见 [TASK-0026 验证记录](development/TASK-0026-validation.md)；上云前的审计与测算保留在[面试演示部署方案](development/DEPLOYMENT-DEMO.md)。目标 ECS 上尚未部署。

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

