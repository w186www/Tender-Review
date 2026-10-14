# TASK-0018 本地验收与远端交付记录

- 日期：2026-10-15
- 基线：`62c49cd326152f0f5bef75e5cc87efb7014b2f38`，包含 TASK-0011 最终证据提交
- 状态：本地正式验收完成；代码提交远端 Full 与 verify-required 已通过；本次归档证据更新按 Quick 门禁执行
- 范围决策：ADR-0016 经用户批准调整 TASK-0018；ADR-0015 原文保留，不修改 TASK-0012/TASK-0013、已归档任务、法规原文或历史已发布结果
- 数据边界：未读取真实 API Key；未调用在线模型；未上传真实招标文件或法规文本；没有 BGE/PaddleOCR 部署

审计与执行依据包括 `AGENTS.md`、`PROJECT_STATE.md`、`docs/development/roadmap.yaml`、`docs/development/TASK-0010-validation.md`（人工复核/审计报告）、`docs/development/TASK-0011-validation.md`、法规检索与安全解析启动说明、`ADR-0013`、`ADR-0015`、`ADR-0016`、`contracts/VERSION.md` 及 `docs/development/testing-standard.md`。

## 法规检索基线

脚本 `scripts/evaluate_legal_retrieval.py` 每次从固定索引输入重建 43 个法规版本、3,120 个片段，校验索引、清单、查询集和适用性样本哈希，然后使用原有 `CharacterEmbedding`、BM25 与 RRF。没有替换或修改 CharacterEmbedding 算法，也没有把合成向量放入此评测。

| 指标 | 首次基线 | 重复运行 |
|---|---:|---:|
| Recall@5 / Recall@10 | 1.000 / 1.000 | 1.000 / 1.000 |
| MRR@10 | 0.4867 | 0.4867 |
| nDCG@10 | 0.6141 | 0.6141 |
| 平均查询延迟（30 次测量） | 1,202.33 ms | 1,020.30 ms |
| p95 查询延迟 | 1,363.33 ms | 1,212.43 ms |
| 索引构建时间 | 417.39 ms | 见单次报告 |
| 检索前工作集 / 峰值工作集 | 76,177,408 / 125,927,424 bytes | 见单次报告 |
| 未核验法规引用 | 77（独立计数） | 77（独立计数） |
| 专家未确认风险候选 | 0 个已提供标签 | 0 个已提供标签 |

第三次实际复测已单独保存为 [最终复测报告](../../evals/legal_retrieval/results/character-repeat-final-20261015.json)：排序指标仍与前两次完全相同，平均查询延迟为 546.89 ms、p95 为 588.74 ms。三次耗时差异说明这组主机基准下延迟受运行状态影响；排序质量与冻结输入可重复，延迟需连同各次原始报告和资源采样解释，不能用单个数字承诺生产性能。报告 SHA-256：`90b334e084c52191d3f12ee9f3f9e69f61cb0a967888fcc7f7ee654a7fdc61a7`。

两份结果使用相同法规索引 SHA-256 `69d340d65f5e9114c8a2e76f8b3b524b67f47d0cbc0088c4e01d80b7db8729fd`、清单 SHA-256 `7e96248b7851a6b0ffd2d70074a20203dbb76f43c0969be1363e001b723f2813`、查询集 SHA-256 `5cee47a53e7d3c2bd360ce8216be64d824288085ad1021ef32f7f024e93d7266` 和适用性样本 SHA-256 `95c84576832023fc2254ad24d5dd8878f087297c675b7bea4c744403d72c673b`。42 个版本为 `unverified`；检索质量分母只含一个已核验版本内的 10 条查询。77 个未核验候选不计为真阳性。风险候选数据集为空，0 不能解释为确认无风险。

| 过滤类别 | TP | TN | FP | FN | 错误数 |
|---|---:|---:|---:|---:|---:|
| 地区/主体/采购类型/方法/框架适用性 | 1 | 3 | 0 | 0 | 0/4 |
| 法规效力与核验时限 | 0 | 1 | 0 | 0 | 0/1 |
| 检索标签因适用性被错误排除 | — | — | — | — | 0/10 |

