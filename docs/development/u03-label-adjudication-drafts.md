# U03 评测数据身份与待裁定标签材料

更新日期：2026-10-18。责任：TASK-0019 / U03。状态：工程材料已准备，专业裁定未完成（D2）。

## 1. 这组材料是什么

- 五个合成案例（GC-0001—GC-0005）的来源、版本、SHA-256、分区和候选规则已登记在 `evals/capability_baseline/dataset_registry.yaml`。
- 每个案例的原文位置、候选原因、建议类别/严重度、拟用法律依据、适用前提、判断理由、不确定性和待裁定问题，见 `evals/capability_baseline/labels/pending-adjudication.yaml`。
- 这些是**工程侧标签草案**，不是专家金标，不是人工签署记录。`risk_precision`、`risk_recall`、`false_positive_rate` 保持 `null`；五个案例只进入开发/回归分区，不进入冻结验收分母。

## 2. 数据身份

| 项目 | 身份 |
|---|---|
| 五个案例 CRLF 清单 | `78a99d196c6f998d6e427445fa472f9f0a7dd2207145042fb2d76bdba664ccdb` |
| 五个案例 LF 规范化清单 | `ea888e9f9a587b478f3ac2461d00cb4ce45fd1320a47c2c2d2bf5b0ce0762052` |
| 阈值 CRLF / LF | `00194bbf…` / `c6ff964…` |
| 原评测器（备份） | `7b2c2b0673b3f28c1c0cd7c33aea32163e4c42e3c3ea071428ad51307da5712e` |
| 当前评测器（仅格式适配） | `2888a44b2cf9d6b15ac2ca2bb92af654a119cb8084db8c9d60c27700a04ab3c9` |
| 规则集 | `a96326b3dc16e31cadb6bedcb243e3fc86b0dd6f1e77573816bb3e0c4721ceab` |
| 法规检索报告 | `.verification/task0019-legal/u03-character-baseline-20261018.json`，SHA-256 `b4709ef2…` |

原备份 `_backups/worktrees-uncommitted-20261017T080625Z/task0019` 保持只读未改。当前评测器只做了 Ruff 格式化和行宽换行，评测逻辑未改；原始哈希与适配后哈希并列记录，便于对照。历史两份结果原样保存在 `evals/capability_baseline/results/`。

## 3. 可重复运行

```powershell
PYTHONPATH=src ./.venv/Scripts/python.exe scripts/evaluate_legal_retrieval.py --output .verification/task0019-legal/u03-character-baseline-20261018.json
PYTHONPATH=src ./.venv/Scripts/python.exe scripts/evaluate_review_capabilities.py --output .verification/task0019-reuse/u03-baseline-adapted-20261018.json --legal-retrieval-report .verification/task0019-legal/u03-character-baseline-20261018.json
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_review_capability_evaluation.py
```

2026-10-18 实跑结果：`external_model_calls=0`、fixture 模式 5/5、引文/定位 7/7、重复率 0、专家确认 0；法规检索 Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中。以上只代表固定合成夹具与检索排名，不代表真实模型风险质量、法律适用或违法认定。

## 4. 与历史结果的差异

- 指标、案例计数、候选数、引文/定位计数与历史结果一致。
- 案例/阈值哈希差异来自当前 Git 检出的 CRLF；LF 规范化后与历史基线完全一致。
- 规则源清单哈希变化是因为规则源码在 TASK-0019 暂停后发生了兼容演进（`engine.py`/`models.py`）；规则集哈希与新运行一致。
- 法规报告原文件缺失，已用现有离线入口重新生成到新路径；核心指标一致，延迟不同，文件哈希不同。

## 5. 待用户（D2）确认的问题

1. 五个案例是否接受为风险/非风险样本；接受哪些、拒绝哪些、理由是什么。
2. 每个案例的主法律依据和适用前提（草案里给出了候选条文和不确定性）。
3. 建议严重度是否调整（尤其 GC-0001/GC-0002 的 high、GC-0005 的 critical）。
4. 是否补充真实文件样本；真实文件必须有逐文件外发/处理授权记录。
5. 2026-10-14 到期的法规核验期限是否重新核验并延长；未确认前系统只能显示参考条款，不能作为正式法律依据。

在上述问题得到明确、可追溯的人工决定前，U03 不能标记完成，冻结验收集不能建立，产品效果验收不能放行。
