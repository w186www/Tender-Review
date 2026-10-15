# PROJECT_STATE

更新时间：2026-10-15
架构基线：ADR-0012本期法规生命周期/来源映射接受；ADR-0015历史决策保留、其TASK-0018 BGE/Paddle部署计划由已批准ADR-0016局部修订；Word V2.0 + ADR-0011开发验证替代ADR-0009，ADR-0010法规方案proposed；业务ADR-0001至0008保留 / 开发契约v1alpha3
当前里程碑：M1、M2、M2A、M3 已按记录退出；M3 的上传至报告、复核与恢复退出条件已由 TASK-0020 真实 Edge/Checkpoint 证据满足，提交 SHA 的远端适用 CI 成功。M3A/TASK-0019 保留为 planned，其独立工作树与未提交成果不参与本任务。TASK-0021 的一次 DEC-002 授权已于 2026-10-15 消耗，合成数据在线 Edge E2E 本地 5/5 通过，硬预算上限 ¥0.10；代码提交 Full CI 与归档证据提交 Quick CI 均成功。当前 TASK-0021 完成态归档提交的 Quick CI 正在运行，M3B 在该最终闭环前仍标记 `in_progress`。M4/M5 及 TASK-0012/0013/0014 原验收范围不变，M4 依赖 M3B 退出。

## 已完成

- 建立模型无关的仓库协作规则与文档入口。
- 建立需求 ID、验收 ID、安全 ID 和非功能需求 ID 的追踪机制。
- 建立 LangGraph 状态、风险、证据、任务事件和 OpenAPI 初始契约。
- 建立模型网关协议与供应商适配边界。
- 初始纳入42份法规全文及来源索引；TASK-0006已完成版本化摄取（新增1份新版）。
- 建立统一仓库验证脚本。
- TASK-0003修正：正式契约校验、State生成、流程依赖、分离风险状态、局部验收证据、锁定环境和CI配置。
- 已建立M0至M6七个里程碑与17个任务；53个需求/验收ID均已分配阶段，尚未全部实现。
- TASK-0002：可启动FastAPI/Uvicorn后端、健康检查、环境配置、请求追踪、统一错误和结构化安全日志。
- TASK-0015：夹具位置、独立诊断、错误码契约、模型数据策略、秘密扫描与文档冲突修复；首次Git提交已推送、CI已成功。

- TASK-0004：显式数据库迁移、可撤销JWT身份、租户/RBAC、版本化项目与事务幂等；PostgreSQL真实CI通过。
- TASK-0005：安全文件上传、持久作业、ClamAV强制扫描、受限Docker解析、PDF/DOCX/扫描件定位、人工质量/上下文版本、鉴权下载；真实容器与远程三作业CI通过。

- TASK-0006已完成并归档：43版本/3120片段，D01–D07本期缺陷全部解决/边界保持；效力与条款适用分开、完整HTML/PDF来源映射、独立全局授权、不可变核验/发布/双CAS/回滚/审计，Result5。源码5347b110a8c3561c72086afd455755810de59abf本地/远程Full413项与全部真实集成/汇总成功。旧42文本保持未核实，法规能力不替代最终违规判断。

- TASK-0017：单Codex实施、Quick/Focused/Full与失败关闭CI已完成；修复跨平台CRLF检出，最终源码68d67a80943e9c531f58ced7557d0c24938d84e9本地/远程Full279项与PostgreSQL、ingestion、汇总门禁通过，归档记录用Quick。

