# TASK-0023 验证记录

2026-10-15。独立 `work/TASK-0023`，继承 TASK-0022 未提交成果。

**当前状态：完整真实 AI 审查闭环已打通。** 最后一次运行（DEC-006）在真实网页上完成了
天津地铁 11 号线 DOCX 的审查 → 证据核验 → 人工复核 → 结果发布 → Word/PDF 生成与下载，
模型调用 10/15 次、费用 ¥0.062695。上一轮（DEC-005）的 end-to-end 阻断（`semantic_analysis`
单请求超时）已修复。

## A/B/C/D 状态分类

| 分类 | 内容 |
|---|---|
| **C 已完成真实模型验证** | DEC-005：真实 Qwen 独立风险发现（17 批、1209 片段、41 个原文绑定候选）、真实 `text-embedding-v4`（1024 维、RRF 融合、缓存复用）。DEC-006：7 批发现 + 3 批分批语义分析、19 个模型候选、真实审计与费用账本 |
| **D 已完成网页端到端验收** | **已完成**（DEC-006）。网页完成登录、建项目、上传真实标书、正式校正、上下文确认、发起审查、分批语义分析、证据核验、19 项人工复核、结果发布、Word/PDF 生成与下载（下载内容 SHA-256 与服务端 `content_hash` 完全一致） |
| **B 已通过 Mock/定向测试** | 分批切分/缓存/幂等恢复、预算与失败关闭、候选验证与去重、脱敏、Embedding 契约、图谱失败路径、重试策略 |
| **A 已编写代码** | 见"代码变更"一节 |

禁止把 A 或 B 当作 C 或 D。

## 本轮（DEC-006）真实闭环结果

| 项目 | 结果 |
|---|---|
| 供应商/模型 | 阿里云百炼北京 `bailian` / `qwen3.8-flash`；`text-embedding-v4` |
| 模型调用 | **10 / 15** 次（发现 7 批 + 分批语义分析 3 批） |
| 费用 | **¥0.062695**（授权上限 ¥5） |
| 发现覆盖 | 7 批覆盖 1207 个非空片段；确定性 Skills 候选 0 项 |
| 模型候选 | **19 项**，全部 `origin=model`，全部 `evidence_status=insufficient_evidence` |
| 原文定位 | 报告中 **19/19** 定位均存在于服务端原文片段；含表格单元格与段落 |
| 违法断言 | **0**（全部标注"待核验"，未宣告违法） |
| 人工复核 | 19/19 已提交决定（accepted），复核理由与时间由服务端记录 |
| 结果发布 | `result_published`（结果版本 `a6142d30…`） |
| Word/PDF | 均生成成功；下载 SHA-256 与服务端 `content_hash` 一致（docx `2a6d3087…`、pdf `31e697f0…`） |
| 报告内容 | 含项目/任务/结果版本/执行批次/输入快照/报告版本表格、类别分布、每项证据状态与复核决定、原文定位与限制说明 |

质量抽样（19 项）示例：逾期违约金比例过高、报价得分方法未明确、集团内部黑名单作为资格条件、
合同条款序号重复冲突、财务要求逻辑冲突、谈判顺序规则模糊、报价评分公式缺失、特定认证名称表述。

## 本轮修复的真实缺陷

1. **`semantic_analysis` 单请求超时**（上一轮阻断）：节点现在按 `candidate_id` 稳定排序并确定性分批
   （每批 8 个候选、上限 13 批），每批独立 `call_id`/`node_run_id`/缓存件/契约校验，聚合时累加
   usage 并记录 `semantic_batches` 明细；单批时保持历史 `call_id` 与 `model_analysis` 结构不变。
   真实运行中 3 批语义分析全部成功（此前单批 41 候选连续两次超时）。
2. **脱敏最小化器外发上限与批次容量不一致**：发现批次容量提升到 18,000 字节后，最小化器仍按 9,000
   字节拒绝，导致首批请求在零调用下失败。现在两者绑定同一常量。
3. **发现节点错误码折叠**（上一轮已修）：保留真实网关错误码，`response_invalid` 纳入前后端一致的有界重试。
4. **验证记录 Schema**：验收证据改为仓库内文件引用；`status` 字段不属于任务 Schema 已移除。

## 1. 环境与基线