这是同一固定数据的复跑证据，不是覆盖 42 个未核验法规的法律结论，也不用于宣称神经检索效果。详细逐查询结果、排序、过滤和资源采样位于 [首次报告](../../evals/legal_retrieval/results/character-baseline-20261015.json)、[重复报告](../../evals/legal_retrieval/results/character-repeat-20261015.json) 和 [最终复测报告](../../evals/legal_retrieval/results/character-repeat-final-20261015.json)。候选数据与复跑说明见 `evals/legal_retrieval/`。

## 百炼 Embedding 接口与向量索引

新增 `EmbeddingProvider` 协议和百炼适配器位于 `src/bidding_compliance/legal/embedding_provider.py`。默认关闭；本任务显式拒绝非 `httpx.MockTransport`。配置不从环境变量读取密钥；调用接口需显式注入 secret，但本任务只在 Mock 中使用测试占位值。适配器验证 endpoint、请求字段、响应顶层 `object/model/usage`、每条向量的 `object/index/embedding`、索引顺序、维数和有限数值；将认证、限流、超时、服务端和 Schema 错误映射为不含正文或密钥的异常。

2026-10-15 查阅的官方文档列出 Qwen3.7 Text Embedding 与 Text Embedding V4，北京和新加坡工作空间端点，维度与批量限制。当前实现身份明确写成 `provider-managed-unversioned`，权重和 tokenizer 哈希为 null；文档核对与 Mock 协议测试不等于真实端点验证、可用性 SLA 或供应商质量评测。

| 模型标识 | 官方列出的维数 | 单批上限 | 单条 Token 上限 | 地域端点模板 |
|---|---|---:|---:|---|
| `qwen3.7-text-embedding` | 256、512、768、1024（默认）、1536、2048、2560 | 20 条文本 | 128,000 | 北京 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings`；新加坡 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/embeddings` |
| `text-embedding-v4` | 64、128、256、512、768、1024、1536、2048 | 10 条文本 | 8,192 | 同上 |

官方目录还列出 Qwen3.7 Text Embedding Flash、text-embedding-v3/v2 等型号；当前 Mock 适配器明确只允许上表两种，不宣称实现了完整型号目录。

成功响应的兼容 API 文档样例包含 `id`、`model`、顶层 `object=list`、`data[]` 中的 `object=embedding/index/embedding` 和 `usage.total_tokens`；`prompt_tokens` 只由部分模型返回，所以适配器将其设为可选。文档列有 400/401/403/429/5xx 等失败类别，Mock 测试覆盖本适配器的安全错误映射。由于不含供应商 tokenizer，适配器不能精确预估每条输入的 token 数；输入超长时依赖供应商 400 拒绝，不重试。

百炼隐私说明（2026-08-25 更新）称数据不用于模型训练、传输加密并会依法存储调用数据。百炼服务协议（2026-09-02 生效）要求上传者具有合法处理权，业务数据原则上按指令处理，但保留法律要求/内容安全处理例外，并描述删除和备份清除限制及中国境内存储/跨境处理规则；部分第三方模型可能由第三方服务商处理。公开资料没有为本项目确认拟用账号/模型的日志保留期、访问主体或新加坡模型的数据驻留细节，故地域 endpoint 不能替代针对项目数据的授权和合规核验。DEC-002 仍待批准，没有任何真实请求。

接口和 SQLite 精确余弦索引独立于法规发布表/快照。SQLite 构建绑定 provider、地域、模型/修订、维度、参数、法律索引 SHA、publication/revision、法规片段/原文哈希和构建器版本；使用批次 checkpoint，缓存键隔离不同 identity，重复构建幂等，失败可续建。仅合成数据验证写入、恢复、校验和、身份/维数隔离和过滤；其向量/排序完全不进入上节质量指标。现有法规快照、Evidence Checker 和历史审查结果不变。约 3,120 个法规片段没有 pgvector 的性能依据；未引入 pgvector。