- TASK-0007已完成并归档：五类无模型确定性Skill、版本化规则与候选发现契约、原文定位/稳定去重及法规检索主题。源码236d2a6e231be030f719b0bbabc3f2b0a50039b3 Focused 30项、最终Full448项本地通过（0失败/错误/跳过），真实HTTP/身份/租户集成检查通过；远程38516913371适用作业及汇总门禁成功。详见TASK-0007-validation.md。
- TASK-0010已完成并归档：源码候选`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`本地Full504及PostgreSQL16专项通过；源码CI38556383801、验收记录CI38557180768、归档CI38557509858所有适用作业均成功。复核/审计、不可变Word/PDF报告、引用回查和越权导出审计已实现。生产模型路由仍受DEC-002限制；详见`docs/development/TASK-0010-validation.md`。
- TASK-0011已完成并归档：源码候选`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`，归档提交`05c2b91655a7152b28692c7f5216de3ace3d7ff8`；源码CI 38600922153、验收记录CI 38603582949、归档CI 38604186570 的适用作业均成功。FR-013配置版本管理已实现；真实浏览器E2E 5/5、PostgreSQL16专项、Focused 69和本地Full 510通过。DEC-002仍未批准在线模型；详见`docs/development/TASK-0011-validation.md`。
- TASK-0018已完成本地与远端交付：源码提交 da7325bb95a10a10fcca82151c22c6272980d091 的 GitHub Actions Run 38641374412 completed/success；mode=full，baseline 537 passed/2 warnings，PostgreSQL、ingestion、verify-required success，quick 因 Full 模式合法 skipped。隔离副本正式Focused 144、Full 537项通过；前端检查、真实HTTP/身份 smoke、PostgreSQL16/RLS/Checkpoint/ReviewEngine provenance 持久化专项通过。修复 SQLite 完整向量缓存一致性校验并补齐损坏/缺失/续建测试和运行来源身份测试。仅官方 npm registry 安装，lockfile 未变；交付前审计为61条状态路径（29个已跟踪改动、32个未跟踪文件），原工作区与隔离副本路径集合和逐文件SHA-256完全一致。无供应商调用、真实API密钥、真实文件或法规文本外发；DEC-002仍待批准。详见`docs/development/TASK-0018-validation.md`。

