# 开发契约版本与兼容性

当前契约集合：v1alpha12（2026-10-19），当前修改尚未验证或部署。

本次新增 `llm-candidate-discovery-v2.schema.json` 和 `semantic-analysis-v2.schema.json`，
响应版本均为 v1alpha2，仅由新 `task0029-semantic-evidence-v2` 运行选用。
旧响应 Schema 与旧提示文本保留；历史运行和已发布报告不改写。
发现输出支持 1—4 个各自连续、各自唯一定位的原文引用；语义输出增加问题身份、
同源重复代表项、原文条件复核和逐法条关联理由。这些字段是模型建议，仍由服务端验证来源和关系，
不构成独立法规核验或用户验收。OpenAPI 0.10.5 加法新增可选 `failed_rescan_units`，
指父批次已成功提交但后续补扫失败的唯一原文单元；报告模板升级为 task0010-v3.4。
调用状态沿用现有 failed/not_applicable 和 unknown/unknown，无数据库迁移。

本轮未发布 v2 的收口约束：context_review 的复核/反证哈希上限为26（最多20个来源摘录+6个关联摘录），源引用哈希仍至多20。conclusion 与 assessment 的一致性规则及语义缓存/报告引用身份见 docs/development/product-contract-baseline.md；旧模型响应 Schema 不变。

| 契约 | 当前版本 | 本次变化 |
|---|---|---|
| EvidenceRef / LegalResult / ReviewReport | v1alpha8 加法 | 新增可选 `adoption_status`、`adopted_evidence`、`adoption_policy_id` 及报告 `legal_adoption_policy`/采用参考计数；采用政策不等于独立法律核验，`citable_evidence` 仍只含原独立核验命中；旧字段和旧报告保持原义 |
| OpenAPI | 0.10.5 | 在 0.10.3 上为法规参考加可选的法规/版本 ID、官方来源 URI 与哈希、全文哈希/定位、适用框架、资格和采用状态元数据；旧报告仍可读取，新增字段不改变正式证据资格。0.10.3 明确 `Error.details` 可包含结构化字段，用于上下文补正提示；错误包络字段不变且该对象可选，旧消费者可忽略。0.10.2 在 0.10.1 上加法升级：产品执行投影新增候选拒绝尝试/去重数、原因、唯一原文单元和后续恢复统计；旧响应字段与消费者保持有效。0.10.1 在 0.10.0 上新增可选 `product_execution` 覆盖与完整度投影 |
| LegalManifest、LegalIndex | Manifest v1alpha3 / Index v1alpha4 | D01条款效力；D07冻结原始字节/PDF字符框映射与显式文本排除；旧索引明确升级，原文与来源字节不变。法律地区归一化 cn-regions-2 增加安徽滁州映射，旧 cn-regions-1 结果仍可读取 |
| RetrievalQuery、RunSnapshot | Query schema_version=v1alpha3 / 集合v1alpha2 | TASK-0006纠正：地区规范化、持久运行与基准日来源；纯CLI不伪造项目运行 |
| RetrievalResult | schema_version=v1alpha5 / Query v1alpha3 | D03续建：正式EvidenceRef、同一文本制品URI/hash/locator、citable_evidence与矛盾/引用关联校验。旧result v1alpha1/v1alpha2显式拒绝，不改写追加写历史；无生产数据，不更改表DDL |
| ParsedDocument、ParserRequest、ParserResponse、Fragment | schema_version=v1alpha1 / 集合v1alpha9 | 闭合字段、定位、哈希、OCR置信度和可选词级 TSV 记录（文档页码、块/段/行/词序、原始像素框/置信度及文档坐标）、封闭问题码、资源策略、结果/错误互斥；解析类型为源并生成验证，OpenAPI 加法字段保持旧片段兼容 |
| ComplianceReviewState / ComplianceFinding | schema_version=v1alpha2 / 集合v1alpha2 | TASK-0009增加有界Skill汇合/结果引用、result_published和显式冲突；State findings为摘要子集 |
| SemanticAnalysisResponse | v1alpha1 / v1alpha2 | 新增严格闭合的模型语义响应契约，模型只产生分析建议 |
| DevelopmentTask | schema_version=v1alpha2 | 相关需求与局部验收分离，completed逐项需要证据 |
| EvidenceRef、ModelResponse | 集合v1alpha2 | 格式与内容约束沿用，增加有效正反例 |
| ErrorCode | 集合v1alpha2 | 明确11个业务码和HTTP_ERROR兜底，未知码被拒绝 |
| ModelPolicy | 集合v1alpha2 | data_policy仅允许public/internal/confidential/restricted |
| ReviewTaskEvent | envelope schema_version=v1alpha1 | 信封字段未变，保持原版本；payload另行按生产事件契约细化 |
| 模型profile配置 | schema_version=v1alpha1 | 当前用途示例未变，运行时校验待TASK-0008 |
| RuleDefinition / SkillDefinition / CandidateDiscovery | 新增闭合 v1alpha1 Schema；CandidateDiscovery绑定输入文档/项目版本、规则集摘要、引擎版本、逐Skill覆盖、检索主题、定位原文摘录及稳定候选身份，不改变Risk或Graph State |
| ReviewDecision / ReviewReport | 新增复核请求与结构化报告 Schema；决定保存独立证据状态及前后值，报告定位绑定源文档哈希、片段修订和原文摘录哈希 |
| ProductReviewExecution / ReviewReport | 新增版本化执行包络、覆盖/完整度/模型调用结果未知契约；报告 v3 带完整度摘要，v1/v2 读取规则不变 |
| EmbeddingModelIdentity / VectorIndexManifest | 新增模型/供应商/地域/维度/参数与规范化身份哈希；SQLite向量清单绑定法规索引、发布与修订、片段集合、构建器及数据校验和。TASK-0018仅以合成数据验证，不启用实际线上向量化或质量对比 |
| OCRRuntimeIdentity / ParserExecutionMetrics / ReviewRuntimeProvenance | ParsedDocument/ParserResponse记录OCR引擎、模型文件哈希、参数、隔离镜像哈希与解析资源指标；不可变运行身份记录OCR文档来源、CharacterEmbedding、检索配置、Prompt内容哈希和模型配置版本。调用级审计独立，仍属后续范围 |

