# TASK-0025 验证记录：证据分类、账本防护与 CI 超时

2026-10-16。基线 `cc94394`，分支 `work/TASK-0023`。本轮只修复源码审查已定位的问题，
不新增功能、不重构 Agent、未调用任何供应商 API。

## 一、证据分类修复（P1）

**根因**：`graph/review.py::merge_findings` 把 `verify_legal_hit` 通过的法条全部计入 `verified_laws`，
再写入 `finding["evidence"]`。但该函数只证明**引用真实性**——法条存在于冻结发布、检索运行可重读一致、
引用字节与条文一致；它**不证明**法律有效性、版本核验或适用性。因此会出现：

- 某法条为 `unverified`（或超核验期、或适用性未知）；
- 模型在 `legal_evidence_ids` 中引用它；
- `verify_legal_hit` 成功 → 进入 `evidence`，同时被排除出 `legal_references`；
- `evidence_status` 仍为 `insufficient_evidence`（最终门禁没有错误升级，但**证据分类错误**）。

**修复**：在节点内区分两类结果。

| 结果 | 判定 | 去向 |
|---|---|---|
| 引用可验证且通过确认链（`eligible_for_confirmation`） | 版本已核验、未超期、条款已核验、已定位、适用性已声明且与项目框架相交 | `finding["evidence"]`（正式法律证据） |
| 引用可验证但未通过确认链 | `unverified`／`outside_verification_horizon`／`applicability_unverified` 等 | `finding["legal_references"]`，带 `confirmation_reason`、`version_status`、`applicable: false` |
| 引用不可验证（运行不可重读、发布不匹配、条文被改写） | `verify_legal_hit` 返回空或引用不符 | 两处都不进入，并标记 `law_invalid` |

`has_confirmable_legal_support` 现在只接收 `confirmable_laws`；`sources` 中的 `retrieval`
标记只由正式法律证据触发。原文证据校验、`evidence_status` 计算和已发布报告契约均未改动。

**修复前后对比**（同一场景：模型选中一条 `unverified` 法条）

| 字段 | 修复前 | 修复后 |
|---|---|---|
| `evidence` | 含该法条（`kind=law`） | 只含标书原文证据 |
| `legal_references` | 空 | 含该法条，标注 `confirmation_reason=unverified` |
| `sources` | 含 `retrieval` | 不含 `retrieval` |
| `evidence_status` | `insufficient_evidence` | `insufficient_evidence`（不变） |

这也消除了此前合成 E2E 出现的"`evidence` 含 `retrieval` 来源、`legal_references` 为空、
状态仍为 `insufficient_evidence`"这条不符合分类要求的路径。

## 二、预算账本回滚防护（P1）

**现状分析**：

- 账本为单文件 SQLite（`.verification/private/TASK-0023/dec005-budget.sqlite3`），
  按授权分别累计调用次数与费用，另有同目录审计日志 `model-audit.jsonl`。
- **正常重启**：账本存在且有记录 → 计数保留 ✓
- **首次初始化**：账本与审计都不存在 → 合法创建 ✓
- **文件丢失/被旧备份覆盖**：单文件是唯一状态源，缺失即被当作首次初始化 → **额度被错误恢复** ✗
- **文件损坏**：原本会抛出 sqlite 错误或被当作空账本 ✗

**已实施的最小修复**：`services/real_ai_runtime.py::verify_ledger_continuity`，在装配网关前检查

1. 审计日志不存在或为空 → 通过（无证据表明发生过调用）；
2. 审计日志非空且账本存在可读、`requests` 表有记录 → 通过（正常重启）；
3. 审计日志非空而账本缺失、为空或**不可读** → **失败关闭**，拒绝恢复额度。

**仍未解决（如实报告为部署阻断）**：本机单目录内的任何锚点都无法检测**两文件被协同回滚**
（审计与账本一起被旧快照覆盖）。可靠防回滚需要部署级支持——外部不可变存储、WORM 审计、
或由 KMS/HSM 签名的调用计数。当前架构**不能**区分"首次初始化"与"整体回滚"，
因此该能力**不宣称已实现**。

## 三、Windows baseline CI 超时（P0）

`.github/workflows/verify.yml` 中 `jobs.baseline.timeout-minutes` 由 10 改为 **20**。
未修改 `quick`（10）、`postgres`（10）、`ingestion`（20）；未跳过、屏蔽或减少任何测试。
该次运行已确认 `619 passed`，被取消的原因是作业达到 10 分钟上限，`KeyboardInterrupt`
落在 PIL/ImageFont.py 只是超时被中断的位置，不构成 Pillow 缺陷结论。

## 四、回归测试

`tests/test_legal_evidence_classification.py`（新增 7 项）：

| 场景 | 断言 |
|---|---|
| 模型选中 `unverified` 法条 | 正式证据不含法条；`legal_references` 含 1 条且 `applicable=false`；`sources` 不含 `retrieval` |
| 模型选中超核验期法条 | 同上，`confirmation_reason=outside_verification_horizon` |
| 模型选中适用性未知法条 | 同上，`confirmation_reason=applicability_unverified` |
| 模型选中被改写条文的引用 | 两处都不进入；状态保持 `insufficient_evidence` |
| 模型选中跨/不可重读运行的引用 | 同上 |
| 模型选中真正通过确认链的法条 | 进入正式证据且 `version_status=verified_current`；`legal_references` 为空；`sources` 含 `retrieval` |
| 模型未选择任何法条 | 检索到的法条仍作为参考候选可见 |

`tests/test_authorized_runtime.py`（新增 3 项）：账本缺失而审计存在 → 失败关闭；
账本不可读 → 失败关闭；首次初始化与正常重启仍被允许。

Word／PDF 与前端的证据分类一致性由 `tests/test_review_reports.py` 的渲染测试覆盖（提取文本断言）。

## 五、边界与未完成

- 未修改法规库内容与核验状态；未重做 TASK-0023 的真实模型审查；未调用 Qwen／Embedding。
- DEC-005／DEC-006 账本与历史记录未重置或删除。
- **部署阻断**：预算账本的防整体回滚能力需要部署级不可变存储支持，当前未实现，不宣称已解决。