- 前端：Biome Windows 可执行文件已恢复（2.5.15），lint/typecheck/单测/build 全部通过。
- 后端：`ruff` 通过；`mypy src` 104 个源文件通过；Focused 后端定向测试 **73 项**通过。
- 备份：`_private_backups/TASK-0023-20261015-210602`，清单 689 项 SHA-256 全部匹配。
- 环境隔离注意：TASK-0021 venv 的 `.pth` 指向其自身 `src`，直接设置 `PYTHONPATH` 必须使用 Windows 路径
  形式，否则会静默加载 TASK-0021 的代码。本轮所有运行均显式设置 `PYTHONPATH` 指向 TASK-0023。

## 2. 真实 Qwen 接入（DEC-005 阶段二）

- 装配：`scripts/task0023_real_ai_app.py` → `ModelGatewayService::BailianQwenChatAdapter`，provider `bailian`、
  model `qwen3.8-flash`、profile `dec005-real-qwen`。不是 `OfflineReviewGateway`，无 `MockTransport`。
- 首次最小真实调用（授权合成样本，6 片段 1 批）：
  - provider/model/profile：`bailian` / `qwen3.8-flash` / `dec005-real-qwen`
  - tokens 463 / 236，费用 ¥0.0010076，延迟 4532 ms，`finish_reason=stop`
  - `response_hash=dee3306efd4e451e13926f878d4e20d1724ece84f17db5364d62f408459743e2`
  - 供应商返回 2 项疑点，全部 `origin=model`，服务端定位到 `paragraph:2`、`paragraph:4`，引用哈希 100% 匹配
- 审计（`model-audit.jsonl`）只含身份、模型、tokens、费用、延迟、响应哈希与状态，无 Key、无请求/响应正文。
- 失败不回退 Mock：真实调用失败时审查失败关闭。

## 3. LLM 独立风险发现

合成样本验证（Skills 0 候选 → 模型独立发现）：见上，2/2 引用哈希正确、候选 ID 唯一、`origin=model`。
本地补充验证：空 `findings` 为合法零候选；真实响应重放结果与记录一致；`merge_model_candidates` 二次合并幂等。
虚构/歧义引用拒绝、脱敏映射、表格邻格掩码由 `tests/test_llm_candidate_discovery.py` 覆盖。

真实标书（天津地铁 11 号线 DOCX，SHA `b1ea60ee…63`）：

- DEC-005：17 批全部完成，覆盖 1209 个非空片段，模型独立发现 41 个候选（41/41 引用哈希一致）。
- DEC-006：7 批全部完成，覆盖 1207 个非空片段，模型独立发现 19 个候选并完成后续闭环。
- 两轮候选 ID／去重键均唯一、全部 `origin=model`、未伪装成 Skill 结论。

## 4. 真实 Embedding 与法规检索

- 供应商：DashScope 北京 `text-embedding-v4`，`execution_mode=online`；查询向量维度 1024、全非零、有限、单位范数。
- 法规子集：真实快照 3120 条款中索引 10 条，**覆盖度 10/3120**（不代表整库向量化）。
- SQLite 索引绑定文档片段、模型身份、法规快照与 publication/revision；`bm25-dense-cosine-rrf-1` 同时给出
  BM25 排名、向量排名与融合分数。
- 缓存复用：DEC-006 未授权新的 Embedding 批次（上限 0），运行完全命中既有 `vector_cache`，未产生供应商请求。
- 法规适用框架未确认时保持 `CONTEXT_INVALID`，未为获取法条而修改采购类型。

## 5. 网页端到端（DEC-006）

浏览器后端：本机仅提供 执行环境内置浏览器（IAB），**不是 Microsoft Edge**。IAB 不支持原生文件选择器，
真实标书字节由页面上下文脚本注入到 `input[type=file]` 并触发标准 change 事件，其余全部为正式页面操作。

完成的网页步骤：登录 → 新建项目（企业采购／服务／天津／非招标／企业／服务，适用制度留空）→ 上传真实
DOCX（HTTP 202）→ 按原始 OOXML 核对页脚缓存 `PAGE` 值 `36` 后经正式 corrections API 记录 → 网页确认
上下文（P2 C3，法律框架留空）→ 发起真实 AI 审查 → 分批语义分析 → 证据核验 → 19 项人工复核（网页表单
逐条提交决定与理由）→ 继续审查流程 → 发布不可变结果版本 → 生成 Word／PDF → 下载。
下载文件 SHA-256 与服务端 `content_hash` 一致，未出现 Mock 或离线替代。

