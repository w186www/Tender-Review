# TASK-0023 验证记录

2026-10-15。独立 `work/TASK-0023`，继承 TASK-0022 未提交成果。本轮使用 DEC-005 批准的阿里云百炼真实
Qwen 与真实 Embedding 完成了真实供应商验证，但**未能完成端到端审核**，详见"阻断"一节。

## A/B/C/D 状态分类

| 分类 | 内容 |
|---|---|
| **C 已完成真实模型验证** | 真实 Qwen 独立风险发现（17 批、1209 片段、41 个原文绑定的候选）；真实 `text-embedding-v4`（1024 维、RRF 融合、缓存复用）；真实供应商审计与费用账本 |
| **D 已完成网页端到端验收** | **未完成**。已用正式网页完成登录、建项目、上传真实标书、正式校正、上下文确认、发起真实 AI 审查与重试；未完成人工复核与 Word/PDF 报告 |
| **B 已通过 Mock/定向测试** | 预算与失败关闭、候选验证与去重、脱敏、Embedding 契约、图谱失败路径、重试策略 |
| **A 已编写代码** | 见"代码变更"一节 |

禁止把 A 或 B 当作 C 或 D。

## 1. 环境与基线

- 前端：Biome Windows 可执行文件已恢复（`@biomejs/cli-win32-x64/biome.exe` 2.5.15），lint/typecheck/单测/build 全部通过。
- 后端：`ruff` 通过；`mypy src` 104 个源文件通过；Focused 后端定向测试通过（68 项）。
- 备份：`_private_backups/TASK-0023-20261015-210602`，清单 689 项 SHA-256 全部匹配。
- 环境隔离注意：TASK-0021 venv 的 `.pth` 指向其自身 `src`，直接设置 `PYTHONPATH` 必须使用 Windows 路径
  形式，否则会静默加载 TASK-0021 的代码。本轮所有运行均显式设置 `PYTHONPATH` 指向 TASK-0023。

## 2. 真实 Qwen 接入（阶段二）

- 装配：`scripts/task0023_real_ai_app.py` → `ModelGatewayService::BailianQwenChatAdapter`，provider `bailian`、
  model `qwen3.8-flash`、profile `dec005-real-qwen`。不是 `OfflineReviewGateway`，无 `MockTransport`。
- 首次最小真实调用（授权合成样本，6 片段 1 批）：
  - provider/model/profile：`bailian` / `qwen3.8-flash` / `dec005-real-qwen`
  - tokens 463 / 236，费用 ¥0.0010076，延迟 4532 ms，`finish_reason=stop`
  - `response_hash=dee3306efd4e451e13926f878d4e20d1724ece84f17db5364d62f408459743e2`
  - 供应商返回 2 项疑点，全部 `origin=model`，服务端定位到 `paragraph:2`、`paragraph:4`，引用哈希 100% 匹配
- 审计（`model-audit.jsonl`）只含身份、模型、tokens、费用、延迟、响应哈希与状态，无 Key、无请求/响应正文。
- 失败不回退 Mock：真实调用失败时审查失败关闭。

## 3. LLM 独立风险发现（阶段三）

合成样本验证（Skills 0 候选 → 模型独立发现）：见上，2/2 引用哈希正确、候选 ID 唯一、`origin=model`。
本地补充验证：空 `findings` 为合法零候选；真实响应重放结果与记录一致；`merge_model_candidates` 二次合并幂等。
虚构/歧义引用拒绝、脱敏映射、表格邻格掩码由 `tests/test_llm_candidate_discovery.py` 覆盖。

真实标书（天津地铁 11 号线 DOCX，SHA `b1ea60ee…63`）：

- **17 个 discovery 批次全部完成**，覆盖 1209 个非空片段（计划 17 批，逐批记录覆盖与拒绝项）。
- **模型独立发现 41 个候选**，确定性 Skills 候选 0 项。
- 全部候选 `origin=model`，provenance 模型身份 `qwen3.8-flash`。
- 候选 ID 与去重键均唯一；**41/41 引用哈希与原文一致**；定位包含 30 个段落与 11 个表格单元格。
- 类别分布：contract 16、qualification 10、procedure 9、evaluation 3、technical 3。
- 未产生未经原文支持的候选，也没有把模型候选伪装成 Skill 结论。

## 4. 真实 Embedding 与法规检索（阶段四）

- 供应商：DashScope 北京 `text-embedding-v4`，`execution_mode=online`；查询向量维度 1024、全非零、有限、单位范数。
- 法规子集：真实快照 3120 条款中索引 10 条，**覆盖度 10/3120**（不代表整库向量化）。
- SQLite 索引 build_id `96a3c680…` 绑定文档片段、模型身份、法规快照与 publication/revision。
- 检索：`bm25-dense-cosine-rrf-1` 同时给出 BM25 排名、向量排名与融合分数（10 个命中均有双排名）。
- 缓存复用：第二次相同检索未产生新的供应商批次（批次计数不变），避免重复付费。
- 法规适用框架未确认时保持 `CONTEXT_INVALID`，未为获取法条而修改采购类型。

## 5. 网页端到端（阶段六）

浏览器后端：本机仅提供 ZCode 内置浏览器（IAB），**不是 Microsoft Edge**。IAB 不支持原生文件选择器，
真实标书字节由页面上下文脚本注入到 `input[type=file]` 并触发标准 change 事件，其余全部为正式页面操作。

