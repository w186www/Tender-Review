# ADR-0016：TASK-0018 的云端 Embedding 契约验证范围

- 状态：已接受（经用户明确批准；适用于 TASK-0018）
- 日期：2026-10-15
- 补充：ADR-0015、ADR-0003、ADR-0008、ADR-0013
- 适用任务：TASK-0018

## 背景

TASK-0018 初始方案按 ADR-0015 评估本地 BGE-base-zh-v1.5，并把 PaddleOCR 作为隔离候选。当前机器采样可用 RAM 约 1.1 GiB；用户据此批准收窄本阶段部署目标。现有 CharacterEmbedding/BM25/RRF 指标是唯一已实测检索质量基线。法规向量不能改变官方原文、法律修订、发布快照或确定性证据门禁。

用户明确禁止本任务读取真实 API Key、调用在线模型、上传真实招标文件或法规运行文本。DEC-002 仍待批准。真实供应商调用、跨进程预算账本、逐次模型调用审计和供应商质量评测属于后续独立任务。

## 决策

1. **保留历史与实测基线。** 不改写 ADR-0015 原文、CharacterEmbedding/BM25/RRF 行为、既有法规发布快照、TASK-0011 及归档任务的验收证据。ADR-0016 只为 TASK-0018 后续工作补充并部分替代 ADR-0015 的计划范围。
2. **本地资源范围调整。** 本任务不要求下载/部署 BGE，也不要求安装/部署 PaddleOCR。Tesseract 继续作为 OCR 默认实现；对合成扫描 PDF 经现有真实隔离解析容器测量质量。不得放宽网络隔离、只读、非 root、CPU/内存/PID/超时/输出限制、定位、失败关闭或人工复核门禁。
3. **Provider 与外发限制。** 保留 CharacterEmbedding 对照，新增模型身份闭合契约、可替换 Embedding Provider 协议及阿里云百炼 OpenAI-compatible Embeddings 适配器。TASK-0018 仅可通过 `httpx.MockTransport` 验证合成输入、请求/响应 Schema、批量上限、状态码、超时和失败处理；Provider 默认禁用，并拒绝非 Mock HTTP Transport。不得从环境变量或仓库配置自动读取凭据。实现的 SecretStr 只接受显式注入；本任务不允许真实凭据或真实请求。
4. **百炼 API 文档契约。** 本 ADR 记录 2026-10-15 查阅的官方资料：北京工作空间端点为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings`，新加坡端点为 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/embeddings`；OpenAI-compatible 请求使用 `model`、文本数组 `input`、`dimensions` 和 `encoding_format=float`。成功响应含顶层 `id`/`model`/`object=list`/`usage` 和 `data[]` 的 `object=embedding`/`index`/`embedding`。Qwen3.7 与 V4 的 `usage` 文档样例保证 `total_tokens`；`prompt_tokens` 仅部分模型返回，因此实现只要求 `total_tokens` 并将 `prompt_tokens` 视为可选。常见 HTTP 错误有 400、401、403、429 和 5xx，具体错误码/消息应按官方错误页及状态处理。当前适配器只允许 Qwen3.7 Text Embedding 和 Text Embedding V4：Qwen3.7 维度为 256/512/768/1024（默认）/1536/2048/2560，每批最多 20 条、每条最多 128,000 Token；V4 维度为 64/128/256/512/768/1024/1536/2048，每批最多 10 条、每条最多 8,192 Token。官方目录另列 Qwen3.7 Text Embedding Flash、text-embedding-v3/v2 等模型，但它们不在本适配器支持列表中。适配器验证批量数/维度，不含供应商 tokenizer，不能预先精确验证每条 token 上限；超限由供应商错误安全拒绝。文档还定义了 `text_type`/`instruct` 一类检索参数，但其用法依赖非 OpenAI-compatible 调用路径；本最小适配器不发送或声称验证这些参数。以上文档核对不代表实际端点连通性、请求验收或 SLA 验证。
5. **模型身份与可复现边界。** 向量身份记录供应商、地域、模型 ID、声明维度、API 契约版本及参数。百炼当前兼容 API 未给出不可变权重/分词器修订身份，因此明确记为 `provider-managed-unversioned`，权重/分词器哈希为空。该身份可以隔离向量空间，但不能证明供应商侧同名模型权重永久不变；正式真实质量对照与生产冻结须等待供应商可固定版本、数据授权和后续任务批准。不得声称云端模型身份已达到权重级确定性复现。
6. **向量存储与安全门禁。** 向量工件使用独立 SQLite 精确余弦索引，不依赖 pgvector。构建清单、模型身份、法条片段/文本哈希、法规索引哈希、publication/revision、维度、索引器版本、校验和及逐批 checkpoint 均绑定。重复执行幂等；失败后可续建；不同模型身份、维度、法规修订或发布身份拒绝混用。重算不写官方法规文本、发布快照、审查结果或历史结果。检索先执行地区/采购范围、效力、核验截止、条款适用性与已核验条件，向量排序只返回候选 ID/分数，不生成或认证证据；Evidence Checker 独立验证原有法规引用。
7. **合成数据的用途。** 仅用合成文本和合成向量测试协议/索引工程。不把这些向量或排名加入法规检索质量指标。CharacterEmbedding 既有实测数据仍是唯一已实测相关性基线。未知法律依据与专家未确认风险继续分开记录。
8. **版本追溯。** 审查级冻结内容包含 OCR 引擎/模型/参数/隔离镜像身份、Embedding 身份、检索算法/top-k/RRF 配置、向量索引构建身份占位、Reranker 开关/版本占位、Prompt 内容哈希和模型配置身份。逐次模型调用审计仍分离，并不在本任务实现或伪造。
9. **在线调用与数据处理。** 截至 2026-10-15，百炼隐私页称输入数据不会用于模型训练、传输数据使用 AES-256 加密，并称模型/应用调用产生的数据依法存储。2026-09-02 生效的《阿里云百炼服务协议》要求用户确认拥有上传数据的合法权利，并描述业务数据按用户指令处理（法律要求/内容安全过滤除外）、删除指令及备份清除限制、默认中国境内数据处理/存储和跨境情形的单独同意等要求；协议也指出部分第三方模型可能由第三方模型商处理。地区 endpoint 不单独证明本项目文件的数据驻留、日志留存期限、访问主体或特定 Qwen 模型的数据流，未来须对拟用地域、账户/模型、数据类型及适用合同单独核验。上述公开政策和协议不构成本项目数据处理授权。DEC-002 和明确的数据处理授权完成前，禁止真实在线模型调用和真实文件/法规文本外发。真实样本只可使用用户明确给定的仓库外路径与范围，本任务默认只生成合成样本。

