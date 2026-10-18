# 产品评测数据基线与标签协议（U03）

状态：U03 准备阶段；本记录不构成业务金标、法律结论或 M5 放行。

## 数据分区与证据等级

- `evals/golden_cases/` 中现有五个案例的 `synthetic` 均为 `true`。目录名称沿用历史命名；因为每个文件都没有裁定人、标签版本和裁定理由，它们当前仅是开发候选，统一按 `development_candidate` 处理。
- 这五个案例均不得计入冻结验收集或安全攻击集，也不得作为法律适用性、违法结论或产品召回率的金标分母。
- 冻结验收集和安全攻击集当前为空。真实/脱敏样本不在本单元默认输入中；用户独立验收样本不得用于调优。
- 当前 `evals/thresholds.yaml` 保持原样，SHA-256：`00194BBF1C7F764B2048ED1CD419D8CBD950F5605B0EF247C29D43E30958550F`。阈值不因样本不足而放宽；没有满足人工裁定及固定分母的样本时，质量指标记为 `not_measured`，不以候选案例推算。

## 当前样本清单

所有哈希在当前 `work/TASK-0027` 固定工作区计算。案例内容只含合成文字/定位，不含真实招标文件。

| 案例 | 当前文件 SHA-256 | 文件内预期 | 分区 | 标注状态 |
|---|---|---|---|---|
| GC-0001 地域资格条件 | `269FEFFA0B62046475D1EEB7FCF044695BBA34822831EB3C90C3FF11C8C49518` | `suspected`，需法规证据及人工复核 | development_candidate | candidate_only；无裁定人/标签版本 |
| GC-0002 排他品牌 | `DCEDEC5130E79F8F9604E8A9FA36D74E93A1CEC9DA745E427C42FE96DD84AB24` | 1 个发现候选 | development_candidate | candidate_only；无裁定人/标签版本 |
| GC-0003 评分总分不一致 | `931A5556C028E38223D1B787016D25D0BBE390FE807A5248CB937090D52D6462` | 1 个发现候选 | development_candidate | candidate_only；无裁定人/标签版本 |
| GC-0004 合同付款占位符 | `A82358B72196B7420BA8DA4233F9818D749D441338274A43049E9BDE103FAA79` | 1 个发现候选 | development_candidate | candidate_only；无裁定人/标签版本 |
| GC-0005 时间先后矛盾 | `5A1A4200B8A96F7FB6165B756FC4856A87532839DD5853A3AC605E515C82267C` | 1 个发现候选 | development_candidate | candidate_only；无裁定人/标签版本 |

若案例内容变化，须增加版本、原因和人工裁定记录并更新哈希；原有案例文件不通过覆盖方式“升级标签”。

## 标签字段与统计口径

下一版可供裁定的标签记录应把下列信息分开保存：

- 原文证据：输入文件身份、段落/页码/表格单元格定位、原文摘录和定位核验状态。
- 风险标签：风险类别、严重度、是否为风险、适用前提、非风险理由及裁定人/裁定时间/标签版本。
- 法律标签：候选依据、适用主体/地区/采购制度/方式、效力区间、核验状态及法律裁定人；未签署时只能记录 `unknown` 或 `unverified`。

风险真值、原文位置正确性和法律适用性分别计数，不能用其中一类通过替代另一类。每个正式汇总须记录评测集身份、代码/规则/法规/Prompt/模型配置身份、分子分母、排除项、失败案例 ID 及样本限制。沿用既有阈值文件；具体统计实现先与原 TASK-0019 冻结评测器及历史报告核对，再复用，不在缺失来源时猜测或新造兼容性断言。

## 来源核对与当前限制

暂停清单 `tasks/handoffs/TASK-0019-paused-20261015.md` 记录的原 worktree 路径为 `D:\自由项目\招标审核\bidding-compliance-agent`，并列出冻结评测器、测试、两份结果及 TASK 文件的 SHA-256。核验时该目录不存在，`git worktree list --porcelain` 只列出当前 TASK-0027 工作区；对应评测器/测试/结果也不在当前固定目录。未按未知内容重建或覆盖这些文件，原 TASK-0019 仍为 `blocked`，其冻结清单保留作来源指纹。

2026-10-17 的检查只看了 `repo-20261017T081226Z.bundle`，未发现同目录的未提交工作树备份；该结论不完整，2026-10-18 已纠正，见下节。