- TASK-0020已完成并归档：实现提交`c85e9155949b1a1d961a1031949f003e1bfe0313`对应GitHub Actions [Run 38688174502](https://github.com/w186www/Tender-Review/actions/runs/38688174502) completed/success；baseline 545 passed/2 warnings，PostgreSQL、ingestion、verify-required success，quick因Full模式合法skipped。归档记录提交`f2b1b91e3bd6b08141414f0edd99dcfff0f8905e`对应[Quick Run 38689517542](https://github.com/w186www/Tender-Review/actions/runs/38689517542) success。本地Focused 76、Full 545、Microsoft Edge E2E 5/5、PostgreSQL/Checkpoint、parser sandbox、安全摄取及`--serve`清理均通过。只在严格OCRRuntimeIdentity持久化JSON读取边界兼容数组/tuple，原字段、类型、身份与provenance哈希验证保留；仅合成数据、离线Gateway，无真实模型调用或外发。M3退出条件满足；M3A/TASK-0019仍planned。详见`docs/development/TASK-0020-validation.md`。

## 正在进行

- TASK-0021 完成态归档提交已推送，正等待其对应的远端 Quick CI；只有该 Run 成功后才将 M3B 标记退出。已用尽的 DEC-002 唯一调用授权不允许额外请求。
- TASK-0019 离线评测保持 `planned`；其部分未提交实现仍完整留在本机独立 `work/TASK-0019` 工作区，本轮未在该工作树执行或写入。
- DEC-001 外部部署仍待决策。42 个法规版本仍未核验，演示必须保留证据状态，不得默认外发法规正文。

## 下一步

1. 核验 TASK-0021 完成态归档提交的 GitHub Actions Quick；成功后补记其提交 SHA/Run，并将 M3B 标记为 completed。
2. TASK-0019 继续保持 `planned`，其原工作树和未提交内容不得在本任务修改；42 个未核验法规版本与到期核验日期继续按既有边界处理，DEC-001 未获批准前不部署公网服务。

## 最近验证

- 2026-10-15 TASK-0021源码/测试证据：manifest SHA-256 `407a0564c2d8508bde52cee3626394f50a8a5a3c82c934c5d9a0e2204442fd1d`；Focused 25 passed，Full 570 passed/2条既有pypdf弃用警告，Ruff、Mypy98源文件、前端6项/build及HTTP/身份smoke通过；PostgreSQL16/Checkpoint 专项通过。官方北京价格按输入¥0.8/百万tokens、输出¥2.7/百万tokens核验；授权硬预算¥0.10且调用前全额预留，白名单规范化JSON发送前强制≤2,048 UTF-8字节。
- 2026-10-15 TASK-0021唯一真实在线实证：run `30180d4e152040ccb9f805634617b456`，Microsoft Edge 5/5通过，0 failure/error/skip；合成DOCX SHA-256 `c770a3576555fc9225b2612c98966e809cc087194e3bb2d3d7c3bfb05ed65341`。恰好一条 `bailian/qwen3.8-flash` 请求，供应商报告424输入/420输出tokens，费用按北京官方单价估算¥0.0014732，延迟10,125ms，重试0/无回退；响应哈希`5f462b27fa9cf59015a14db08bb411d76da24f617c8ac17ea8b51f3241e47dcb`。结构化输出关联审计哈希并进入 merged finding；本地RAG、人工复核/Checkpoint恢复、DOCX/PDF生成及下载均由E2E断言通过。无源码/测试变化，复用Full 570；代码提交及归档证据提交CI成功，完成态归档提交CI待核验。详细证据见`docs/development/TASK-0021-validation.md`。
- 2026-10-15 TASK-0020 本地及远端最终验收：Git index 源码/测试十文件 manifest SHA-256 `c5ec2a5a0e28d9c5317f6a9ae0d019131694b7d8673d7758991d469a1ff9cf7a`；Focused 76 passed，Full 545 passed/2 条既有 pypdf 弃用警告，Mypy97源文件；真实 Edge 5/5（run `86521e79591241c19b28aaecf0988323`，合成 DOCX→安全解析→离线ReviewEngine→人工复核/发布→Word/PDF下载）；PostgreSQL16、Checkpoint/ReviewEngine、parser sandbox、ClamAV/MinIO/S3安全摄取均通过；`--serve` run `9a9478a6b4dc4d8b9c1fd0e34b40f09c` Ctrl+C 后 manifest `stopped` 且三容器已移除。GitHub Actions Run 38688174502 对提交`c85e9155949b1a1d961a1031949f003e1bfe0313`全部适用门禁成功；baseline JUnit 545/0/0/0。TASK-0019工作树状态和12个变更文件哈希与本轮开始快照一致。详见`docs/development/TASK-0020-validation.md`。

- 2026-10-15 TASK-0018检索基线：43版本/3120片段，法规索引SHA-256 `69d340d65f5e9114c8a2e76f8b3b524b67f47d0cbc0088c4e01d80b7db8729fd`；其中42版本未核验、仅1个已核验版本用于10条正式标签。CharacterEmbedding/BM25/RRF实际指标Recall@5/10=1.0/1.0、MRR@10=0.4867、nDCG@10=0.6141；平均查询延迟1,202ms，峰值进程工作集125,927,424字节。相同快照/标签的重复运行指标相同，平均查询延迟1,020ms。适用性过滤4例0错，效力/核验期限过滤1例0错；77个未核验候选单列，专家未确认风险样本数为0（不代表已证实无此风险）。
- 2026-10-15 TASK-0018 Tesseract：实际固定摘要隔离解析镜像 `2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597`、Tesseract 5.3.0、chi_sim/eng模型SHA记录。合成3页双栏扫描 CER 20.79%，关键标记5/6，表格单元7/14，页码标记3/6、OCR定位100%，重复短语定位0/2。页面被现有入库质量门判为passed，尽管这些指标触发合成评测警报；该不一致在本任务报告中保留，不改变门禁。单文档进程RSS峰值90,099,712字节、容器峰值146,718,720字节、解析耗时1,515ms、主机端到端2,591ms；超时0，空白件降为requires_review，畸形PDF失败关闭为INVALID_FILE。仅为合成样本结果，不代表真实招标件质量。详见`evals/ocr/results/tesseract-baseline-final-reviewed-20261015.json`。
- 2026-10-15 TASK-0018本地与远端验收：官方`registry.npmjs.org` DNS/HTTPS成功；隔离副本安装184个npm包，package-lock SHA-256保持`CE42801FF4EF6A086191D78203C91185F582131F8E246AFDB0FEC295E1724A29`。正式Focused 144项、Full 537项通过；Mypy97源文件，前端6项、OpenAPI、Biome、TypeScript、build及真实HTTP/身份 smoke通过。SQLite向量缓存完整性损坏/缺失/断点续建测试和ReviewRuntimeProvenance JSON持久化专项通过；PostgreSQL16迁移/RLS/Checkpoint/发布/撤权专项通过。交付前61条状态路径与隔离副本逐路径、逐文件SHA-256一致；52个源码/契约/脚本/测试/评测文件清单SHA-256为92D559884EEA235BB217277519BC4BE765323ED8290268EEBEB9F1338E2265AD。原工作区与隔离副本两处lockfile均未变。无实际模型/API Key/真实招标文件或法规正文外发；源码提交远端 Full 与 verify-required 已通过，TASK-0018本地及远端交付闭环，DEC-002仍待批准。详见`docs/development/TASK-0018-validation.md`。
- TASK-0011已归档：源码候选`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`的 Windows baseline、PostgreSQL、ingestion、verify-required CI 全部成功；验收记录CI和归档CI的impact/quick/verify-required适用作业成功。归档提交`05c2b91655a7152b28692c7f5216de3ace3d7ff8`对应归档CI 38604186570。源码本地 Full 510 passed（对应源码`57d3a833f59a09e9c938837671a8769d91c7fc5b`，其后仅扩展前端LF检出属性），FR-013 Focused 69 passed，PostgreSQL16两个专项通过；真实 Microsoft Edge Playwright E2E 5/5，使用真实 FastAPI/PostgreSQL/文件服务及授权注入的离线ReviewEngine，并验证持久化结果。前端 OpenAPI生成内容与契约一致；Windows CRLF检出问题已通过`.gitattributes`固定所有前端文本为LF解决。详情见`docs/development/TASK-0011-validation.md`。
- TASK-0009归档候选：源码`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`的Focused13、最终Full500（0失败/错误/跳过）、Ruff、Mypy80文件、契约/生成/秘密检查、真实HTTP/身份/撤权和PostgreSQL恢复/并发/事务故障专项通过。用户确认源码及验证记录提交的必要远程CI通过；本次归档记录Quick通过，归档提交远程CI待核验。DEC-002未批准、在线模型调用未验证、预算账本仅单进程一致性、法律证据最高为suspected；TASK-0010源码/记录/归档CI均已成功。详见`docs/development/TASK-0009-validation.md`。
- TASK-0010源码候选`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`：最终完整`verify.ps1 -Mode Full`通过504项、0失败/错误/跳过；Ruff、Mypy85源文件、契约/生成一致性与真实HTTP/身份/项目流程通过。PostgreSQL16真实迁移/RLS/复合FK/并发/回滚及TASK-0009审查恢复、TASK-0010决定幂等与并发、共享结构化报告、DOCX/PDF生成、原文回查、授权与拒绝导出审计专项通过。源码CI38556383801、验收记录CI38557180768及归档CI38557509858均全部适用作业成功。DEC-002未批准，生产模型路由仍关闭。详见`docs/development/TASK-0010-validation.md`。

- TASK-0007最终代码源码236d2a6e231be030f719b0bbabc3f2b0a50039b3：Focused 30项通过；Full 448项、0失败/0错误/0跳过，Ruff、Mypy64源文件、契约生成检查及真实HTTP/身份/项目/撤权/租户隔离验证通过。Full在本机回环网络授权下执行，JUnit `.verification/pytest-result.xml`；两个既有pypdf `add_js`弃用警告。远程https://github.com/w186www/Tender-Review/actions/runs/38516913371 对应该源码，impact/baseline/postgres/ingestion/verify-required全部success；远端JUnit artifact已生成，但下载接口需认证，未声称远端测试数量。代码提交与证据绑定；后续文档/任务归档改动仅Quick，不重复Full，不合入main、不启动TASK-0008。详见docs/development/TASK-0007-validation.md。

- TASK-0006最终源码5347b110a8c3561c72086afd455755810de59abf：一次Full413项、0失败/错误/跳过，Ruff/Mypy54源文件与契约/生成、两个实际HTTP通过；真实PostgreSQL原迁移/RLS/复合FK/增量降级及全局核验/发布竞争、最小权限、撤权、失败事务回滚/历史重现通过。最终固定Docker官方PDF84条/15页、隔离、MinIO/ClamAV/OCR/HTTP全部通过，测试容器清理。远程https://github.com/w186www/Tender-Review/actions/runs/38510406707 completed/success，impact/baseline/postgres/ingestion/verify-required全部success，下载远程JUnit413/0/0/0。归档/证据后仅Quick，源码无变化，不重复Full。

- TASK-0006历史D03续建：95项Focused、真实PostgreSQL16及最终Full323项通过（JUnit0失败/0错误/0跳过，Ruff、Mypy48文件、正式契约/生成与两项实际HTTP检查）。修复Result v1alpha3正式EvidenceRef/资格矛盾/引用集合与冻结制品解析；D07同文本制品引用部分修复，原始清洗映射等余项保留。最终源码f0bd8270d990d5e5dc6897f329a770d7db332099已推送，远程https://github.com/w186www/Tender-Review/actions/runs/38498549575 completed/success，baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验323/0/0/0，后续仅工程记录Quick，无重复Full；TASK-0006继续in_progress。

- TASK-0017已归档：初始0016b306源码本地Full277项，但远程38446832736最终failure；日志确认旧42份法规CRLF哈希与Linux LF检出不一致。修复源码68d67a80943e9c531f58ced7557d0c24938d84e9，84项Focused、真实PostgreSQL16专项和最终Full279项通过（0失败/0错误/0跳过，Mypy48源文件及两个真实HTTP检查）。远程https://github.com/w186www/Tender-Review/actions/runs/38496768950 completed/success：baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验279/0/0/0。仅记录/归档变动后Quick通过，未重复Full。完成规则ADR-0011，证据TASK-0017-validation.md；TASK-0006没有自动完成。

- TASK-0006本轮纠正：最终完整verify.ps1通过251项、0失败/0错误/0跳过（JUnit已核对），Mypy48文件；真实HTTP健康/身份/项目/撤销通过。56项法规专项、109项组合检查通过；临时PostgreSQL16增量/重复迁移、RLS/WITH CHECK、最小权限、运行读取/撤权/触发器/完整回滚实证通过，容器已清理。两次中间失败保留在TASK-0006-validation.md；无远端CI新证据。

- TASK-0006历史恢复分支自测（不是独立审查）：25项通过；Mypy46源文件无错误；真实43版本/3120条款摄取、新版84条完整提取与政府工程投标保证金检索通过。归档后最终完整verify.ps1通过215项、0失败/0错误/0跳过（JUnit已核对），真实HTTP健康及身份/项目/撤销流程通过；Ruff与契约/生成一致性通过。见docs/development/TASK-0006-validation.md。

- TASK-0005本地：完整verify.ps1通过，186项、0失败/0跳过，Mypy41源文件；真实解析隔离、官方源码MinIO/ClamAV/OCR/扫描PDF/HTTP及PostgreSQL增量迁移/RLS均通过。
- TASK-0005最终源码远程实证：4d6fca6b16fbae66aed82041e08097162a444468，https://github.com/w186www/Tender-Review/actions/runs/38424742422 的baseline/postgres/ingestion均completed/success；已下载JUnit核验186项、0失败/0错误/0跳过。详细范围见docs/development/TASK-0005-validation.md。本次归档证据提交另触发相同CI，链接绑定明确源码版本，不将该SHA冒充后续HEAD。

- TASK-0004本地最新：完整verify.ps1通过，152项测试、0失败/0跳过，Mypy检查27个源文件；真实HTTP身份与项目流程通过。
- TASK-0004最终代码远程实证：提交5dca2e341b97ce08d830a91936ca4d3d0f511aaa，https://github.com/w186www/Tender-Review/actions/runs/38393126223 的baseline与postgres均completed/success。已下载远程JUnit核验152 tests、0 failures、0 errors、0 skipped。链接对应明确的代码SHA；本证据文档提交自身另触发CI，不将代码SHA冒充后续HEAD。

- TASK-0015历史结果：按项修复后完整verify.ps1通过，121项测试、0失败；当时Mypy检查18个应用源文件，真实HTTP检查通过。分项记录见docs/development/TASK-0015-validation.md。
- 健康200、未知路径404、请求编号一致；临时服务已停止。默认启动方式：./scripts/start.ps1。
- 独立环境安装与pip check通过，实际版本已锁定；TASK-0002证据见docs/development/TASK-0002-validation.md，M0历史证据见baseline-validation.md。
- 远程CI已实际成功：提交1e744ed15e7d35934cbe536695ab2b8276b02980，运行https://github.com/w186www/Tender-Review/actions/runs/38388275001，状态completed/success。该链接核验对应源代码提交；证据提交会另行触发CI，不能将历史SHA冒充当前HEAD。
- 没有宣告业务审查、数据库就绪或完整生产安全验收。

## 已知问题

- TASK-0011的真实浏览器链路与FR-013配置版本管理已通过本任务局部验收并正式归档；局部完成不代表相关全局AC或M3已完成。
- Word内嵌图片需人工转录；DOCX外部关系含超链接严格拒绝；中文复杂版面质量仍需黄金集验收。详见secure-ingestion-start.md。
- 本机Docker Linux Engine已可用（29.2.1）；临时PostgreSQL16本机迁移/权限/RLS/并发/回滚与真实S3/扫描/OCR检查通过，仅测试服务已清理。TASK-0005历史PowerShell完整门禁186项全通过；当前任务结果见最近验证。
- Windows受限沙箱会阻断asyncio内部回环连接；完整验收须允许本机回环网络，不能跳过测试。
- 系统默认Python存在打包路径/ensurepip问题。已使用独立Python 3.12.14环境，统一脚本优先使用.venv；新环境按README创建，测试临时目录限定在项目内。
- 法规元数据已固定43个版本：42份旧文本仍未逐项核实，1份司法部2019修订《实施条例》核验到2026-10-14且仅启用工程范围。本期全局管理服务/鉴权CLI已实现；完整生产法规效力验收、pgvector、神经语义召回及管理前端仍待实施。
- 《建设工程施工合同（示范文本）》等 3 项资料未收录，详见 `knowledge/legal/索引.md`。
- 默认OCR已按ADR-0008采用中英文Tesseract端口、存储提供S3和本地开发适配；首选模型、生产服务和部署环境仍待确定。
- 当前方案不安装或下载BGE/PaddleOCR。百炼模型为供应商托管且权重/Tokenizer修订无可固定身份；DEC-002 的一次本地合成数据授权已消耗，任何后续真实模型调用、真实数据处理或部署均未授权。跨进程预算账本、生产级模型审计、云端质量评测及真实样本验证需后续独立TASK和授权。

## 待决策

- DEC-001：首个部署目标（本地 Docker Compose、云主机或 Kubernetes）。
- DEC-002：已批准 TASK-0021 一次合成数据演示；生产模型、真实业务数据处理与部署约束仍待决策。
- DEC-003：Tesseract为首期实现；生产扫描件性能预算与复杂中文版面效果待评估。
- DEC-004：前端技术栈与企业OIDC集成；首期本地认证已按ADR-0007落地。

## 数据与迁移

- 数据库迁移版本：202610151000（TASK-0018解析引擎/模型/参数和容器身份来源追溯，位于202610141900 TASK-0010报告制品迁移之后）；显式执行，API不自动建表，回滚按迁移逆序删除新增结构。
- 契约集合版本：`v1alpha3`；事件信封和模型profile示例维持各自v1alpha1，详见contracts/VERSION.md。
- 生产数据：无。


## 当前分支与审查基线

- 2026-10-14用户新指令覆盖之前的恢复分支限制：实现已保全迁移到work/TASK-0006；git fetch origin main核对最新main=bd2da2da984b6d1c34f3cfdb7da69e21661523be，当前任务分支已包含该提交。无force push/reset --hard，恢复分支和保全stash保留。
- 用户本次指令由ADR-0011记录，撤销ADR-0009默认跨软件/独立代理关卡；现有实现/问题与法规ADR-0010 proposed保留。Codex按实际验收自行收尾，不能假称独立审查或自动关闭问题。
- 不恢复DeepSeek派工或自动代理审批。当前无额外代理运行；保留历史审查的真实发现作为问题清单。

当前TASK-0007验收源码236d2a6e231be030f719b0bbabc3f2b0a50039b3；本地Focused30、Full448/真实集成和远程38516913371适用作业全部成功，任务已完成并归档。TASK-0008验收源码`4d1f59f69143c63c7d4273958a12da19ecf5acdf`（归档前工程记录提交`5b9b9f1bf68b245abb05b75cd855d07d30497d2a`）从归档提交`6edea37c071cfcec6cf8354b9d74f92fbcaba0a5`创建并包含TASK-0007验收源码；原stash@{0}仍保留。Focused54项、Full487项、真实本机后端/身份检查及源码提交远程CI运行`38521959503`（impact/baseline/postgres/ingestion/verify-required全部success）均通过。TASK0008-001/002按正式验收条件完成并归档；详见`docs/development/TASK-0008-validation.md`。生产预算仅实现单进程原子参考ledger，不能支持多进程生产一致性；DEC-002待批准、生产路由保持禁用，真实在线供应商调用未执行。TASK-0009源码`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`验收通过；源码与验证记录提交远程CI由用户确认成功，归档提交远程CI待核验。TASK-0010源码候选ab878ecd9f5df5d60ea4e27fe7edc451246ca75e本地验收通过，远程CI待执行。