官方 API、模型、限流、错误、隐私声明和协议资料在 [ADR-0016](../decisions/ADR-0016-task-0018-cloud-embedding-contract.md) 中逐项链接。云端隐私声明不是本项目的数据处理授权，DEC-002 仍待批准。

## Tesseract OCR 合成扫描评测

`scripts/evaluate_tesseract_ocr.py` 生成不含嵌入文字层的三页中文扫描 PDF（双栏、金额、关键条款号、中文多列表格、重复文本）、空白扫描和畸形 PDF。通过正式 `DockerParser` 及固定摘要容器执行；复用 `config/ingestion.yaml`，没有放宽置信度、OCR 页数、解析超时或人工确认门禁。唯一此处报告为 [已审阅指标](../../evals/ocr/results/tesseract-baseline-final-reviewed-20261015.json)。

| 指标/控制 | 实测结果 |
|---|---:|
| CER | 20.79% |
| 关键数字/金额/条款标记 | 5/6 |
| 表格单元格 | 7/14 |
| 预期页码标记 | 3/6 |
| OCR 页/坐标定位合法率 | 100% |
| 重复短语定位 | 0/2 处 |
| Tesseract 平均置信度 | 0.8809 |
| 解析器耗时 / 主机端到端 | 1,515 ms / 2,591 ms |
| 解析进程峰值 RSS / 容器峰值内存 | 90,099,712 / 146,718,720 bytes |
| 超时 / 失败关闭 | 0 次超时；畸形 PDF 为 `INVALID_FILE` |
| 空白低质量降级 | `requires_review`，`LOW_QUALITY` |

固定 Tesseract `5.3.0`、`chi_sim`/`eng` 模型文件 SHA、参数、隔离镜像 SHA 和运行身份哈希均记录在报告。该报告 SHA-256 为 `04507576862982b346463eb18e98216ae2b259051b643fb03358ad2bd932c77b`。双栏扫描合成页的 OCR 结果触发了评测警报，但现有解析质量规则仍把它标为 `passed`。本任务记录该门禁对语义漏识不敏感的证据，不据此放松或悄悄修改门禁，也不把 `passed` 宣称为 OCR 准确。Tesseract 继续保留为默认；未下载或评测 PaddleOCR。没有真实招标件，以上不代表真实文件总体质量。

再次使用同一摘要镜像和隔离策略进行的实际复测另存为 [复测报告](../../evals/ocr/results/tesseract-repeat-20261015.json)，SHA-256 为 `69e86087e59b366b48582dab508c050356fd122d6358407b28ca8bf1a86671b5`。核心质量结果一致：CER 20.79%、关键标记 5/6、表格单元 7/14、页码命中 3/6、定位合法率 100%、重复短语 0/2、空白件人工复核、畸形件 `INVALID_FILE`。复测主扫描页端到端 3,119 ms、解析 1,742 ms、进程 RSS 峰值 90,038,272 bytes、容器峰值 262,799,360 bytes；容器峰值与首测不同，因此保留逐次报告，不把一次峰值当作固定承诺。两次均为合成样本且均触发语义质量警报。

## 运行版本与持久化范围

- `OCRRuntimeIdentity` 绑定引擎/版本、模型文件哈希、参数、隔离镜像哈希和身份摘要；解析耗时、进程 RSS 与容器峰值作为单次解析指标单独传回。
- `EmbeddingModelIdentity` 绑定 supplier/region/model/revision/dimensions/API contract/parameters/权重和 tokenizer 哈希占位。Character 身份保持稀疏算法、没有固定 dense 维度。
- `RetrievalRuntimeSnapshot` 记录原有 BM25/Character/RRF 版本、top-k、融合参数、reranker 状态/版本占位、Embedding 身份及向量 build ID 空值；当前正式运行仍只使用原 CharacterEmbedding 检索。
- `ReviewRuntimeProvenance` 冻结解析文档、Embedding、检索、Prompt 内容 SHA 和模型配置版本/哈希。它属于不可变审查级快照，不替代逐次调用审计；无已批准配置修订时明确标记 `code-default`。
- 新数据库字段仅保存解析来源身份；迁移 `202610151000` 是增量迁移。未改写历史已发布审查结果。

