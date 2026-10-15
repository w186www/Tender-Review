# Changelog

本项目遵循语义化版本；正式发布前使用 `0.x`。

## [Unreleased]

### Added

- TASK-0026 单机容器化部署（编排与配置，未改业务代码）：新增 `docker-compose.demo.yml`（postgres/minio/clamav/api/worker/nginx 六服务、四个显式命名卷、backend 与 edge 两个内部网络，只有 nginx 发布端口），`Dockerfile.api`（复用 `requirements-dev.lock`，内置 docker CLI 27 供 worker 启动隔离解析容器）与 `Dockerfile.web`（两阶段构建 React 产物 + nginx 托管），`deploy/` 下的容器入口 `api_entry.py`（按 `DEPLOY_REVIEW_MODE` 选择仓库既有 app 装配，不自行实现审查逻辑）、幂等初始化 `demo_init.py`（迁移、非超级用户 NOBYPASSRLS 角色与授权、租户账号、对象桶、ClamAV 就绪门禁、法规快照发布）、反向代理配置（HTTP 与 TLS 共用同一 location 片段）、`bootstrap.sh`（生成密钥、构建并固化 parser 镜像 ID、探测 Docker socket 属组）、`backup.sh` / `restore.sh`（含非破坏性 `--verify` 演练）、业务验收与持久化核对脚本、部署说明。本机 Docker Linux 引擎实测：六服务健康，经反向代理完成合成标书「登录→建项目→上传→ClamAV 扫描→隔离解析→上下文确认→LangGraph 审查→风险与证据→人工复核→发布→Word/PDF 下载」全链路（下载 SHA-256 与服务端 `content_hash` 一致），真实浏览器验证前端各页面与「离线确定性演示」如实标注；`docker compose down` 删除全部容器后重建，项目/文档/任务/报告字节一致；备份恢复演练逐表行数一致且未修改线上数据。空闲稳态内存实测约 1.64 GiB（ClamAV 964.7 MiB、API 417.8 MiB），未下调装配中审查过的 `--memory=3g`。实测并如实记录：受限 Docker API 代理（只放行容器生命周期）会破坏 `docker run -i` 的 HTTP 劫持式 attach，解析 `PARSE_TIMEOUT`，故未交付该加固层。零供应商调用、零密钥入库；真实 Qwen 仍受独立授权与文档哈希白名单阻断。详见 `docs/development/TASK-0026-validation.md`。

- TASK-0024 法规质量与检索相关性：三案例召回质量核对表明《民法典》第五百八十五条并未缺失，命中排名由查询构造决定（仅原文=未命中 → 加法律领域词=第 6 → 法律术语主导=第 1，分词为字符 bigram+BM25）；库内存在更贴近企业内部黑名单风险的《公平竞争审查条例》等规范，但采购用词使政府采购类法规排在前面，且因未声明适用范围一律标为 applicability_unknown。法规库质量画像：43 个版本中 42 个同时缺失核验、生效日期、适用范围与条款清单。《民法典》585 条库内原文与官方文本逐字一致，但 source_uri 为地方转载、有效性未核验（技术比对，不构成法律签署）。新增 `legal_references` 使未核验候选在 Word/PDF 中以『可能相关依据（适用性未经确认，仅供参考，不计入已核验证据）』展示，经 verify_legal_hit 逐条复验，不进入 evidence/sources，不提升 evidence_status，门禁不变。详见 docs/development/TASK-0024-validation.md。

- TASK-0024 AI 风险与法规自动对应：查明 CONTEXT_INVALID 根因——`RetrievalQuery.consistent_context` 对企业非招标采购推导出空法律框架并抛错，检索在构造查询阶段即终止，且 `applicability_exclusions` 把空框架判为 `framework_mismatch` 二次阻断。修复为「未知框架不等同于不匹配」：不推断框架、允许检索参考候选，但 `confirmation_reason` 在无可确认框架或法规未声明适用范围时返回 `applicability_unverified`，永不返回 `valid`；新增四级适用状态投影（applicable_verified／potentially_relevant／applicability_unknown／not_applicable）。离线验收：三个真实风险（逾期违约金、集团黑名单资格条件、报价得分不明确）各召回 8 条参考候选，全部标为 applicability_unknown、可引用依据 0，未为凑命中降低校验标准。法规快照 42/43 版本未核验、唯一已核验版本已超核验期，因此当前不存在可用于确认的法规依据。详见 docs/development/TASK-0024-validation.md。

