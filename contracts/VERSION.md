# 开发契约版本与兼容性

当前契约集合：v1alpha2（2026-10-13），尚未对生产消费者发布。

| 契约 | 当前版本 | 本次变化 |
|---|---|---|
| OpenAPI | 0.4.0 | 新增文档查询、片段、附件下载、质量修正和上下文确认；Document 增加状态与解析版本，消费者须更新状态枚举 |
| LegalManifest、LegalIndex、RetrievalQuery、RetrievalResult | schema_version=v1alpha1 / 集合v1alpha2 | TASK-0006新增独立闭合契约，原有State/EvidenceRef/OpenAPI不变；有效区间、核验截止日、来源快照及可确认资格，见ADR-0010 |
| ParsedDocument、ParserRequest、ParserResponse | schema_version=v1alpha1 / 集合v1alpha2 | 闭合字段、定位、哈希、OCR置信度、封闭问题码、资源策略、结果/错误互斥；由类型源生成并验证漂移 |
| ComplianceReviewState | schema_version=v1alpha2 | 补齐引用，Python类型从Schema生成 |
| ComplianceFinding | 集合v1alpha2 | status拆为evidence_status与review_status，人工决定需审计字段 |
| DevelopmentTask | schema_version=v1alpha2 | 相关需求与局部验收分离，completed逐项需要证据 |
| EvidenceRef、ModelResponse | 集合v1alpha2 | 格式与内容约束沿用，增加有效正反例 |
| ErrorCode | 集合v1alpha2 | 明确11个业务码和HTTP_ERROR兜底，未知码被拒绝 |
| ModelPolicy | 集合v1alpha2 | data_policy仅允许public/internal/confidential/restricted |
| ReviewTaskEvent | envelope schema_version=v1alpha1 | 信封字段未变，保持原版本；payload另行按生产事件契约细化 |
| 模型profile配置 | schema_version=v1alpha1 | 当前用途示例未变，运行时校验待TASK-0008 |

风险的旧status不能自动等价迁移：accepted等人工状态无法证明原证据状态，导入时须补证或人工决定。旧State/Checkpoint不得静默按新定义恢复。当前没有生产数据，因此本次没有实际数据迁移。

未来发布后的破坏性契约改变，必须新版本、兼容测试、迁移和回滚方案。需要更改Prompt、规则、模型或法规时使用审查快照保留旧运行版本。
