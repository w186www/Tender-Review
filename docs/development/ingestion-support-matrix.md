# 摄取支持矩阵与质量信号（U06 开发基线）

状态（2026-10-18）：用户已批准 D1 首版范围——自托管单机、多租户、人工复核；支持 PDF、DOCX、PNG、JPEG；单文件最大 10 MiB、300 页，其中 OCR 最多 30 页；保留五类审查能力并继续执行本矩阵的安全、解析资源和质量限制。本文件是该已批准范围的工程执行基线；超限、解析不可靠或覆盖不足时必须明确拒绝、转人工或显示部分完成，不得静默截断后显示全部完成。U06 的专业效果验收仍需 U03 冻结样本与 D2 标签，D1 批准本身不等于产品效果验收。

## 1. 格式与硬限制

硬限制来自 `config/ingestion.yaml` 的 `IngestionPolicy`，并由上传校验、隔离解析器和质量门禁分别执行；任何一项失败都不会进入审查。

| 项目 | 当前值 | 执行点 |
|---|---|---|
| 单文件大小 | 10 MiB | `validation.py` / 上传限制 |
| 页数 | 300 | 解析器与 `PAGE_LIMIT` |
| OCR 页数 | 30 | `OCR_LIMIT` |
| 单图像像素 | 20,000,000 | `IMAGE_LIMIT` |
| ZIP 条目/解压大小/压缩比 | 2,000 / 100 MiB / 100 | `ARCHIVE_LIMIT` |
| 片段数/文本字符 | 10,000 / 2,000,000 | `TEXT_LIMIT` / `max_fragments` |
| 解析超时/输出 | 60 秒 / 8 MiB | `PARSE_TIMEOUT` / `OUTPUT_LIMIT` |
| 最小有效文本 | 20 字符 | `LOW_QUALITY` |

## 2. 格式支持

| 格式 | 当前支持 | 明确限制 |
|---|---|---|
| PDF（含文本层） | 原生文本、页码/字符框定位、扫描页 OCR | 复杂多栏、跨页表格、页眉页脚重复可能触发人工复核；不承诺自动恢复阅读顺序 |
| DOCX | 段落、表格单元格、页眉页脚、嵌套表格的文本提取 | 内嵌图片需人工转录；外部关系/超链接严格拒绝；合并单元格可能触发 `TABLE_STRUCTURE_GAP` |
| PNG/JPEG | Tesseract 中英文 OCR、图像坐标定位 | 手写、低分辨率、倾斜/复杂版面不承诺识别质量；单文件只作为图像页处理 |
| 加密/畸形/恶意文件 | 失败关闭 | `ENCRYPTED_FILE`/`INVALID_FILE`/`MALICIOUS_CONTENT`，不得人工放行 |

不支持或无法可靠判定的输入不会显示为“审查完成”；质量门禁失败进入 `needs_review`，由审核员按原件转录后再确认上下文。

## 3. 质量信号（U06 新增）

`quality_issues()` 在平均 OCR 置信度之外检查以下结构信号；任一信号使文档进入 `needs_review`，并写入 `Document.issues` 供页面显示。它们不替代原文/定位校验，也不改变“审查结果不是违法认定”的边界。

| 信号 | 检测内容 | 人工处理 |
|---|---|---|
| `LOW_QUALITY` | 有效文本过短、OCR 空片段、`(cid:)`/替换字符、平均 OCR 置信度低 | 按原件转录全部不可用片段 |
| `LOW_CONFIDENCE_NUMERIC` | OCR 片段含数字/日期但该片段置信度低于 `min_numeric_confidence`（默认 0.80），避免平均值掩盖关键数字 | 对照原件核对金额、日期、比例和编号 |
| `INVALID_DATE` | 形如 `YYYY年M月D日`/`YYYY-MM-DD` 的日历值不存在（如 2 月 30 日） | 核对日期原件；不得自行推断 |
| `DUPLICATE_TEXT` | 长度 ≥20 的片段重复字符占比达到 `max_duplicate_text_ratio`（默认 0.50） | 检查是否缺页、重复解析或页眉页脚误识别 |
| `PAGE_COVERAGE_GAP` | 已出现页码的去重数量/最大页码低于 `min_page_coverage_ratio`（默认 0.90） | 检查缺页/空白页，按原件补齐 |
| `READING_ORDER_GAP` | 片段页码相对前一片段倒退 | 检查多栏/跨页阅读顺序，必要时人工转录 |
| `TABLE_STRUCTURE_GAP` | 同一表格行宽与多数行相差超过 `max_table_row_deviation`（默认 1 格） | 对照原表补齐单元格；不要把合并单元格当成已完整提取 |

这些阈值是版本化 `IngestionPolicy` 的默认值，可随 D1 支持范围调整；调整阈值必须走契约/配置版本流程，不能为让某个文件通过而临时放宽。

## 4. 人工校正与版本失效

1. 审核员通过 `GET /projects/{projectId}/documents/{documentId}/sections` 读取自动原文和生效文本。
2. 只提交发生修改的片段和必填理由到 `POST .../corrections`；必须带服务端当前 `parse_version`。
3. 服务端重新计算质量：通过则 `needs_confirmation`，不通过仍为 `needs_review`；自动原文和文件哈希不变。
4. 校正递增 `parse_version` 和 `context_version`，写入新的未确认上下文；旧上下文确认失效。旧审查结果保留，不得用新版本重新解释旧结果。
5. 未达到 `ready` 的文档不能发起审查；容量前检在冻结运行前拒绝必然超限的选择。

## 5. 已知 OCR 基线（合成数据，非真实招标件）

TASK-0018 的合成扫描件基线：CER 20.79%、关键标记 5/6、表格单元 7/14、重复短语定位 0/2；页面被旧门禁判为 passed 是已知缺陷。U06 的结构信号用于在类似情况下转人工，不声称已经修复 OCR 引擎或达到真实件质量。真实件效果、专业标签和最终支持范围仍受 D1/D2 与 U03 冻结评测资产限制。

## 6. 审查容量前检

`review_management.document_requests` 在创建运行前检查所选文档的片段数（上限 `MAX_DISCOVERY_BATCHES × MAX_BATCH_SECTIONS`）和生效文本字节（上限 `MAX_DISCOVERY_BATCHES × MAX_BATCH_SOURCE_BYTES`，包含人工修订）。超出即拒绝，不进入排队或付费调用；图执行层仍保留自己的批次上限，二者不互相替代。

## 7. 未完成与授权边界

- D1 的首版格式/规模/OCR 页数范围已批准并有 `tests/test_task0029_support_scope.py` 的边界测试；D1 的服务档位/吞吐承诺仍以实测报告为准，不虚构性能。
- D2 的专业标签与法规内容核验仍未签署；`risk_precision`/`risk_recall` 保持未测量，未核验法规只能作为参考。见 `evals/capability_baseline/labels/pending-adjudication.yaml` 与 `docs/development/u03-label-adjudication-drafts.md`。
- D3 的真实模型调用与内容外发、D4 的生产部署按用户 2026-10-18 指令在受控范围内执行；单次授权不取消机构策略、逐文件外发授权和预算控制。
- 真实 OCR 替换/重排模型只有在 Tesseract 无法满足已批准范围时，才用对比证据提出；当前不更换引擎。