## 与 ADR-0015 的关系

ADR-0015 是当时的方案和决策历史，保留原文，不删除、不改写。ADR-0016 在 TASK-0018 范围内修订 ADR-0015 第 1、2、6 点的执行计划：不部署本地 BGE、不评测/安装 PaddleOCR，改为 Mock-only 百炼 Provider 契约验证并保留 Tesseract。ADR-0015 中保留 Character 基线、精确本地索引、确定性法律过滤、证据独立验证、快照不可变和真实数据不外发等决策仍然适用。此局部范围变化不批准其他任务、在线调用或生产模型路由。

## 备选方案

- 仍要求在低可用内存环境本地部署 BGE：有较高失败风险，且已超出用户批准的本期范围，不采用。
- 现在部署 PaddleOCR 或直接替换 Tesseract：缺少本机真实隔离质量证据，不采用。
- 以 Mock 向量/排名宣称供应商或法规检索质量：不可验证供应商语义质量，且会污染 Character 基线，不采用。
- 直接引入 pgvector：3120片段可先用本地精确 SQLite 索引；当前无性能/迁移证据，不采用。
- 立即调用百炼验证：DEC-002 和用户数据处理授权尚未完成，禁止执行。

## 验收与限制

- 真实实测只包括已冻结 CharacterEmbedding 检索基线和在受限 Tesseract 解析容器中运行的合成 PDF；合成向量只用工程测试。
- 百炼官方契约通过文档核对与 MockTransport Schema 测试，不宣称真实网络/API/供应商质量已验证。
- 无模型权重级哈希、真实云端向量质量、真实扫描件代表性、PaddleOCR 性能、逐调用预算/审计与生产数据授权是明确未完成事项。
- 任一隔离容器、Docker 或 Postgres 环境不可用时，验收记为阻断/未测，不以 Mock 替代真实隔离解析或数据库专项。

## 后果

TASK-0018 仍能完成契约、持久化/恢复、安全门禁、Tesseract 基线和版本追溯的本地工作；但不产出 BGE 对比、百炼真实向量质量或 PaddleOCR 质量结论。供应商托管模型的未知权重变化降低了跨时间复现能力，须在未来真实调用批准前通过不可变供应商模型版本或受控调用快照策略解决。向量 SQLite 工件不包含法规正文，但其哈希/片段 ID 仍按内部数据管理。未来 Qwen/DeepSeek 适配器可实现相同 `EmbeddingProvider` 协议并使用独立 provider/model/revision/region/dimensions 身份；不得复用百炼索引身份。真实供应商评测、调用级预算账本和调用审计必须通过独立任务与授权完成。

## 官方资料（查询日期：2026-10-15）

- [文本向量同步 API](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api?scm=20140722.H_2712515._.OR_help-T_cn~zh-V_1)
- [Embedding 模型说明](https://help.aliyun.com/zh/model-studio/embedding)
- [模型服务限流说明](https://help.aliyun.com/zh/model-studio/rate-limit)
- [错误码说明](https://help.aliyun.com/zh/model-studio/error-code/)
- [百炼隐私声明](https://help.aliyun.com/zh/model-studio/privacy-notice)
- [阿里云百炼服务协议（生效日期：2026-09-02）](https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20230728213935489/20230728213935489.html)