## 向量缓存完整性与 provenance 回归

- `SQLiteVectorIndex` 在生成/读取 manifest、复用已完成构建和搜索候选时，逐项核对索引项与缓存键绑定、维数、向量字节长度/有限数值、缓存 SHA-256 与索引项 SHA-256；缺失或损坏的缓存不再被当作空候选静默跳过。
- `tests/test_legal_vector_index.py` 覆盖完整构建中缓存字节被篡改、缓存行被删除，以及 building checkpoint 的缓存损坏后拒绝续建；拒绝路径覆盖 manifest、build 重用和 search。
- `tests/test_legal_runs.py` 覆盖 provenance JSON 往返/冻结、OCR 身份摘要绑定、重复文档、检索/运行 Embedding 身份不一致、未启用向量索引的约束和额外字段拒绝。
- `scripts/check_review_engine.py` 验证实际 PostgreSQL JSON 快照可按 JSON 语义恢复为严格 provenance 模型，并绑定文档、Embedding、Prompt、模型配置摘要与审查快照哈希；`scripts/check_legal_publications.py` 实际运行通过。
- 上述向量全部是合成向量，不进入 CharacterEmbedding 质量指标。没有真实 Embedding 调用或数据外传。

## 验证状态

| 检查 | 状态 | 证据/说明 |
|---|---|---|
| 官方 npm registry 可达性/依赖安装 | 通过 | DNS 查询 `registry.npmjs.org` 成功（本机解析答复 `198.18.1.207`）；官方 HTTPS GET 状态 200，系统 TLS 校验保持开启。Lockfile 的 216 个 `resolved` 地址全部为 `https://registry.npmjs.org/`；独立副本 `src/frontend` 安装 184 包成功，`package-lock.json` SHA-256 前后均为 `CE42801FF4EF6A086191D78203C91185F582131F8E246AFDB0FEC295E1724A29`。 |
| 仓库治理、契约与秘密 Quick 阶段 | 通过 | 最终任务、验证记录、路线图和项目状态更新后运行 `./scripts/verify.ps1 -Mode Quick`，退出 0。 |
| 正式 Focused | 通过 | 独立验证副本运行正式 Focused：144 passed、0 failed/errors/skipped；Ruff、Mypy 97 个源文件、OpenAPI、Biome、TypeScript、前端 Vitest 6 项与生产构建均通过。JUnit：`.verification/pytest-focused-result.xml`。 |
| 正式 Full 与前端检查 | 通过 | 独立验证副本运行正式 Full：537 passed、0 failed/errors/skipped；前端 Vitest 6 项、OpenAPI、Biome、TypeScript、生产构建以及真实回环 HTTP 健康检查、身份/项目生命周期 smoke 均通过。JUnit：`.verification/pytest-result.xml`。仅有 2 条既有 `pypdf.add_js` 弃用警告。 |
| GitHub Actions（代码提交） | 通过 | [Run 38641374412](https://github.com/w186www/Tender-Review/actions/runs/38641374412)，对应源码提交 da7325bb95a10a10fcca82151c22c6272980d091。impact 选中 mode=full（首次推送无可比较基线，按策略失败关闭到 Full）；baseline 日志为 537 passed、2 warnings；postgres、ingestion、verify-required 均 success。quick 因 Full 模式 skipped，属合法选择。 |
| PostgreSQL 16 专项 | 通过 | 已缓存的 PostgreSQL 16 镜像以 `--pull=never` 启动一次性随机密码容器，仅映射 `127.0.0.1`；`check_postgres.py` 与 `check_legal_publications.py` 均通过。覆盖迁移/ORM、FORCE RLS、租户隔离、复合 FK、并发幂等与 CAS、法规检索运行、Checkpoint 新进程中断恢复、人工决定、撤权、发布生命周期、审计失败事务回滚及本次 ReviewRuntimeProvenance JSON 快照恢复断言。容器结束后清理。 |
| 真实隔离容器安全门禁 | 通过 | 固定 parser SHA `2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597`：`check_parser_sandbox.py` 验证非 root、只读、无网络、无权限提升、noexec tmpfs、512 MiB/32 PID 限额；`check_ingestion_containers.py` 使用合成 PDF/DOCX/PNG/扫描 PDF，通过真实 MinIO、ClamAV、Tesseract、隔离解析、HTTP、定位、租户隔离与下载检查，退出 0 并清理本次服务容器。 |
| 百炼 MockTransport Schema/错误/超时测试 | 通过 | Provider、SQLite 索引和 OCR 夹具专项 22 项通过；模型网关安全/适配器协议 39 项通过；完整 Pytest 中均再次执行。没有真实 HTTP transport、API Key 或供应商调用。 |

正式 Focused 有 1 条、Full 有 2 条既有 `pypdf.add_js` 弃用警告；无失败/错误/跳过。审批后的 DNS/HTTPS、npm 安装及正式 Focused/Full 均只针对 `_task0018_isolated_20261015_a`；随后仅把通过哈希核对的源码、测试和任务记录同步到原工作区。原有 46 项工作内容均保留；TASK-0018 记录按验收结果更新并移至 `tasks/completed`，交付前审计共 61 条状态路径（29 个已跟踪改动、32 个未跟踪文件）；路径集合与隔离副本一致且逐文件 SHA-256 全匹配。52 个源码/契约/脚本/测试/评测文件清单 SHA-256 为 92D559884EEA235BB217277519BC4BE765323ED8290268EEBEB9F1338E2265AD。源码/测试文件时间均早于 Full JUnit 日志，Full 后只有归档/状态文档变化；原工作区 Quick 退出码 0。原工作区与隔离副本的 `package-lock.json` SHA-256 相同。正式本地验收时没有访问在线模型、读取真实 API Key、上传真实文件或法规原文，也没有触碰历史发布快照。交付候选只含合成评测及指标、标识和来源哈希，不含真实招标文件或法规正文。

代码提交远端 CI 与本轮归档证据提交的验证范围分别记录；当前源码 Full 已通过，归档证据更新继续执行 Quick/远端门禁。

## 未授权与后续依赖

- DEC-002 未批准；真实百炼请求、真实 API Key、招标文件或法规文本外发、供应商质量评测均未执行，需后续明确批准与数据处理授权。
- BGE、本地模型权重、PaddleOCR 和在线 OCR 不属 TASK-0018 的验收目标。
- 百炼供应商托管模型未提供本实现可用的权重/tokenizer 不可变摘要，未来如要求跨时间质量可复现，应先取得可固定模型版本契约或明确受控快照策略。
- 跨进程预算账本、逐次调用审计、真实云供应商验收及真实文件样本评估需要另建 TASK；不扩展本 TASK-0018。
- 后续接入建议：Embedding 走 `EmbeddingProvider`，对话/审查模型走既有 `ModelGateway`/Adapter 和授权、Schema、超时/限流、预算、审计边界；代码依赖以现有 `httpx`/Pydantic 契约为主，不把供应商 SDK 或密钥写入业务模块。Qwen Embedding 可按[百炼官方同步接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)另写专用适配器并分配独立 provider/model/region/dimensions 身份；DeepSeek 官方文档本次确认了 [Responses](https://api-docs.deepseek.com/api/create-response/) 与 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 文本生成 API，但截至 2026-10-15 未核实到 Embedding 端点，不能把文本生成响应当向量服务。上线前应重新核对当时的官方模型目录、API Schema、地域/数据处理政策和限流，再决定是否适配或选用其他经批准的 Embedding 服务。
