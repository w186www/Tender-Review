# LangGraph 状态、依赖与节点契约

基线：ADR-0005 / `ComplianceReviewState` v1alpha2。TASK-0009 已实现审查图、持久恢复和结果发布基础；TASK-0010/0011 的人工审核管理、报告渲染和前端仍未实现。独立能力可单测；有数据依赖的节点不得直接并行。

## 主图

```mermaid
flowchart TD
    START --> load_context
    load_context --> parse_document
    parse_document --> quality_gate
    quality_gate -->|不合格| human_parse_review
    human_parse_review -->|持久中断| END
    quality_gate -->|通过| plan_review
    plan_review --> candidate_discovery
    candidate_discovery -->|按稳定 skill_id 动态分发| skill_work
    skill_work --> candidate_join
    candidate_join --> legal_retrieval
    legal_retrieval --> semantic_analysis
    semantic_analysis --> merge_findings
    merge_findings --> evidence_check
    evidence_check --> human_risk_review
    human_risk_review -->|合法决定后恢复| publish_result
    publish_result -->|结果持久化；仅交接| generate_report
    generate_report --> finalize_task
    finalize_task --> END
```

## 数据依赖

`candidate_discovery` 从原文和上下文产生规则候选、语义线索与每类 Skill 的检索主题。语义线索不构成合规结论；检索覆盖既包括候选问题也包括 Skill 检查清单，不能仅检索已经命中的规则。

`legal_retrieval` 消费上述线索，按项目地区、采购类型、审查基准日和法规快照过滤。`semantic_analysis` 明确消费原文、项目上下文、候选与法规条款。检索失败或无适用依据时，模型只能输出疑似或证据不足。Evidence Checker 再执行独立校验。

解析/上下文不足时停止相关审查，不把未审查项当作“无风险”。TASK-0009的`parse_document`读取TASK-0005已持久化的解析结果，不替代解析Worker；`human_parse_review`只建立持久中断，本任务不实现片段修订管理。

## 节点与字段归属

| 节点 | 必需输入 | 独占输出 | 失败策略 |
|---|---|---|---|
| load_context | 租户、项目、任务 ID | project_context_ref、review_snapshot_ref | 无权或关键上下文缺失时终止/等待确认 |
| parse_document | document_refs | section_index_ref、parse_quality_ref | 有限重试，资源上限 |
| quality_gate | parse_quality_ref | 路由与质量门禁记录 | 低质量转人工 |
| human_parse_review | 原文定位、低质量原因 | 持久中断状态 | 本任务没有修订管理；保持 waiting_human |
| plan_review | 上下文、章节索引、快照 | review_plan_ref | 缺少已发布配置则失败 |
| candidate_discovery | 审查计划、原文 | discovery_ref、rule_findings_ref | 每个Skill输出覆盖/失败记录 |
| legal_retrieval | discovery_ref、快照、上下文 | retrieval_results_ref | 缺证据显式标记，不造证据 |
| semantic_analysis | 原文、候选、retrieval_results_ref | model_findings_ref | 无效结构最多2次尝试；不可重试错误失败关闭，可重试供应商错误经显式有限retry入口重试 |
| merge_findings | 候选、规则、模型输出 | findings | 稳定ID去重，保留来源与冲突 |
| evidence_check | findings、原文与法规 | findings、pending_review_ids | 按证据状态降级，不覆盖人工决定 |
| human_risk_review | 证据结果、待审列表、持久决定 | 审计绑定的已复核摘要 | interrupt；没有完整决定时不得发布 |
| publish_result | 已复核结果、版本快照 | PostgreSQL不可变结果引用 | 行锁、快照哈希、数据库唯一约束和事务 |
| generate_report | 已发布不可变结果版本 | 当前为显式空 `report_ref` handoff | 报告渲染属于TASK-0011，不假报完成 |
| finalize_task | 已发布结果 | `result_published` | 不产生报告或完成事件 |

State 中的 findings 只保存有界摘要；完整候选、逐条证据和审计历史保存在租户隔离的 PostgreSQL 制品/结果表。运行时总量上限64 KiB，最多100个输入文档、100条错误、500条finding和100个候选；超出时失败关闭。动态工作项以冻结run内稳定的`skill_id`标识；`skill_expected` / `skill_finished`集合必须完全相等后汇合，失败覆盖保存在对应制品中。共同集合使用稳定reducer，完整Skill结果只经制品引用读写。

`human_risk_review`只接收持久化、逐finding的合法人工决定；没有决定不能发布。`publish_result`使用数据库事务、冻结快照身份、唯一约束和行锁写入不可变结果。报告节点只提供后续报告任务的交接边界，当前返回`report_ref=null`；最终状态保持`result_published`，不能误报为报告已生成或任务已完成。

## 并行与汇合

- 可以按章节、Skill并行发现候选和检索；分析必须等待所属工作单元的法规检索完成。
- 静态分支用显式多前驱汇合；动态Skill分发由调度节点分配稳定 work_item_id，并以本轮 expected/finished 集合汇合。
- 所有工作单元完成或返回可见失败记录后才能融合；不得“先返回的结果即全量结果”。
- 独立分支优先写各自的引用字段。共同集合使用按稳定ID合并的 reducer；共享 errors 也需专用reducer。禁止并行写 status 或一个未配置reducer的字段。
- 幂等键包含 tenant_id、review_task_id、run_id、work_item_id 和配置快照版本；重试不得追加重复候选。

## State 的唯一来源

`contracts/schemas/compliance-state.schema.json` 是唯一字段来源。运行 `python scripts/generate_state.py` 生成 `src/bidding_compliance/graph/state.py`。生成文件禁止手改，统一检查比较生成结果并拦截漂移。TypedDict 负责静态类型，边界处仍需 JSON Schema 校验；生成类型不表示已实现运行时验证。

Schema 中非必填字段生成 NotRequired，nullable 字段生成 `| None`；GraphError 中可选字段遵循相同规则。State 初始版本为 v1alpha2。

U02 产品化状态契约（`product-review-execution.v1alpha1`）是与 LangGraph checkpoint 分离的持久运行摘要：它补充执行身份、当前授权检查、覆盖、模型调用结果未知及业务完整度，不替换或重解释 `ComplianceReviewState v1alpha2`。运行生命周期继续由 `review_engine_run`/ReviewTask API 负责；`result_published` 不表示报告渲染成功。详见 `docs/development/product-contract-baseline.md` 与 ADR-0019。

## Checkpoint、重试与版本

- Checkpoint 使用 LangGraph PostgreSQL `AsyncPostgresSaver`；隔离键由 tenant_id、review_task_id 和 run_id 组成，PostgreSQL RLS 再按tenant线程前缀隔离。每个run使用PostgreSQL session advisory lock防止多个Worker同时恢复；恢复前重新校验身份、任务权限和冻结输入。
- review_snapshot_ref 指向冻结的输入哈希、规则、法规、Skill、Prompt、模型profile和参数快照。恢复不得静默使用新版本。
- 网络、限流等临时错误有限重试；权限和前置条件错误不自动重试。模型Schema错误使用受限修复策略，与基础设施重试分开计数。
- 文档、上下文或版本快照发生变化时创建新run；旧Checkpoint保持可追溯，升级须明确迁移或拒绝恢复。
- 取消与不可重试失败保持持久状态；模型临时错误只允许有界重试。恢复/重复投递复用完成的节点和结果，数据库发布幂等不承诺外部系统物理exactly-once。

