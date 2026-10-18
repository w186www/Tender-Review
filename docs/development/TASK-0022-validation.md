# TASK-0022 本地真实文件诊断记录

- 状态：`in_progress`；隔离运行器的最小列权限修复已验证。先前 DOCX 因空 OCR 未通过质量门禁；本轮当前 PDF 被正式解析器以 `ENCRYPTED_FILE` 拒绝，未产出合规风险结论。
- 日期：2026-10-15。
- 分支：`work/TASK-0022`，基于已完成的 `work/TASK-0021` / `2624e14b39c25baca939ebede552527481c8ea53`。
- TASK-0019：独立原工作树保持未修改；暂停前分支、HEAD 和 12 项未提交路径指纹见 [暂停清单](../../tasks/handoffs/TASK-0019-paused-20261015.md)。
- 收尾复核：TASK-0019 仍为 `work/TASK-0019` / `00829851018612a275faca9ad6609e10fa38305d`；清单 12/12 个文件 SHA-256 匹配。原工作树仍为 7 个已跟踪修改、5 个未跟踪文件（两个评测结果由 Git 折叠显示为一个目录状态行）。
- 详细解析片段、原文件指纹和运行日志仅保存在本机受限目录 `.verification/private/TASK-0022/`，不提交或外发。

## 先前 DOCX 诊断（已停止，不作为当前样本）

用户提供的 DOCX 通过本地 Demo 正式上传 API（HTTP 202）、文件校验、真实 ClamAV INSTREAM 和固定摘要隔离解析器。DOCX SHA-256、完整分片与逐项定位只记在本机私有诊断文件；ClamAV 当次扫描通过，病毒库日期为 2026-10-11。解析器镜像为 `2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597`。本轮重新运行的隔离 run 为 `235f699b745947d7b0edc02c47e8c2e4`。

| 解析测量 | 实际结果 |
|---|---:|
| 文件状态 | `needs_review`，问题 `LOW_QUALITY`；parse version 1 |
| 最小权限修复后校正 | parse/context version 2；正式 corrections API HTTP 200；保存 9 项有确认依据的校正，2 个重复 Logo 引用仍空；质量门禁仍失败 |
| 输出片段 | 1,003：535 个段落、457 个表格单元格（9 张表） |
| 有效文本 | 20,519 字符；134 个非空表格单元格 |
| 定位 | 1,003/1,003 有 OOXML 定位；DOCX 不提供可信分页页码 |
| 嵌入图像 OCR | 11 个片段均为空、置信度均为 0.0；满足“任意空 OCR 片段即需复核”门禁条件 |
| 字符异常 | 未发现替换字符或 `(cid:`；不代表数字、表格语义已校验 |
| 自动上下文 | 未确认；启发式多次给出 `project_type=works`（置信度 0.6），与项目名称所示测评服务不一致，不能采纳 |

质量判定来自 `src/bidding_compliance/ingestion/quality.py`：任何空 OCR 片段会失败关闭。对原 DOCX 的本地只读检查发现，这 11 个占位中有重复绘图/回退对象和重复 Logo 引用。首次校正尝试经正式 corrections API 返回 HTTP 500，数据库报告 `InsufficientPrivilege`；根因与用户指出的一致：运行器只授予 `document_section` 的 SELECT/INSERT，而 `correct_text()` 会递增 `DocumentSection.revision`。

按 TASK-0022 契约，仅在隔离运行器初始化补充 `GRANT UPDATE (revision) ON document_section TO task0011_runtime`。运行角色仍为 `NOSUPERUSER NOBYPASSRLS`，`document_section` 的 FORCE RLS 与 `tenant_scope` USING/WITH CHECK 策略未改；未执行管理员 SQL 或直接写业务表。Focused `tests/test_ingestion.py` 中同租户 reviewer correction 成功、跨租户 correction 返回 404 的检查通过。重新运行后，同租户 reviewer 经正式 corrections API 得到 HTTP 200；只保存了 9 项确认内容（8 个有可读文字的 OOXML 绘图对象及唯一 Logo 图像的一份人工转录）。没有把同一 Logo 文本复制到另两个重复图像引用中，也没有为凑数提交空/猜测校正。

校正后文档仍为 `needs_review / LOW_QUALITY`，parse version/context version 为 2。剩余两个空 OCR 定位是指向同一 Logo 图像资源的重复引用；现有质量门禁把每个空 OCR 引用都视为失败，因此当前 DOCX 仍未通过质量门禁。根据任务要求，不确认上下文、不运行 Skills/RAG、不启动审查流程。整份 DOCX 可视渲染因本机缺少 LibreOffice 未能运行；没有宣称完整页面、表格或数字的视觉核验结果。

## 下游能力与结论边界

