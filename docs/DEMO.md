# 演示指南

本文件给出可复现的演示路径，并标明哪些是**真实运行证据**、哪些是**离线测试证据**。

## 一、最短演示（无需任何供应商调用）

### 1. 法规检索解阻对比

```powershell
python .verification/private/TASK-0024/case_ranking.py
```

输出三个真实风险的检索排名，展示：

- 生产检索**已是逐候选查询**（`category + problem_key + matched_reason + 原文摘录`）；
- 《民法典》第五百八十五条在逾期违约金案例的生产查询下**排第 7**；
- 所有命中标注 `applicability_unknown`，可引用依据为 **0**。

要点话术：**Embedding 相似度高不代表法律适用，检索得分不能直接成为合法性判定。**

### 2. 三案例证据链

```powershell
python .verification/private/TASK-0024/case_retrieval.py
```

每个案例输出：标书原文定位、检索命中的法规（名称/条款号/原文/来源/版本状态）、适用状态分布。

### 3. 参考候选的实际渲染

```powershell
python -m pytest tests/test_review_reports.py -q
```

该测试渲染 DOCX 与 PDF 后**提取文本**断言："可能相关依据（适用性未经确认，仅供参考，不计入已核验证据）"
与条款号、版本状态、未确认原因在两种格式都出现，且参考区域**不出现"违反/违法依据"**字样。

### 4. 证据隔离的负路径

```powershell
python -m pytest tests/test_evidence_checker.py -q
```

覆盖被改写条文、跨发布引用、运行不可重读三种情况一律拒绝，并保持 `insufficient_evidence`。

## 二、完整真实审查（需供应商授权与预算）

> 真实运行记录：TASK-0023 / DEC-006，`qwen3.8-flash`，10/15 次调用、¥0.062695。
> **不要**在没有新授权时重跑；本轮演示请使用已有的报告与审计。

已有制品（私有目录，未入 Git）：

- 报告：`.verification/private/TASK-0023/reports/real-ai-review-result.docx`、`.pdf`
- 账本与审计：`.verification/private/TASK-0023/dec005-budget.sqlite3`、`model-audit.jsonl`
- 说明：`docs/development/TASK-0023-validation.md`

真实运行要点：天津地铁 11 号线 DOCX，7 批发现覆盖 1207 个非空片段，Skills 候选 0 项而模型独立发现
**19 个候选**，19/19 原文定位一致，**0 条违法断言**，全部 `insufficient_evidence`；19 项人工复核后
发布结果并生成 Word/PDF，下载 SHA-256 与服务端 `content_hash` 一致。

## 三、必须如实说明的限制

| 限制 | 事实 |
|---|---|
| 法规库核验状态 | 43 个版本中 42 个未核验，唯一已核验版本已超核验期 → **已核验适用法规数为 0** |
| 法规库元数据 | 42 个版本缺生效日期与适用范围声明，无法判定适用性 |
| 语义检索覆盖 | 真实 Embedding 仅覆盖 10/3120 个法规片段，不代表整库 |
| 风险发现上限 | 每批最多 3 项；单次审查候选数量受批次容量约束（为在 15 次授权内完成闭环已上调批次容量） |
| 浏览器 | 演示环境使用 ZCode 内置浏览器；IAB 不支持原生文件选择器，文件字节由页面脚本注入标准 input |

**不可宣称**：任何风险的违法认定、任何条款的"已核验适用"、整库法规向量化完成。

## 四、环境准备

- Python：使用 `../bidding-compliance-agent-TASK-0021/.venv`（仓库未自带 venv）。
- 必须显式设置 `PYTHONPATH` 为 **Windows 路径形式**指向本仓库 `src`，否则会加载到相邻工作树的代码。
- 完整检查：`./scripts/verify.ps1 -Mode Focused -PythonExecutable <python> -TestPaths @(...)`。
