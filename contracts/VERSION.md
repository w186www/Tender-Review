# 开发契约版本与兼容性

当前契约集合：v1alpha3（2026-10-14），尚未对生产消费者发布。

| 契约 | 当前版本 | 本次变化 |
|---|---|---|
| OpenAPI | 0.7.0 | 增加法规与审查配置的草稿、发布、停用、回滚管理接口；模型配置只允许安全运行策略，不包含密钥或外部路由 |
| LegalManifest、LegalIndex | Manifest v1alpha3 / Index v1alpha4 | D01条款效力；D07冻结原始字节/PDF字符框映射与显式文本排除；旧索引明确升级，原文与来源字节不变 |
| RetrievalQuery、RunSnapshot | Query schema_version=v1alpha3 / 集合v1alpha2 | TASK-0006纠正：地区规范化、持久运行与基准日来源；纯CLI不伪造项目运行 |
| RetrievalResult | schema_version=v1alpha5 / Query v1alpha3 | D03续建：正式EvidenceRef、同一文本制品URI/hash/locator、citable_evidence与矛盾/引用关联校验。旧result v1alpha1/v1alpha2显式拒绝，不改写追加写历史；无生产数据，不更改表DDL |
| ParsedDocument、ParserRequest、ParserResponse | schema_version=v1alpha1 / 集合v1alpha2 | 闭合字段、定位、哈希、OCR置信度、封闭问题码、资源策略、结果/错误互斥；由类型源生成并验证漂移 |
| ComplianceReviewState / ComplianceFinding | schema_version=v1alpha2 / 集合v1alpha2 | TASK-0009增加有界Skill汇合/结果引用、result_published和显式冲突；State findings为摘要子集 |
| SemanticAnalysisResponse | schema_version=v1alpha1 | 新增严格闭合的模型语义响应契约，模型只产生分析建议 |
| DevelopmentTask | schema_version=v1alpha2 | 相关需求与局部验收分离，completed逐项需要证据 |
| EvidenceRef、ModelResponse | 集合v1alpha2 | 格式与内容约束沿用，增加有效正反例 |
| ErrorCode | 集合v1alpha2 | 明确11个业务码和HTTP_ERROR兜底，未知码被拒绝 |
| ModelPolicy | 集合v1alpha2 | data_policy仅允许public/internal/confidential/restricted |
| ReviewTaskEvent | envelope schema_version=v1alpha1 | 信封字段未变，保持原版本；payload另行按生产事件契约细化 |
| 模型profile配置 | schema_version=v1alpha1 | 当前用途示例未变，运行时校验待TASK-0008 |
| RuleDefinition / SkillDefinition / CandidateDiscovery | 新增闭合 v1alpha1 Schema；CandidateDiscovery绑定输入文档/项目版本、规则集摘要、引擎版本、逐Skill覆盖、检索主题、定位原文摘录及稳定候选身份，不改变Risk或Graph State |
| ReviewDecision / ReviewReport | 新增复核请求与结构化报告 Schema；决定保存独立证据状态及前后值，报告定位绑定源文档哈希、片段修订和原文摘录哈希 |

风险的旧status不能自动等价迁移：accepted等人工状态无法证明原证据状态，导入时须补证或人工决定。旧State/Checkpoint不得静默按新定义恢复。当前没有生产数据，因此本次没有实际数据迁移。

未来发布后的破坏性契约改变，必须新版本、兼容测试、迁移和回滚方案。需要更改Prompt、规则、模型或法规时使用审查快照保留旧运行版本。

D04新增Project/ContextFields采购方式、采购主体、对象与框架字段；旧API输入仍有效，缺省unknown/空框架，法规检索返回context_incomplete且不调用Embedding。旧项目/运行行不改写；新Query v1alpha3、Result v1alpha5、Manifest v1alpha3/Index v1alpha4明确升级，State与正式EvidenceRef不变。

全局管理新增CorpusBundle/RevisionRequest/PublicationRequest/OperatorCapabilities独立Schema；actor不从请求取得。数据库新迁移1600授权及1700不可变修订/发布/状态/身份，不更改已有业务表。Result仍v1alpha5，持久请求额外冻结publication/revision标识，由request_hash绑定并读回对照不可变索引。

TASK-0009的State/Risk扩展仍处于未对生产消费者发布的v1alpha3开发契约集合中；本仓库无生产消费者或持久生产Checkpoint。State只保留有界摘要/引用（运行时State最多64 KiB、500条finding、100条error），完整结果放在PostgreSQL制品表。严格Schema消费者应重新生成并接受新增状态/字段；若未来发布时需要兼容旧Risk完整对象或旧枚举封闭行为，应升级契约版本并提供迁移。新增持久表由迁移202610141800创建，旧数据/Checkpoint不作静默改写。
