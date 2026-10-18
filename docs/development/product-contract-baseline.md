# 产品契约与状态基线

当前实现契约：OpenAPI 0.10.5 / 契约集合 v1alpha12。下述历史阶段记录保留其发生时版本；不代表当前候选已验收。

## TASK-0029 v2 语义与制品一致性约束（2026-10-19，待验证）

- `context_review.conclusion` 描述上下文对候选疑点的关系：supported/qualified 表示支持原疑点/仅支持较窄疑点，不能配 no_issue；contradicted 配 no_issue；unresolved 配 uncertain。矛盾输出保留待人工复核，不静默抑制。reviewed_quote_sha256 必须列出本次实际发送的全部主文及关联摘录哈希（至多20个来源摘录加6个关联摘录，共26个不同哈希），反证哈希必须属于该集合；未发送摘录不要求模型复核，容量删减单独记录。
- 语义批次制品统一使用 semantic_analysis_batch_N，最终 model_analysis 仅作为汇总。批次保存规范化输入哈希（含候选、关联摘录、项目分类、同源候选、检索结果、提示/Schema/策略身份）和排序候选 ID；新响应、缓存响应使用相同验证。哈希缺失/不符时停止恢复，不自动付费重放；旧无绑定批次不得补造来源。
- 报告按实际 model_analysis.related_document_evidence_ref 读取上下文并核对租户、task、run、内容哈希和快照。缺引用的历史分析不补造上下文；不得从同类制品中任选一条。
- v2 多段引文按冻结文档位置及字符区间规范排序后生成身份和稳定定位，保留全部独立精确引文，不以模型返回顺序决定候选身份。归并保留代表项文本及来源/分类/严重度冲突，不使用固定摘要补写事实。
- v2 被拒候选同样先规范化引用集合再校验，拒绝身份、错误选择与恢复族主锚点不依赖模型返回顺序；片段内部唯一连续原文校验不放宽。标题、描述、推理摘要、建议分别检查条件反证，否定与显式条件只在本句内解释，不跨字段抵消冲突。
- 报告/定位中的 candidate_discovery 与 llm_candidate_discovery 制品按租户/task/run/kind 校验唯一性和内容哈希；覆盖制品确实缺失时保留旧运行的 unknown/not_applicable 回退，不在歧义时任选第一条。普通标量计数查询不受影响。
- v1 提示文本、响应 Schema 和已发布结果不重写。新 v2 上下文关系约束仅用于 v2；证据真实性与安全纠错、禁止摘要补造事实适用于尚未发布的在途计算，须保留原始制品。旧缓存无法核实身份时明确阻塞，不暗中重跑。
- v2 最多 100 个候选，初始每批 4 个，按容量拆分后最多 100 批。身份登记上限不是费用授权；每次请求仍受实时逐文件授权、租户策略和原子预算约束。
- 项目分类（地区、采购/项目/主体类型、采购方式、法规框架）与同源候选的疑点描述，仅在既有授权覆盖该文件及其审查用途时发送。最小化器只输出白名单分类字段和脱敏后的描述，用户姓名、备注及任意额外字段不外发；不扩大供应商、文件、用途或预算范围。
- DEC-009 允许已采用库内条文参与带条件的参考分析和报告引用；参考引用须匹配实际选中的条文及支持关系，不能转为自动违法认定，不能把无关条文作为其他结论的授权。

状态：U02 冻结的本地开发契约；由 [ADR-0019](../decisions/ADR-0019-product-execution-and-review-contracts.md)、`contracts/schemas/product-review-execution.schema.json` 与 OpenAPI 0.10.5 / 契约集 v1alpha12 共同约束。U04 经用户授权只增加取消操作；U05 增加产品模式逐文件授权绑定字段/撤销操作；TASK-0029 明确错误响应 `details` 承载可忽略的字段级补正提示，并以 [ADR-0021](../decisions/ADR-0021-tenant-execution-authorization-and-budget.md) 明确 PostgreSQL 授权/预算权威源。TASK-0029 后续为法规参考新增可选身份、来源、适用框架和采用状态字段；它们不改变正式证据资格。现有状态和响应 Schema 保持兼容。它不代表生产部署或 D1—D4 的外部授权。

## 1. 生命周期所有权

