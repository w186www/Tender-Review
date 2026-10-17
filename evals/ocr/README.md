# TASK-0018 Tesseract 合成扫描件评测

本目录只保存合成扫描件评测方法和经真实隔离解析容器执行后的聚合报告。PDF 每次从脚本按本机已授权字体生成，原始字体和扫描件不提交。脚本不调用上传 API、ClamAV 或任何供应商；它只把本次自行生成的无害合成 PDF 交给仓库现有 `DockerParser`，使用固定镜像摘要、无网络、只读、非 root 和既有资源限制。该解析器专项不会被当作真实用户文件的正式上传授权流程。

## 覆盖内容

- 三页图像扫描 PDF：中文双栏复杂版式、人民币金额、关键数字、条款号和日期。
- 中文多列表格：逐单元格统计可识别内容。
- 重复文本：分别记录页码和在 PDF 点坐标中的纵向位置。
- 空白低质量扫描：验证解析结果进入 `requires_review`。
- 损坏 PDF：验证解析失败关闭。
- 报告包含 CER、关键 token、表格单元格完整度、页码/边界坐标一致性、重复文本位置、容器/进程峰值内存与墙钟/容器耗时，以及超时/失败/低质量降级计数。

## 生成基线

仓库依赖已含 ReportLab 与 Pillow，不需安装 PaddleOCR。选择一个本机已许可的中文字体；脚本记录文件名与 SHA-256，但不会复制或提交字体。

```powershell
$env:PARSER_VERIFY_IMAGE = (docker image inspect bidding-parser:task0018-ocrfix2 --format '{{.Id}}').Trim()
if ($env:PARSER_VERIFY_IMAGE -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Parser image must be pinned by immutable SHA-256.' }
./.venv/Scripts/python.exe scripts/check_parser_sandbox.py
./.venv/Scripts/python.exe scripts/evaluate_tesseract_ocr.py --image $env:PARSER_VERIFY_IMAGE --output .verification/task0018-ocr/tesseract-reproduction.json
```

验证镜像必须已按 `docs/development/secure-ingestion-start.md` 构建，并通过沙箱探针。默认报告路径有防覆盖保护；新的重复执行请传入新的 `--output`，保留每次测量证据。缺少 Docker/镜像/中文字体时脚本失败并报告阻断，不退回 Mock OCR。

2026-10-15 已保存两次真实隔离容器报告：`results/tesseract-baseline-final-reviewed-20261015.json` 与 `results/tesseract-repeat-20261015.json`。两次均为合成图像扫描，不含嵌入文字层；关键识别率与定位缺陷一致，内存和耗时按逐次报告保留。质量警报不会改变正式解析门禁。

报告只代表生成样本上的 Tesseract 质量，不代表真实招标文件。PaddleOCR 不安装、不下载、不运行；如需后续对照，应创建独立授权任务，在等同隔离限制下采集独立证据。
