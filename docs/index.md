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

## 需求追踪规则

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