- 五类 Skills：未运行，因为剩余两个空 OCR 引用使质量门禁继续失败。风险候选数和 R-01 至 R-07 命中/误报/漏报均**没有有效分母**，不能报准确率或称为“零风险”。
- 法规 RAG、适用性、法规版本核验：未运行；本轮没有为该文件形成任何法律引用。
- Evidence Checker、人工复核、报告：未运行；没有审查报告。
- LLM：真实供应商调用 0。当前 Demo 使用 `OfflineReviewGateway`，但质量门禁前未启动 ReviewEngine；Mock 不构成本文件的模型结果。
- 可复现的私有诊断摘要：`.verification/private/TASK-0022/parse-diagnostic.json`；运行 `235f699b745947d7b0edc02c47e8c2e4` 的解析片段和服务日志只在同目录与私有运行目录，不提交或外发。正式 corrections API 已持久化 9 项经人工确认的修正；无审查风险证据可供报告。

## 阻断与下一步

隔离运行器列权限缺口已修复；Focused `tests/test_ingestion.py` 共 31 项通过（退出码 0），其中同租户 correction API 成功和异租户 correction 返回 404 的 API 回归通过。PostgreSQL 真实隔离运行验证了同租户 corrections API HTTP 200；本轮未在真实 PostgreSQL run 中构造第二租户账号，因此跨租户边界的动态验证来自应用回归测试，数据库强制 RLS 策略保持未改。仓库 Quick 通过；未运行 Full 570。此前默认 Windows 沙箱临时路径不可写导致的首次 fixture setup 错误不计为代码失败。旧 run `4139392e2dfb` 的具名 PostgreSQL/MinIO/ClamAV 容器此前已按 run ID 停止，端口 50502/50504 无监听；本轮 `235f699b7459` 的三个具名容器也已按 run ID 精确停止，端口 54768 无监听。质量门禁仍因同一 Logo 的两个重复空 OCR 引用失败；继续处理需要系统支持“同一资源已人工核验”的显式状态，或用户提供不含重复空 OCR 引用的修正版文件。本任务本轮不扩展代码去改变质量门禁。

TASK-0021 的真实 Qwen 在线路径是 DEC-002 合成文件 SHA 白名单、2,048 字节和一次性限制，且该次授权已消耗；本地 Demo 明确使用离线网关，不能直接接入真实标书。DEC-005 按用户最新指令仍未批准；本轮外部模型/Embedding 调用为 0。Focused 文件测试通过；不运行 Full 570。TASK-0022 契约、权限修复和本次诊断记录更新后运行仓库 Quick。

## 当前 PDF 试运行（2026-10-15）

- 输入为用户新指定的本地 PDF；原文件未修改。原文件 SHA-256 与完整路径保存在 `.verification/private/TASK-0022/bh-finance-2026-06/ingestion-report.json`，不写入仓库摘要。
- 正式上传 API 返回 HTTP 202，`application/pdf` 与文件签名校验通过。独立 PostgreSQL/MinIO、ClamAV 与固定 parser 的本地 run 为 `7ad95a037bce4c98b2cadfbaec564468`；worker 执行 ClamAV INSTREAM 后进入 parser，随后以 `ENCRYPTED_FILE` 拒绝。文档状态 `rejected`，`parse_version=0`、`context_version=0`，没有解析片段。
- 仅在安全拒绝之后读取 PDF 元数据：47 页，RC4 加密；权限标记为允许打印、禁止复制/修改/添加注释。没有尝试解密、转换、绕过或打开正文。由于没有安全提取文本，个人信息/账号口令扫描无法进行，不能断言文件不含敏感内容。
- Skills、法规 RAG、上下文确认、Evidence Checker、LangGraph ReviewEngine、人工复核、报告导出和 Edge 浏览器端到端均未运行；没有真实风险候选、法规引用或审查报告可提供。外部模型/Embedding 调用为 0；文件内容未发送外部。
- 只停止本 run 的 `task0011-pg-7ad95a037bce`、`task0011-minio-7ad95a037bce`、`task0011-clam-7ad95a037bce`。数据库、对象存储、ClamAV、API 和 UI 端口均无监听；临时 reviewer 凭据已删除。详细本地状态和解析器拒绝记录留在上述私有目录。
- 最小下一步是取得有权提供、无加密且可复制的 PDF 源件，再从正式上传 API 重跑；在此之前不审查、不转换。此样本不使用先前 DOCX 的任何对照问题或结论。

## 零候选离线工作流修复与天津地铁 DOCX 重审（2026-10-15）

