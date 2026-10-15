# TASK-0020 Demo 可用性差距核查

核查基线：`work/TASK-0020`，基线 HEAD `00829851018612a275faca9ad6609e10fa38305d`。旧 TASK-0011 的 5/5 浏览器 manifest 指向 `5ffe1b6…`，不代表当前候选。首次隔离 E2E 因独立工作树缺少 Vite 依赖在浏览器启动前失败；随后仅通过官方 npm registry 安装锁定依赖，并完成当前工作区的真实 Edge 运行。当前最终候选使用 TASK-0018 parser 和正式生成的合成 DOCX，文件解析、队列消费均成功，但 ReviewEngine 在读取持久化 OCR provenance 时返回 422，详见下方 P1。

## 用户流程核查

| 步骤 | 当前能力和证据 | 当前状态 / 阻断 |
|---|---|---|
| 登录网页 | React 工作台调用真实 FastAPI token/session API；当前 E2E 登录、错误登录和撤权后会话失效测试通过。 | 已实测；离线横幅可见。 |
| 创建项目 | 项目 API、租户 RBAC、幂等和乐观锁已实现，前端可创建项目。 | 当前真实浏览器用例通过创建和版本冲突检查。 |
| 上传 DOCX/PDF | 前端上传到真实 API，后端保存作业并固定原文件哈希。 | 已实现；测试由真实文档处理 worker 接续。 |
| 安全扫描与解析 | `scripts/process_document.py` 使用隔离解析器、ClamAV 和对象存储执行持久化作业；TASK-0020 worker 轮询本机演示队列。 | 最新 parser `2c440c…` 的真实 E2E 上传后自动扫描、解析并进入“可用于审查”；摄取专项也通过。 |
| 启动审查任务 | API `create_app()` 默认把 `app.state.review_engine` 置为 `None`；创建/恢复审查会 fail closed 返回 503。 | 普通 API 启动入口没有授权的 ReviewEngine 装配；仅测试宿主通过显式依赖注入运行。 |
| 五类 Skill | 五类确定性规则在真实 ReviewEngine 图的测试宿主执行。 | 测试可用；普通服务未装配 ReviewEngine。 |
| 法规检索 | CharacterEmbedding/BM25/RRF 与法规发布快照存在，演示测试通过真实本地索引检索。 | 有条件可用；多数法规版本未核验，必须保留待核验标签，不能呈现为确定法律结论。 |
| ModelGateway | Gateway 协议、结构化校验与供应商适配器已实现；E2E 显式注入 `OfflineReviewGateway`。 | 在线供应商路由受 DEC-002 禁止；现有离线输出是固定合成协议替身，不是 Qwen/DeepSeek 语义推理。 |
| Evidence Checker | 真实审查图执行证据检查，旧 E2E 会检查候选、引用和状态。 | 仅在注入离线网关的工作流中集成；不能据此声称真实模型分析质量。 |
| 人工复核 | 前端、API、PostgreSQL 决定记录、审计、发布和恢复代码已存在。 | 当前 E2E 到创建审查前中止，无法以此确认最新 parser 下的人工复核闭环。 |
| Checkpoint 恢复 | ReviewEngine 使用 PostgreSQL AsyncPostgresSaver；真实 PostgreSQL 专项执行跨 worker 恢复。 | 专项证据存在；须在 Demo 中使用真实临时 PostgreSQL，而非内存模拟。 |
| 风险详情与引用 | Review 页面显示 finding、证据状态、引用位置并可回查原文。 | 该候选下 ReviewEngine 尚未创建运行，页面结果与证据引用未实测。 |
| Word/PDF | 从不可变已发布结果生成和下载两类报告，真实 PostgreSQL 专项会解析文件并检查溯源。 | 最新 parser 候选的浏览器链路被 P1 阻断，不能声称端到端下载已复验。 |

## 当前 P1 阻断

真实浏览器上传 `scripts/generate_demo_fixture.py` 生成的 DOCX 后，TASK-0018 parser 的扫描、OCR provenance 记录与持久化均成功；项目页显示文档“可用于审查”。创建审查进入 `services/candidate_discovery.py` 后，`OCRRuntimeIdentity.model_validate(record.parse_provenance)` 对 PostgreSQL JSON 解码出来的 `model_ids` list 抛出严格 tuple 校验错误，API 返回 422。测试运行 `5484f1c5d8564fd7aa40eb7204fae9ba` 的 JUnit 是 5 tests、3 passed、2 failed；第二个失败只是第一个审查流程未建成后的级联 `flow is null`。

影响：使用已批准的 TASK-0018 parser 解析的文件无法进入审查，Demo 主路径不可用。最小修复应在严格解析持久化 OCR provenance 时兼容 JSON 数组，同时仍验证原始 `identity_sha256`；建议补充 PostgreSQL JSON round-trip 与伪造哈希拒绝测试，再跑当前 parser 的真实浏览器 E2E。此处涉及 `src/bidding_compliance/**`，超出当前 TASK-0020 允许修改范围，本轮没有修改生产审查逻辑，也没有以旧 parser 或测试跳过掩盖该问题。

## 结论与范围

已有模块和 TASK-0011 历史测试不等于当前默认服务可以直接演示。最小本地方案是在隔离演示脚本中使用现有 API 工厂和 ReviewEngine 显式注入离线适配器，并消费既有持久化 `ingestion_job` 队列；不改变生产入口、权限、法律证据状态、LangGraph/Evidence Checker 语义或模型路由。演示 UI 必须标示离线确定性模式。

当前工作区不存在经确认授权的原始招标样本；本任务只构造明确标为合成的 DOCX，不读取真实资料、不连接在线模型、不发送业务数据。

DEC-002 的供应商/模型、地域与端点、发送数据类别、留存与审计、调用预算、故障降级等仍须用户批准。DEC-001 的公开/远程部署方式、HTTPS/访问控制、保留清理和费用也仍须用户批准。TASK-0020 只做本机 loopback 离线演示，不替代 TASK-0012/0013/0014 或 M5 验收。