- TASK-0023 完整真实 AI 审查闭环已打通（独立授权 DEC-006）：`semantic_analysis` 改为按 `candidate_id` 稳定排序的确定性分批（每批 8 个候选、上限 13 批），每批独立调用身份/缓存件/契约校验并按批次累加 usage 与哈希，单批时保持历史 `call_id` 与 `model_analysis` 结构不变；同时修复脱敏最小化器外发上限与发现批次容量不一致的缺陷（该缺陷会在零调用下拒绝首批请求）。真实运行：7 批风险发现 + 3 批分批语义分析，LLM 10/15 次、费用 ¥0.062695；确定性 Skills 0 候选而模型独立发现 19 个候选，19/19 原文定位一致、0 条违法断言、全部标为 `insufficient_evidence` 待核验；网页完成上传、正式校正、上下文确认、审查、19 项人工复核、结果发布与 Word/PDF 生成下载，下载 SHA-256 与服务端 `content_hash` 一致。新增多授权账本（`AUTHORIZATION_LIMITS` 与 `requests.authorization_id`），DEC-005 历史计数与费用保留不重置。为在 15 次授权内完成闭环，发现批次容量按输入 token 预算上调（9,000→18,000 字节、80→200 片段），单次审查候选上限相应下降。详见 `docs/development/TASK-0023-validation.md`。

- TASK-0022 零候选离线审查路径已修复：OfflineReviewGateway 对合法空候选返回 Schema 合法的空 findings，同时保留调用身份/响应哈希和非空候选的严格证据断言。Focused 新增 3 项回归通过。天津地铁 DOCX 在正式本地链路上得到 0 个 Skill 候选，RAG 5/5 `CONTEXT_INVALID`；离线 LangGraph、空结果复核及 Word/PDF API 导出成功。真实模型调用为 0，任务仍 in_progress。详细限制与本地结果见 TASK-0022 验证记录。

- TASK-0022「真实招标文件离线基线与受控 Qwen 评测」已在 `work/TASK-0022` 独立工作树启动。TASK-0019 原工作树和未提交成果按 SHA-256 快照保留；因任务 Schema 不支持 `paused`，仅在新治理分支将其标记为 `blocked` 并记录用户要求的临时暂停。DEC-003/004 已占用，真实文件 Qwen 外发方案登记为待批准的 DEC-005。当前仅本地离线诊断；无真实文件或法规内容外发。

- TASK-0021「真实 Qwen LLM 接入与在线审查 Demo」已完成归档：代码提交 `19a29fa0e62b6dc57d4493dc111f56194199e51c` 的 GitHub Actions Run 38707492669 对应 SHA，Full 适用 Job 全部成功；完成态归档提交 `75bc559c609711dff7111da4545ca51a9d3f511c` 的 Run 38709878505 中 `impact`、`quick`、`verify-required` 成功，baseline/postgres/ingestion 按文档 Quick 条件合法 skipped。DEC-002 唯一授权的一次真实 `qwen3.8-flash` 北京 Workspace 请求已在本地隔离在线 Edge E2E 中完成：5/5 浏览器用例通过，provider 报告 424/420 输入/输出 tokens，按官方单价估算 ¥0.0014732；模型响应通过结构化校验并实际进入风险融合，上传/解析/人工复核/DOCX/PDF 流程成功。Focused 25、Full 570 及 PostgreSQL/Checkpoint 专项通过，授权已消耗。详见 `docs/development/TASK-0021-validation.md`。

- TASK-0020 已完成：本机 loopback Demo 使用合成 DOCX 和显式离线 Gateway；修复 OCRRuntimeIdentity 对持久化 JSON 数组的严格 tuple 兼容，保留原身份/provenance 哈希校验。Focused 76、Full 545、真实 Edge 5/5、PostgreSQL/Checkpoint、解析隔离与安全摄取专项及 `--serve` Ctrl+C 清理均通过。提交 `c85e9155949b1a1d961a1031949f003e1bfe0313` 的 GitHub Actions Run 38688174502 全部适用门禁成功（baseline 545 passed，postgres/ingestion/verify-required success；Full 模式 quick 合法 skipped）；TASK-0020 已归档，M3 已完成。TASK-0019 仍为 planned，原本机部分实现保留在独立工作区。未调用真实模型、未外发真实业务数据；DEC-001/DEC-002 未获批准前不部署、不接入在线模型。详见 `docs/development/TASK-0020-validation.md`。