| 对象 | 权威字段/存储 | 语义 |
|---|---|---|
| 文档 | 当前 Document API 与摄取记录 | 文档是否可读取/审查；审查入口仍要求 `ready`。支持范围、解析质量与校正失效由 U06 冻结，本基线不重解释既有文档状态。 |
| 摄取作业 | `ingestion_job.status` | 仅 `queued`、`running`、`succeeded`、`failed` 描述解析作业；`succeeded` 不表示文档已通过质量门禁。 |
| 审查执行 | `review_engine_run.status` / ReviewTask API | `queued`、`running`、`waiting_human`、`result_published`、`failed`、`cancelled`。审查生命周期不使用 `succeeded`。 |
| 审查完整度 | `product_execution.completion_status` | `pending`、`complete`、`partial`、`failed`、`cancelled`；与运行生命周期分开。 |
| 覆盖 | `product_execution.coverage` | `complete`、`partial`、`failed`、`not_applicable`、`unknown`；有计划单元及完成/失败/未处理计数，另显式记录截断、饱和和原因。 |
| 人工决定 | ReviewDecision / immutable result | 仅授权审核员按任务版本逐项决定并留理由；决定“接受”不更改法规核验状态，也不自动证明违法。 |
| 报告 | `ReviewReport.schema_version` + result_id | 只从已发布不可变结果生成。重复渲染同一 `result_id` 不重跑审查；报告创建/渲染失败不把执行标为完成。 |

审查生命周期转换：`queued → running → waiting_human → running → result_published`；执行中可以转 `failed` 或 `cancelled`。有界重试仅对明确可重试失败开放，保留同一冻结输入/快照身份并递增 attempt；输入或配置改变则创建新 run。已发布结果是终态。取消与重试竞争以数据库原子条件更新/lease 世代裁决，输掉竞争的一方不能产生后续副作用。实现与并发证据属于 U04。

## 2. 覆盖、候选与结束条件

- `candidate_count = 0` 是合法发现结果，不等于“整个文档没有风险”。只有所有应审非空单元已有终结覆盖（完成或明确不适用）、没有失败/未处理单元、没有未解决截断/饱和、没有未知模型调用，完整度才可为 `complete`。
- 零候选完整路径跳过语义分析调用；报告仍需审核员显式 `confirm_no_findings` 才能将“无待处理发现”发布。缺确认时保持人工待处理，不能以空数组自动发布。
- 任一应审单元失败、未处理、输出截断或供应商饱和且未由有界细分补全时，覆盖为 `partial` 或 `failed`，不能展示为完整无风险。分批与后续补扫要保留原始覆盖计划和结果身份。
- 全部规则/模型来源及失败原因保留；融合不得因先返回的分支结果而标成全量完成。`not_applicable` 需要具体范围理由，不能用来掩盖缺失执行。

## 3. 模型调用、执行身份与授权

- 调用状态：`prepared → reserved → dispatched → succeeded | failed | unknown`。未发送的准备/预留失败可安全停止；一旦请求可能已发出但没有可核实响应，记 `unknown`、用量 `unknown`，保留预算预留并暂停自动重发。只有经权威调用记录核实未发生副作用后，才可走有界恢复路径；不承诺供应商 exactly-once。
- 每个 `call_id` 绑定租户、任务、run、node、attempt、冻结配置、请求哈希、授权决策与预算预留。原始正文、凭据和完整响应不进入 State 或普通审计日志；State 仅保存摘要/引用。
- `identity.requester_id` 是发起请求的用户；`worker_identity` 是服务端执行主体。JWT/浏览器 session 不作为后台身份。Worker 在领取/恢复以及每个外部或不可逆副作用前，重新检查当前用户/租户/资源权限及撤权状态。
- 外发必须同时满足服务端 provider/model/data policy 与每一输入文件的授权；每次调用的文件哈希集合必须是当前授权集合的子集。授权请求体不接受 caller 自报 hash/actor。撤权即时阻止后续副作用；已发出但结果未知的调用保留为未知并审计。
- 产品模式 PostgreSQL 是作业调度、lease、授权和预算账本的权威源，变更与审计在事务边界内提交（U05 已实现迁移 `202610172000`）。现有单进程/JSONL/SQLite 授权只保留为受控历史导入源，不充当多 Worker 产品权威源；`scripts/migrate_execution_ledgers.py` 只读导入并保留来源 ID、未知预留、费用和 scope 映射。U02 未新增迁移；U04/U05 已分别实现向前兼容迁移和对账。产品模式装配为 `DEPLOY_REVIEW_MODE=product-postgres`，不使用环境哈希白名单。

