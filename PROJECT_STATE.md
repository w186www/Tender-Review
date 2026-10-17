# PROJECT_STATE

更新时间：2026-10-17

## 当前有效进度：U01、U02、U04、U05 已完成；U03、U07 进行中；U06/U08 有本地准备成果但正式 planned（前置/授权未满足）

- 固定目录：`D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；当前分支 `work/TASK-0027`，GitHub 备份提交 `7959d9cc9b526aec9269d7352784d89f1681807d`（U05 完成 + U06 质量切片），其后只有记录提交；`origin/work/TASK-0027` 与本地分支一致。未合并 main、未部署。
- 后续准备提交：`2b2b737a157b11438d6ecec66466b81cdc55a366`（U06 结构质量/容量前检）、`93861034dfd4d014ce546f981a142f78066144b3`（U08 饱和/覆盖摘要）；均已推送到 `origin/work/TASK-0027`，未合并 main、未部署。
- 开始时未提交内容：用户的 `docs/development/luna-execution-entry.md`、`docs/development/product-delivery-plan.md`、`question.txt` 均为未跟踪文件，SHA-256 分别为 `BF4AADCDF9A3D91DB4D0A23C4787C0F7FAF899FD41FB39C7F35C489F90F94195`、`15DAFDD856AE13B6376238487A726A296DF596822205FDD386D47977A8FC664A`、`DAB6DC7FBA01721398735A45A985712414B0C6504919B2857ED32A287D1561ED`。备份提交 `7959d9c` 已包含前两份规划文件；`question.txt` 按用户私人记录处理，仍为未跟踪且未推送。文件内容未被改写。
- 产品单元：U01/U02/U04/U05 已完成；U06 本地准备成果已完成，但正式单元仍为 `planned`（U03 前置未完成，不跳过验收）；TASK-0029 保持 `in_progress`。U05 完成产品模式（`DEPLOY_REVIEW_MODE=product-postgres`）的 PostgreSQL 租户策略、版本绑定逐文件授权/撤销、授权/审计同事务、原子预算预留/结算、unknown 保留、历史 JSONL/SQLite 只读幂等导入和隐私反例；真实 PostgreSQL 专项退出码 0，U04 Docker/PostgreSQL 部署 E2E 5/5 兼容通过。U06 已实现结构质量信号（低置信数字/非法日期/重复文本/页码覆盖/阅读顺序/表格行宽）、容量前检、已 ready 文档校正后的上下文失效和合成 OCR 已知失败回归；Full 通过（880 passed/6 warnings）。U06 仍未完成：TASK0029-002 需要 U03 冻结评测器/专家标签与 D2 专业标签，D1 也未批准最终支持范围/容量承诺；不把开发样例冒充冻结验收。U03 仍在进行：开发候选与标签边界已登记；冻结评测器/测试/结果来源未恢复，唯一已知备份 bundle 未找到 TASK-0019 来源且未导入/覆盖。U07 的本地生命周期与“无人工 binding 不支持违法结论”工程边界通过；法规核验及规则—法规人工绑定仍受 D2 限制。U08 已有离线覆盖准备成果（每批 3 项饱和标记、覆盖摘要进入运行制品、3 项纯测试），但正式 `planned`，真实质量评测需 D3；有界细分/重扫尚未实现。U09 仍需 U03/U07 等前置。逐单元 G3 证据见 `docs/development/product-delivery-validation.md`。
- 新任务映射：TASK-0028（U01/U02/U04/U05，`completed`）；TASK-0029（U02/U06—U12，`in_progress`）；U03→TASK-0019/TASK-0013，U13/U14→TASK-0012，U15→TASK-0013，U16→TASK-0014。用户原有任务的局部验收范围未被重写。
- 原任务状态保留：TASK-0019 `blocked`（保全工作树/成果不写入）；TASK-0022 `in_progress`（仅原授权的本地离线范围）；TASK-0027 `in_progress`（第七轮交付已提交、CI和公网证据存在，产品级遗留按 U02/U10/U11 收尾）；TASK-0012/0013/0014 `planned`。
- D1—D4 当前均没有新的明确批准：本地/合成数据实现继续；仅阻止路线图所列的支持范围/专业标签签署、真实外发/模型调用、线上/发布操作。DEC-002/007 的历史批准不扩大新的授权。本轮未调用模型、外发数据、访问线上或推送/合并。
- 环境复用：当前目录 `.venv` 的 Python 解释器可用；源码使用 `PYTHONPATH=src` 时指向本目录 `src/bidding_compliance`。`src/frontend/node_modules` 已存在，Node v24.14.0。未安装或重建依赖。
- 整合核对：`origin/main`=`7923086`，`origin/integration/TASK-0027-main-20261017`=`b344709`；整合候选的两个父提交分别为 main 与当前交付 HEAD `9e1a584`，相对交付 HEAD 仅多 `PROJECT_STATE.md`、`README.md`、`docs/index.md` 三项差异，未找到该候选自身 CI 证据。本地没有该候选分支，不自动合并或推送。
- 验证结果：U05 最终实现候选官方 `./scripts/verify.ps1 -Mode Full` 七阶段全部通过：后端 `868 passed, 6 warnings in 689.82s`；U06 后续代码候选官方 Full 七阶段通过：后端 `880 passed, 6 warnings in 772.91s`（`.verification/u06-full.log`）；U08 离线覆盖准备候选官方 Full 七阶段通过：后端 `883 passed, 6 warnings in 891.80s`（`.verification/u08-prep-full.log`）。三次 Full 分别绑定各自候选，不互相冒充。HTTP health=200/404 与 request ID 关联、鉴权和项目生命周期通过；Ruff、Mypy 109 源文件、前端 14/14 与构建通过。6 条 warning 为 2 条既有 pypdf 弃用提示和 4 条既有 `test_verification_modes` PowerShell 输出解码警告（测试通过）。真实 PostgreSQL 专项 `scripts/check_postgres.py` 在隔离 `postgres:16` 容器退出码 0，覆盖 U05 授权/RLS/审计/并发预算/历史导入及迁移升降级；U04 Docker/PostgreSQL 部署 E2E `.verification/task0011-e2e-1394bf3bcfca4065ac1f214989e3e20a/` 通过 5/5 浏览器测试并记录取消、并发 claim、lease/fencing、Checkpoint 恢复及 unknown 不重放。详细命令及证据见 `docs/development/product-delivery-validation.md`。
- 已知问题与待决策：TASK-0019 仍为 `blocked`；只读检查 `D:\自由项目\招标审核\_backups\repo-20261017T081226Z.bundle` 的 refs 未含 TASK-0019 分支或冻结评测资产，bundle 未解包。D1/D2 未批准的支持范围/容量承诺及专业标签签署继续局部阻塞；U06 因此正式仍为 `planned`，TASK0029-002 evidence 为空。U05 的产品模式尚未在生产启用，历史账本真实迁移/切换、D3 真实供应商调用/内容外发和 D4 线上活动未获授权且未执行；没有外发项目数据、真实模型调用或线上操作。Full 的 4 条 PowerShell 输出解码警告为既有测试基础设施问题，未通过放宽检查消除。
- 下一步：本地可执行准备已到边界。U06/U08 有准备成果但正式 `planned`；U09/U10/U11/U12 仍缺 U03/U06/U07 等前置，U13/U14 最终演练需稳定候选与 D4，U15/U16 需用户独立验收。必须由用户决定/提供的外部条件：D1 支持范围/服务档位，D2 法规核验与专业标签责任人，D3 真实模型/数据外发授权，D4 生产迁移/发布窗口，以及 U03 冻结评测器/专家标签来源是否可恢复。未获这些条件前不重搜 U03、不重建评测器、不以开发候选替代金标、不执行真实外发/生产操作；可以继续做不依赖它们的代码审查、bug 修复和文档准备，但不能把 U06/U08 或产品整体标为完成。

## TASK-0027 第七轮交付快照（第七轮实现已完成；TASK-0027 总体仍 in_progress）

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，基线 HEAD `2fc9800`
  （第六轮已由用户提交：`feat(TASK-0027): lift the DEC-007 ceilings and let a reviewer approve one file`）；
  **第七轮改动已由本轮交付提交**并推送：修复提交 `3b0df81`，合并远端 `8a7021b`（只改 `README.md`）
  后的分支 HEAD `61a0185`（`61a0185e7f6b0e4eaeeeae4004b97adeb3aaf2c8`）；该 SHA 的 CI
  （run 38931207073）全部适用作业 success（impact/baseline/postgres/ingestion/verify-required；
  quick 在 Full 模式下按条件合法 skipped），公网已按该提交更新并验收（见"公网真实 AI 上线记录"）。
- 用户 2026-10-16 指令（本轮目标：**任意用户自有文件上传后能在网页里走到真实 AI 审查**）：
  ① 修复 `needs_review` 文档在网页里无法推进（前端没有任何校正/上下文确认入口 → 浏览器死路）；
  ② 验证并（如需要）修正第六轮引入的逐文件外发授权流程。底线：**不放宽/不绕过 `ingestion/quality.py`、
  `services/ingestion_worker.py` 的质量门禁与病毒扫描、不绕过租户隔离与鉴权、不改 `knowledge/legal/**`、
  `config/legal/**`、`contracts/**`、`tests/completed/**`、`legal/retrieval.py`、`services/evidence_checker.py`、
  不改法规 `verification` 状态、不删除/重置账本与索引、不触碰线上服务器、不新增无关设施、不 git 提交**。
- **修复 1（needs_review 死路）**：新增前端「查看/校正文本」（仅 reviewer 且状态 `needs_review` 时出现）
  → `GET .../sections` 列出解析片段（自动原文只读展示、生效文本可编辑、空片段提示按原件转录）
  → 只提交发生修改的片段 + 必填理由 `POST .../corrections`（`expected_parse_version` 取自 `sections.parse_version`）
  → 服务端重新判定质量：通过（`needs_confirmation`）则自动接着打开既有上下文确认弹窗
  （`expected_version` 取自 `GET .../context` 的 `version`）→ `POST .../context` → `ready` → 可勾选发起审查；
  未通过则弹窗不关闭、如实提示"质量门禁仍未通过"并重新读取服务端解析版本继续转录；409 冲突同样重读。
  门禁**一字未改**：`needs_review` 仍不能直接确认上下文（服务端 409），仍只有 `ready` 可勾选，
  `correctDocumentText` 的请求体完全按 `src/frontend/src/api/schema.d.ts` 契约实现（未猜字段）。
  页面对存在 `needs_review` 文档时新增数量提示与修复指引。后端**无需改动**即支持该路径
  （`services/documents.py` 的 `correct_text` 原本就允许 `needs_review` 入口，只是前端从未调用）。
- **修复 2（逐文件外发授权）**：端到端复验并修掉一个真实缺陷——外发拒发消息为
  "…does not authorize…"，`api/reviews.py` 的 `_translate` 因消息不含 "authorized" 把"文件未授权"
  误映射为 **409**，页面只能显示"数据已被其他操作更新"，与"未授权"完全不符；改为
  `"this document is not authorized for external processing"` 后正确映射 **403**
  （`src/bidding_compliance/services/real_ai_runtime.py` 一行 + 注释说明为何措辞是接口的一部分），
  前端在"发起审查"的 403 分支给出明确指引（"真实模型部署还要求所选文件已逐个登记外发授权…"）。
  同时修掉两个弹窗 `key` 重复（都是 `"none"`）导致的 React 同键告警（改为 `correction-…`/`authorization-…`）。
  授权入口本身**可用**：浏览器实测可见、可提交、可写入注册表并回显服务端记录（actor/时间/理由/哈希）。
- **本轮真实数字（本机合成数据、零付费调用、未触碰线上服务器、未放宽任何门禁）**：
  ruff `All checks passed!`；mypy `Success: no issues found in 104 source files`；`scripts/verify_repo.py` PASS；
  官方 Focused（两个改动测试文件）`17 passed`；前端 `biome check`（23 文件，0 错误）/`tsc --noEmit`（0 错误）/
  `vitest run`（**14 passed**，4 文件）/`vite build` 成功；官方 **Full 退出码 0**（`[1/7]`–`[7/7]` 全过，
  `[5/7]` **818 passed, 6 warnings in 525.69s**，JUnit tests 818 / failures 0 / errors 0 / skipped 0）。
- **交付复核（2026-10-17 本机在同一工作树重跑，命令与数字如下）**：ruff `All checks passed!`；
  mypy `Success: no issues found in 104 source files`；`scripts/verify_repo.py` PASS；官方 Focused
  （三个改动测试文件 `tests/test_task0027_needs_review_repair.py`、
  `tests/test_task0027_external_authorization_api.py`、`tests/test_task0027_per_file_authorization.py`）
  `26 passed in 77.09s`；前端 `biome check`（23 文件，0 错误）/`tsc --noEmit`（0 错误）/
  `vitest run`（**14 passed**，4 文件）/`vite build` 成功；官方 **Full 退出码 0**（`[1/7]`–`[7/7]` 全过，
  `[5/7]` **818 passed, 6 warnings in 525.69s**，JUnit tests 818 / failures 0 / errors 0 / skipped 0），
  `[6/7]`/`[7/7]` 真实启动与鉴权生命周期 PASS；未发现缺陷，无需返工。
  两组新增/扩展的真实测试：`tests/test_task0027_needs_review_repair.py`（**6 项**：修复路径到 `ready`
  并创建任务、校正后仍不达标不得放行、未修复不可发起审查、租户/角色/定位符/版本校验、自动原文与文件
  哈希不被改写且上下文版本无缺口）与 `tests/test_task0027_external_authorization_api.py`（**6 项**，含新增
  上传→未授权拒绝→端点登记→同一运行中装配放行该哈希的最小化器/引擎证明，以及"未登记文件的审查 =
  403 且在冻结前拒绝、无任务行"的映射回归）。
- **端到端（本机回环 compose 栈、本 Worktree 镜像、仅 `127.0.0.1:8090`）**：栈 `t27r7`
  （`tender-review-api:t27r7` / `tender-review-web:t27r7` / `tender-review-parser:t27r7`，独立
  `VOLUME_PREFIX=tender-review-t27r7`、独立项目名，未触碰其它栈与线上）。Phase A（`offline` +
  `offline-deterministic` 前端，Microsoft Edge/Playwright）：上传 `scripts/generate_demo_fixture.py`
  生成的合成 DOCX（`sha256=7eb5a497…` → `needs_confirmation`）与一份质量不足的合成 DOCX
  （`sha256=60c5f8aa…` → `needs_review`）→ 用新入口转录并提交（P1→P2、`LOW_QUALITY` 清空）→ 上下文确认
  → 两份均 `ready` → 发起审查（202，离线确定性网关，无供应商路径）→ 任务 `28c254d6…` `等待人工复核`
  （1 条风险）→ 记录人工决定 → 发布结果 `41a1b475…`，任务列表 `结果已发布`。Phase B（`authorized-real`
  + `dec007-real-qwen` 前端，与真实部署同构；本机一次性 DEC-007 身份/卷，占位供应商凭据**从未被调用**）：
  页面显示「已配置真实模型路由」横幅与逐文件授权文案 → 新上传文件走同一修复路径到 `ready` →
  「登记外发授权」→ 201 并回显服务端记录（reviewer / `2026-10-16T07:45:18+00:00` / `60c5f8aa…`）→
  注册表追加一行 → 对另一份**未登记**的 `ready` 文件发起审查被**冻结前拒绝**（403 + 页面明确指引），
  无任务行；账本 `llm_calls=0 / embedding_batches=0 / charged_or_reserved_cny=0 / unsettled_requests=0`，
  `dec007-model-audit.jsonl` 与 `embedding-audit.jsonl` 均 **0 字节**，日志零供应商主机名。
  证据：`.verification/t27r7/`（`phase-a-result.json`、`phase-b-result.json`、`registry.jsonl`、
  `allowlist.txt`、`phase-a-documents.txt`、`shots/` 15 张截图）——`.verification/` 为 gitignore 目录。
- **本轮不得宣称超出**：本机 Phase A/B 未做真实供应商调用（"登记后放行"由 pytest 的引擎/最小化器断言证明，
  浏览器侧只到"登记成功 + 未登记被拒"）；`contracts/**` 未改，端点仍未进入 OpenAPI；
  `VITE_REVIEW_MODE` 是构建期开关，切模式必须重建 nginx 镜像；校正只替换"生效文本"，
  自动解析原文与文件哈希保持不变，质量是否达标始终由服务端判定。
  公网更新与本轮的公网真实调用见下方"公网真实 AI 上线记录"。

## 已完成：TASK-0027（DEC-007 完整能力）第六轮：解除自设额度上限 + 工作台逐文件授权（HEAD `2fc9800`）

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，基线 HEAD `8204239`
  （`feat(TASK-0027): unify the deployed data path, recover from a review timeout, prepare the switch`，
  已推送且工作树干净）；**本轮（任务 A/B）改动未提交**，由用户复核后提交——**部署前必须已有提交**。
- 用户 2026-10-16 指令：公网真实 AI 上线（DEC-007 完整能力），三项任务 A（解除自设上限）、
  B（允许对当前上传文件做逐文件授权）、C（公网部署，含回滚准备）、D（公网真实端到端验收）。
  底线：**不删除/重建/重置任何账本与 3112 条向量索引、不改授权 ID 与历史行、不动法规核验状态、
  不伪造 valid、不外发未授权文件、密钥不入仓库/镜像/前端/日志**；出现不可恢复数据丢失风险即停止。
- **任务 A（本轮完成，本机验证）**：`AUTHORIZATION_LIMITS[DEC-007]` 仅数值 300/800/¥30 →
  **2000/2000/¥200**（`src/bidding_compliance/model_gateway/authorized_runtime.py`，含理由注释）；
  授权 ID `DEC-007-2026-10-16`、账本 `dec007-budget.sqlite3`、全部历史行原样保留（只在同一账本上
  继续累计）；防失控机制未放宽：单次全额预留、`max_attempts=1`、并发 1、失败/未知用量保留预留且
  不自动补发、构造期拒绝超限参数、上限不写入账本。测试期望与文档同步（budget_boundaries、
  per_file_authorization、round_limits、validation_entry、README-demo 8.1/8.4/8.5、demo.env.example、
  DEC-007 决定记录加"修订二"）。
- **任务 B（本轮完成最小实现，本机验证）**：保留"未授权文件不外发"，把授权动作做进工作台：
  受鉴权端点 `POST /projects/{projectId}/documents/{documentId}/external-authorization`，
  服务端 `api/documents.py` 新端点 + `api/schemas.py` 两个模型；**按用户底线本轮不改 `contracts/**`**
  （端点未登记进 `contracts/openapi.yaml`，`src/api/schema.d.ts` 保持原样、`api:check` 通过；
  前端改用 `src/api/client.ts` 新增的显式鉴权 JSON 调用 `postJson`——与仓库"契约先行"规则的
  已知偏离，是否补契约由用户决定）；`confirmed` 必须为 true（服务端校验）、
  SHA-256 **由服务端从数据库解析该文档**（请求体不接受哈希，`extra="forbid"`）、**没有"全部放行"开关**、
  每次登记写追加式注册表一行 + 租户审计事件 `document.external_authorization_approved`、
  **不触碰任何账本**；只有 `authorized-real` 装配与 8.4 验证实例设置
  `app.state.external_authorization_registry`（`offline` 装配一律 503）；权限仅 reviewer。
  前端 `src/api/operations.ts` 暴露 `authorizeDocumentExternalProcessing`（走 `postJson`），
  `pages/project.tsx` 在文档行新增「登记外发授权」（仅 `VITE_REVIEW_MODE=dec007-real-qwen`
  构建显示），弹窗含固定声明文案 + 必填理由 + 必选确认。`deploy/manage_authorization.py` CLI 未改动，
  两条途径写同一文件同一种行。**nginx 镜像必须重建**该前端才可见（构建期常量）。
  任务 YAML 同步（`allowed_paths` 收录本轮文件、`must_not_change` 收紧为具体未改文件并保留
  `contracts/**`、新增验收项 `TASK0027-012`），`scripts/verify_repo.py` PASS。
- 本轮真实数字（本机合成数据、零付费调用、未触碰线上服务器）：ruff `All checks passed!`；
  mypy `Success: no issues found in 104 source files`；`scripts/verify_repo.py` PASS；
  pytest（6 个相关文件，含新增 `tests/test_task0027_external_authorization_api.py` 4 项）
  `72 passed in 205.95s`；前端 `api:check`/`lint`/`typecheck`/`test`(8 passed)/`build` 全通过；
  官方 **Full 退出码 0**（`[1/7]`–`[7/7]` 全过，`[5/7]` **810 passed, 6 warnings in 528.45s**，
  JUnit tests 810 / failures 0 / errors 0 / skipped 0）。
  命令与转录见 [TASK-0027 验证记录 第六轮](docs/development/TASK-0027-validation.md)。
- **任务 C/D（公网部署与真实端到端验收）**：见本文件"公网真实 AI 上线记录"一节（随后续步骤更新）。
- **本轮不得宣称超出**：上限只是数值（未做真实 2000 次调用）；端点/按钮的可用性与构建模式绑定；
  端点尚未进入 OpenAPI 契约（见上）；
  注册表行只证明"谁在何时为哪个文件哈希登记"，操作者仍是信任链的一环；未在服务器执行任何上述命令。

## 公网真实 AI 上线记录（任务 C/D）

- 状态：**第七轮修复已上线并完成公网真实验收（2026-10-17）**。切换在第六轮已完成
  （`DEPLOY_REVIEW_MODE=authorized-real`、`VITE_REVIEW_MODE=dec007-real-qwen` 都在
  `deploy/.env` 里，本轮**原样未改**）；本轮只把 api 与 nginx 镜像换成本轮提交的构建产物。
- **服务器**：`/opt/tender-review`，本轮先 `git fetch` 再 `git reset --hard origin/work/TASK-0027`
  → HEAD `61a0185`，工作树干净（这条 `reset --hard` 只作用于服务器检出，用户已授权）。
- **镜像（新）**：`tender-review-api:task0027-61a0185`
  （镜像 ID `sha256:42c4ff4f69fe32e21aac1fd3e695a813c1ec6cd7301bbb801b9098f7dc57a34e`）与
  `tender-review-web:task0027-61a0185`
  （`sha256:69d6f1a31f8cd77f5d2698c3f558a07ec5b6a33fa829aa57093ad5940fcdb258`，
  构建期 `VITE_REVIEW_MODE=dec007-real-qwen`，`docker compose config` 已确认该 ARG 生效）。
  **旧镜像保留可回滚**：`tender-review-api:task0027-2fc9800`
  （`sha256:f0b955a8…`）与 `tender-review-web:task0027-2fc9800`（`sha256:14e1e32d…`）仍在宿主机。
- **重建方式**：`IMAGE_TAG=task0027-61a0185` 作为**命令行覆盖**传给 compose（api 用
  `-f docker-compose.demo.yml`，nginx 额外带 `-f deploy/docker-compose.tls.yml`，与两容器当初的
  config_files 标签一致），`up -d --force-recreate` 只重建 api 与 nginx；`deploy/.env`、
  `/opt/tender-review-private/`、`modelstate` 卷、账本、注册表、索引、HTTPS 证书与 certbot 定时器
  一律未动。worker 仍是 `tender-review-api:demo`（本轮范围外，其镜像已含 TASK-0018 起的解析/质量代码）。
  **已知操作性残留（如实记录）**：`deploy/.env` 的 `IMAGE_TAG` 仍是 `task0027-2fc9800`，
  运行中容器由命令行覆盖创建；若之后有人**不加覆盖**执行 `docker compose up -d`，compose 会把
  api/nginx 重新创建回旧镜像标签。按用户"`deploy/.env` 一律不动"的指令，本轮未改该文件。
- **公网真实 Qwen 端到端（`deploy/verify_deployment.py`，`--base-url https://47.83.132.211`，
  容器 `--user 0:0 --network host --env-file deploy/.env` + `/fixtures:ro`，冻结样本
  `080511f9…`）**：`status: passed`，40.1 秒。项目 `8dabba41-…`，文档 `20371e4e-…`，
  `needs_confirmation`→上下文确认→`ready`→审查 `2a9aac5d-…`/run `7e6d6c75-…` → `waiting_human`，
  2 条风险（`evidence_status=insufficient_evidence`）→ 记录 2 条决定 → 发布 `ce2180cb-…`
  （`content_hash=caacb164…`）；`model_runtime`：`execution_mode=real-qwen`、`provider=bailian`、
  `model=qwen3.8-flash`、`model_calls=2`、`input_tokens=1009`、`output_tokens=699`、
  `estimated_cost_cny=0.0026945`、`embedding_model=text-embedding-v4`、
  `vector_index_build_id=c7344cac…`（与钉住的预构建索引一致）；Word 40563 字节
  `sha256=55ca8c24…`、PDF 7622 字节 `sha256=7090ab0d…`，**两者 `matches_content_hash` 均为 true**。
- **`needs_review` 闭环公网实测（本轮核心目标，API 实测；脚本 `.verification/t27public/closure.py`
  经 `workbench upload` 送服务器、一次性容器内执行）**：`status: passed`。上传故意低质量的合成 DOCX
  （1 个片段 `"Short"`，`sha256=0258e691…`）→ `needs_review` + `LOW_QUALITY` →
  `GET .../sections` 读到该片段 → `POST .../corrections`（人工转录，`expected_parse_version=1`）
  → `needs_confirmation`、`issues` 清空、`parse_version=2` → `POST .../context`（`expected_version=2`）
  → `ready`（`context_version=3`）→ **对未登记文件发起审查被 403 拒绝**（冻结前，无任务行）→
  `POST .../external-authorization`（reviewer 确认）→ 201 并写入注册表 →
  再发起审查 **202** → `waiting_human`，`model_runtime`：`real-qwen`/`bailian`/`qwen3.8-flash`、
  `model_calls=2`、`input_tokens=1165`、`output_tokens=821`、`estimated_cost_cny=0.0031487`、
  `model_candidate_count=2`。即"质量不足的文档能在网页同源 API 上完成校正并继续走到真实审查"。
- **账本（`dec007-budget.sqlite3`，只增不减，未重置）**：本轮开始 20 次 LLM / 312 批 Embedding /
  ¥0.1413027 / 未结算 0；结束时 **25 次 LLM / 312 批 Embedding / ¥0.1474435 / 未结算 0**
  （337 条请求全部 settled）。新增 5 次真实 LLM 调用 = 公网验收 2 次（¥0.0026945）+ 首次闭环尝试
  1 次（发现零候选缺陷，仅 discovery，¥0.0002976）+ 成功闭环 2 次（¥0.0031487）。
  注册表 8 → 10 行（两次闭环登记各一行，均 reviewer 确认）。索引、embedding 账本、法规核验状态未动。
- **本轮发现但未修（范围外，如实记录）**：当 discovery 的候选数为 0 时，`semantic_analysis`
  节点在调用模型前就以 `ValueError` 失败（`src/bidding_compliance/graph/review.py` 的
  `batches = _semantic_batches(discovery.candidates)` + `if not batches ... raise ValueError
  ("semantic analysis exceeds the authorized batch capacity")`），运行被标 `failed`
  （`failure_code=review_execution_failed`），API 把该 `ValueError` 映射成 **422**（用户看不到原因）。
  证据：首次闭环尝试用极短转录（65 字）时，真实模型对单片段返回 `{"findings": []}`
  （run `e2fdfe45-…`，仅 1 次 discovery 调用后失败，无任何 semantic 工件）。这是**既有行为**
  （本轮未改 graph），影响"内容过少/无可发现候选的文件"，与 needs_review 修复路径无关
  （同一文档用有内容的转录即可走通，见上条闭环证据）；报告生成层本身支持 0 候选
  （`services/reporting.py` 有 `candidate_count == 0` 文案），因此属于图执行层的缺口，
  建议单独任务处理。

以下保留第五轮（阶段二调整后的交付项）与更早的记录。

## 第五轮（已提交为 HEAD 8204239）：阶段二调整后的交付项完成

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，当前 HEAD `da28f9f`
  （`fix(TASK-0027): close the detection blind spot and stop the README using the old image`）；
  **本轮（阶段二调整后的 5 项交付）改动未提交**，由用户复核后自行提交。
- 本轮边界：本机合成数据与回环容器验收；**零付费调用、未触碰线上服务器 47.83.132.211、
  公网 `DEPLOY_REVIEW_MODE` 仍 `offline`**；**未做任何法规核验、未改任何 `verification` 状态**、
  未删除/重建/重置 3112 条向量索引与 DEC-007 账本、未扩大外发授权、未 git 提交。
  全部命令与转录见 [TASK-0027 验证记录 第五轮](docs/development/TASK-0027-validation.md)。
- 交付 1（统一 modelstate 正式部署路径，不动数据）：正式装配/部署的 private root 由不存在的
  `…/private/TASK-0023` 改为**卷根** `…/private`（`scripts/task0023_real_ai_app.py`、
  `scripts/task0027_real_ai_validation_app.py`、`scripts/prebuild_legal_vectors.py`、
  `scripts/task0027_ledger_baseline.py`、`deploy/manage_authorization.py` 默认注册表），
  并写入 `deploy/demo.env.example`、`docker-compose.demo.yml`、`deploy/README-demo.md`。
  新增只读一致性核对 `scripts/task0027_identity_check.py`（授权 ID、账本 scope、注册表路径、
  模型审计、法规 publication/revision、索引 build_id/条目/覆盖率/缓存向量；缺失即报告绝不
  创建，退出码 0/2）与 `scripts/task0027_index_plan.py`（本地只读重算 build id + 快照增删/
  缓存命中）。账本基线期望改为**阶段二：LLM 2 / Embedding 312 / 累计 ¥0.1062161 / 未结算 0**，
  README 输出示例同步。
- 交付 2（120 秒超时找回与幂等，证明不重构）：新增 `tests/test_task0027_timeout_recovery.py`
  （4 项，真实 Uvicorn 回环 + 真实路由/持久化 + 真实账本），覆盖"客户端中断后任务仍可查询
  （running→result_published）""同幂等键重提同一任务、执行器只 1 次、账本字节与摘要不变"
  "同键不同文档集 409""新键才是新任务"，并断言前端 **120_000 ms** 常量；前端仅在 `AbortError`
  分支加最小引导（`REVIEW_TIMEOUT_NOTICE` + 立即刷新持久化任务列表），后台与幂等语义零改动。
  内部验证实例（本机回环 compose `tender-review-t27`，本 Worktree 镜像、`offline`、仅
  `127.0.0.1:8090`）真实输出：0.203 秒中断后 `task_found_after_abort=true`、
  `running→waiting_human`、同键重提 202 同一任务、跨项目同键 409、任务数仍 1。
- 交付 3（测试与 CI，本机真实数字）：ruff `All checks passed!`；mypy
  `Success: no issues found in 104 source files`；`scripts/verify_repo.py` PASS；
  前端 vitest `3 files / 8 passed`（新增 `utils.test.ts` 2 项）；官方 Focused
  `123 passed in 105.57s`（`[1/7]`–`[5/7]` 全过）；官方 Full **退出码 0**：
  `[1/7]` PASS、`[2/7]` ruff 通过、`[3/7]` mypy 通过、`[4/7]` 前端通过、
  `[5/7]` **806 passed, 6 warnings in 486.12s**、`[6/7]`/`[7/7]` 真实启动与鉴权生命周期
  `PASS`（JUnit：tests 806 / failures 0 / errors 0 / skipped 0）。**既有环境前置**：
  `tests/test_verification_modes.py` 会不带 `-PythonExecutable` 调内层 `verify.ps1`，
  必须把 venv 的 `Scripts` 前置到 `PATH`（未前置时该测试失败，属环境前置不属代码缺陷；
  第一轮记录同款要求）。
- 交付 4（部署与回滚方案，文档不执行）：`deploy/README-demo.md` 新增 8.5——api 与 nginx
  **分别构建同一提交**、`VITE_REVIEW_MODE=dec007-real-qwen` 是**构建期**参数（不重建不生效）；
  切换 `DEPLOY_REVIEW_MODE=authorized-real` 的前置逐项（索引 pinned 校验、宿主 offline 证据、
  账本基线、注册表=卷根、身份一致性、受控验证轮、白名单非空且**新上传文件不自动授权**）；
  **回滚**=改回 `offline` + `--force-recreate api`（前端一并重建）、账本不重置、索引与卷保留、
  `revoke` 立即生效、HTTPS/`tender-certbot-*.timer`/审计账本/数据库不动。
- 交付 5（浏览器验收 + Word/PDF 正文断言）：内部实例上 Microsoft Edge（Playwright）全流程
  8 张截图（登录→项目→上传→上下文→审查详情→风险与服务端精确定位→人工复核历史→
  继续审查流程→Word/PDF 下载→项目任务列表 `结果已发布`）；对下载的 Word（1697 字符）与
  PDF（2 页）**抽正文**断言风险标题、原文摘录、`证据状态：insufficient_evidence`、
  `法律适用框架尚未确认`/`未完成有效适用性匹配`/不补造条文、**无任何违法认定**（否定式免责
  声明存在）——**明确声明这是替代品**：阶段一服务器报告
  `/opt/tender-review-private/evidence/task0027-report-*.{docx,pdf}` 未取得。
- **本轮不得宣称超出**：账本记录值（scope/计数/审计/索引条目）只能在宿主核对，本轮未在服务器
  执行；`status_timeline` 是列表轮询采样；pytest 与脚本用缩放后的超时复现 120 秒语义
  （未做真实 120 秒挂起回归）；浏览器验收是内部离线实例，不是公网、不是 `authorized-real`；
  8.5 是方案不是执行记录。
- 本机验收用 compose 栈 `tender-review-t27`（回环、离线、全新卷 `tender-review-t27-*`）
  在验收结束后以 `docker compose down`（保留卷）停止；**未触碰**既有 `tender-review-demo`
  栈与其卷，也未触碰线上任何资源。

以下保留 TASK-0027 第四轮（第二实例检测覆盖启动命令/镜像 + 逐文件授权 CLI 改用验证镜像）与更早的记录。


- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，当前 HEAD `972ef54`
  （`feat(TASK-0027): pin the index identity and prove offline mode from the host`，即第三轮改动已提交）；
  **第四轮（用户 2026-10-16 指定的两处最小修正）改动未提交**，由用户复核后自行提交。
- 本轮两处修正（全部本机合成测试与 fixture 回放；**零付费调用、未触碰线上服务器 47.83.132.211、
  未挂 Docker Socket、未给任何容器 Docker 权限、未扩展其他功能**）：
  1. **第二个真实模型实例的检测覆盖实际启动命令与镜像**（消除已确认盲区）：`deploy/verify_api_offline_mode.py`
     （`.sh` 调用同一逻辑）原来主要靠容器环境里的 `DEPLOY_REVIEW_MODE=authorized-real` 判定，而隔离验证
     容器由 `scripts/task0027_real_ai_validation_app.py` 启动、其 `DEPLOY_REVIEW_MODE` **可能仍是 `offline`**，
     因此旧判定会漏掉它。现在检查对象是宿主上由只读 `docker ps -aq --no-trunc` 枚举、逐个只读
     `docker inspect` 的容器（**按容器 ID 排除预期的线上 api 容器本身**），除原有判定外，满足任一条即
     `untrusted`：入口/命令出现 `task0023_real_ai_app`（authorized-real 装配，覆盖 `.py` 与 `:app` 写法）、
     出现 `task0027_real_ai_validation_app`（隔离验证入口，**即使 mode 仍是 `offline`**）、命令为
     `api_entry.py` 且 mode 为 `authorized-real`、镜像引用带验证标签 `task0027-validation`；
     证据里每条实例都带 `reason`。
  2. **无法读取执行身份时判 `unknown`（用户明确要求）**：任一容器的 `docker inspect` 失败/无 JSON、
     容器 ID/镜像引用/入口命令/`State.Running` 读不到，或命令是 `api_entry.py` 而 `DEPLOY_REVIEW_MODE`
     读不到 → 新增检查 `all_running_containers_identified: false`、退出码 2、提示立即停止，
     **绝不声称"不存在第二个真实模型实例"**；已证明未在运行的容器不在范围内（`Running=false`）。
     证据升版 `schema_version: v1alpha1 → v1alpha2`（`execution_instances.second_real_model_instances`
     每条含 `{container_name, container_id, reason}`，检查键 `no_second_real_model_instance`），
     加载器同步改名，旧版证据按版本明确拒绝。
  3. **README 逐文件授权 CLI 不再依赖公网旧镜像**：`deploy/README-demo.md` 8.2 与 8.4 第二步的
     `manage_authorization.py approve/list/revoke` 原来用 `$D exec api ...`（依赖运行中的 `:demo`，
     即尚未更新的公网 TASK-0026 镜像，**里面没有该脚本**），改为 `IMAGE_TAG=task0027-validation $D build api`
     + `docker compose run --rm --no-deps api python deploy/manage_authorization.py ...` 一次性容器
     （复用 api 服务环境变量、网络与 `-modelstate` 读写挂载），并写明不影响运行中的 api/worker/nginx 与
     `offline` 模式、`IMAGE_TAG` 只作用于该条命令、`$D up -d` 仍解析为 `:demo`（标签独立、不覆盖），
     以及"先 approve/revoke、确认一次性容器已退出，再跑宿主证据脚本"。
- 测试：`tests/test_task0027_host_offline_evidence.py` 20 → **28 项**，含用户指定必测反例：运行中且
  `DEPLOY_REVIEW_MODE=offline` 的第二容器命令指向 `task0027_real_ai_validation_app.py` → `untrusted`；
  命令匹配 `task0023_real_ai_app.py` 与 `scripts.task0023_real_ai_app:app` → `untrusted`；镜像标签匹配
  → `untrusted`；`api_entry.py`+`authorized-real` → `untrusted`；运行容器 inspect 不可读/命令读不到/
  `Running` 读不到/`api_entry.py` 无 mode 四种 → `unknown`；边界（另一个 offline 的 `api_entry.py`、
  已停止的验证入口容器）→ `ok`。全部沿用现有 fixture 注入机制，**未调用真实 Docker**。
- 本轮验证真实数字：ruff `All checks passed!`（官方范围 `src scripts tests`；
  `deploy/verify_api_offline_mode.py` 额外检查亦通过）、mypy `Success: no issues found in 104 source files`、
  `scripts/verify_repo.py` PASS、新增测试 `28 passed in 0.66s`、相关 6 文件 `90 passed in 121.54s`、
  相关 8 文件 `90 passed in 6.50s`、官方 Focused `90 passed in 127.74s`（`[1/7]`–`[5/7]`；
  Focused 按设计不跑 `[6/7]`/`[7/7]` 真实启动 smoke）；CLI fixture 回放：验证入口（offline）→
  `untrusted` 退出码 3、inspect 不可读 → `unknown` 退出码 2、正常离线 → `ok` 退出码 0，证据不含注入的
  供应商密钥。**按用户指令未重跑 Full、未 git 提交**。命令与转录见
  [TASK-0027 验证记录 第四轮](docs/development/TASK-0027-validation.md)。
- **本轮边界（不得宣称超出）**：判定是启动命令/镜像的**子串匹配**（把装配改名或用 shell 间接 `exec` 会漏）；
  "验证镜像标签"规则会同时命中用该镜像跑的一次性辅助容器（**有意的失败关闭**，README 已写明先后顺序）；
  全文仍是 fixture 回放，**未在真实宿主运行该脚本**；证据仍是内容不是签名，操作者仍在信任链中。
  同类未改项：`deploy/README-demo.md` 8.1 第 3 条的预构建命令
  （`$D exec api python scripts/prebuild_legal_vectors.py`）同样依赖运行中的 `:demo` 镜像，
  按用户本轮明确范围未改动，线上 api 切到新代码镜像时应一并处理。

以下保留 TASK-0027 第三轮（验证入口强制索引身份 + 宿主机侧离线证据）与更早的记录。

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，第三轮
  （验证入口强制索引身份 + 宿主机侧离线证据）改动已由用户提交为 HEAD `972ef54`
  （`feat(TASK-0027): pin the index identity and prove offline mode from the host`）。
- 本轮两条"最小修正"（用户 2026-10-16 指令，全部本机合成测试，**零付费调用、未触碰线上服务器**）：
  1. **预构建索引校验不再可选**：`scripts/task0027_real_ai_validation_app.py` 的
     `--publication-id/--revision-id` 变为 argparse 必需项（缺失即退出码 2），新增
     `verify_prebuilt_index` 把两者与 `modelstate` 卷内 `vector-manifest.json` 记录值**逐一比对**，
     并校验 `legal_snapshot_sha256`（对冻结语料）、`embedding_identity.identity_sha256`（对本装配
     embedding 身份）、`item_count`（常量 **3112**）、`source_item_count`（**3120**）、覆盖率，
     以及索引库中该构建的 `status=complete`、身份/发布/计数/`manifest_sha256` 一致与条目数相等；
     索引库以 SQLite `mode=ro` 打开，**不创建、不写入**。全部一致才打印一行
     `prebuilt index verified build_id=<64 位> item_count=3112 source_item_count=3120 ...`；
     任一项不一致 → 退出码 2、不启动、**不打印该行**、零供应商请求。
  2. **offline 状态必须有宿主机侧实际检查证据**：人工标志 `--online-api-offline-verified` 保留语义
     但不再单独成立；`--preflight` 同时要求新鲜的 `verdict: "ok"` 证据文件
     （`--host-offline-evidence`，默认窗口 600 秒、可配 60–3600 秒），且证据里的 api 容器 ID 与
     compose 项目必须与当前部署一致（`DEC007_API_CONTAINER_ID`/`--api-container-id`；
     compose 注入的 `DEPLOY_COMPOSE_PROJECT`/`--compose-project`）。缺失/过期/`unknown`/
     `untrusted`/标识不一致/只有人工标志无证据，一律退出码 2、不启动、零供应商请求。
  3. 新增宿主机侧只读脚本 `deploy/verify_api_offline_mode.sh`（逻辑在同目录
     `verify_api_offline_mode.py`，标准库 only、按宿主 python3.10 兼容编写）：只用只读
     `docker compose ... ps` / `docker ps` / `docker inspect`，**不创建/启动/停止/删除/进入容器、
     不挂 Docker Socket、不给任何容器 Docker 权限**；唯一写入是 `--evidence-dir` 下的证据 JSON，
     记录检查时间戳、compose project、api 容器名与 64 位 ID、`docker inspect` 里**实际生效**的
     `DEPLOY_REVIEW_MODE`、`APP_ENV`、镜像引用/镜像 ID、入口与主进程命令、运行状态、health、
     扫描容器数，以及"是否存在第二个 `authorized-real` 执行实例"；判定 `ok`=0 / `untrusted`=3 /
     `unknown`=2，两种非 ok 均为失败关闭并明确提示"立即停止、不发起供应商调用"。
     **只输出白名单字段，绝不输出完整环境变量或任何密钥**（测试注入 `DASHSCOPE_API_KEY` 与 `PATH`
     后断言二者都不出现在证据与终端输出中）。
  4. `docker-compose.demo.yml` 的 api 服务新增 `DEPLOY_COMPOSE_PROJECT: tender-review-demo`
     （与顶层 `name:` 相同、非密钥、其他服务零注入），供一次性验证容器取得当前项目名。
- 测试：新建 `tests/test_task0027_host_offline_evidence.py`（20 项：ok/untrusted/unknown 三类 verdict、
  只读 docker 调用审计、密钥不外泄、证据键集合等于白名单、fixture 回放、严格加载器的全部拒绝路径），
  `tests/test_task0027_validation_entry.py` 扩到 28 项（必需 ID、`prebuilt index verified` 打印与
  **反例不打印**、manifest 发布/修订/快照/身份/计数不一致各自被拒——用摘要自洽的篡改清单避免只测到
  digest 校验、缺 manifest/索引库**零写入**、拒绝时**零网络请求**），`tests/test_task0027_deploy_compose.py`
  固定项目名常量。全部合成数据、无真实 Docker、无供应商。
- 本轮验证真实数字：ruff `All checks passed!`（官方范围 `src scripts tests`）；mypy
  `Success: no issues found in 104 source files`；`scripts/verify_repo.py` PASS；
  pytest `55 passed`（3 个新增/修改文件）、`79 passed`（6 文件）、`90 passed`（8 文件相关回归）；
  官方 Focused `82 passed in 115.46s`（另一次 `82 passed in 125.00s`，7 步全过）；
  **按用户指令未重跑 Full**。命令与转录见
  [TASK-0027 验证记录 第三轮](docs/development/TASK-0027-validation.md)。
- **本轮边界（不得宣称超出）**：证据是**内容不是签名**——能运行宿主脚本的人也能写出同样的 JSON，
  操作者仍是信任链的一环（与人工标志同一信任假设，区别是"确实检查过"由可核对证据与时间窗口固定）；
  容器内无法读取宿主 Docker 状态（也不允许挂 socket），当前 api 容器 ID/compose 项目由操作者声明
  与 compose 常量提供；`item_count/source_item_count` 常量绑定冻结语料，语料变更必须重新测量；
  **未在真实宿主运行该脚本**（本机只有 fixture 回放）；线上 `--publication-id/--revision-id` 与
  `modelstate` 卷的实机校验、任何容器构建/`docker compose run`、任何付费调用都**尚未发生**。

以下保留 TASK-0027 上一轮（硬门禁接线 + 独立隔离验证入口）与更早的记录。

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，基线 HEAD `37e380f`；
  **本轮（硬门禁接线 + 独立隔离验证入口）改动未提交**，由用户复核后自行提交。
- 本轮按用户 2026-10-16 批准的**方案 A**（装配层固定本轮额度，不新增租约锁、不改账本表结构、
  不永久写入收紧上限）完成：
  1. `create_dec005_gateway` 新增 `llm_limit`/`embedding_limit`/`total_cny` 可选参数并透传到
     `Dec005BudgetLedger`（同一账本文件、同一 authorization_id，计数累计）；`AUTHORIZATION_LIMITS[DEC-007]`
     的 300/800/¥30 不变，只作构造期上界。
  2. 隔离验证入口 `scripts/task0027_real_ai_validation_app.py`：本轮上限固定为常量
     `llm_limit=4`、`embedding_limit=322`（312 已用 + 10）、`total_cny=Decimal("2")`（含已结算
     ¥0.1035070 的累计口径）；环境变量/命令行/演示账号都无法放宽；独立镜像标签
     `IMAGE_TAG=task0027-validation`（不覆盖 `:demo`）、同一 `modelstate` 卷读写挂载、同一发布/修订
     与 embedding 身份与授权 scope、`allow_build=False` 缺索引即拒绝；`--preflight` 只做本地/只读检查
     （基线、scope、公网 API 可达性、操作者 offline 确认、可选预构建索引校验），零预留零写入零外发。
  3. 账本基线只读核对 `scripts/task0027_ledger_baseline.py`（`mode=ro`，不创建/不修改/不重置）；
     基线期望值 **LLM 0 / Embedding 312 / ¥0.1035070 / 未结算 0**，不一致退出码 2 并要求停止上报。
  4. 反例测试 `tests/test_task0027_round_limits.py`（8 项）与 `tests/test_task0027_validation_entry.py`
     （16 项）：第 5 次 LLM、第 11 次新增 Embedding、¥2 耗尽（次数仍有余量）、失败与未知用量保留且不
     自动补发、跨实例/重启计数不减、两实例竞争最后一个名额原子拒绝、宽窄实例差异与账本不被写入收紧值、
     环境与 CLI 无法放宽、拒绝时 transport 零调用。
  5. 文档：`deploy/README-demo.md` 新增 8.4（三步顺序：门禁与测试通过 → 登记冻结 DOCX 的 SHA-256 →
     才发起真实调用；独立镜像命令；基线核对；方案 A 边界），`docs/development/TASK-0027-validation.md`
     第二轮记录，任务 YAML 新增 `TASK0027-008`。
- 本轮验证：ruff `All checks passed!`、mypy `Success: no issues found in 104 source files`、
  新测试 24 passed、相关回归 49 passed / 75 passed、官方 Focused `49 passed in 72.74s`（未重跑 Full）。
- **方案 A 的边界（不得宣称超出）**：账本只存计数、上限是进程内参数，宽上限实例理论上仍可打开同一账本；
  本轮必须确保只有一个真实模型验证实例运行，**不提供**跨任意进程的全局收紧锁（选项 C 未实现）。
  收紧上限不落盘：后续正式演示恢复 300/800/¥30 时继续累计使用原有账本，**不得删除账本恢复额度**。

- 工作树 `bidding-compliance-agent-TASK-0027` / 分支 `work/TASK-0027`，基线 HEAD `fced54b`
  （DEC-007 方案 A 已实现）；**本轮改动未提交**，由用户复核后自行提交。
- 本轮完成 9 项验收前阻断问题，逐条命令与真实数字见
  [TASK-0027 验证记录](docs/development/TASK-0027-validation.md)：
  1. `docker-compose.demo.yml` 新增 `x-real-model-environment` 锚点，真实模型变量**只注入 api**
     （worker/init 零注入，由解析 compose YAML 的测试固定）；全部 `${VAR:-}` 可选，留空时
     `DEPLOY_REVIEW_MODE=offline` 仍正常启动；`deploy/demo.env.example` 只留注释占位。
  2. 服务端真实检索**必须复用预构建索引**：`AuthorizedRetrieverFactory.allow_build` 默认 False、
     API 装配显式传 False；缺索引/未完成/校验失败直接拒绝，**零供应商调用**；维护命令
     `scripts/prebuild_legal_vectors.py` 仍可独立建库与断点续建。
  3. 预构建与 API 的 embedding 身份、发布版本、`modelstate` 卷与账本 scope 一致性在正式外发前
     校验，四种不一致各自被拒（`planned_build_id` + manifest 身份校验）。
  4. 逐文件授权注册表按文件 mtime/size 重读，**撤销对运行中的 API 立即生效**（`_freeze_run`/
     `_invoke` 与出站 minimizer 每次判定重解析）；测试以"进程已启动 → 外部 revoke → 外发被拒"
     证明（含 gateway 级：撤销后第二次请求 0 次供应商外发）。
  5. 前端新增 `dec007-real-qwen` 模式说明（授权范围 + 逐文件白名单 + 本地检索/人工复核），
     保留 `offline-deterministic`/`online-qwen`/`dec005-real-qwen` 既有模式；`Dockerfile.web` 与
     env 模板注释同步。
  6. DEC-007 Embedding 上限 400 → **800**（LLM 300、¥30、授权 ID `DEC-007-2026-10-16` 不变，
     建库与查询共用同一账本、不重置 DEC-005/006），并补 800 允许/801 拒绝、¥30 耗尽即拒绝
     （批次仍有余额）、失败与未知用量保留预留且不自动补发的边界测试。
  7. 文档补齐：DEC-007 修订说明、`deploy/README-demo.md` 逐文件授权运维步骤（approve/list/
     revoke、立即生效语义、与账本 scope 的关系）、`CHANGELOG.md`、任务 YAML 证据路径。
  8. 已运行 Focused/Full/`scripts/verify_repo.py`、ruff、mypy 与前端四项检查；命令与数字见验证记录。
  9. **线上保持离线**：未执行任何部署或容器操作，未访问任何付费供应商，`47.83.132.211` 未触碰。
- 仍未完成/待批准：git 提交与远程 CI 观察；DEC-007 首次真实调用申请（批次、费用、文件哈希、
  外发数据范围）；线上切换到 `authorized-real` 与预构建索引；本轮未重跑 Full。
- 不可宣称：任何风险的违法认定、任何条款已核验适用、生产级防回滚、跨任意进程的全局预算收紧锁；
  本地账本只挡住"审计存在而账本被删/空"的明显回滚形态。

以下保留 TASK-0026 上线状态与更早的历史记录。

## 历史快照：TASK-0026 已在阿里云 ECS 上线并通过公网 HTTPS 验收（记录时点见下文）

- **线上地址：https://47.83.132.211**（阿里云 ECS 香港 B，Ubuntu 22.04，2 vCPU / 7.5 GiB / 40 GB，
  实例 `i-j6ccqpfriae57w0hkskn`）。六服务健康，公网仅开放 22/80/443。
- **Let's Encrypt IP 地址证书**：`shortlived` profile，IP SAN `47.83.132.211`，有效期 160 小时；
  外部 `Verify return code: 0 (ok)`，TLS 1.3；已部署为实体文件（非 certbot 符号链接）。
- **自动续期**：双 systemd 定时器 + 2 天续期阈值（≈1.5 张/周，低于 5 张/周配额）；
  dry-run 通过、真实 renew 正确跳过未到期证书、并发锁与到期告警均实测有效。
  首次真实续期预期 2026-10-20 前后；已设只读定时核对。
- **公网 HTTPS 业务 E2E passed**：登录→建项目→上传→ClamAV 扫描→隔离解析→上下文确认→
  LangGraph 审查→风险与证据→人工复核→发布→Word/PDF 下载（下载 SHA-256 与服务端 `content_hash` 一致）。
- **线上 GUI 逐屏验收已完成**（项目创建、审查运行记录、服务端精确定位、复核历史、报告下载、路由与错误提示）；
  唯一未做的是 GUI 文件上传，因为内置浏览器不支持原生文件选择器，该路径由 API 层实测覆盖。
- **模型仍为离线确定性模式**，零付费调用；真实 Qwen 待 DEC-007 单独审批。
- 不可宣称：任何风险的违法认定、任何条款已核验适用、生产级防回滚；未配置外部告警渠道。

以下保留 TASK-0026 本地阶段与更早的历史记录。

- 工作树：`bidding-compliance-agent-TASK-0026` / 分支 `work/TASK-0026`（自 `work/TASK-0023`
  的 `ca1c15d76150bc64c9ca8a3425fc65e7d416dcf1` 创建）。
- **TASK-0026 完成本地部署验收**（详见 [TASK-0026 验证记录](docs/development/TASK-0026-validation.md)）：
  只新增编排与配置，未改 `src/`、`contracts/`、`tests/`、`scripts/`、`knowledge/` 与两份锁文件。
  - 新增 `docker-compose.demo.yml`（六服务、四个显式命名卷、两个内部网络，只有 nginx 发布端口）、
    `Dockerfile.api`、`Dockerfile.web`、`deploy/` 下的容器入口/幂等初始化/反向代理/备份恢复/验收脚本与说明。
  - 本机 Docker Linux 引擎实测：六服务健康；经反向代理完成合成标书全链路（上传 → ClamAV 扫描 →
    隔离解析 → 上下文确认 → LangGraph 审查 → 风险证据 → 人工复核 → 发布 → Word/PDF 下载，
    下载 SHA-256 与服务端 `content_hash` 一致）；真实浏览器验证前端页面与「离线确定性演示」如实标注；
    `docker compose down` 删除全部容器后重建，项目/文档/任务/报告字节一致；备份恢复演练逐表一致
    且未修改线上数据。
  - 空闲稳态内存实测约 **1.64 GiB**（ClamAV 964.7 MiB、API 417.8 MiB、PostgreSQL 94.9 MiB、
    MinIO 89.3 MiB、worker 59.9 MiB、nginx 13.8 MiB）；**未下调**装配中审查过的 `--memory=3g`。
  - 实测结论：受限 Docker API 代理无法转发 `docker run -i` 的交互式 attach（解析 `PARSE_TIMEOUT`），
    故未交付该加固层；worker 持有 Docker Socket 是本方案剩余的主要风险面，已如实记录。
- **当前阶段：等待真实服务器凭据后上云**。已确认目标为阿里云 ECS（Ubuntu 22.04、2 vCPU / 8 GiB、
  公网 IP 47.83.132.211、磁盘待登录后检测）。**尚未在目标主机执行任何部署**，HTTPS 未签发、
  真实 Qwen 未启用。
- **真实 Qwen 仍被阻断**：模型网关仅有 `DEC-005`（30 次/¥20）与 `DEC-006`（15 次/¥5）两条已消耗的
  本地授权，且外发受文档 SHA-256 白名单约束；新上传的演示文件要获得真实 Qwen 审查，必须新增独立授权
  并登记文件哈希，均需用户单独批准。本轮零供应商调用、零密钥入库。
- 不可宣称：任何风险的违法认定、任何条款已核验适用、生产级防回滚、在目标主机上已完成实测。
- TASK-0019/TASK-0021/TASK-0022 工作树未被写入。

以下保留 TASK-0023/0024/0025 阶段的历史记录。

- **TASK-0023 完成**：真实 Qwen 业务验收闭环（DEC-006，10/15 次、¥0.062695，19 个模型候选，
  19 项人工复核，Word/PDF 下载哈希与服务端 `content_hash` 一致）。
- **TASK-0024 完成**：法规检索解阻、参考候选展示（页面与 Word/PDF）、三案例排名评测。
- **TASK-0025 完成**：证据分类修复（未核验法规不得进入正式法律证据）、账本连续性防护、
  Windows baseline 超时 10→20 分钟；Full CI 全绿。
- 部署前审计方案见 [面试演示部署方案](docs/development/DEPLOYMENT-DEMO.md)；实际落地与实测见
  [TASK-0026 验证记录](docs/development/TASK-0026-validation.md) 与 `deploy/README-demo.md`。

以下保留TASK-0022阶段的历史记录，包括当时DEC-005未获批准的叙述；本轮状态以上述记录和汇总文档为准。

架构基线：ADR-0012本期法规生命周期/来源映射接受；ADR-0015历史决策保留、其TASK-0018 BGE/Paddle部署计划由已批准ADR-0016局部修订；Word V2.0 + ADR-0011开发验证替代ADR-0009，ADR-0010法规方案proposed；业务ADR-0001至0008保留 / 开发契约v1alpha3
当前里程碑：M1、M2、M2A、M3、M3B 已按记录退出；M3A/TASK-0022 继续进行本地离线诊断。当前天津地铁 DOCX 经正式上传、安全扫描、隔离解析和上下文确认后完成离线 LangGraph；五类 Skills 产生0候选，RAG 5/5 `CONTEXT_INVALID`，空候选合并、人工确认和 Word/PDF 报告路径已验证。该结果不表示全部合规；适用法律框架未确认、法规证据未匹配，且没有真实 Qwen 调用。TASK-0019 按用户要求临时暂停，在本分支以 Schema 支持的 `blocked` 表示，其原工作树/未提交成果不参与本任务。DEC-002 唯一合成数据请求已消耗；DEC-005 仍未批准，真实文件和法规正文尚未外发。M4/M5 及 TASK-0012/0013/0014 原验收范围不变。

## 已完成

- 建立模型无关的仓库协作规则与文档入口。
- 建立需求 ID、验收 ID、安全 ID 和非功能需求 ID 的追踪机制。
- 建立 LangGraph 状态、风险、证据、任务事件和 OpenAPI 初始契约。
- 建立模型网关协议与供应商适配边界。
- 初始纳入42份法规全文及来源索引；TASK-0006已完成版本化摄取（新增1份新版）。
- 建立统一仓库验证脚本。
- TASK-0003修正：正式契约校验、State生成、流程依赖、分离风险状态、局部验收证据、锁定环境和CI配置。
- 已建立M0至M6七个里程碑与17个任务；53个需求/验收ID均已分配阶段，尚未全部实现。
- TASK-0002：可启动FastAPI/Uvicorn后端、健康检查、环境配置、请求追踪、统一错误和结构化安全日志。
- TASK-0015：夹具位置、独立诊断、错误码契约、模型数据策略、秘密扫描与文档冲突修复；首次Git提交已推送、CI已成功。

- TASK-0004：显式数据库迁移、可撤销JWT身份、租户/RBAC、版本化项目与事务幂等；PostgreSQL真实CI通过。
- TASK-0005：安全文件上传、持久作业、ClamAV强制扫描、受限Docker解析、PDF/DOCX/扫描件定位、人工质量/上下文版本、鉴权下载；真实容器与远程三作业CI通过。

- TASK-0006已完成并归档：43版本/3120片段，D01–D07本期缺陷全部解决/边界保持；效力与条款适用分开、完整HTML/PDF来源映射、独立全局授权、不可变核验/发布/双CAS/回滚/审计，Result5。源码5347b110a8c3561c72086afd455755810de59abf本地/远程Full413项与全部真实集成/汇总成功。旧42文本保持未核实，法规能力不替代最终违规判断。

- TASK-0017：单Codex实施、Quick/Focused/Full与失败关闭CI已完成；修复跨平台CRLF检出，最终源码68d67a80943e9c531f58ced7557d0c24938d84e9本地/远程Full279项与PostgreSQL、ingestion、汇总门禁通过，归档记录用Quick。

- TASK-0007已完成并归档：五类无模型确定性Skill、版本化规则与候选发现契约、原文定位/稳定去重及法规检索主题。源码236d2a6e231be030f719b0bbabc3f2b0a50039b3 Focused 30项、最终Full448项本地通过（0失败/错误/跳过），真实HTTP/身份/租户集成检查通过；远程38516913371适用作业及汇总门禁成功。详见TASK-0007-validation.md。
- TASK-0010已完成并归档：源码候选`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`本地Full504及PostgreSQL16专项通过；源码CI38556383801、验收记录CI38557180768、归档CI38557509858所有适用作业均成功。复核/审计、不可变Word/PDF报告、引用回查和越权导出审计已实现。生产模型路由仍受DEC-002限制；详见`docs/development/TASK-0010-validation.md`。
- TASK-0011已完成并归档：源码候选`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`，归档提交`05c2b91655a7152b28692c7f5216de3ace3d7ff8`；源码CI 38600922153、验收记录CI 38603582949、归档CI 38604186570 的适用作业均成功。FR-013配置版本管理已实现；真实浏览器E2E 5/5、PostgreSQL16专项、Focused 69和本地Full 510通过。DEC-002仍未批准在线模型；详见`docs/development/TASK-0011-validation.md`。
- TASK-0018已完成本地与远端交付：源码提交 da7325bb95a10a10fcca82151c22c6272980d091 的 GitHub Actions Run 38641374412 completed/success；mode=full，baseline 537 passed/2 warnings，PostgreSQL、ingestion、verify-required success，quick 因 Full 模式合法 skipped。隔离副本正式Focused 144、Full 537项通过；前端检查、真实HTTP/身份 smoke、PostgreSQL16/RLS/Checkpoint/ReviewEngine provenance 持久化专项通过。修复 SQLite 完整向量缓存一致性校验并补齐损坏/缺失/续建测试和运行来源身份测试。仅官方 npm registry 安装，lockfile 未变；交付前审计为61条状态路径（29个已跟踪改动、32个未跟踪文件），原工作区与隔离副本路径集合和逐文件SHA-256完全一致。无供应商调用、真实API密钥、真实文件或法规文本外发；DEC-002仍待批准。详见`docs/development/TASK-0018-validation.md`。

- TASK-0020已完成并归档：实现提交`c85e9155949b1a1d961a1031949f003e1bfe0313`对应GitHub Actions [Run 38688174502](https://github.com/w186www/Tender-Review/actions/runs/38688174502) completed/success；baseline 545 passed/2 warnings，PostgreSQL、ingestion、verify-required success，quick因Full模式合法skipped。归档记录提交`f2b1b91e3bd6b08141414f0edd99dcfff0f8905e`对应[Quick Run 38689517542](https://github.com/w186www/Tender-Review/actions/runs/38689517542) success。本地Focused 76、Full 545、Microsoft Edge E2E 5/5、PostgreSQL/Checkpoint、parser sandbox、安全摄取及`--serve`清理均通过。只在严格OCRRuntimeIdentity持久化JSON读取边界兼容数组/tuple，原字段、类型、身份与provenance哈希验证保留；仅合成数据、离线Gateway，无真实模型调用或外发。M3退出条件满足；M3A/TASK-0019仍planned。详见`docs/development/TASK-0020-validation.md`。

- TASK-0021已完成并归档：代码提交`19a29fa0e62b6dc57d4493dc111f56194199e51c`对应 GitHub Actions [Full Run 38707492669](https://github.com/w186www/Tender-Review/actions/runs/38707492669) 全部适用门禁成功；归档提交`75bc559c609711dff7111da4545ca51a9d3f511c`对应[Quick Run 38709878505](https://github.com/w186www/Tender-Review/actions/runs/38709878505) 的 impact/quick/verify-required success，baseline/postgres/ingestion 按文档 Quick 条件合法 skipped。本地Focused 25、Full 570、PostgreSQL16/Checkpoint专项及 DEC-002 唯一真实 Qwen 合成数据 Edge E2E 5/5 通过，完成上传、解析、审查、人工复核与 DOCX/PDF 导出；供应商报告 424/420 tokens，按北京官方价格估算 ¥0.0014732。授权已消耗，不可额外调用。详见`docs/development/TASK-0021-validation.md`。

## 正在进行

- TASK-0019 暂停：由于任务 Schema 没有 `paused`，新治理分支中的状态为 `blocked`，语义是用户要求先执行 TASK-0022；其原分支 `work/TASK-0019`、HEAD `00829851018612a275faca9ad6609e10fa38305d` 和 12 项未提交文件均按 SHA-256 清单记录，原工作树未写入。详见 `tasks/handoffs/TASK-0019-paused-20261015.md`。
- TASK-0022 正在执行：独立分支 `work/TASK-0022`，基线 `work/TASK-0021` / `2624e14b39c25baca939ebede552527481c8ea53`。当前文件为天津地铁11号线 DOCX。真实文件经正式上传、ClamAV、隔离 parser、人工校正 API 与正式上下文确认后达到 ready；空候选阻断已在离线测试 Gateway 修复。实际离线运行得到0个候选、RAG 5/5 `CONTEXT_INVALID`、LangGraph `result_published`；测试审核账号确认空结果，Word/PDF API 生成和下载均 HTTP 200。Focused 3项通过；Full未重跑。DEC-005未批准、真实模型调用0；本次审查不构成合规结论，且未用 Edge 浏览器验证真实文件流程。详见 `docs/development/TASK-0022-validation.md`。
- DEC-005 单次 Qwen 评测授权仍为 proposed；用户明确批准前不得调用。即使获批，也须先解决解析质量和上下文确认；TASK-0021 的 DEC-002 合成样本授权不得复用。
- DEC-001 外部部署仍待决策。42 个法规版本仍未核验，演示必须保留证据状态，不得默认外发法规正文。

## 历史下一步记录（截至 2026-10-15；当前顺序以 U01—U16 路线图为准）

1. TASK-0022 保持 in_progress：离线工作流与报告路径可演示，但法规框架/法条匹配未完成，Skills 覆盖有限；不可把0候选称为无风险或合规。当前不得调用真实 Qwen。
2. 真实文件演示与 TASK-0021 合成样本真实 Qwen 演示须分开标注。DEC-005 如需执行真实文件评测，需按独立授权继续；DEC-002 不可复用。
3. TASK-0022 收尾后由用户决定是否恢复 TASK-0019；其工作树和 12 项文件哈希需与暂停清单一致。
4. 42 个未核验法规版本及到期核验日期继续按既有边界处理；DEC-001 未获批准前不部署公网服务。

## 最近验证

- 2026-10-15 TASK-0022 零候选离线工作流：`scripts/check_review_engine.py` 仅放宽合法空 candidates 时对 RAG 结果非空的测试夹具断言；candidate evidence 键仍须精确匹配，非空候选仍须有法规检索结果。Focused `tests/test_task0022_zero_candidate_review.py` 3 passed；Ruff、Mypy 98文件、前端6项及 build 通过；未重复 Full。真实文件 run `ef621b8a-a7b8-56fd-ba22-05955b5b02bd` 到达 `result_published`，0 findings；RAG 5/5 `CONTEXT_INVALID`、可引用命中0。正式测试审核账号记录 `confirm_no_findings`，其原因明确否定合规推断。Word/PDF 报告 API 下载均 HTTP 200；详细私有诊断留在 `.verification/private/TASK-0022/`。外部模型请求0，DEC-005未批准。
- 2026-10-15 TASK-0021源码/测试证据：manifest SHA-256 `407a0564c2d8508bde52cee3626394f50a8a5a3c82c934c5d9a0e2204442fd1d`；Focused 25 passed，Full 570 passed/2条既有pypdf弃用警告，Ruff、Mypy98源文件、前端6项/build及HTTP/身份smoke通过；PostgreSQL16/Checkpoint 专项通过。官方北京价格按输入¥0.8/百万tokens、输出¥2.7/百万tokens核验；授权硬预算¥0.10且调用前全额预留，白名单规范化JSON发送前强制≤2,048 UTF-8字节。
- 2026-10-15 TASK-0021唯一真实在线实证：run `30180d4e152040ccb9f805634617b456`，Microsoft Edge 5/5通过，0 failure/error/skip；合成DOCX SHA-256 `c770a3576555fc9225b2612c98966e809cc087194e3bb2d3d7c3bfb05ed65341`。恰好一条 `bailian/qwen3.8-flash` 请求，供应商报告424输入/420输出tokens，费用按北京官方单价估算¥0.0014732，延迟10,125ms，重试0/无回退；响应哈希`5f462b27fa9cf59015a14db08bb411d76da24f617c8ac17ea8b51f3241e47dcb`。结构化输出关联审计哈希并进入 merged finding；本地RAG、人工复核/Checkpoint恢复、DOCX/PDF生成及下载均由E2E断言通过。无源码/测试变化，复用Full 570；代码提交、归档提交及对应 CI 均成功。详细证据见`docs/development/TASK-0021-validation.md`。
- 2026-10-15 TASK-0020 本地及远端最终验收：Git index 源码/测试十文件 manifest SHA-256 `c5ec2a5a0e28d9c5317f6a9ae0d019131694b7d8673d7758991d469a1ff9cf7a`；Focused 76 passed，Full 545 passed/2 条既有 pypdf 弃用警告，Mypy97源文件；真实 Edge 5/5（run `86521e79591241c19b28aaecf0988323`，合成 DOCX→安全解析→离线ReviewEngine→人工复核/发布→Word/PDF下载）；PostgreSQL16、Checkpoint/ReviewEngine、parser sandbox、ClamAV/MinIO/S3安全摄取均通过；`--serve` run `9a9478a6b4dc4d8b9c1fd0e34b40f09c` Ctrl+C 后 manifest `stopped` 且三容器已移除。GitHub Actions Run 38688174502 对提交`c85e9155949b1a1d961a1031949f003e1bfe0313`全部适用门禁成功；baseline JUnit 545/0/0/0。TASK-0019工作树状态和12个变更文件哈希与本轮开始快照一致。详见`docs/development/TASK-0020-validation.md`。

- 2026-10-15 TASK-0018检索基线：43版本/3120片段，法规索引SHA-256 `69d340d65f5e9114c8a2e76f8b3b524b67f47d0cbc0088c4e01d80b7db8729fd`；其中42版本未核验、仅1个已核验版本用于10条正式标签。CharacterEmbedding/BM25/RRF实际指标Recall@5/10=1.0/1.0、MRR@10=0.4867、nDCG@10=0.6141；平均查询延迟1,202ms，峰值进程工作集125,927,424字节。相同快照/标签的重复运行指标相同，平均查询延迟1,020ms。适用性过滤4例0错，效力/核验期限过滤1例0错；77个未核验候选单列，专家未确认风险样本数为0（不代表已证实无此风险）。
- 2026-10-15 TASK-0018 Tesseract：实际固定摘要隔离解析镜像 `2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597`、Tesseract 5.3.0、chi_sim/eng模型SHA记录。合成3页双栏扫描 CER 20.79%，关键标记5/6，表格单元7/14，页码标记3/6、OCR定位100%，重复短语定位0/2。页面被现有入库质量门判为passed，尽管这些指标触发合成评测警报；该不一致在本任务报告中保留，不改变门禁。单文档进程RSS峰值90,099,712字节、容器峰值146,718,720字节、解析耗时1,515ms、主机端到端2,591ms；超时0，空白件降为requires_review，畸形PDF失败关闭为INVALID_FILE。仅为合成样本结果，不代表真实招标件质量。详见`evals/ocr/results/tesseract-baseline-final-reviewed-20261015.json`。
- 2026-10-15 TASK-0018本地与远端验收：官方`registry.npmjs.org` DNS/HTTPS成功；隔离副本安装184个npm包，package-lock SHA-256保持`CE42801FF4EF6A086191D78203C91185F582131F8E246AFDB0FEC295E1724A29`。正式Focused 144项、Full 537项通过；Mypy97源文件，前端6项、OpenAPI、Biome、TypeScript、build及真实HTTP/身份 smoke通过。SQLite向量缓存完整性损坏/缺失/断点续建测试和ReviewRuntimeProvenance JSON持久化专项通过；PostgreSQL16迁移/RLS/Checkpoint/发布/撤权专项通过。交付前61条状态路径与隔离副本逐路径、逐文件SHA-256一致；52个源码/契约/脚本/测试/评测文件清单SHA-256为92D559884EEA235BB217277519BC4BE765323ED8290268EEBEB9F1338E2265AD。原工作区与隔离副本两处lockfile均未变。无实际模型/API Key/真实招标文件或法规正文外发；源码提交远端 Full 与 verify-required 已通过，TASK-0018本地及远端交付闭环，DEC-002仍待批准。详见`docs/development/TASK-0018-validation.md`。
- TASK-0011已归档：源码候选`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`的 Windows baseline、PostgreSQL、ingestion、verify-required CI 全部成功；验收记录CI和归档CI的impact/quick/verify-required适用作业成功。归档提交`05c2b91655a7152b28692c7f5216de3ace3d7ff8`对应归档CI 38604186570。源码本地 Full 510 passed（对应源码`57d3a833f59a09e9c938837671a8769d91c7fc5b`，其后仅扩展前端LF检出属性），FR-013 Focused 69 passed，PostgreSQL16两个专项通过；真实 Microsoft Edge Playwright E2E 5/5，使用真实 FastAPI/PostgreSQL/文件服务及授权注入的离线ReviewEngine，并验证持久化结果。前端 OpenAPI生成内容与契约一致；Windows CRLF检出问题已通过`.gitattributes`固定所有前端文本为LF解决。详情见`docs/development/TASK-0011-validation.md`。
- TASK-0009归档候选：源码`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`的Focused13、最终Full500（0失败/错误/跳过）、Ruff、Mypy80文件、契约/生成/秘密检查、真实HTTP/身份/撤权和PostgreSQL恢复/并发/事务故障专项通过。用户确认源码及验证记录提交的必要远程CI通过；本次归档记录Quick通过，归档提交远程CI待核验。DEC-002未批准、在线模型调用未验证、预算账本仅单进程一致性、法律证据最高为suspected；TASK-0010源码/记录/归档CI均已成功。详见`docs/development/TASK-0009-validation.md`。
- TASK-0010源码候选`ab878ecd9f5df5d60ea4e27fe7edc451246ca75e`：最终完整`verify.ps1 -Mode Full`通过504项、0失败/错误/跳过；Ruff、Mypy85源文件、契约/生成一致性与真实HTTP/身份/项目流程通过。PostgreSQL16真实迁移/RLS/复合FK/并发/回滚及TASK-0009审查恢复、TASK-0010决定幂等与并发、共享结构化报告、DOCX/PDF生成、原文回查、授权与拒绝导出审计专项通过。源码CI38556383801、验收记录CI38557180768及归档CI38557509858均全部适用作业成功。DEC-002未批准，生产模型路由仍关闭。详见`docs/development/TASK-0010-validation.md`。

- TASK-0007最终代码源码236d2a6e231be030f719b0bbabc3f2b0a50039b3：Focused 30项通过；Full 448项、0失败/0错误/0跳过，Ruff、Mypy64源文件、契约生成检查及真实HTTP/身份/项目/撤权/租户隔离验证通过。Full在本机回环网络授权下执行，JUnit `.verification/pytest-result.xml`；两个既有pypdf `add_js`弃用警告。远程https://github.com/w186www/Tender-Review/actions/runs/38516913371 对应该源码，impact/baseline/postgres/ingestion/verify-required全部success；远端JUnit artifact已生成，但下载接口需认证，未声称远端测试数量。代码提交与证据绑定；后续文档/任务归档改动仅Quick，不重复Full，不合入main、不启动TASK-0008。详见docs/development/TASK-0007-validation.md。

- TASK-0006最终源码5347b110a8c3561c72086afd455755810de59abf：一次Full413项、0失败/错误/跳过，Ruff/Mypy54源文件与契约/生成、两个实际HTTP通过；真实PostgreSQL原迁移/RLS/复合FK/增量降级及全局核验/发布竞争、最小权限、撤权、失败事务回滚/历史重现通过。最终固定Docker官方PDF84条/15页、隔离、MinIO/ClamAV/OCR/HTTP全部通过，测试容器清理。远程https://github.com/w186www/Tender-Review/actions/runs/38510406707 completed/success，impact/baseline/postgres/ingestion/verify-required全部success，下载远程JUnit413/0/0/0。归档/证据后仅Quick，源码无变化，不重复Full。

- TASK-0006历史D03续建：95项Focused、真实PostgreSQL16及最终Full323项通过（JUnit0失败/0错误/0跳过，Ruff、Mypy48文件、正式契约/生成与两项实际HTTP检查）。修复Result v1alpha3正式EvidenceRef/资格矛盾/引用集合与冻结制品解析；D07同文本制品引用部分修复，原始清洗映射等余项保留。最终源码f0bd8270d990d5e5dc6897f329a770d7db332099已推送，远程https://github.com/w186www/Tender-Review/actions/runs/38498549575 completed/success，baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验323/0/0/0，后续仅工程记录Quick，无重复Full；TASK-0006继续in_progress。

- TASK-0017已归档：初始0016b306源码本地Full277项，但远程38446832736最终failure；日志确认旧42份法规CRLF哈希与Linux LF检出不一致。修复源码68d67a80943e9c531f58ced7557d0c24938d84e9，84项Focused、真实PostgreSQL16专项和最终Full279项通过（0失败/0错误/0跳过，Mypy48源文件及两个真实HTTP检查）。远程https://github.com/w186www/Tender-Review/actions/runs/38496768950 completed/success：baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验279/0/0/0。仅记录/归档变动后Quick通过，未重复Full。完成规则ADR-0011，证据TASK-0017-validation.md；TASK-0006没有自动完成。

- TASK-0006本轮纠正：最终完整verify.ps1通过251项、0失败/0错误/0跳过（JUnit已核对），Mypy48文件；真实HTTP健康/身份/项目/撤销通过。56项法规专项、109项组合检查通过；临时PostgreSQL16增量/重复迁移、RLS/WITH CHECK、最小权限、运行读取/撤权/触发器/完整回滚实证通过，容器已清理。两次中间失败保留在TASK-0006-validation.md；无远端CI新证据。

- TASK-0006历史恢复分支自测（不是独立审查）：25项通过；Mypy46源文件无错误；真实43版本/3120条款摄取、新版84条完整提取与政府工程投标保证金检索通过。归档后最终完整verify.ps1通过215项、0失败/0错误/0跳过（JUnit已核对），真实HTTP健康及身份/项目/撤销流程通过；Ruff与契约/生成一致性通过。见docs/development/TASK-0006-validation.md。

- TASK-0005本地：完整verify.ps1通过，186项、0失败/0跳过，Mypy41源文件；真实解析隔离、官方源码MinIO/ClamAV/OCR/扫描PDF/HTTP及PostgreSQL增量迁移/RLS均通过。
- TASK-0005最终源码远程实证：4d6fca6b16fbae66aed82041e08097162a444468，https://github.com/w186www/Tender-Review/actions/runs/38424742422 的baseline/postgres/ingestion均completed/success；已下载JUnit核验186项、0失败/0错误/0跳过。详细范围见docs/development/TASK-0005-validation.md。本次归档证据提交另触发相同CI，链接绑定明确源码版本，不将该SHA冒充后续HEAD。

- TASK-0004本地最新：完整verify.ps1通过，152项测试、0失败/0跳过，Mypy检查27个源文件；真实HTTP身份与项目流程通过。
- TASK-0004最终代码远程实证：提交5dca2e341b97ce08d830a91936ca4d3d0f511aaa，https://github.com/w186www/Tender-Review/actions/runs/38393126223 的baseline与postgres均completed/success。已下载远程JUnit核验152 tests、0 failures、0 errors、0 skipped。链接对应明确的代码SHA；本证据文档提交自身另触发CI，不将代码SHA冒充后续HEAD。

- TASK-0015历史结果：按项修复后完整verify.ps1通过，121项测试、0失败；当时Mypy检查18个应用源文件，真实HTTP检查通过。分项记录见docs/development/TASK-0015-validation.md。
- 健康200、未知路径404、请求编号一致；临时服务已停止。默认启动方式：./scripts/start.ps1。
- 独立环境安装与pip check通过，实际版本已锁定；TASK-0002证据见docs/development/TASK-0002-validation.md，M0历史证据见baseline-validation.md。
- 远程CI已实际成功：提交1e744ed15e7d35934cbe536695ab2b8276b02980，运行https://github.com/w186www/Tender-Review/actions/runs/38388275001，状态completed/success。该链接核验对应源代码提交；证据提交会另行触发CI，不能将历史SHA冒充当前HEAD。
- 没有宣告业务审查、数据库就绪或完整生产安全验收。

## 已知问题

- TASK-0011的真实浏览器链路与FR-013配置版本管理已通过本任务局部验收并正式归档；局部完成不代表相关全局AC或M3已完成。
- Word内嵌图片需人工转录；DOCX外部关系含超链接严格拒绝；中文复杂版面质量仍需黄金集验收。详见secure-ingestion-start.md。
- 本机Docker Linux Engine已可用（29.2.1）；临时PostgreSQL16本机迁移/权限/RLS/并发/回滚与真实S3/扫描/OCR检查通过，仅测试服务已清理。TASK-0005历史PowerShell完整门禁186项全通过；当前任务结果见最近验证。
- Windows受限沙箱会阻断asyncio内部回环连接；完整验收须允许本机回环网络，不能跳过测试。
- 系统默认Python存在打包路径/ensurepip问题。已使用独立Python 3.12.14环境，统一脚本优先使用.venv；新环境按README创建，测试临时目录限定在项目内。
- 法规元数据已固定43个版本：42份旧文本仍未逐项核实，1份司法部2019修订《实施条例》核验到2026-10-14且仅启用工程范围。本期全局管理服务/鉴权CLI已实现；完整生产法规效力验收、pgvector、神经语义召回及管理前端仍待实施。
- 《建设工程施工合同（示范文本）》等 3 项资料未收录，详见 `knowledge/legal/索引.md`。
- 默认OCR已按ADR-0008采用中英文Tesseract端口、存储提供S3和本地开发适配；首选模型、生产服务和部署环境仍待确定。
- 当前方案不安装或下载BGE/PaddleOCR。百炼模型为供应商托管且权重/Tokenizer修订无可固定身份；DEC-002 的一次本地合成数据授权已消耗，任何后续真实模型调用、外发真实数据或公网部署均未授权。TASK-0022 只获准对用户指定的真实文件进行本机离线处理；真实 Qwen 外发仍须 DEC-005 批准。跨进程预算账本、生产级模型审计及云端质量评测需后续独立决策。

## 历史待决策记录（截至 2026-10-15；D1—D4 当前状态见文首）

- DEC-001：首个部署目标（本地 Docker Compose、云主机或 Kubernetes）。
- DEC-002：已批准 TASK-0021 一次合成数据演示；生产模型、真实业务数据处理与部署约束仍待决策。
- DEC-003：Tesseract为首期实现；生产扫描件性能预算与复杂中文版面效果待评估。
- DEC-004：前端技术栈与企业OIDC集成；首期本地认证已按ADR-0007落地。
- DEC-005：单份真实招标文件受控 Qwen 评测外发授权；当前仅为 proposed，待用户明确批准。

## 数据与迁移

- 数据库迁移版本：202610151000（TASK-0018解析引擎/模型/参数和容器身份来源追溯，位于202610141900 TASK-0010报告制品迁移之后）；显式执行，API不自动建表，回滚按迁移逆序删除新增结构。
- 契约集合版本：`v1alpha3`；事件信封和模型profile示例维持各自v1alpha1，详见contracts/VERSION.md。
- 生产数据：无。


## 历史分支与审查基线（截至 2026-10-14）

- 2026-10-14用户新指令覆盖之前的恢复分支限制：实现已保全迁移到work/TASK-0006；git fetch origin main核对最新main=bd2da2da984b6d1c34f3cfdb7da69e21661523be，当前任务分支已包含该提交。无force push/reset --hard，恢复分支和保全stash保留。
- 用户本次指令由ADR-0011记录，撤销ADR-0009默认跨软件/独立代理关卡；现有实现/问题与法规ADR-0010 proposed保留。Codex按实际验收自行收尾，不能假称独立审查或自动关闭问题。
- 不恢复DeepSeek派工或自动代理审批。当前无额外代理运行；保留历史审查的真实发现作为问题清单。

当前TASK-0007验收源码236d2a6e231be030f719b0bbabc3f2b0a50039b3；本地Focused30、Full448/真实集成和远程38516913371适用作业全部成功，任务已完成并归档。TASK-0008验收源码`4d1f59f69143c63c7d4273958a12da19ecf5acdf`（归档前工程记录提交`5b9b9f1bf68b245abb05b75cd855d07d30497d2a`）从归档提交`6edea37c071cfcec6cf8354b9d74f92fbcaba0a5`创建并包含TASK-0007验收源码；原stash@{0}仍保留。Focused54项、Full487项、真实本机后端/身份检查及源码提交远程CI运行`38521959503`（impact/baseline/postgres/ingestion/verify-required全部success）均通过。TASK0008-001/002按正式验收条件完成并归档；详见`docs/development/TASK-0008-validation.md`。生产预算仅实现单进程原子参考ledger，不能支持多进程生产一致性；DEC-002待批准、生产路由保持禁用，真实在线供应商调用未执行。TASK-0009源码`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`验收通过；源码与验证记录提交远程CI由用户确认成功，归档提交远程CI待核验。TASK-0010源码候选ab878ecd9f5df5d60ea4e27fe7edc451246ca75e本地验收通过，远程CI待执行。