## 2026-10-18 来源纠正与最小复用（只读核验）

用户指出并确认存在 `D:\自由项目\招标审核\_backups\worktrees-uncommitted-20261017T080625Z	ask0019`。本次只读核验结果：

| 类别 | 结果 |
|---|---|
| 评测工具 | `untracked/scripts/evaluate_review_capabilities.py` SHA-256 `7b2c2b0673b3f28c1c0cd7c33aea32163e4c42e3c3ea071428ad51307da5712e`，与暂停清单一致 |
| 评测测试 | `untracked/tests/test_review_capability_evaluation.py` SHA-256 `e59247e9a47b84b8cd4c25a77b5a2405fb1fda714122003b2893c25a8cafd640`，与暂停清单一致 |
| 两份基线结果 | `task0019-baseline-20261015.json` / `task0019-baseline-final-20261015.json`，SHA-256 `9031…` / `1696…`，与暂停清单一致 |
| 原 TASK 文件 | `TASK-0019-offline-capability-baseline.yaml` SHA-256 `faf9e12f…`，与暂停清单一致 |
| 五个黄金案例 | 当前检出为 CRLF；按 LF 规范化后的逐文件 SHA-256 与原结果清单一致，清单哈希 `ea888e9f9a587b478f3ac2461d00cb4ce45fd1320a47c2c2d2bf5b0ce0762052` 与原基线完全相同 |
| 阈值 | 当前 CRLF；LF 规范化 SHA-256 `c6ff96427ec97b6eaa3662e3b3d7afe8b96a75e0dfbdfdade54215ed35db2316`，与原基线一致 |
| OCR 报告 | `evals/ocr/results/tesseract-baseline-final-reviewed-20261015.json` SHA-256 `04507576862982b346463eb18e98216ae2b259051b643fb03358ad2bd932c77b`，与原基线一致 |
| 法规检索数据 | 查询集/适用性案例/索引/清单快照均在当前仓库；当前 `character-baseline-20261015.json` 的 Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中，与原基线指标一致 |
| 原法规报告 | 原结果引用的 `.verification/task0019-legal/character-baseline-20261015.json`（SHA-256 `47df…`）不在备份或当前仓库；当前检入报告是等价指标、不同运行/哈希 |
| 专家确认标签 | 原结果明确 `expert_confirmed_risks=0`、`expert_confirmed_nonrisks=0`、`candidate_unconfirmed=5`；从未具备专家风险/非风险标签 |

**只读复用验证（不覆盖原结果）**：用备份中的原脚本（哈希未变）加载当前仓库资产，输出到 `.verification/task0019-reuse/current-baseline-readonly.json`。结果：`external_model_calls=0`、5/5 fixture 期望模式、7/7 引文/定位匹配、`expert_confirmed_* = 0`；法规检索指标与原基线一致。当前 `fixture_manifest_sha256`/`thresholds_sha256` 的原始字节哈希因 CRLF 与历史 LF 不同，但 LF 规范化后与历史清单一致；`rule_source_manifest_sha256` 因后续模型候选 provenance 代码演进而不同，`ruleset_sha256` 与原基线一致。该差异是检出/代码演进身份，不是案例内容缺失。

**分类与最小复用方案：**

1. **已找回且来源匹配**：评测脚本、测试、两份结果、原 TASK 文件、五个合成案例、阈值、OCR 报告、法规检索查询/适用性/快照/当前等价报告。
2. **尚缺的运行依赖**：原 `.verification/task0019-legal/character-baseline-20261015.json` 精确文件；当前 CRLF 检出导致原始字节清单/阈值哈希与历史 LF 基线不同。前者可在获准恢复时用现有离线法规检索入口重新生成到**新路径**（不覆盖旧结果）；后者用 LF 规范化视图或干净 LF 检出复现，不修改保护文件。
3. **从未具备**：专家确认的风险/非风险标签；五个案例只能作为 `development_candidate`，风险 precision/recall 仍为 `not_measured`。这需要 D2 指定裁定人，不能从备份“找回”。

**边界**：TASK-0019 仍为 `blocked`，本次没有解包/导入/覆盖备份、没有复制评测器进正式路径、没有解除暂停、没有改任务状态或阈值。最小复用限定为只读验证；正式恢复需用户明确授权，并按原任务允许路径接入原脚本/测试、记录新的资产身份，且不能把五案例称为专家金标。