风险的旧status不能自动等价迁移：accepted等人工状态无法证明原证据状态，导入时须补证或人工决定。旧State/Checkpoint不得静默按新定义恢复。当前没有生产数据，因此本次没有实际数据迁移。

未来发布后的破坏性契约改变，必须新版本、兼容测试、迁移和回滚方案。需要更改Prompt、规则、模型或法规时使用审查快照保留旧运行版本。

D04新增Project/ContextFields采购方式、采购主体、对象与框架字段；旧API输入仍有效，缺省unknown/空框架，法规检索返回context_incomplete且不调用Embedding。旧项目/运行行不改写；新Query v1alpha3、Result v1alpha5、Manifest v1alpha3/Index v1alpha4明确升级，State与正式EvidenceRef不变。

U02 (2026-10-17)新增 `product-review-execution.v1alpha1` 与 `task0010-report.v3`：运行生命周期与完整度/覆盖分开；未知调用不得按成功/失败重解释或自动重放；零候选完整结果须显式人工确认。ComplianceReviewState v1alpha2、ReviewReport v1/v2 和已有数据库行保持原义；此处未新增/执行数据库迁移。逐文件授权端点登记为 OpenAPI 0.8.0 加法路径。

U04 (2026-10-17，经用户授权) 将 OpenAPI 从 0.8.0 加至 0.9.0，新增 `POST /review-tasks/{reviewTaskId}/runs/{runId}/cancel`。这是只增加 operation 的向后兼容变化：无请求体，返回既有 ReviewTask；旧状态/Schema、数据库表与既有路由不变。仅审核员可调用；重复取消返回当前 cancelled 状态；已发布结果返回 409。取消事务锁定运行行并清除 lease，阻止活动/过期 Worker 写入。未对生产消费者发布，无数据库迁移。

U05 (2026-10-17) 将 OpenAPI 从 0.9.0 加至 0.10.0，新增产品模式逐文件授权的可选绑定字段和 `POST /projects/{projectId}/documents/{documentId}/external-authorization/revoke`。授权请求仍只要求 `reason`/`confirmed`，旧客户端不发送新字段时由服务端策略填入 purpose/provider/expiry；旧本地验证装配收到新字段会明确拒绝而不是静默忽略。数据库迁移 `202610172000` 只新增租户策略、授权、预算、预留和导入表，不改既有表或历史账本。产品模式（`DEPLOY_REVIEW_MODE=product-postgres`）以 PostgreSQL 为唯一授权/预算权威源；DEC-007 的 JSONL/SQLite 装配保留为本地验证路径。切换、真实迁移与真实外发仍受 D3/D4 约束。

U08 (2026-10-18) 将契约集合升级到 v1alpha9、OpenAPI 0.10.2，只加可选覆盖统计字段。新生产者以稳定来源身份去重计划、提交、失败、饱和和被拒绝原文单元；明确区分候选拒绝尝试、去重候选、原因及后续子批恢复。旧 `rejected_units` 保持原值并标注为历史 partial-batch section 总数，不再当作候选拒绝数展示；旧报告仍按原契约读取。无数据库迁移。

TASK-0029（2026-10-18）将契约集合升级到 v1alpha10、OpenAPI 0.10.3：`Error.details` 明确为可选扩展对象以支持服务端校验给出的字段级补正动作；项目上下文错误仍使用原 Error 包络。新增 `CN/安徽/滁州` 归一化别名并升为 `cn-regions-2`，读取器仍接受历史 `cn-regions-1` 结果。无数据库迁移，不重建未变化的法规索引/Embedding。

TASK-0029（2026-10-18）将契约集合升级到 v1alpha11、OpenAPI 0.10.4：法规参考新增可选的法规 ID/版本、原文哈希/定位、法规文本哈希、适用框架、证据资格、采用状态及政策 ID；既有 `EvidenceRef` 的文本制品 URI/hash 语义不变，正式法规证据判定不变。仅加法字段，无数据库迁移；旧报告仍按原快照读取。

全局管理新增CorpusBundle/RevisionRequest/PublicationRequest/OperatorCapabilities独立Schema；actor不从请求取得。数据库新迁移1600授权及1700不可变修订/发布/状态/身份，不更改已有业务表。Result仍v1alpha5，持久请求额外冻结publication/revision标识，由request_hash绑定并读回对照不可变索引。

TASK-0009的State/Risk扩展仍处于未对生产消费者发布的v1alpha3开发契约集合中；本仓库无生产消费者或持久生产Checkpoint。State只保留有界摘要/引用（运行时State最多64 KiB、500条finding、100条error），完整结果放在PostgreSQL制品表。严格Schema消费者应重新生成并接受新增状态/字段；若未来发布时需要兼容旧Risk完整对象或旧枚举封闭行为，应升级契约版本并提供迁移。新增持久表由迁移202610141800创建，旧数据/Checkpoint不作静默改写。
