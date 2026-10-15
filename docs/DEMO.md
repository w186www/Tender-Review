# 演示指南

本文件区分两类演示：**公开可复现**（任何 GitHub 克隆都能运行）与**本机私有**（依赖未入 Git 的真实数据）。
私有步骤未标注为公开可运行时，不得视为克隆环境的必需输入。

## 一、公开可复现演示（无需供应商调用，无需私有数据）

### 1. 法规适用性与检索契约

```powershell
python -m pytest tests/test_legal_applicability.py tests/test_legal_retrieval.py tests/test_legal_runs.py -q
```

覆盖：无已确认法律框架时仍可检索但**永不返回可确认结论**；未知/冲突上下文不得被推断；
已失效、未核验、超期版本不能生成已确认结论。

### 2. 参考候选的渲染与隔离

```powershell
python -m pytest tests/test_review_reports.py tests/test_evidence_checker.py -q
```

覆盖：渲染 DOCX 与 PDF 后**提取文本**断言"可能相关依据（适用性未经确认，仅供参考，不计入已核验证据）"
与条款号、版本状态、未确认原因在两种格式都出现，且参考区域**不出现"违反/违法依据"**；
被改写条文、跨发布引用、运行不可重读三类情况一律被拒绝，`evidence_status` 保持 `insufficient_evidence`。

### 3. 三案例检索结论

可直接阅读 [TASK-0024 三案例检索证据摘要](development/TASK-0024-case-evidence.md)：三个真实风险的标书定位、
命中法规清单（名称/条款号/版本核验/适用状态）、排名结论与边界声明。该文件是私有运行记录的脱敏摘要。

要点话术：**相似度高不等于法律适用**；生产检索**已是逐候选查询**，《民法典》第五百八十五条在
生产查询下排第 7、追加中文法律领域词后第 6；所有命中一律 `applicability_unknown`，可引用依据为 0。

### 4. 环境准备

- Python：使用 `../bidding-compliance-agent-TASK-0021/.venv`（仓库未自带 venv）。
- 必须显式设置 `PYTHONPATH` 为 **Windows 路径形式**指向本仓库 `src`，否则会加载到相邻工作树的代码。

## 二、本机私有演示（公开克隆不可用）

以下步骤依赖**未入 Git** 的真实数据（真实标书的解析片段、真实运行账本与报告），仅在开发机可运行。
GitHub 克隆环境**不包含**这些文件，因此它们不是必需输入。

| 步骤 | 依赖的私有文件 | 作用 |
|---|---|---|
| `python .verification/private/TASK-0024/case_ranking.py` | 真实标书解析片段 `sections.json` | 输出三案例在三种查询构造下的排名 |
| `python .verification/private/TASK-0024/case_retrieval.py` | 同上 | 输出三案例的命中法规明细与适用状态 |
| 打开 TASK-0023 报告 | `.verification/private/TASK-0023/reports/real-ai-review-result.docx`、`.pdf` | 真实 Qwen 运行产出的 Word/PDF |
| 核对真实调用与费用 | `.verification/private/TASK-0023/dec005-budget.sqlite3`、`model-audit.jsonl` | 持久授权账本与模型审计 |

**可公开替代**：上面的排名与命中结论已脱敏写入
[TASK-0024 三案例检索证据摘要](development/TASK-0024-case-evidence.md)，无需私有数据即可复核。

## 三、完整真实审查（需供应商授权与预算）

> 真实运行记录：TASK-0023 / DEC-006，`qwen3.8-flash`，10/15 次调用、¥0.062695。
> **不要**在没有新授权时重跑；演示请使用已有制品与审计。

真实运行要点：天津地铁 11 号线 DOCX，7 批发现覆盖 1207 个非空片段，Skills 候选 0 项而模型独立发现
**19 个候选**，19/19 原文定位一致，**0 条违法断言**，全部 `insufficient_evidence`；19 项人工复核后
发布结果并生成 Word/PDF，下载 SHA-256 与服务端 `content_hash` 一致。详见
[TASK-0023 验证记录](development/TASK-0023-validation.md)。

## 四、必须如实说明的限制

| 限制 | 事实 |
|---|---|
| 法规库核验状态 | 43 个版本中 42 个未核验，唯一已核验版本已超核验期 → **已核验适用法规数为 0** |
| 法规库元数据 | 42 个版本缺生效日期与适用范围声明，无法判定适用性 |
| 语义检索覆盖 | 真实 Embedding 仅覆盖 10/3120 个法规片段，不代表整库 |
| 风险发现上限 | 每批最多 3 项；单次审查候选数量受批次容量约束 |
| 浏览器 | 演示环境使用 ZCode 内置浏览器；IAB 不支持原生文件选择器，文件字节由页面脚本注入标准 input |

**不可宣称**：任何风险的违法认定、任何条款的"已核验适用"、整库法规向量化完成。