- TASK-0018 本地与远端交付验收完成：法规检索评测、Mock-only 百炼 Embedding Provider、SQLite 向量持久化与断点续建、Tesseract 合成扫描基线、运行版本追溯。补齐向量缓存损坏/缺失/续建完整性检查与 ReviewRuntimeProvenance JSON 持久化测试。本地正式 Focused 144 项、Full 537 项及 PostgreSQL16/RLS/ReviewEngine 专项通过；源码提交 da7325bb95a10a10fcca82151c22c6272980d091 的 GitHub Actions Run 38641374412 completed/success（mode=full，baseline 537 passed/2 warnings，postgres/ingestion/verify-required success）；官方 npm registry 安装184包，`package-lock.json` SHA-256 未变。交付前审计的61条状态路径与隔离副本逐路径、逐文件SHA-256一致。无真实 API Key、供应商调用或真实文件外发；DEC-002 待批准。详见 `docs/development/TASK-0018-validation.md`。

- TASK-0011已正式归档：源码候选`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`，归档提交`05c2b91655a7152b28692c7f5216de3ace3d7ff8`；源码CI 38600922153、验收记录CI 38603582949和归档CI 38604186570 的适用作业均成功。FR-013配置版本服务/API/页面、审计与ReviewEngine冻结快照已实现；真实 Microsoft Edge E2E 5/5，PostgreSQL16专项、FR-013 Focused 69和本地Full 510通过。Windows CRLF根因已通过固定前端文本LF解决，OpenAPI与Biome检查均保留。DEC-002未批准，未调用在线模型。详见`docs/development/TASK-0011-validation.md`。

- TASK-0010已完成归档：人工复核决定/审计历史、幂等发布、不可变结构化报告版本、Word/PDF渲染、原文历史片段回查及授权导出审计。源码候选`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`本地Full504项与PostgreSQL16专项通过；源码CI38556383801、验收记录CI38557180768及归档CI38557509858全部适用作业成功。DEC-002未批准，默认模型执行关闭。详见`docs/development/TASK-0010-validation.md`。

- TASK-0009 已本地归档并完成远端交付：TASK0009-001/002正式验收、本地 Full 500、Focused 13、真实 PostgreSQL 恢复/并发/事务故障专项通过；源码、验收记录、归档分别对应 GitHub Actions Runs 38546165564、38547021471、38547822892，适用门禁成功。DEC-002仍待批准、生产模型路由禁用、预算账本仅单进程一致性、法律证据最高为suspected；未进行真实供应商调用。详见 `docs/development/TASK-0009-validation.md`。

- TASK-0008 archived after formal TASK0008-001/002 checks, local Focused 54 and Full 487, real local HTTP/identity checks, and GitHub Actions run 38521959503 succeeded for impact/baseline/postgres/ingestion/verify-required. Added a provider-neutral gateway, OpenAI Responses and Anthropic Messages adapters, strict structured output validation, server-side routing/authorization, budget reservation, bounded retry/circuit breaker, and audit metadata. No live OpenAI/Anthropic calls were made. DEC-002 remains pending, production routes remain disabled, and the in-memory budget ledger provides single-process consistency only; shared persistence and multi-process production safety remain prerequisites.

- TASK-0007：实现五类无模型确定性Skill、版本化规则/Skill/候选发现契约、失败关闭覆盖、可追溯原文定位、稳定去重与法规检索主题。源码236d2a6e本地Focused30及Full448全通过，远程38516913371所有适用作业成功；任务已归档，M2仍待TASK-0008及整体退出验收。

- TASK-0006 D01/D02/D04/D05/D07：明确未知有效期与局部废止；采购方式/主体/对象及双框架、条款范围交集；原始HTML字节和PDF页框与清洗文本映射；独立全局grant及鉴权CLI；不可变来源/核验修订、稳定法规身份、双CAS发布/停用/回滚和原子审计。Manifest3/Index4/Query3/Result5、OpenAPI0.5.0、迁移1600/1700；旧法规核验状态及原文保留。源码5347b110的本地/远程Full413项及真实PostgreSQL/Docker/官方PDF/文件接入成功，D01–D07本期退出条件满足并归档；证据38510406707，远程JUnit413/0/0/0。后续记录Quick，不重复Full、不合入main、不启动后续任务。

- TASK-0006 D03续建：Result v1alpha3正式EvidenceRef与完整citable_evidence关联校验，拒绝未核实却可确认、引用/哈希/定位/日期矛盾；证据URI/hash指同一清洗文本，冻结索引解析复核来源及适用性，新增39项回归。旧结果版本显式拒绝，历史记录保留，无DDL变更；其余D问题和任务in_progress保持。

- TASK-0017：verify.ps1增加Quick/Focused并保留默认Full；显式测试路径防越界、独立局部JUnit、失败关闭的CI选档及verify-required汇总门禁。