- TASK-0022 契约先新增最小允许路径：`scripts/check_review_engine.py` 和 `tests/test_task0022_zero_candidate_review.py`，验收要求是合法空输入得到空 findings，并维持 Schema、调用身份、响应哈希和非空候选证据断言。实现仅调整 OfflineReviewGateway 的候选/检索非空断言条件，并使候选/法规覆盖标志仅在实际收到对应输入时置位；没有改业务源代码、规则、RAG、Prompt、证据逻辑、阈值或法规库。
- Focused 命令：`./scripts/verify.ps1 -Mode Focused -PythonExecutable <TASK-0021 venv> -TestPaths tests/test_task0022_zero_candidate_review.py`；新增 pytest 3 passed。Quick/契约、Ruff、Mypy 98个源文件、前端 OpenAPI/Lint/TypeScript/6项单测/构建通过。首次测试选择误用了仓库不存在的 pytest-asyncio 插件；改为同步包装 `asyncio.run` 后同一 Focused 全部通过。未重跑 Full 570。
- 当前用户指定天津地铁11号线 DOCX 在全新隔离 run `c25b5c3e248941fe9d70e03bfd9d2c3d` 中重新走正式上传 API，HTTP 202；Worker 先执行 ClamAV INSTREAM 再进入固定 parser。原始文件哈希与上传后哈希相同，原件未修改。初次 `needs_review` 来自两个空 OCR 页脚图形；经 OOXML 核对为缓存 PAGE 值36后，通过正式 corrections API校正，禁止手工猜造。之后正式上下文确认状态为 `ready`，parse_version 2 / context_version 3。上传辅助脚本在完整上传解析之后对字符串格式的 issue 列表作对象式展示时抛 AttributeError；并未影响服务端上传、解析、校正或后续审查。
- 解析摘要（细节/原文留本机）：1,537片段（903段落、632表格单元格、11张表），约41,835字符，0替换字符、0 `(cid:)`；无可靠页码。隐私扫描只存计数：手机号样式1、邮箱3、联系人标签1；身份证样式、账户与密码/密钥标签均0。原件 SHA 和完整片段保存在忽略的私有目录，不进入 Git。
- 正式项目与文档上下文确认天津市、企业、服务、非招标，法律框架留空。五类 Skills 的实际结果为0候选、每类各评估1条规则；评分 Skill `ambiguous_score_table`、程序 Skill `ambiguous_tender_times`，合同 Skill `not_applicable`，其他两类 `completed_no_candidates`。不能把0候选解释成没有风险。
- ReviewEngine run `ef621b8a-a7b8-56fd-ba22-05955b5b02bd` / `811a8d6c-3ba9-5f58-9427-ce2661926d69`。RAG 实际执行5个 `bm25-char-cosine-rrf-5` 工作项；5/5 为 `context_incomplete / CONTEXT_INVALID`，法条命中和可引用依据均为0。原因是企业非招标上下文无法推导法律框架；没有更换为政府采购，也未伪造法律证据。
- OfflineReviewGateway 返回 `schema_version=v1alpha1, findings=[]`；model artifact provider/model 明确是离线适配器，Schema 与响应 SHA-256 校验成功。合并 findings 为空；LangGraph 经 `merge_findings` 和 Evidence Checker 空集合路径进入 `waiting_human`。测试审核账号以正式 API 提交 `confirm_no_findings`，理由标明不是合规或无风险结论；恢复后到 `result_published`。这是隔离工作流测试，不是真实 Qwen 语义分析，也不是法律审查员对内容的实质签字。
- 官方 DOCX/PDF 报告均经正式报告 API 生成并 HTTP 200 下载至私有目录；PDF 单页已渲染检查。报告仅显示本任务/快照下0候选并有通用法律与证据限制，不嵌入 `CONTEXT_INVALID` 的详细原因；私有诊断摘要补充明确指出法律框架未确认、法规有效匹配未完成、规则覆盖有限及0候选不等于无风险。未在 Microsoft Edge 中重跑真实文件上传；本轮主要通过正式 API 完成流程。
- 模型能力边界只读核对：当前真实 Qwen Online Gateway 的 TASK-0021 SHA 白名单 Minimizer 要求1至20个 Skills 候选，空候选会拒绝请求；Schema 的 candidate_id 仅校验语法，merge 节点只融合 discovery 中的 candidate_id，不允许模型新建候选。因此当前 Qwen 不具备绕开 Skills 独立发现风险的能力。没有真实外部调用，DEC-002已消耗、DEC-005仍未批准。
- 容器/API/UI 只属于该 `c25b5c3e2489` run。PTY Ctrl+C 未能让 `--serve` runner 正常进入 finally；随后只终止该 runner 的精确进程树、停止其三个具名容器（容器由 `--rm` 自动移除）、核实 loopback 端口关闭并删除临时 reviewer 凭据。由于 runner 被提前终止，其最终 `run.json` 未写出；实际运行证据来自正式 API 结果、只读数据库 artifact/hash 检查及私有 helper 记录。未触碰其它服务。TASK-0019工作树未访问/修改。TASK-0022 保持 `in_progress`；没有通过代码/文档宣称法律合规，也未提交/推送本轮产物。