## 6. 预算与费用（真实供应商）

| 项目 | DEC-005（已耗尽） | DEC-006（本轮） | 授权上限 |
|---|---|---|---|
| LLM 调用 | 30 | 10 | 15 |
| Embedding 批次 | 3 | 0 | 0（不授权） |
| 费用 | ¥1.081571 | ¥0.062695 | ¥5 |

- 两条授权在同一 SQLite 账本中分别累计：`authorization` 表与 `requests.authorization_id` 列记录归属，
  `summary()` 返回全量 `ledger_history` 供审计；DEC-006 不重置、不回收 DEC-005 的历史计数。
- 失败或未知用量的请求按整笔预留记账，符合授权规定。
- API Key 仅通过 Windows 用户环境变量注入后端进程；未写入代码、日志、命令行参数或仓库。

## 7. 安全与数据边界

- 外发文本经服务端最小化器脱敏（电话、邮箱、带标签姓名、账号、表格邻格），并通过隐私预检；
  合成样本验证了外发文本中无残留联系方式。
- 未发送二进制、整库、密钥文件或无关本机文件；真实标书、报告与运行明细仅落在忽略目录
  `.verification/private/TASK-0023`。
- 未知文档 SHA 被白名单拒绝；`AuthorizedTenderMinimizer` 与 `AuthorizedRealReviewEngine` 双重校验。
- 法规快照仍存在未核验与超过核验期限的限制；真实向量相似度不提升法规证据效力。

## 8. 已知限制

- 为在 DEC-006 的 15 次上限内完成闭环，发现批次容量按输入 token 预算上调（9,000→18,000 字节、
  80→200 片段），批次由 17 降到 7；每批最多 3 项发现的输出上限不变，因此单次审查的候选数量上限降低
  （本轮 19 项，DEC-005 为 41 项）。这是刻意的时间/成本权衡，不是发现能力的改善或退化结论。
- 上一轮真实运行数据库随一次性容器删除，DEC-005 的 run 状态无法恢复，因此 DEC-006 重新执行了风险发现。
- 报告与结果仍受未核验法规限制：19 项全部为 `insufficient_evidence`，需人工与有效法条核验。

## 9. 代码变更（本轮与上一轮）

| 文件 | 变更 |
|---|---|
| `scripts/task0023_real_ai_acceptance.py` | 新增：DEC-005 最小真实调用的验收脚本（含 `--dry-run`） |
| `scripts/task0023_real_embedding_acceptance.py` | 新增：真实 Embedding、SQLite 索引与 RRF 融合的验收脚本 |
| `scripts/run_task0011_e2e.py` | DEC-005 分支改用确定性合成样本（与账本 scope 一致） |
| `src/bidding_compliance/graph/review.py` | `semantic_analysis` 确定性分批与聚合；发现节点保留真实网关错误码 |
| `src/bidding_compliance/services/review_engine.py` | `response_invalid` 纳入有界重试集合 |
| `src/bidding_compliance/services/review_management.py` | 运行投影纳入分批语义记录并排除聚合重复计数 |
| `src/bidding_compliance/services/real_ai_runtime.py` | 最小化器外发上限绑定发现批次容量；支持按授权装配；填充语义批次授权 |
| `src/bidding_compliance/services/llm_candidate_discovery.py` | 批次容量按输入 token 预算调整（18,000 字节／200 片段） |
| `src/bidding_compliance/model_gateway/authorized_runtime.py` | 多授权账本（`AUTHORIZATION_LIMITS`、`authorization_id` 迁移与按授权统计） |
| `src/frontend/src/pages/reviews.tsx` | 前端可重试失败类型与后端策略一致 |
| `scripts/task0023_real_ai_app.py` | 装配 DEC-006 授权 |
| `tests/test_semantic_batching.py` | 新增：分批切分、缓存幂等恢复、契约失败、容量约束、未知引用拒绝 |
| `tests/test_llm_candidate_discovery.py` | 更新错误码断言；容量断言改为从常量推导 |
| `docs/decisions/DEC-006-semantic-batch-authorization.md` | 新增：本轮独立授权记录 |

## 10. TASK-0019／TASK-0022 边界

- TASK-0019 原树未访问、未修改；暂停交接清单指纹仍匹配（结果记录在忽略目录）。
- TASK-0022 原树未写入；本轮只读访问其私有验证目录用于核对校正值与上下文基线。