- TASK-0006纠正：在效版本状态按基准日比较；注册地区映射、context_incomplete与excluded原因；新增202610141200检索运行快照/基准日来源/哈希、读取重新鉴权、RLS和追加写触发器，Query/Result v1alpha2。

- TASK-0006：法规来源/文本哈希、有效区间、核验截止日及范围契约；不可变索引、精确条款定位、BM25与字符向量混合检索，服务端身份/项目范围检查。
- 用户授权法规更新：保留42份原文，新增司法部2019修订《实施条例》与来源HTML，43版本/3120片段；旧资料保持待核实，新增25项回归与ADR-0010及启动说明。

- TASK-0005：鉴权上传与持久化解析作业、固定镜像隔离、强制ClamAV、S3/本地开发存储、PDF/DOCX/中英文OCR定位。
- 人工文本修正与质量复检、上下文确认/版本历史、鉴权附件下载；OpenAPI 0.4.0与增量迁移202610131300。
- 真实Docker隔离/S3/杀毒/OCR/HTTP CI门禁，文件接入启动说明；租约重入和权限撤销回归。

- TASK-0004：Argon2账号引导、短期JWT与可撤销会话、数据库即时身份/RBAC校验。
- 显式Alembic核心迁移、租户复合外键、PostgreSQL FORCE RLS、不可覆盖历史与审计。
- 项目创建/分页查询/版本更新/历史、事务幂等与乐观锁；真实业务HTTP启动检查和独立PostgreSQL CI门禁。
- 工程治理基线、需求追踪、架构决策记录和跨模型交接机制。
- OpenAPI、领域 Schema、事件 Schema 与模型网关协议草案。
- 统一仓库验证入口与初始黄金评估样本。
- 法规全文库及来源索引。
- M0至M6里程碑与14个任务，局部验收证据、依赖顺序和显式范围。
- JSON Schema与OpenAPI正式校验、正反例、State生成检查、Ruff、Mypy和Pytest门禁。
- Python 3.12独立环境与已解析依赖锁文件。
- TASK-0002：FastAPI应用工厂、健康接口、Pydantic环境配置、请求编号与统一错误响应。
- JSON日志字段允许列表、秘密配置隐藏、公开URL禁止夹带凭据、开发文档按环境开关。
- Uvicorn启动入口、PowerShell启动脚本、后端接口测试和真实HTTP启动检查。

### Changed

- TASK-0006 D03源码f0bd827：95项Focused、真实PostgreSQL及最终Full323项通过；远程38498549575完整门禁成功，下载JUnit323/0/0/0。记录更新仅Quick，TASK-0006保留in_progress及具体D余项，未合入main。

- TASK-0017已归档：源码68d67a809的本地/远程279项Full、真实PostgreSQL、ingestion及verify-required均通过；远程JUnit0失败/错误/跳过。TASK-0006仍进行中，D问题保留。

- TASK-0017远程PostgreSQL故障定位：旧42份法规的CRLF哈希与Linux默认LF检出不一致。固定跨平台检出字节并增加真实Git克隆/全部语料哈希与定位回归，保留原文及严格哈希断言。

- 用户要求恢复单Codex直接实施/自检/收尾，ADR-0011替代默认跨软件/独立代理审批；既有TASK-0006代码和问题保留。纯记录/归档改动Quick，代码候选Full，取消相同源码反复全测。

- TASK-0006实施者自行归档已撤销；迁移work/TASK-0006并恢复ADR-0009独立审查关卡，正式任务in_progress。

- TASK-0005局部验收完成并归档；M1基础退出检查通过，下一项为TASK-0006。源码CI三作业成功，186项远程JUnit与本地归档后门禁已核验。

- TASK-0005：文本转录与上下文确认并发时返回409且保留既有快照；SQLite租约时间条件由数据库判断。

- TASK-0015：修复任务移动后的测试夹具依赖，更正历史验收记录。
- 增加独立安全异常诊断、错误码契约/正反例、data_policy枚举及秘密扫描回归。
- 补齐ADR备选方案、数据流/部署索引和Word差异登记；首次main提交已推送并获得GitHub CI成功实证。

- 初始开发契约升级至v1alpha2：修正项目响应组合，分离证据状态与人工复核决定。
- 主链按候选发现→法规检索→基于证据分析执行；人工解析修正后复检；发布结果快照后渲染报告。
- State类型从Schema生成，阻断字段与必填定义漂移。
- TASK-0001完成范围修正为初始治理，不表示两个适配器或生产交接已验收。