## 4. 证据、检索和报告

- 排序相关性、法规版本核验、适用资格、可引用法律证据、Finding 的证据强度、人工决定是五个不同维度。相似度/RRF 分数或模型输出不能提升法律资格。
- 文件原文引用须能从冻结输入哈希、解析/修订版本、稳定定位符及摘录哈希重核。检索命中但未核验/不适用的法规保留为 `legal_references`，不能计入 `citable_legal_evidence`。只有服务端重核发布快照、版本、生效日期、地区/主体/采购制度和引用后才可计入。
- 真实 RAG 顺序为受授权候选发现 → 法规检索 → 基于原文与法规候选的分析 → 服务端证据重核。模型只能返回受限引用 ID 与建议；没有可用法条则保留证据不足。DEC-009 已允许采用库内条文作为参考分析及报告引用，不再以逐条独立核验作为工程交付前置；独立核验状态和专家标签仍须如实呈现，不伪造专业效果指标。
- 报告 v1/v2 按原 schema 和保存的 result 快照读取；新增 v3 才要求 `assessment_scope.product_execution`，包含完整度、覆盖、未处理、截断/饱和和未知调用摘要。零候选 complete 的 v3 报告必须带人工 `confirm_no_findings`。旧版本不补造缺失信息、不按新规则重算。

## 5. 兼容与消费矩阵

| 消费者 | 契约责任 | 兼容要求 |
|---|---|---|
| API | OpenAPI 0.10.5；逐文件授权为 `POST .../external-authorization`，撤销为 `POST .../external-authorization/revoke`；运行取消为 `POST /review-tasks/{reviewTaskId}/runs/{runId}/cancel` | 0.10.5 增加可选 failed_rescan_units，表示成功父批的补扫失败，不等于原文从未提交；0.10.4 为法规参考加可选法规/版本身份、官方来源 URI/hash、文本 hash/定位、适用框架、资格与采用元数据，旧消费者可忽略且不提升证据状态。0.10.3 明确已有可选 `Error.details` 对象可扩展，现用于字段级补正入口；原有错误码/包络保持兼容。0.10.2 增加可选覆盖统计字段；0.10.1 增加 `product_execution` 投影；0.10.0 增加逐文件授权字段和撤销操作。取消语义不变。 |
| Worker/调度 | 新执行 envelope + 当前 DB 状态与 lease | 只处理可领取状态；旧 lease 世代写入被拒；恢复使用冻结快照。 |
| LangGraph | 现有 `ComplianceReviewState v1alpha2` 是有界 checkpoint 投影 | 本单元不改变其字段或旧枚举含义；未来字段先改 schema 再 `scripts/generate_state.py`。历史 Checkpoint 显式按版本读取，不按新 envelope 重解释。 |
| Model Gateway | ModelResponse v1alpha2 + 新 call outcome 身份 | 未知调用不伪装失败/成功、不自动重发；完整响应仍执行本地 Schema 验证。 |
| 审核台 | ReviewTask lifecycle 与独立 completion/coverage | `result_published` 只表示不可变审查结果已发布；部分完成、未知调用、待人工及报告失败必须可见。 |
| 报告/导出 | immutable result + `task0010-report.v1/v2/v3` | v1/v2 原样读；v3 明确产品执行摘要。报告下载继续按租户/项目/result 授权并审计。 |

数据库迁移按“新增可空/可回填数据 → 双读/兼容写 → 核对/切换 → 后续收缩”的顺序另行实施；没有明确旧记录映射时保持原值并只读，不能默认迁移历史预算、Checkpoint、模型调用结果或报告。旧严格消费者只能继续读取它支持的 schema；不能把新状态送入旧封闭枚举。

## 6. U05 实施与未执行项

U05 已实现产品模式的租户策略、逐文件授权/撤销、PostgreSQL 预算账户与预留、授权/审计同事务、历史账本受控导入和隐私反例；ADR-0021 与 `docs/architecture/authorization-matrix.md` 记录边界。OpenAPI 0.10.0 只做加法升级。旧的 DEC-007 JSONL/SQLite 装配保留为本地验证路径，未被改写。

仍未执行：真实供应商调用/真实内容外发（D3）、生产数据库/历史账本迁移切换、线上部署和 D4 操作；产品模式的实际切换必须另行批准并先停外发、备份、演练核账。D1—D4 所需审批继续限定对应验收活动。