已完成的网页步骤：

1. 登录（真实租户 `tenant-a/reviewer`，令牌仅存 sessionStorage）。
2. 新建项目（企业采购 / 服务 / 天津 / 非招标 / 企业 / 服务，适用制度**留空**）。
3. 上传真实 DOCX（HTTP 202，页面显示真实 SHA-256、扫描与解析状态）。
4. 解析质量门禁要求人工检查：按原始 OOXML 核对两个页脚图形均含缓存 `PAGE` 域值 `36`，
   经正式 corrections API 记录该确切源文本（parse 2 / context 2，issues 清空）。
5. 网页确认上下文（天津、企业、服务类、非招标；法律框架留空，未强改政府采购），达到"可用于审查"（P2 C3）。
6. 发起真实 AI 审查，并在失败后使用网页"重试审查"按钮。

未完成：人工复核、Word/PDF 报告，以及报告与实际运行数据的一致性核对。

## 6. 阻断（未完成项的具体错误）

**阻断 1：`semantic_analysis` 节点超时，且 LLM 预算已用尽。**

- `llm_candidate_discovery` 17 批全部成功后，`semantic_analysis` 将 41 个候选放入**单个**请求，
  在 DEC-005 授权的 60 秒超时内未返回（连续两次，`failure_code=timeout`）。
- LLM 调用已达 DEC-005 上限 30 次，无法再验证修复，因此停止重试。

**最小修复建议**：把 `semantic_analysis` 改为按候选分批（与 discovery 相同的模式）——每批 ≤10 个候选、
每批独立 `call_id`／缓存件／响应校验、按 `candidate_id` 合并 `findings` 并累加 usage。候选数不超过批次上限时
行为与现在完全相同，因此改动面可控。

**阻断 2：真实模型对单批次输出存在偶发不合规响应。**

- 同一批次（index 6，80 片段）在该修复前连续两次返回 `response_invalid`；相同输入的精确重放两次均通过本地
  严格校验（`object_pairs_hook` 拒绝重复键 + Draft 2020-12），说明是模型侧偶发而非确定性契约问题。
- 影响：单批失败会中止整个审查。

**本轮已实现的相关修复（通过定向测试，未获真实网页端到端验证）**：discovery 节点此前把所有失败折叠为
`llm_discovery_failed`，使 `ReviewEngine.retry` 的 `retryable` 集合（网关错误码）**永远无法匹配**，
有界重试实际不可达。现在节点保留真实网关错误码，并把 `response_invalid` 纳入有界重试集合（前后端一致）。
该修复在本轮真实运行中生效：批次 6 在修复前连续两次失败，应用修复后重试成功并继续完成全部 17 批。

## 7. 预算与费用（真实供应商）

| 项目 | 已用 | 授权上限 |
|---|---|---|
| LLM 调用 | 30 | 30 |
| Embedding 批次 | 3 | 200 |
| 累计费用 | ¥1.081571（LLM ¥1.080404 + Embedding ¥0.001167） | ¥20 |

- 失败或未知用量的请求按整笔预留记账（两次失败的批次各 ¥0.25），符合 DEC-005 规定。
- API Key 仅通过 Windows 用户环境变量注入后端进程；未写入代码、日志、命令行参数或仓库。

## 8. 安全与数据边界

- 外发文本经服务端最小化器脱敏（电话、邮箱、带标签姓名、账号、表格邻格），并通过隐私预检；
  合成样本验证了外发文本中无残留联系方式。
- 未发送二进制、整库、密钥文件或无关本机文件；真实标书与详细报告仅落在忽略目录
  `.verification/private/TASK-0023`。
- 未知文档 SHA 被白名单拒绝；`AuthorizedTenderMinimizer` 与 `AuthorizedRealReviewEngine` 双重校验。
- 法规快照仍存在未核验与超过核验期限的限制；真实向量相似度不提升法规证据效力。

## 9. 代码变更（本轮）

| 文件 | 变更 |
|---|---|
| `scripts/task0023_real_ai_acceptance.py` | 新增：DEC-005 最小真实调用的验收脚本（含 `--dry-run` 前置校验） |
| `scripts/task0023_real_embedding_acceptance.py` | 新增：真实 Embedding、SQLite 索引与 RRF 融合的验收脚本 |
| `scripts/run_task0011_e2e.py` | DEC-005 分支的合成样本改用确定性生成（与账本 scope 一致） |
| `src/bidding_compliance/graph/review.py` | discovery 节点保留真实网关错误码，不再全部折叠为 `llm_discovery_failed` |
| `src/bidding_compliance/services/review_engine.py` | `response_invalid` 纳入有界重试集合 |
| `src/frontend/src/pages/reviews.tsx` | 前端可重试失败类型与后端策略保持一致 |
| `tests/test_llm_candidate_discovery.py` | 更新并新增覆盖真实错误码保留与契约失败折叠的断言 |

## 10. TASK-0019／TASK-0022 边界

- TASK-0019 原树未访问、未修改；暂停交接清单指纹仍匹配（结果记录在忽略目录）。
- TASK-0022 原树未写入；本轮只读访问其私有验证目录用于核对校正值与上下文基线。
