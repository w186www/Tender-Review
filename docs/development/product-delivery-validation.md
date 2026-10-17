# 产品交付单元验证记录

本文件只保存 U01—U16 的单元验收证据和历史 G3 报告；当前进度唯一摘要见 `PROJECT_STATE.md`，机读依赖见 `roadmap.yaml`。

## U01｜统一实施基线、任务归属和有效状态

正式 TASK：TASK-0028（`TASK0028-001`）

实际工作目录：`D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`

开始分支/HEAD：`work/TASK-0027` / `9e1a5840970f2c61b8558cf87e8f57398baf80c2`

结束分支/HEAD：`work/TASK-0027` / `9e1a5840970f2c61b8558cf87e8f57398baf80c2`（未提交）

### 1. 本次完成

- 核对本地、远端跟踪分支、当前 HEAD 和工作区；未切换分支、未 reset、未 stash、未清理成果。
- 开始前仅有三个未跟踪用户成果：
  - `docs/development/luna-execution-entry.md` SHA-256 `BF4AADCDF9A3D91DB4D0A23C4787C0F7FAF899FD41FB39C7F35C489F90F94195`
  - `docs/development/product-delivery-plan.md` SHA-256 `15DAFDD856AE13B6376238487A726A296DF596822205FDD386D47977A8FC664A`
  - `question.txt` SHA-256 `DAB6DC7FBA01721398735A45A985712414B0C6504919B2857ED32A287D1561ED`
  三者均未覆盖或移动。
- 检查正式任务：TASK-0019 `blocked`、TASK-0022 `in_progress`、TASK-0027 `in_progress`、TASK-0012/0013/0014 `planned`。保留这些状态及原局部验收范围；历史 TASK-0027 第七轮交付证据已完成，但其产品化遗留仍需 U02/U10/U11 收尾。
- 未发现同责任任务，登记 TASK-0028（产品执行、授权与恢复一致性）和 TASK-0029（审查内核、证据与报告闭环）。U01—U16 到正式 TASK 的映射和依赖写入 `roadmap.yaml`；D1—D4 按具体活动阻塞，不将单元整体误标为不可执行。
- 整合候选 `origin/integration/TASK-0027-main-20261017`（`b34470921fd19c74342416585c18bd26f69a2c3a`）的父提交是 `origin/main`（`79230861948574b5bc2161bc0c560a6873cc7b48`）和当前交付 HEAD（`9e1a5840970f2c61b8558cf87e8f57398baf80c2`）。相对交付 HEAD 只有 `PROJECT_STATE.md`、`README.md`、`docs/index.md` 三项差异；该候选没有本轮重新核验的 CI 证据。它仅是 remote-tracking ref，本地没有对应分支，本轮不创建分支、不合并、不推送。
- 依赖复用：使用项目 `.venv\Scripts\python.exe`；在 `PYTHONPATH=src` 下导入的模块来自当前目录 `src\bidding_compliance`。未安装 editable 包或其他 Python 依赖。复用既有 `src/frontend/node_modules`，Node 为 `v24.14.0`；未运行 npm 安装。

### 2. 实际变更

- `docs/development/roadmap.yaml`：增加 U01—U16 单元、TASK 映射、依赖与局部决策阻塞；增加产品化里程碑 P1。
- `docs/development/roadmap.md`：记录产品单元顺序、任务映射、D1—D4 边界，并修正产品级验收口径。
- 新增 `tasks/active/TASK-0028-product-execution-consistency.yaml` 与 `tasks/active/TASK-0029-product-review-evidence-closure.yaml`。
- `scripts/verify_contracts.py`、`tests/test_repository_checks.py`：检查产品单元 ID 完整性、任务映射和依赖图，避免路线图缺项或环。
- 更新 `docs/index.md`、`PROJECT_STATE.md`、`CHANGELOG.md` 中过时的有效状态描述。
- 未改 contracts 的产品运行时契约、源码、数据库、法规数据、模型配置、私有文件或部署配置。没有新增 ADR；U01 仅落实已采纳规划的任务治理，不把规划写成已批准架构 ADR。

### 3. 设计与授权

- 依据：用户采纳的 `docs/development/product-delivery-plan.md`、仓库 `AGENTS.md`、现有 roadmap/任务 Schema、ADR-0011 单 Codex规则。
- 产品规划本身不构成 D1—D4 决策、真实调用、数据外发或线上操作授权。本轮未进行这些活动。
- 既有 DEC-002/DEC-007 批准仅按其原范围保留，不扩展额度或用途。

### 4. 验证

- 按官方 Full 脚本 `./scripts/verify.ps1` 验证，复用现有 `.venv` 与 `src/frontend/node_modules`，没有安装依赖。
- 首次在默认 Windows 沙箱执行时，阶段 5 的两个既有 `test_real_corpus_fresh_checkout_preserves_hashes_and_locators` 参数化用例在本地 `git clone --no-local` 创建 MSYS 对象时遇到 `NtCreateDirectoryObject ... 0xC0000022`；前四阶段通过，该运行不能作为 Full 通过证据。获准提升本地验证权限后，在同一工作区、同一源码重跑官方 Full，全部七阶段通过：阶段 1 契约/仓库检查通过；阶段 2 Ruff `All checks passed!`；阶段 3 Mypy `Success: no issues found in 104 source files`；阶段 4 前端契约生成、Bi​​ome（23 文件）、TypeScript、Vitest（14/14）和 Vite build 通过；阶段 5 `823 passed, 2 warnings in 489.93s`；阶段 6 回环 HTTP 健康检查与请求 ID 检查通过；阶段 7 鉴权、项目生命周期及会话撤销检查通过。
- 阶段 5 的两项 warning 是既有 pypdf `add_js` 弃用提示，分别来自 `tests/test_ingestion.py` 和 `tests/test_legal_sources.py`；未因此放宽检查。成功的提升权限运行是 U01 的正式 Full 证据。
- Full 后仅调整路线图和状态/记录元数据；官方 `./scripts/verify.ps1 -Mode Quick` 退出码 0，契约、正反例、State 生成、任务证据及秘密扫描通过，不运行 Pytest/服务启动。该 Quick 对应状态记录更新前的 U01 实施版本。

### 5. 集成

- 所有新增修改均留在 `work/TASK-0027` 工作区，未暂存、未提交、未推送、未创建 PR、未合并、未部署。
- 原用户三份未跟踪成果保留为未跟踪；没有 worktree/目录创建或依赖安装。

### 6. 风险与恢复

- 新增的路线图校验可能暴露原任务映射缺失或产品依赖环；校验失败时修正路线图数据，不放宽验证器。
- 没有新外发、模型调用、预算预留或生产数据变更。
- 本轮变更均为路线图、任务和验证代码；可通过恢复这些文件的提交前版本回退，不涉及不可逆迁移。

### 7. 结论

- U01 的基线核对、状态整理、任务归属、路线图映射及成果保全已实施；官方 Full 七阶段通过，局部验收 `TASK0028-001` 的证据可查。
- 用户独立验收尚未进行。

### 8. 下一步

- U01 已完成；U02 已开始。冻结共享状态、调用、执行身份、授权、证据和报告语义及兼容策略，并为契约提供正反例与历史兼容测试。
- 后续按 `roadmap.yaml` 的单元依赖推进；D1—D4 只阻断对应活动。

### 9. 环境复用

- Python：复用 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027\.venv`。
- 前端：复用 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027\src\frontend\node_modules`。
- 未安装或修复任何依赖。

## U02｜冻结产品契约、状态语义和兼容策略

正式 TASK：TASK-0028（`TASK0028-002`）、TASK-0029（`TASK0029-001`）

实际工作目录：`D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`

开始分支/HEAD：`work/TASK-0027` / `9e1a5840970f2c61b8558cf87e8f57398baf80c2`

结束分支/HEAD：`work/TASK-0027` / `9e1a5840970f2c61b8558cf87e8f57398baf80c2`（未提交）

### 1. 本次完成

- 建立 15 FR、14 SEC、12 NFR、12 AC 到 U01—U16、再到 G3 证据记录的机读追踪映射；仓库 Quick 检查逐项验证 ID 完整、单元合法及 G3 文件存在。
- 冻结文档/摄取作业/审查运行/业务完整度/覆盖/人工决定/报告的独立语义和转换，明确零候选、部分完成、失败/取消、待人工、未知调用、覆盖缺口、截断/饱和、执行身份/撤权、证据资格和版本化兼容规则。
- 新增 `product-review-execution.v1alpha1` 包络契约；报告只新增 `task0010-report.v3` 摘要，保留 v1/v2；现有 `ComplianceReviewState v1alpha2` 与数据库迁移链不改写。
- 将已实现的逐文件外发授权端点登记进 OpenAPI 0.8.0，请求无 caller-supplied 哈希/actor，确认字段必须为 true；记录由服务端根据已鉴权文档哈希返回。
- 形成 ADR-0019 正式设计；本地契约正反例覆盖零候选完整发布、未知调用不得完整、覆盖不全不可标完整、授权请求不得自报哈希及历史报告兼容。

### 2. 实际变更

- 新增：`contracts/schemas/product-review-execution.schema.json`、`docs/development/product-contract-baseline.md`、`docs/development/product-delivery-traceability.yaml`、`docs/decisions/ADR-0019-product-execution-and-review-contracts.md`。
- 修改：`contracts/openapi.yaml`、`contracts/schemas/review-report.schema.json`、`contracts/examples/manifest.yaml`、`contracts/VERSION.md`、`scripts/verify_contracts.py`、`tests/test_repository_checks.py`、`src/frontend/src/api/schema.d.ts`、`docs/architecture/langgraph.md`、`docs/index.md`、`PROJECT_STATE.md`、`CHANGELOG.md`、两个新 TASK 的 U02 evidence。
- 没有改数据库迁移、生成 State、运行时代码、法规资料/标签、调用/预算账本、配置、部署或历史报告；迁移责任和历史数据兼容在契约中明确留给 U04/U05。

### 3. 设计与授权

- 依据用户采纳的产品交付计划 E1、ADR-0002/0004/0005/0007/0010/0013/0017/0018 和现有契约；新增 ADR-0019。
- D1—D4 仍未新增批准。本单元仅做本地设计和合成契约验证；未调用模型/Embedding/OCR、未外发正文、未变更线上或部署，没有迁移历史数据、预算或法规状态。
- DEC-002/005/006/007 的历史记录不扩展为本次或后续真实调用授权。

### 4. 验证

- `.\\scripts\\verify.ps1 -Mode Quick`：退出码 0；包含 OpenAPI/JSON Schema、全部契约正反例、追踪 ID、State 生成、任务状态/证据与秘密检查，不含运行时测试/服务启动。
- `npm run api:generate`（复用 Node v24.14.0 与既有 `src/frontend/node_modules`）：成功生成 `src/frontend/src/api/schema.d.ts`。
- `npm run api:check`：通过，生成 TypeScript 与 OpenAPI 0.8.0 一致。
- 官方 Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_contract_validation.py','tests/test_repository_checks.py')` 通过；Ruff、104 个源文件 Mypy、前端契约/lint/typecheck、Vitest 14/14、Vite build 通过；所选后端文件 `104 passed in 100.13s`。首次 Focused 指出测试中一行超长，按 Ruff 结果做局部格式修正后通过。
- 官方 Full：`./scripts/verify.ps1 -Mode Full` 退出码 0，阶段 1—7 全部通过。阶段 1 契约/示例/State/任务证据检查通过；阶段 2 Ruff 通过；阶段 3 Mypy 104 个源文件通过；阶段 4 OpenAPI 客户端一致、Biome 23 文件、TypeScript、Vitest 14/14、生产构建通过；阶段 5 `835 passed, 2 warnings in 522.83s`；阶段 6 回环 HTTP health=200、404 和 request ID 关联通过；阶段 7 登录、项目创建/读取/版本及登出撤销通过。两条既有 pypdf `add_js` 弃用 warning 来自 `tests/test_ingestion.py` 和 `tests/test_legal_sources.py`。
- Full 的首轮候选发现一项契约边界用例只调用 JSON Schema、未并行执行跨字段语义断言；测试已修正为同时验证 schema 与语义规则，之后 Focused 与最终 Full 均通过。
- `git diff --check`：通过。U01 三个原始用户未跟踪文件 SHA-256 复核未变。Full 后只有路线图、项目状态、变更日志和验证记录等状态/证据元数据变化；代码、契约、依赖、配置、测试和验证脚本均未改变，随后以 Quick 验证这些记录更新。

### 5. 集成

- 仍在原 `work/TASK-0027` 工作区，未暂存、提交、推送、创建 PR、合并或部署；未创建目录/worktree。
- 合成契约样例仅验证结构与拒绝条件，不构成法律/模型质量结论。用户独立验收尚未进行。

### 6. 风险与恢复

- 新 envelope/report v3 尚无运行时生产者；后续 U04/U05/U10/U12 必须按同版本实现，并用兼容测试证明旧格式保持原义。
- PostgreSQL 新字段/表及历史 JSONL/SQLite 导入尚未实施；任何生产历史账本/Checkpoint迁移都不在本单元发生。
- 外发授权 endpoint 的 OpenAPI 仅反映现有代码，OpenAPI 登记本身不表示当前部署开启外发或取得 D3 批准。

### 7. 结论

- U02 的状态、执行身份、授权、模型调用未知、覆盖、证据和报告版本契约已形成；兼容例、机读追踪和正式 TASK 局部证据均已登记，官方 Full 七阶段全部通过，U02 完成。该结论仅限开发基线，不代表业务/安全/发布或最终产品验收。

### 8. 下一步

- U02 已完成；按依赖进入 U03。继续核验和复用 TASK-0019 的本地合成评测资产，先验证其冻结来源与摘要，再在正式任务允许范围内接续；D1/D2 仅阻止支持范围/容量签署和专家法律/风险金标签署，TASK-0019 原 worktree 与未提交成果保持不变。

## U03｜冻结业务样本与可重复评测（进行中）

正式责任：TASK-0019（原任务保持 `blocked`）与 TASK-0013（产品级最终验收仍为 `planned`）。本阶段只推进 U02 后不依赖 D1/D2 的本地合成准备。

### 已完成的本轮核对

- 检查了 TASK-0019 暂停记录、允许路径、原 SHA-256 清单、当前五个合成案例及原阈值；确认当前检查环境只包含固定 TASK-0027 checkout，记录中的原 `bidding-compliance-agent` 路径不可用，冻结评测器/测试/结果也未出现在当前目录。未改写原任务文件、原 worktree 或原阈值；未按哈希猜测重建资产。
- 2026-10-17 按用户许可只读检查已知 `_backups`：原 worktree 和当前 checkout 下均不存在该目录；父目录唯一备份 `D:\自由项目\招标审核\_backups\repo-20261017T081226Z.bundle` 的 refs 仅含 TASK-0027/main/integration，没有 TASK-0019 分支或冻结评测资产来源。bundle 未解包或导入；不再扩大搜索范围。
- 对当前五个案例复算 SHA-256，并在 `docs/development/product-evaluation-protocol.md` 登记输入含义、分区与状态。五个文件均声明 `synthetic: true`；因缺少裁定人、标签版本及理由，全部仅为开发候选，不称为专家金标，也不进入冻结验收/安全集或指标分母。
- D1/D2 只阻止支持范围/容量最终承诺和专业法律/风险标签署；冻结评测器来源不可用是另一个本地复用限制。没有新增模型调用、真实数据输入或法规结论。

### 验证与当前结论

- 本次为文档/样本身份记录，无运行时实现、契约、测试、配置、依赖或阈值变化；官方 `./scripts/verify.ps1 -Mode Quick` 退出码 0，契约、示例、State、任务证据、仓库与秘密检查通过；按文档范围未运行 Pytest 或服务启动。U03 当前目录仅含本次证据/状态记录变化，故 Quick 为对应档位。
- U03 部分完成，仍在进行：开发候选清单与标签边界已建立；冻结评测器来源恢复、可重复指标/差异报告、冻结验收/攻击分区、专家标签与最终范围签署未完成。未知原来源未被覆盖；后续可在来源可用时按哈希接续，其他 U04 等依赖 U02 的单元可继续。

### 2026-10-18 来源判断纠正（用户指出，只读核验）

用户指出 `D:\自由项目\招标审核\_backups\worktrees-uncommitted-20261017T080625Z	ask0019` 存在。此前“唯一已知备份 bundle 未找到来源”的结论只对 `repo-20261017T081226Z.bundle` 成立，遗漏了同目录的未提交工作树备份，现纠正：

| 类别 | 核验结果 |
|---|---|
| 评测工具/测试 | `evaluate_review_capabilities.py` SHA-256 `7b2c2b0673b3f28c1c0cd7c33aea32163e4c42e3c3ea071428ad51307da5712e`；`test_review_capability_evaluation.py` `e59247e9a47b84b8cd4c25a77b5a2405fb1fda714122003b2893c25a8cafd640`；均与 `TASK-0019-paused-20261015.md` 一致 |
| 原结果/TASK 文件 | 两份 capability baseline 结果 `9031…`/`1696…` 与原 TASK YAML `faf9…` 均与暂停清单一致 |
| 五个黄金案例 | 当前为 CRLF 检出；LF 规范化后的逐文件哈希及清单哈希 `ea888e9f9a587b478f3ac2461d00cb4ce45fd1320a47c2c2d2bf5b0ce0762052` 与原基线完全一致 |
| 阈值/OCR | 阈值 LF 规范化 `c6ff964…` 与原基线一致；OCR 报告原始 SHA-256 `045075768…` 与原基线一致 |
| 法规检索 | 查询集/适用性/快照数据在当前仓库；当前 `character-baseline-20261015.json` 的核心指标（Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中）与原基线一致；原 `.verification/task0019-legal/character-baseline-20261015.json`（`47df…`）文件缺失 |
| 专家确认标签 | 原结果明确 `expert_confirmed_risks=0`、`expert_confirmed_nonrisks=0`、`candidate_unconfirmed=5`；从未具备专家标签 |

**只读复用验证：** 用备份中的原脚本（哈希未变）加载当前仓库资产，输出到 `.verification/task0019-reuse/current-baseline-readonly.json`；`external_model_calls=0`、fixture 期望模式 5/5、引文/定位 7/7、专家确认 0、法规指标与原基线一致。未覆盖原结果、未复制评测器进正式路径、未修改备份/阈值/任务状态。

**分类与最小复用方案：**

1. **已找回且来源匹配**：评测脚本、测试、两份结果、原 TASK 文件、五个合成案例、阈值、OCR 报告、法规检索数据与等价报告。
2. **尚缺**：原 `.verification/task0019-legal/character-baseline-20261015.json` 精确文件；当前 CRLF 检出导致原始字节清单/阈值哈希与历史 LF 不同。前者可在获准恢复时用现有离线法规检索入口重新生成到**新路径**，不覆盖旧结果；后者用 LF 规范化视图或干净 LF 检出复现。
3. **从未具备**：专家风险/非风险标签；五个案例仍是 `development_candidate`，风险 precision/recall 为 `not_measured`，需 D2 指定裁定人。

**边界与下一步：** TASK-0019 仍 `blocked`，本次没有解包/导入/覆盖备份、没有解除暂停、没有改状态或降低验收；U03 仍为 `in_progress`。最小复用限定为只读验证；正式恢复需用户明确授权并按原任务允许路径接入原脚本/测试、记录新资产身份。此次为文档/证据纠正，未改代码/契约/测试，未因来源核对重跑 Full；后续按用户要求只做必要的 Quick 和证据记录。

## U04｜持久调度、重启接管与调用恢复（进行中）

正式 TASK：TASK-0028（`TASK0028-003`）；前置 U02 已完成。

### 1. 本次完成

- 审查 API 现改为持久登记 `start/resume/retry` 意图并及时返回；部署新增独立 `review-worker`。Worker 从 PostgreSQL 原子领取排队任务或过期 lease，递增执行代次并续租；旧执行身份不能写入已被接管的运行。
- Checkpoint 按持久队列动作恢复；重试使用不同模型调用身份。模型调用在出站前登记，成功响应与 artifact 持久化后才交给图执行；重启后可复用成功响应。结果可能已外发但未落库时标记为 `unknown`，不自动重放。
- 增加 `review_model_call` 迁移、RLS/actor policy 与运行角色 grants；部署 E2E 接入 Worker，并增加 PostgreSQL 并发领取、过期 lease 接管、旧身份 fencing、取消竞争及未知调用不重放的专项验证入口。
- 补齐模型网关的租户/审查任务身份检查；不匹配的请求在模型调用和账本写入前拒绝。

### 2. 实际变更

- 主要实现：`src/bidding_compliance/services/review_engine.py`、`services/persisted_model_gateway.py`、`services/review_persistence.py`、`domain/identity.py`、`services/legal.py`、`api/reviews.py`、`graph/review.py`、`persistence/models.py`。
- 数据库/部署/专项：`contracts/database/migrations/202610171000_task0028_durable_review_queue.py`、`docker-compose.demo.yml`、`scripts/run_review_worker.py`、`scripts/run_task0011_e2e.py`、`scripts/check_review_engine.py`、`scripts/assert_task0011_e2e.py`。
- 测试适配：`tests/test_task0027_timeout_recovery.py`、`tests/test_task0027_needs_review_repair.py`、`tests/test_task0028_persisted_model_gateway.py`、`tests/test_task0027_deploy_compose.py`、`tests/test_semantic_batching.py`、`src/frontend/e2e/workbench.spec.ts`。新增 ADR-0020，更新数据库迁移与 demo 部署说明。
- 没有调用供应商、发送真实内容、操作线上、改账本或启动/删除服务；没有拉取 Docker 镜像或安装依赖。

### 3. 设计与授权

- 依据 U02 的冻结执行/调用契约及 U04 的实施顺序，选择 PostgreSQL 持久队列和带 fencing 的 lease；ADR-0020 记录方案、未知调用和旧 Worker 写入防护。
- D3 的真实供应商调用、真实内容外发及故障演练未获批准，未执行。合成离线实现与测试不依赖该批准。

### 4. 验证

- 官方 Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_identity_projects.py','tests/test_task0027_external_authorization_api.py','tests/test_task0027_timeout_recovery.py','tests/test_task0027_needs_review_repair.py','tests/test_task0022_zero_candidate_review.py')`，退出码 0；所选后端测试 `49 passed in 220.39s`。同次 Quick、Ruff、Mypy（105 个源文件）、前端生成契约/lint/typecheck、Vitest（14/14）及生产构建均通过。
- Focused 包含 SQLite migration 与 ORM schema 一致性检查；此前迭代中该检查发现 SQLite 不能原地增删 CHECK constraint，已改用 batch migration 并保留既有约束后通过。
- 补充官方 Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_task0028_persisted_model_gateway.py')` 退出码 0，`7 passed in 6.03s`；Ruff/Mypy/前端检查亦通过。该合成 SQLite 测试覆盖成功响应持久化与重启复用、未知结果禁止重放、租户/任务身份拒绝、旧 generation fencing、过期 claim/续租、取消竞争及未决调用令运行失败。它不证明 PostgreSQL `SKIP LOCKED` 并发/部署行为。
- 扩展该测试文件期间的一次多文件 Focused 曾为 46 passed、3 个 fixture setup errors；修复 fixture 显式导入和父记录写入顺序后，当前新测试文件官方 Focused 7/7 通过。既有 U04 Focused `49 passed in 220.39s` 是较早代码候选证据，不覆盖随后增加的 gateway fencing 断言；两次证据分别记载。
- （2026-10-17 用户授权前的状态）PostgreSQL 部署入口专项尚未执行；当时沙箱检查无法连 Docker Engine，专项证据缺失。以下本机 Docker 补验取代此项“未执行”结论，不改变其历史记录。
- 官方 Focused（本轮修复的 `tests/test_semantic_batching.py` 与 `tests/test_task0027_deploy_compose.py`）退出码 0，所选后端 `16 passed in 3.70s`；同次 Quick、Ruff、Mypy（105 个源文件）、前端 OpenAPI/Biome/TypeScript/Vitest（14/14）及 Vite build 均通过。
- 此前普通沙箱权限下的 Full 首轮为 `834 passed, 9 failed, 2 warnings`：5 项语义批处理测试替身缺 `retry_count`、2 项部署断言仍假设只有 API 调用模型、2 项临时 Git clone 被 Windows 沙箱对象创建权限阻断。先修复测试替身与 API/review-worker Compose 期望，Focused 通过后，在允许 Full 临时 Git clone 写入的本机文件系统权限下完成以下最终 Full；未放宽校验或验证门禁。
- （同一工作区较早的候选）此前 Full `843 passed, 2 warnings in 516.10s` 通过；以下新的最终 Full 覆盖本次脚本、应用、前端 E2E 和 runner 变更。

### 5. 集成与成果保护

- 所有变更留在固定 `work/TASK-0027` 工作区，未暂存/提交/推送/合并/部署；复用现有 `.venv` 与 `src/frontend/node_modules`。用户的 `luna-execution-entry.md`、`product-delivery-plan.md` 和 `question.txt` 未修改。

### 6. 风险与恢复

- 本机 Docker 现已按用户授权用于合成数据专项；真实外发与供应商调用仍需独立 D3 批准。U04 的取消竞争目前有 PostgreSQL 服务层证据，但 API/OpenAPI 没有取消操作，因此部署入口取消竞争仍未验证。
- 回退或替换执行器前须按规划停止领取并保留 Checkpoint/调用记录；本次没有做迁移数据回退或数据清理。

### 7. 结论

- （授权前结论）U04 因缺 PostgreSQL 部署入口证据而保持 `in_progress`；本节末尾补验更新该结论。

### 8. 下一步

- U05 仍依赖 U04 完成。U07 的本地生命周期与结论依据边界已推进；D2 内容核验与人工绑定签署仍受阻。

### 2026-10-17 Docker 专项补验与当前 G3 结论

**执行单元/TASK：** U04 / TASK-0028（TASK0028-003）；U03 / TASK-0019、TASK-0013 的来源恢复继续部分完成；U07 / TASK-0029 继续进行 D2 以外的本地工程验证。U05 未开始，roadmap 前置 U04 尚未完成。

**目录、分支、HEAD 与未提交归属：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；HEAD `9e1a5840970f2c61b8558cf87e8f57398baf80c2`。所有既有未提交改动保留。用户的 `docs/development/luna-execution-entry.md`、`docs/development/product-delivery-plan.md`、`question.txt` SHA-256 仍分别为 `BF4AADCDF9A3D91DB4D0A23C4787C0F7FAF899FD41FB39C7F35C489F90F94195`、`15DAFDD856AE13B6376238487A726A296DF596822205FDD386D47977A8FC664A`、`DAB6DC7FBA01721398735A45A985712414B0C6504919B2857ED32A287D1561ED`。本次只在原目录写代码与正式状态/证据，无新 worktree、clone 或开发目录。

**Docker/环境：** 实际连通 Docker Engine 29.2.1，Linux 容器模式；复用已有 PostgreSQL 16、MinIO、ClamAV 和 parser 镜像，没有拉取镜像或安装依赖。入口 `scripts/run_task0011_e2e.py` 生成本轮唯一命名、标记的临时容器与合成 DOCX；最终容器退出后自动移除。检查确认没有本轮标记容器遗留，既有 `tender-review-demo` 容器、卷及数据未更改。服务只监听回环；环境清除了真实供应商凭据，模型适配器明确为 `scripts/check_review_engine.py::OfflineReviewGateway`。

**重用证据与新运行：** 重用 U04 既有 Focused 证据；针对相关测试文件的一次 Focused 命令 `./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_task0027_timeout_recovery.py','tests/test_task0028_persisted_model_gateway.py','tests/test_task0027_deploy_compose.py')` 退出码 0，后端 18 passed，前端 Vitest 14/14、生产构建、Ruff 与 Mypy 105 源文件均通过；此 Focused 运行早于最后两项 E2E runner 调整，后续 Full 覆盖了最终候选。新运行命令 `PYTHONPATH=src ./.venv/Scripts/python.exe scripts/run_task0011_e2e.py`；结果目录 `.verification/task0011-e2e-177be086efca486583c486953f77112c/`，`run.json` 为最终结构化记录，`playwright-junit.xml` 为浏览器报告。官方最终候选 `./scripts/verify.ps1 -Mode Full` 七阶段通过：契约/状态/仓库、Ruff、Mypy、前端生成/静态/类型/单测/构建通过；后端 `843 passed, 2 warnings in 544.05s`；HTTP health=200/404 和 request ID 检查通过；登录、项目创建/读取/版本、登出撤销通过。两个 warning 是既有 pypdf `add_js` deprecation（`tests/test_ingestion.py`、`tests/test_legal_sources.py`）。

**真实 PostgreSQL/部署入口覆盖：**

- 持久登记、领取与独立 worker：真实 API `POST /projects/{projectId}/reviews` 返回 202 queued；两个独立 `run_review_worker.py` 进程运行；浏览器重复 POST 重放同一 Idempotency-Key/body，响应的 task/run ID 相同。正式成功流由 worker 推进到 `waiting_human`，浏览器保存决定后通过 API 排队 resume。
- 重试：共享一次性合成 timeout 导致首轮 run 持久失败；浏览器经真实 retry API 重试，`retry_count=1` 后完成；模型调用账本保留 unknown 原调用及 retry 代次成功响应，报告校验成功响应引用/哈希。
- Checkpoint/进程重启与响应复用：在真实 `waiting_human` 持久中断时停掉原 worker，提交 resume 后启动新 worker；run generation 从 2 到 3 并发布结果，Checkpoint task/run 不变，模型调用 ID 集合在重启前后相同。
- 真实 lease 到期与旧代次 fencing：在真实 PostgreSQL 持有 generation 1 lease 的部署 worker gate 前停止领取并将测试 lease 戳记到期；新 worker 经部署 claim 入口取得 generation 2，调用成功到 `waiting_human`。释放旧 generation worker 后，其写入被拒；状态、调用 ID、响应引用及哈希保持与 generation 2 检查点相同。
- unknown 不自动重放：在模型调用已持久 `dispatched` 后终止原 worker，令 lease 到期并启动新 worker；run 进入 `failed/model_call_outcome_unknown`，唯一调用为 unknown，无 response ref/hash，未重新派发。
- PostgreSQL 补充探针记录并发 claim 2 个竞争者中恰 1 个 winner、generation 2 接管、旧身份 fencing、服务层取消保留、unknown 不重放。并发 claim 与取消该两项使用真实 PostgreSQL 与验证辅助函数；未将它们表述为 API 端到端结果。

**未满足条件与状态边界：** 当前 `src/bidding_compliance/api/reviews.py` 和 `contracts/openapi.yaml` 均无 review cancel operation；因此取消竞争只有实际 PostgreSQL/服务层辅助验证，尚未经过正式部署入口。按任务要求不以内部方法替代部署入口检查，`TASK0028-003` evidence 仍保持空，U04 保持 `in_progress`，U05 不启动。D3 真实模型调用、业务文件外发和生产故障演练未获本次授权，也未执行；这些仅阻塞其对应活动，不影响以上合成离线结果。未更改正式契约、Schema 或 ADR 来迁就测试。

**最终候选指纹：** 39 个变更的实现/契约/测试/部署相关文件，按路径排序后将“相对路径、制表符、该文件 SHA-256”逐行以 UTF-8/LF 组成清单，再对清单计算 SHA-256，摘要为 `c644eef7dd61473300d93d5bb8d44f17fb8e84cb5e932c9b7f93b53b7191e70b`。这识别当前工作区候选，不代表提交或集成。

**U03 与 U07：** TASK-0019 源目录仍不存在；父 `_backups` 唯一 bundle 不含 TASK-0019 refs/冻结资产。U03 仅保留五个候选案例清点和来源查找证据，不重建评测器、不更改标签。U07 本地规则/法规/配置生命周期与“未签署 binding 不支持违法结论”的 Focused 及最终 Full 通过；D2 专业内容核验和 binding 签署仍未批准，U07 `in_progress`。

**结论和交接：** U04 本地代码实现与 PostgreSQL/独立 Worker 专项通过；TASK0028-003 因取消部署入口未验证而部分完成，不能标记 TASK 完成。没有提交、推送、PR、合并、部署或用户独立验收。Full 后只更新 TASK/G3/路线图/状态/变更记录；随后 `./scripts/verify.ps1 -Mode Quick` 退出码 0，contracts/examples/generated State/scoped task evidence 与仓库/秘密检查通过；`git diff --check` 退出码 0。

## U07｜法规、规则与配置可信生命周期（进行中）

正式 TASK：TASK-0029（`TASK0029-003`）；前置 U02 已完成。

### 1. 本次完成

- 复用既有法规全局管理：独立运维 grant、每次操作身份/撤权复核、CAS 草稿与发布序列、内容/索引哈希、不可变 revision/publication、停用与新发布回退、历史证据按冻结 bytes 重现。
- 复用既有审查配置发布：配置快照绑定法规 publication、五类 Skill 与语义版本、rule 版本、ruleset SHA-256 及模型策略；发布、停用、回退保留历史，运行冻结配置不跟随当前发布漂移。Prompt 请求版本和内容 SHA-256 在运行快照中单独固定。
- 修正结论边界：即使检索条文当前已核验且适用，只要没有经过人工确认的 rule-law binding，该条文仍显示为法律参考，不进入 finding 的正式支持证据；finding 标记证据不足，模型输出的违法/处罚断言被替换为待人工核验说明。
- 规则定义仍是五类已有版本化代码规则；正反样本由 `tests/test_rules_skills.py` 覆盖。没有为任何规则登记未经 D2 核验的法条来源或规则—法条绑定。

### 2. 实际变更

- 实现：`src/bidding_compliance/graph/review.py` 将无人工 rule-law binding 的已核验引文降为 reference-only。
- 回归测试：`tests/test_legal_evidence_classification.py` 覆盖未核验法规、已核验但未绑定法规、模型仍声称违法及损坏/跨版本引用；`tests/test_llm_candidate_discovery.py` 的共享 graph harness 增加 U04 引入的 `retry_count` 身份字段。
- 正式记录：`docs/development/roadmap.yaml` 标记 U07 `in_progress`，本记录、`PROJECT_STATE.md`、`docs/development/roadmap.md`、`docs/index.md`、`CHANGELOG.md` 与 TASK-0029 handoff notes 同步实际状态。
- 未修改 `knowledge/legal/**`、核验来源、法规发布状态、规则版本、数据库 Schema 或模型配置；未外发内容、调用模型或操作线上。

### 3. 设计与授权

- 依据 U07 生命周期计划、ADR-0011/0012、法规模块运行规则、U02 执行/证据契约及现有法规管理和审查配置实现。
- D2 尚未指定法规内容核验人与规则—法规绑定裁定人。未批量改 `verified`、未新增法条支持结论；人工 binding registry/签署和承诺范围内的内容核验仍未完成。此限制不阻止本地引用展示与“无 binding 不作违法结论”的合成回归。

### 4. 验证

- 官方 Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_legal_evidence_classification.py','tests/test_legal_publications.py','tests/test_review_configurations.py','tests/test_legal_lifecycle.py','tests/test_legal_authorization.py','tests/test_legal_applicability.py','tests/test_legal_evidence.py','tests/test_rules_skills.py','tests/test_llm_candidate_discovery.py')`，退出码 0；所选后端测试 `179 passed in 73.51s`。同次 Quick、Ruff、Mypy（105 个源文件）、前端 OpenAPI 客户端一致性/Biome/TypeScript、Vitest（14/14）及 Vite build 均通过。
- 首轮 Focused 暴露共享测试 harness 缺少 U04 新增的 `retry_count` 字段，补齐测试替身；第二轮唯一失败为免责声明用词被测试过度断言，收窄断言后上述官方 Focused 通过。未更改生产语义来迎合测试。
- 当前交付候选的官方 Full 已通过（U04 验证记录）；该结果不构成 D2 法规内容核验或规则—法规人工签署。

### 5. 集成、风险与结论

- 变更留在原固定 `work/TASK-0027` 工作区；未暂存/提交/推送/合并/部署。既有 `.venv` 与前端 `node_modules` 复用。
- U07 的法规与配置技术生命周期已有实现证据；没有规则—法规人工签署、承诺范围内内容核验或来源覆盖矩阵的批准结论，因此 **U07 仍为 `in_progress`**。`TASK0029-003` 最终 evidence 保持空，D2 只阻止上述内容/签署活动。

### 6. 下一步

- 在 D2 仍未批准时，不登记实际规则—法条绑定；继续可执行的本地 U03/U04 工程工作。U09 依赖 U03/U05/U07，U05 仍等待 U04；D2 签署或相关前置未满足前不标完成。

## 2026-10-17 U04 取消入口补齐与完成 G3

**执行单元/TASK：** U04 / TASK-0028（`TASK0028-003`）完成；U05 / TASK-0028（`TASK0028-004`）保持 `planned`，尚未开始。U03 / TASK-0019、TASK-0013 的冻结来源缺口继续保持；U07 / TASK-0029 继续进行，D2 内容核验及规则—法规人工绑定未获批准。

**目录、分支、HEAD 与未提交归属：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；HEAD `9e1a5840970f2c61b8558cf87e8f57398baf80c2`。代码与契约保持未提交状态；本次没有 reset、清理、stash、clone 或 worktree。用户的 `docs/development/luna-execution-entry.md`、`docs/development/product-delivery-plan.md`、`question.txt` SHA-256 保持 `BF4AADCDF9A3D91DB4D0A23C4787C0F7FAF899FD41FB39C7F35C489F90F94195`、`15DAFDD856AE13B6376238487A726A296DF596822205FDD386D47977A8FC664A`、`DAB6DC7FBA01721398735A45A985712414B0C6504919B2857ED32A287D1561ED`。

**U04 代码实现与兼容性：** 新增 `POST /api/v1/review-tasks/{reviewTaskId}/runs/{runId}/cancel` 兼容操作，reviewer 鉴权后通过既有 `cancelled` 语义取消；重复 cancel 幂等、审计只写一次、清理当前 lease，已发布结果返回冲突。PostgreSQL 行锁使 cancel 与 resume/retry 串行，完成后的 worker 不能把 cancelled run 重新排队。OpenAPI 从 0.8.0 升为 0.9.0，契约集从 v1alpha4 升为 v1alpha5；属于新增路径/操作，无旧路径删除、响应重解释、数据库迁移或历史记录重写。`contracts/VERSION.md` 与产品契约基线记录了兼容说明；前端类型由生成器更新。

**Docker/真实组件环境：** Docker CLI 实际连接 Docker Engine 29.2.1，Linux 容器模式。复用本地 PostgreSQL 16 与已有 MinIO、ClamAV、parser 镜像；未拉取镜像、安装依赖或使用在线模型路由。专项入口使用本轮合成 DOCX、隔离 PostgreSQL/运行角色与仅回环服务，适配器明确为 `scripts/check_review_engine.py::OfflineReviewGateway`。运行后确认无本轮标记容器遗留；既有 `tender-review-demo` 容器和卷保留。无项目数据、密钥或模型请求外发。

**复用和新验证：** 新 Docker E2E 命令 `.\.venv\Scripts\python.exe scripts\run_task0011_e2e.py`（运行环境清除供应商凭据，`PYTHONPATH=src`）；通过，结构化证据目录 `.verification/task0011-e2e-9e0d7ada01494a0cab4c512522671699/`，`run.json` 标记 `status=passed`，5 个浏览器用例均通过、失败/错误/跳过均为 0。官方 Focused 命令 `.\scripts\verify.ps1 -Mode Focused -TestPaths @('tests/test_task0027_timeout_recovery.py','tests/test_task0028_persisted_model_gateway.py','tests/test_task0027_deploy_compose.py','tests/test_contract_validation.py','tests/test_repository_checks.py')` 通过（123 passed）；其后最终实现候选 `.\scripts\verify.ps1 -Mode Full` 七阶段通过：契约/示例/State/任务证据检查、Ruff、Mypy 105 源文件、前端 OpenAPI/静态/类型/14 个 Vitest/构建、后端 `844 passed, 2 warnings in 538.00s`、HTTP health=200/404+request id、登录/项目创建读取与版本/登出撤销。两项警告仍为既有 pypdf `add_js` 弃用提示。此前 Full 为 U04 代码候选执行，以下正式状态和 G3 文档变化不属于其代码输入。

**真实 PostgreSQL/部署调度入口逐项证据：**

- 持久登记/领取/独立执行：真实 API 登记得到 202 queued；两个独立 `run_review_worker.py` 进程竞争，部署 E2E 和 PostgreSQL 探针证明并发 claim 只有一个 winner。通过真实 API 对相同 Idempotency-Key/body 重复请求，task/run ID 不变。
- 到期接管/fencing：真实 PostgreSQL 中令首代 lease 到期，替换部署 worker 领取 generation 2 并保存成功响应；恢复旧 worker 后其写被拒，最终任务、调用 ID、响应引用/哈希保持新代次结果。
- Checkpoint/重启与成功调用复用：持久 `waiting_human` 时停止 worker，通过 API 排队 resume 后启动独立 worker；task/run/checkpoint 身份保留并发布。重启前后模型调用 ID 集合相同，成功响应复用而未重复发模型调用。
- 请求、重试及 unknown：浏览器重复请求保持幂等；合成 timeout 通过 retry API 建立新代次。已持久 dispatch 的调用在 worker 中断后变为 `model_call_outcome_unknown`，没有响应引用/哈希且未重放。
- 取消竞争：新增兼容 API 后，在运行 worker 进入受控 gate 时经部署 API cancel 得 HTTP 200、状态 `cancelled`、generation 1、lease 清空、恰有一条 cancel audit、模型调用数为 0；释放旧 worker 后写入遭 fencing。重复取消由真实鉴权 API 测试验证幂等及只记一次 audit。
- 可查证记录：`.verification/task0011-e2e-9e0d7ada01494a0cab4c512522671699/run.json`、`playwright-junit.xml`、`tests/test_task0027_timeout_recovery.py`、`scripts/assert_task0011_e2e.py`。SQLite/合成 Focused 仅作为补充，不替代上述 PostgreSQL 部署入口证明。

**风险、授权和恢复：** D3 的真实供应商调用、真实业务内容外发和生产故障演练未获授权且未执行；离线合成适配器不是供应商验收。D4 线上部署/切换未执行。OpenAPI 新增路径兼容但新客户端仍需服务端开放该路由；回退代码时先停止领取并按 ADR-0020 保留运行记录/Checkpoint，不能让旧 worker 恢复写入。本次取消 API 未新增数据库迁移，也没有回退/改写既有历史账本；没有自动清理既有服务/卷。

**U04 结论：** 本轮关闭此前取消入口缺口，`TASK0028-003` 的局部验收证据已经逐项登记，U04 从“代码已实现”升级为“真实组件专项通过、任务局部 AC 满足、单元 `completed`”。这些状态不代表提交、合并、部署、D3 真实模型验收、全局 AC 验收或用户独立验收。TASK-0028 总体仍 `in_progress`，因为 U05/TASK0028-004 未完成。

**下一单元：** U05 的 U02/U04 前置已满足，是路线图下一项；本轮在 U04 完成后停止，未开始 U05 实施。未来继续时依 TASK0028-004 核对租户/角色/资源权限矩阵、外发撤销再检查、PostgreSQL 原子预算预留/结算、故障下权限/授权/费用/审计同事务、历史 JSONL/SQLite ledger 迁移方案与隐私反例；不迁移/改写真实历史账本，不触发真实外发/供应商调用。U03 冻结来源不重搜、不重建；U07 继续 D2 以外的工程工作。

**本次结论范围：** 未暂存、提交、推送、创建 PR、合并、部署或完成用户独立验收。Docker 专项属于真实本地组件/部署入口集成验证；Full 属于官方工程门禁；二者证据分别记录，不能相互替代。状态/任务证据/G3 文档更新后，官方 `./scripts/verify.ps1 -Mode Quick` 退出码 0，`git diff --check` 退出码 0。

## U05｜租户执行授权、外发、预算与隐私一致性（2026-10-17，完成 G3）

**执行单元/TASK：** U05 / TASK-0028（`TASK0028-004`）。前置 U02、U04 已完成。

**目录、分支、HEAD 与未提交归属：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；开始 HEAD `9e1a5840970f2c61b8558cf87e8f57398baf80c2`；结束 HEAD `7959d9cc9b526aec9269d7352784d89f1681807d`（用户明确要求的 GitHub 备份提交，包含 U05 完成和 U06 质量切片）。U05 的实现、契约、测试、迁移和部署入口在 Full 时是工作区候选；随后按用户 2026-10-17 的备份要求提交并推送到 `origin/work/TASK-0027`，未合并 main、未部署。没有 reset、stash、清理、clone 或 worktree。用户的 `docs/development/luna-execution-entry.md`、`docs/development/product-delivery-plan.md`、`question.txt` 未被改写，SHA-256 仍为 `BF4AADCDF9A3D91DB4D0A23C4787C0F7FAF899FD41FB39C7F35C489F90F94195`、`15DAFDD856AE13B6376238487A726A296DF596822205FDD386D47977A8FC664A`、`DAB6DC7FBA01721398735A45A985712414B0C6504919B2857ED32A287D1561ED`。

### 1. 本次完成

- **权限与执行身份**：核对四角色/资源矩阵，写入 `docs/architecture/authorization-matrix.md`；产品装配改用显式 `PRODUCT_TENANT_ID`，不再硬编码 `tenant-a`；旧 `authorized-real` 装配改读 `DEC007_TENANT_ID`/`DEMO_TENANT`（缺省仍是历史本地验证默认），并把它传入账本 scope。后台 Worker 领取时重读租户/用户/角色，写入前重新校验 lease、执行代次和 reviewer 身份；撤权后的执行边界有测试。
- **授权与审计**：新增 `document_external_authorization`，绑定租户、项目、文档、原始 SHA-256、parse_version、用途、供应商、策略版本、授权人/时间、期限和撤销信息；授权/撤销与 `audit_event` 在同一事务提交，失败整体回滚。机构策略限制供应商/用途/预算/授权期限；逐文件确认不能扩大机构权限。撤销优先，下一次出站重新查库；产品模式不再使用环境哈希白名单。
- **预算与调用一致性**：新增 `PostgresBudgetLedger`，以单条条件 UPDATE 原子预留，多 Worker 竞争只有一个 winner；结算只允许一次，重复结算被拒绝；成功结算按实际费用，失败/未知按预留上限记 `unknown`，不释放、不清零、不重放。调用发出前标记 `dispatched`；接管 Worker 把调用标为 unknown 时同步把对应预留标为 unknown；重启只对从未 dispatch 的过期 `reserved` 预留允许 `released`。Embedding 与 LLM 共用同一账户。
- **历史迁移**：新增 `scripts/migrate_execution_ledgers.py` 与只读服务实现。保留来源请求 ID、settled 费用、`reserved`→`unknown` 上限计费、来源 SHA-256、scope/授权身份映射；注册表 approve/revoke 按时间顺序映射；畸形/冲突/无法解析记录使整批失败并列异常；重复运行幂等。真实账本/生产库/受保护原件未被修改。
- **产品装配**：新增 `DEPLOY_REVIEW_MODE=product-postgres`（`scripts/task0028_product_app.py`、`services/product_runtime.py`），只在策略、预算账户和凭据齐备时启动；拒绝同时配置 DEC-007/DEC-005，防止两套额度；启动时核对策略预算与账户上限并执行孤儿预留对账。
- **隐私与密钥**：新增跨段落标签-值、表格相邻单元格、同段联系方式/邮箱/账号反例；出站最小化复用 PII 预检并拒绝残留密钥；日志/诊断继续只输出允许字段、异常类型和栈位置，不输出消息/正文/密钥。密钥只从服务端受保护配置读取。
- **运维与记录**：新增 `scripts/manage_execution_policy.py`（策略/账户/审计同事务）和 `deploy/README-demo.md` 8.6 产品模式运维/回滚说明；ADR-0021 记录数据模型、事务、迁移、隐私、保留/备份和回退边界。

### 2. 实际变更

- 契约/设计：`contracts/openapi.yaml`（0.9.0 → 0.10.0，加法字段与撤销操作）、`contracts/VERSION.md`（v1alpha6）、`contracts/database/README.md`、`docs/decisions/ADR-0021-tenant-execution-authorization-and-budget.md`、`docs/architecture/authorization-matrix.md`、`docs/development/product-contract-baseline.md`。
- 数据库：`contracts/database/migrations/202610172000_task0028_execution_authorization.py`（五张新表、RLS、actor 策略、追加/状态触发器）与 `src/bidding_compliance/persistence/models.py`。
- 运行时：`services/execution_authorization.py`、`services/ledger_migration.py`、`services/product_runtime.py`、`model_gateway/postgres_budget.py`、`api/documents.py`、`api/schemas.py`、`model_gateway/budget.py`、`model_gateway/gateway.py`、`model_gateway/authorized_runtime.py`、`services/review_engine.py`、`services/real_ai_runtime.py`、`services/real_embedding_runtime.py`、`services/llm_candidate_discovery.py`。
- 入口/部署：`scripts/task0028_product_app.py`、`scripts/manage_execution_policy.py`、`scripts/migrate_execution_ledgers.py`、`scripts/check_u05.py`、`scripts/check_postgres.py`、`scripts/task0023_real_ai_app.py`、`scripts/task0027_real_ai_validation_app.py`、`scripts/task0021_online_runtime.py`、`deploy/api_entry.py`、`deploy/README-demo.md`、`deploy/demo.env.example`、`src/frontend/src/api/schema.d.ts`。
- 测试：`tests/test_task0028_execution_authorization.py`（8）、`tests/test_task0028_postgres_budget.py`（7）、`tests/test_task0028_ledger_migration.py`（4）、`tests/test_task0028_privacy_boundaries.py`（5）、`tests/test_task0027_validation_entry.py`（时钟确定性修正）。
- 未修改：`knowledge/legal/**`、`config/legal/**`、`deploy/.env`、`.verification/private/**`、真实历史账本/注册表/生产数据库；没有调用供应商、外发真实内容或操作线上。

### 3. 设计与授权

- 依据 U02 冻结的产品执行契约、U04 的持久调度/未知调用语义、ADR-0019/0020，以及用户已采纳的产品交付计划 U05；新增 ADR-0021 和授权矩阵。OpenAPI/数据库均为向前兼容的新增；旧 DEC-007 JSONL/SQLite 路径保留。
- D3（真实模型/内容外发）和 D4（线上/发布操作）未获本轮授权，未执行；产品模式只做本地合成实现与真实 PostgreSQL 专项。D1/D2 未影响本单元的本地工程验证，但继续限制支持范围承诺与法规/金标签署。

### 4. 验证

**最终代码候选官方 Full（本机，复用 `.venv` 与 `node_modules`）：** `./scripts/verify.ps1 -Mode Full`，退出码 0，阶段 `[1/7]`–`[7/7]` 全部通过；后端 **868 passed, 6 warnings in 689.82s**；前端 OpenAPI 生成/一致性、Biome 23 文件、TypeScript、Vitest **14/14**、Vite build 通过；HTTP health=200/404 与 request ID 关联、登录/项目创建读取/版本/登出撤销通过。6 条 warning 为 2 条既有 pypdf `add_js` 弃用提示，以及 4 条 `tests/test_verification_modes.py` 读取 PowerShell 子进程输出时的既有 `PytestUnhandledThreadExceptionWarning`（测试本身通过，非本轮代码失败）。证据：`.verification/u05-full-final.log`、`.verification/pytest-result.xml`。

首次 Full（`.verification/u05-full.log`）为 866 passed、2 failed：两项 `test_task0027_validation_entry.py` 因测试模块导入时写入的宿主机证据在套件运行 600 秒后过期而失败，与 U05 实现无关。已把 `build_app` 的预检时钟参数化并把测试证据窗口固定为该测试的既有上限 3600 秒，生产默认窗口与显式过期测试未放宽；修正后该文件 28/28 通过，最终 Full 通过。该过程如实保留。

**官方 Focused（中间候选）：** 18 个相关测试文件（U05 四个新文件 + 授权/调度/契约/仓库/身份/网关/语义/隐私回归），退出码 0；后端 **279 passed in 306.84s**；同次 Quick、Ruff、Mypy 109 源文件、前端生成契约/静态/类型/14 个 Vitest/构建均通过。最终 Full 覆盖该候选之后的全部代码变化。

**真实 PostgreSQL/迁移专项：** 本机 Docker Engine 29.2.1，隔离一次性容器 `postgres:16`（镜像摘要 `ca0bd484cb98...`，数据库 `task0004_verification`，仅回环 `127.0.0.1:55432`），未触碰既有 `tender-review-demo` 栈/卷。命令：`POSTGRES_VERIFY_URL=... PYTHONPATH=src ./.venv/Scripts/python.exe scripts/check_postgres.py`，退出码 0，输出 `PASS: PostgreSQL migration, API, RLS, tenant FKs, concurrency, retrieval runs and rollback`。覆盖：新五表 RLS/FORCE RLS 与 actor 策略、跨租户授权拒绝、授权/审计行、撤销后 gate 拒绝、策略/账户/导入、两线程竞争预留仅 1 winner、重复结算拒绝、unknown 计费、过期未发出预留释放、历史账本 dry-run/真实导入/重复导入幂等、注册表 approve/revoke、迁移降级到 base 再升级。证据：`.verification/u05-pg-run.log`；检查实现：`scripts/check_u05.py`（由 `scripts/check_postgres.py` 调用）。

**U04 部署兼容专项：** `PYTHONPATH=src ./.venv/Scripts/python.exe scripts/run_task0011_e2e.py`，退出码 0；`run.json` `status=passed`；真实 PostgreSQL/独立 Worker 的并发领取 1 winner、lease 接管 generation 2、旧代次 fencing、取消竞争（HTTP 200、1 条 cancel audit）、Checkpoint Worker 重启恢复（generation 2→3、模型调用 ID 不变）、unknown 不重放均通过；Microsoft Edge/Playwright **5/5**，failures/errors/skipped 均为 0。证据：`.verification/task0011-e2e-1394bf3bcfca4065ac1f214989e3e20a/run.json`、`playwright-junit.xml`。

**补充：** `scripts/verify_repo.py` PASS；Ruff `All checks passed!`；Mypy `Success: no issues found in 109 source files`；`npm run api:check` 通过。真实供应商调用、真实内容外发、生产数据库/历史账本迁移、线上部署均未执行，因此不计入本轮证据。

### 5. 集成

- 所有 U05 改动最初留在 `work/TASK-0027` 工作区；按用户后续明确要求，已与 U06 质量切片一起提交为 `7959d9c` 并推送到 `origin/work/TASK-0027`，作为 GitHub 备份。未创建 PR、未合并 main、未部署；`question.txt` 未提交/未推送。U05 的 Full 证据绑定其工作区候选指纹，备份提交额外包含尚未 Full 的 U06 质量切片，二者不混同。实现/契约/测试/部署相关文件的清单指纹见本节末尾。
- 真实 PostgreSQL 容器为一次性隔离环境，运行后需删除；既有演示容器、卷和用户数据未修改。

### 6. 风险与恢复

- **在途请求不可撤回**：撤销只阻止下一次出站；已发出的供应商请求仍可能产生费用，代码/文档均不声称可撤回。`unknown` 按预留上限保留，不自动释放或重发。
- **产品切换不是自动行为**：`product-postgres` 需要策略/账户 provision、历史导入演练与 D3/D4 批准；当前部署仍是 `authorized-real`/DEC-007。回退关闭外发并改回旧模式，保留新表/历史账本，不删除、不重置。
- **历史导入的管理连接**：迁移 CLI 需要受控管理角色；运行角色不获得策略写入。导入不修改来源文件，异常整批失败。
- **遗留测试 warning**：Full 的 4 条 `PytestUnhandledThreadExceptionWarning` 来自既有 `test_verification_modes.py` 对 PowerShell 输出的解码，非本轮引入；如实保留，不通过放宽检查消除。
- 未发现新的 P0/P1 代码缺陷；产品模式未在真实供应商/生产环境验证，不能据此宣称生产可用。

### 7. 结论

- U05 的本地实现、契约、迁移、真实 PostgreSQL 专项、U04 部署兼容和官方 Full 均已完成；`TASK0028-004` 的局部验收证据逐项可查。TASK-0028 的 U01/U02/U04/U05 四个步骤均完成，任务状态可置为 `completed`；这只表示开发基线的局部验收，不代表 D3/D4、生产部署、业务金标或用户独立验收。
- 产品级完成仍需 U06/U08—U16、D1—D4 授权和用户独立验收。

### 8. 下一步

- U05 完成后，按 `roadmap.yaml` 检查：U06 依赖 U02/U03，U08 依赖 U03/U05/U06，U09 依赖 U03/U05/U07，U10 依赖多项未完成单元；U03 冻结评测来源缺口和 D2 仍保留。可执行的本地工作优先 U06（解析/OCR/质量/校正），其 D1 只阻塞支持范围/容量最终承诺；不重搜 U03 缺失资产、不重建评测器、不以开发样本替代金标。U07 继续受 D2 内容核验/人工绑定限制。

### 9. 环境复用

- Python：复用 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027\.venv`；前端复用 `src/frontend/node_modules`；Docker 复用本机已有 `postgres:16` 镜像。未安装/升级依赖，未拉取镜像。
- 证据目录 `.verification/` 为 gitignore；不写入提交。真实密钥、生产数据、历史账本原件未进入本轮证据。

**最终候选指纹：** 38 个实现/契约/测试/部署/设计相关文件，按路径排序后将“相对路径、制表符、该文件 SHA-256”逐行以 UTF-8/LF 组成清单，再对清单计算 SHA-256，摘要为 `35142b888cea2f27c409f175ed23848a8cc90e3e37567c20602a7dd2eb655e8f`。该指纹识别 U05 工作区候选（不含本 G3、任务/状态/变更记录本身），不代表提交或集成。

## U06｜解析、OCR、结构化与人工校正（2026-10-17，本地准备成果；正式单元 planned）

**执行单元/TASK：** U06 / TASK-0029（`TASK0029-002`）。正式前置 U02 已完成；U03 仍未完成（冻结评测器/专家标签来源缺失），因此 U06 的正式单元状态保持 `planned`，本节的成果是本地准备而不是单元完成。

**目录、分支/HEAD：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；GitHub 备份提交 `7959d9cc9b526aec9269d7352784d89f1681807d`（U05 完成 + U06 初版切片），其后只有记录提交。本轮 U06 代码候选在 Full 后提交（见本节结论）。

### 1. 本次完成

- **结构质量信号（超出平均 OCR 置信度）**：`quality_issues()` 新增 `LOW_CONFIDENCE_NUMERIC`（OCR 数字/日期片段置信度低于 `min_numeric_confidence`）、`INVALID_DATE`（不存在的日历日期）、`DUPLICATE_TEXT`（重复片段字符占比达到阈值，按出现次数计）、`PAGE_COVERAGE_GAP`（去重页码/最大页码低于覆盖率阈值）、`READING_ORDER_GAP`（页码倒退）和 `TABLE_STRUCTURE_GAP`（表格行宽与多数行相差超过阈值）。失败统一进入 `needs_review`，不丢弃文本、不伪装成功。
- **质量信号落库**：摄取 worker 与人工校正使用 `quality_issues()`，`Document.issues` 记录具体信号，而不是只写 `LOW_QUALITY`；原有平均置信度、空 OCR、`(cid:)`/替换字符、最短文本门禁保持不变。
- **支持矩阵与人工处理**：新增 `docs/development/ingestion-support-matrix.md`，列出格式/页数/OCR/体积硬限制、已知不支持项、每个质量信号的人工处理方式、TASK-0018 合成 OCR 已知失败（CER 20.79%、表格 7/14、重复定位 0/2）以及 D1/D2/D3/U03 边界。
- **版本失效**：新增测试证明已 `ready` 文档在校正后递增 `parse_version`/`context_version`，生成未确认的新上下文；旧上下文确认失效，旧审查不能创建运行。
- **审查容量前检**：`review_management.document_requests` 在冻结运行前检查所选文档的片段数（`MAX_DISCOVERY_BATCHES × MAX_BATCH_SECTIONS`）和生效文本字节（含最新人工修订，`MAX_DISCOVERY_BATCHES × MAX_BATCH_SOURCE_BYTES`）；超出即拒绝，不进入排队或付费调用。图执行层的批次上限仍保留。
- **已知 OCR 失败回归**：合成扫描件夹具的重复文本、低置信数字、表格缺口被显式转为人工复核信号；不更换 Tesseract、不修改既有 OCR 期望。

### 2. 实际变更

- 策略/契约：`config/ingestion.yaml`、`src/bidding_compliance/ingestion/schemas.py`（`IngestionPolicy` 新增 4 个带默认值的结构阈值、`Issue` 新增 6 个质量码）、`contracts/openapi.yaml`（Document.issues 枚举加法）、生成文件 `contracts/schemas/parsed-document.schema.json`、`parser-request.schema.json`、`parser-response.schema.json`、`legal-source-request.schema.json`、`src/frontend/src/api/schema.d.ts`。
- 实现：`src/bidding_compliance/ingestion/quality.py`、`services/ingestion_worker.py`、`services/documents.py`、`services/review_management.py`。
- 前端：`src/frontend/src/pages/project.tsx` 为 6 个新质量码增加中文说明（仅展示，不改变权限或状态判断）。
- 测试：`tests/test_task0029_quality_structure.py`、`tests/test_task0029_review_capacity.py`、`tests/test_tesseract_evaluation_fixtures.py` 扩展；`tests/test_ingestion.py` 与 `tests/test_task0027_needs_review_repair.py` 的校正夹具改为逐片段唯一文本，避免测试自身的重复文本触发新信号；`tests/test_ingestion.py` 的并发校正测试改为 patch `quality_issues`。
- 文档：`docs/development/ingestion-support-matrix.md`、`docs/index.md`。

### 3. 设计与授权

- 依据 U06 计划、U02 契约、ADR-0011 单写者规则；阈值是版本化 `IngestionPolicy` 的默认值，新增字段均有默认值，旧配置仍可读取。没有放宽任何既有质量/安全门禁，没有修改 OCR 引擎、`knowledge/legal/**`、法规核验状态或真实文件。
- D1 未批准支持范围/容量承诺，D2 未批准专业标签，U03 冻结评测器/专家标签来源仍缺失；这些阻止 U06 的最终样本/效果验收，不阻止本轮合成结构验证。

### 4. 验证

- 定向回归：`tests/test_ingestion.py`、`test_task0027_needs_review_repair.py`、`test_task0029_quality_structure.py`、`test_task0029_review_capacity.py`、`test_tesseract_evaluation_fixtures.py`、`test_contract_validation.py`、`test_repository_checks.py`，共 **157 passed, 1 warning**（既有 pypdf `add_js` 弃用提示）。
- 官方 Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths @(...)` 退出码 0；后端 **157 passed in 275.26s**；Quick、Ruff、Mypy 109 源文件、前端 OpenAPI 生成/一致性、Biome 23 文件、TypeScript、Vitest **14/14**、Vite build 均通过。
- 最终代码候选官方 Full：`./scripts/verify.ps1 -Mode Full`，退出码 0，七阶段全过；后端 **880 passed, 6 warnings in 772.91s**；HTTP health=200/404 与 request ID、登录/项目生命周期通过。6 条 warning 为 2 条既有 pypdf 弃用 + 4 条既有 `test_verification_modes` PowerShell 输出解码警告（测试通过）。证据：`.verification/u06-full.log`、`.verification/pytest-result.xml`。
- 未执行：真实 OCR 质量评测、真实模型调用、真实文件/法规内容外发、生产部署。TASK-0018 的合成 OCR 指标是既有基线，不因本轮结构信号改变。

### 5. 集成、风险与结论

- U06 代码候选在 Full 后提交/推送为 GitHub 备份；不合并 main、不部署。
- **U06 正式单元仍为 `planned`**：结构信号、容量前检、版本失效、支持矩阵和合成回归已实施；但"由冻结样本/专家标签专项验证"（TASK0029-002）仍缺 U03 冻结资产和 D2 专业标签，且 D1 未批准最终格式/规模/容量承诺。`TASK0029-002` evidence 保持为空；TASK-0029 保持 `in_progress`，U06 不因本地成果而提前启动或完成。
- 风险：结构阈值可能对合并单元格、重复页眉产生人工复核（这是失败关闭而非自动放行）；阈值调整必须走版本化配置。Tesseract 已知失败未被声称修复。

### 6. 下一步

- U06 剩余内容受 U03/D1/D2 限制，不以开发样例冒充冻结验收。按 roadmap 的 D3 注记，U08 的 Mock/离线覆盖实现可继续，但真实模型质量评测仍需 D3；先做 U08 的覆盖计划/饱和与截断/部分完成语义，再按依赖推进 U09/U10。

## U08｜真实模型发现与覆盖控制（2026-10-17/18，离线准备成果；正式单元 planned）

**执行单元/TASK：** U08 / TASK-0029（`TASK0029-004`）。正式前置 U03/U05/U06 中只有 U05 完成；U03/U06 仍未完成，D3 阻塞真实模型质量评测，因此 U08 正式状态保持 `planned`，本节只记录可离线准备的覆盖语义。

### 1. 本次完成

- **每批饱和可见**：新增 `SATURATION_FINDING_LIMIT=3`、`batch_coverage()` 与 `coverage_summary()`。一个批次返回 3 项（当前 schema/prompt 的单批上限）时标记 `saturated`，而不是 `completed`；有被拒绝候选时标记 `partial`；只有全部批次低于上限且无拒绝时才为 `complete`。
- **覆盖摘要进入运行制品**：`llm_candidate_discovery` 图节点把每批的 `section_count/accepted_count/rejected_count/saturated/subdivided/status` 和总覆盖摘要写入 `llm_candidate_discovery` artifact；饱和批次索引、完成/部分/细分/饱和批次数、候选/拒绝数可见。
- **有界细分/重扫（2026-10-18 补）**：`subdivide_batch()` 把饱和批次按 section 二分，`MAX_SUBDIVISION_DEPTH=2`、`MAX_SUBDIVISION_BATCHES=8` 限制深度和额外调用；子批次分配唯一 index/cache key，图队列按父批次处理完后继续处理子批次；父批次标 `subdivided`，只有子批次全部低于上限且无拒绝时覆盖才为 `complete`；单 section、达到深度或预算耗尽时保留 `saturated/partial`，不伪装完整。子批次复用既有缓存，重启后不重复付费。
- **测试**：`tests/test_task0029_discovery_coverage.py` 覆盖饱和/部分/完成、section 边界二分、深度/单 section 不细分；`tests/test_llm_candidate_discovery.py` 新增饱和→二分→两个子批次→覆盖 complete 的图级测试及重启缓存复用；相关发现/语义/证据/持久网关回归通过。

### 2. 未完成（因此不标 U08）

- 真实模型覆盖质量、冻结集前后对比、跨段/重复候选合并、饱和/截断的实际业务效果；D3 未批准前不进行。
- `TASK0029-004` evidence 保持为空；U08 不因离线覆盖/细分准备而启动/完成。

### 3. 验证

- 定向：`tests/test_task0029_discovery_coverage.py`、`test_task0022_zero_candidate_review.py`、`test_llm_candidate_discovery.py`、`test_semantic_batching.py`、`test_evidence_checker.py`、`test_task0028_persisted_model_gateway.py`、`test_legal_evidence_classification.py`：**75 passed**。
- 最终候选官方 Full：`./scripts/verify.ps1 -Mode Full` 退出码 0，七阶段全过；后端 **886 passed, 6 warnings in 775.96s**；HTTP health=200/404、请求 ID、鉴权/项目生命周期通过。6 条 warning 为 2 条既有 pypdf 弃用 + 4 条既有 PowerShell 输出解码警告（测试通过）。证据：`.verification/u08-subdivision-full.log`、`.verification/pytest-result.xml`。
- 未调用真实模型、未外发内容、未执行真实覆盖效果评测；本轮结果不能作为 U08 或产品验收。

### 4. 结论与下一步

- U08 仍为 `planned`；饱和可见性、有界细分和缓存复用是可复用的本地准备，不替代真实模型质量和冻结集验收。D3 未批准前不进行真实模型质量评测；U03/U06 的冻结样本与输入质量仍缺。之后若继续，可做 U09 的离线双层检索回归和部署恢复准备，但不把本地准备当单元完成。

## U10｜真实 RAG、融合与证据（2026-10-17，零候选路径准备；正式单元 planned）

**执行单元/TASK：** U10 / TASK-0029（`TASK0029-006`）。正式前置 U04/U05/U07/U08/U09 中 U07/U08/U09 未完成，U10 正式状态保持 `planned`；本节只记录一个不需要真实供应商的已知 P1 修复。

### 1. 本次完成

- **零候选不再失败**：`graph/review.py` 的 `semantic_analysis` 在 `discovery.candidates` 为空时跳过语义批次/付费调用，写入显式 `model_analysis` 制品（`findings: []`、`zero_candidate: true`、0 tokens/0 费用），返回 `model_findings_ref`，交给既有 merge/report/人工确认路径。此前空 `batches` 会抛 `ValueError`，运行被标 `review_execution_failed`，API 映射 422（PROJECT_STATE/TASK-0027 记录的 AUD-01）。
- **图级回归**：新增 `test_zero_candidates_skip_paid_semantic_calls_and_store_empty_analysis`，证明网关零调用、空分析制品和零用量；既有非空候选、语义批次、证据分类、持久网关测试保持通过。

### 2. 未完成（因此不标 U10）

- U10 仍需要真实 RAG（法规候选进入模型）、服务端原文/发布/引用/适用资格重核、模型/规则冲突、零候选完整人工确认与报告集成、真实模型效果验收；U07/U08/U09 前置未完成，D3 未批准真实模型/内容外发。`TASK0029-006` evidence 保持为空。

### 3. 验证

- 定向回归（零候选、候选发现、语义批次、证据、持久网关、覆盖、法规证据分类）：**73 passed**。
- 最终候选官方 Full：`./scripts/verify.ps1 -Mode Full` 退出码 0，七阶段全过；后端 **884 passed, 6 warnings in 733.04s**；HTTP health=200/404、请求 ID、鉴权/项目生命周期通过。6 条 warning 为 2 条既有 pypdf 弃用 + 4 条既有 PowerShell 输出解码警告（测试通过）。证据：`.verification/u10-zero-candidate-full.log`、`.verification/pytest-result.xml`。
- 未调用真实模型、未外发内容、未执行真实 RAG 质量/法规资格验收。

### 4. 结论

- 零候选执行缺口（P1）已修复并有 Full 证据；这不表示 U10 完成或产品业务质量达标。U10 正式仍 `planned`，剩余工作受 U07/U08/U09 与 D3 限制。

## U03｜冻结业务样本与可重复评测（2026-10-18，恢复与标签材料）

**执行单元/TASK：** U03 / TASK-0019（`TASK0019-002` 已登记；任务从暂停语义 `blocked` 恢复为 `in_progress`）。

**目录、分支/HEAD：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；恢复前 HEAD `2c6deaa84254192cbd8c1c7321bf555e6702c579`。原备份目录只读，未修改。

### 1. 本次完成

- 从 `_backups/worktrees-uncommitted-20261017T080625Z/task0019` 恢复评测器、测试、两份历史结果和原任务文件；四个文件 SHA-256 与暂停清单一致（评测器 `7b2c…`、测试 `e592…`、结果 `9031…`/`1696…`）。
- 评测器仅做 Ruff 格式化/行宽换行，评测逻辑未改；当前哈希 `2888a44b2cf9d6b15ac2ca2bb92af654a119cb8084db8c9d60c27700a04ab3c9`，原始哈希并列记录在数据集登记中。
- 缺失的法规检索报告用现有离线入口重新生成到 `.verification/task0019-legal/u03-character-baseline-20261018.json`（新路径，不覆盖旧结果）；核心指标与历史报告一致。
- 新增 `evals/capability_baseline/dataset_registry.yaml`：五案例版本、SHA-256、CRLF/LF 身份、规则集、评测器、法规报告、OCR 报告、分区（开发/冻结验收/安全攻击）和指标边界。
- 新增 `evals/capability_baseline/labels/pending-adjudication.yaml` 与 `docs/development/u03-label-adjudication-drafts.md`：逐案例原文位置、候选规则、拟用条文、适用前提、理由、不确定性和待确认问题，明确为待 D2 裁定草案。
- TASK-0019 的暂停记录追加恢复记录；任务状态改为 `in_progress`；`TASK0019-002` evidence 指向数据集登记、标签草案、历史结果和五个案例。

### 2. 验证

- `PYTHONPATH=src ./.venv/Scripts/python.exe scripts/evaluate_legal_retrieval.py --output .verification/task0019-legal/u03-character-baseline-20261018.json`：Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中、10 条有效标签查询。
- `PYTHONPATH=src ./.venv/Scripts/python.exe scripts/evaluate_review_capabilities.py --output .verification/task0019-reuse/u03-baseline-adapted-20261018.json --legal-retrieval-report ...`：fixture 模式 5/5、引文/定位 7/7、重复率 0、`external_model_calls=0`、`risk_precision`/`risk_recall=null`。
- `python -m pytest tests/test_review_capability_evaluation.py`：2 passed。
- 与历史结果比较：指标、计数、候选、引文/定位一致；差异仅为 CRLF 检出导致的案例/阈值/规则源哈希、历史 HEAD、法规报告路径/延迟/哈希；LF 规范化身份与原基线一致。

### 3. 结论与缺口

- 评测工具、可重复入口、数据身份、开发/冻结/安全分区和待裁定标签材料已具备；`TASK0019-002` 可查证。
- 专家确认标签仍为 0，风险 precision/recall/false-positive rate 保持未测量；冻结验收集未建立；D2 逐条确认未发生。U03 仍为 `in_progress`，不能以五个开发候选冒充金标。

## U06｜解析、OCR、结构化与人工校正（2026-10-18，D1 范围验证；正式 planned）

**执行单元/TASK：** U06 / TASK-0029（`TASK0029-002` evidence 保持为空）。

### 1. 本次完成

- 将 DEC-008 批准的 D1 首版范围写入 `docs/development/ingestion-support-matrix.md`：PDF/DOCX/PNG/JPEG、10 MiB、300 页、OCR 30 页、五类审查能力；超限/不可靠输入必须拒绝或转人工，不得静默显示完成。
- 新增 `tests/test_task0029_support_scope.py`（10 项）：策略常量与 D1 一致；四种格式（PDF/DOCX/PNG/JPEG）在合成样例上解析通过；>10 MiB、>300 页、>30 OCR 页分别返回 `SIZE_LIMIT`/`PAGE_LIMIT`/`OCR_LIMIT`；短文本和空 OCR 图像返回 `requires_review` + `LOW_QUALITY`，不伪装通过。
- 既有结构质量信号、容量前检、已 ready 文档校正后的上下文失效和合成 OCR 回归保持不变。

### 2. 验证

- `python -m pytest tests/test_task0029_support_scope.py`：10 passed。
- 官方 Focused（含本文件及相关回归）：57 passed，Ruff/Mypy/前端 14 项/build 通过。
- 最终代码候选官方 Full 七阶段全部通过：后端 `918 passed, 6 warnings in 805.25s`，HTTP 与鉴权/项目生命周期阶段 PASS；D1 边界测试包含在 Full 中（`.verification/u10-u12-full-final4.log`）。

### 3. 结论与缺口

- D1 范围已有可重复的工程边界证据；不表示真实 OCR 质量、复杂版面或冻结样本效果达标。
- U03 冻结样本和 D2 专业标签仍未完成，`TASK0029-002` evidence 保持为空；U06 正式仍 `planned`，不因 D1 范围批准而提前完成。

## U10｜真实 RAG、融合与证据（2026-10-18，法规候选进入模型与覆盖投影；正式 planned）

**执行单元/TASK：** U10 / TASK-0029（`TASK0029-006` evidence 暂保持为空，待真实服务器端到端）。

### 1. 本次完成

- 语义请求现在包含每个候选的前 6 条法规候选：`evidence_id`、标题、条款、版本、原文摘录、版本状态、`eligible_for_confirmation` 和原因；原文只做长度截断，不改写。
- 新 Prompt `task0030-semantic-rag-v1` 要求模型只能引用该候选 `legal_candidates` 中的 `evidence_id`，没有合适条款时返回空数组；保留 `task0023-semantic-v1` 旧 Prompt 和“无法规正文”载荷，保证历史在途运行可恢复。
- 服务端继续用 `verify_legal_hit` 重核条文存在性、冻结发布/修订、引用哈希和版本/资格；新增“模型只能引用实际暴露给它的前 6 条”检查，超出暴露集合的 ID 记为无效引用，不成为正式证据。
- `legal_references` 增加 `selected_by_model` 标记；网页区分“模型引用候选/检索候选”，并继续显示“适用性待确认、不能作为违反依据”。
- 新增 `product_execution` 投影：饱和/部分批次、未处理 section、截断、unknown 模型调用会显示为 `partial`；报告 v3 和 findings API 都暴露该投影；旧真实运行缺少覆盖记录时标为 `unknown`，不冒充 complete。
- 新增确定性重复合并：同一原文摘录（category + source hash + locator + quote）上的规则/模型/子批次候选合并为一条，保留 sources、rule_ids、evidence、legal_references、conflicts 的并集，取最高严重度和最保守证据状态；不同 locator 的相似标题不合并（避免语义猜测）。合并结果保留基础候选的 `finding_id`，使其仍能通过 `_resolve_source_locations` 绑定冻结原文。
- 新 Prompt/载荷、旧 Prompt 兼容、截断、候选上限、字段拒绝、公开法规原文不改写等 15 项定向测试。

### 2. 验证

- `python -m pytest tests/test_task0030_real_rag.py tests/test_legal_evidence_classification.py tests/test_task0022_zero_candidate_review.py tests/test_llm_candidate_discovery.py`：57 passed。
- 官方 Focused（含任务/隐私/报告/评测相关）：57 passed；最终代码候选官方 Full 七阶段全部通过：后端 `918 passed, 6 warnings in 805.25s`，HTTP 与鉴权/项目生命周期阶段 PASS（`.verification/u10-u12-full-final4.log`）。
- 未调用真实模型；真实 RAG 载荷、引用重核、覆盖/部分完成和报告集成需服务器 E2E（D3/D4）。

### 3. 结论与缺口

- U10 的“法规候选真实进入模型、服务端重核、部分完成可见”工程链路已实现；这不等于真实模型效果、法规适用正确或正式证据资格。
- D2 法规内容核验/规则—法规绑定未签署；U03 冻结集未建立；`TASK0029-006` evidence 保持为空，U10 正式仍 `planned`。

## U12｜报告、审计与交付一致性（2026-10-18，报告 v3 覆盖摘要）

**执行单元/TASK：** U12 / TASK-0029（`TASK0029-008` evidence 暂保持为空，待真实报告下载验收）。

### 1. 本次完成

- 报告从 v2 升为 `task0010-report.v3`，`assessment_scope.product_execution` 记录 `pending/complete/partial`、覆盖状态、未处理 section、截断/饱和、原因码和 unknown 调用数；v1/v2 历史读取不变。
- Word/PDF 渲染新增“部分完成/覆盖完整/未使用模型覆盖计划/未处理单元/饱和/截断/unknown 调用”中文说明；旧报告不会补造缺失信息。
- findings API 增加可选 `product_execution`（OpenAPI 0.10.1，契约集 v1alpha7），网页显示部分完成提示；原文摘录块显示页码和 locator。
- 新增报告 v3 部分完成披露测试和前端类型/构建检查。

### 2. 验证

- `python -m pytest tests/test_review_reports.py`：8 passed；v3 部分完成报告通过正式 schema 校验，Word/PDF 均含“部分完成/不得解释为全部内容已审查完成/未处理单元/饱和”。
- 官方 Focused 和最终 Full 覆盖；前端 TypeScript、Biome、Vitest 14/14、Vite build 通过。
- 真实 Word/PDF 报告下载与内容核对需服务器 E2E；当前未执行。

### 3. 结论与缺口

- 报告结构、覆盖披露和前端提示已实现；真实报告的文件可读性、下载鉴权、定位/法规/人工决定一致性和审计仍需 U11/U12 服务器验收，`TASK0029-008` evidence 保持为空。

## 2026-10-18 公网真实 PDF 验收（D3/D4；产品验收，等待用户独立验收）

**执行单元/TASK：** U08/U09/U10/U11/U12 的真实服务器证据；U13/U14 的部署/恢复演练。正式单元状态仍按依赖保留（U10 仍 in_progress，U08/U09/U12 planned），本节不替代用户独立验收。

**目录、分支/HEAD：** 固定目录 `D:\自由项目\招标审核\bidding-compliance-agent-TASK-0027`；分支 `work/TASK-0027`；最终代码候选 `c688232eb96ca42d5b10182566055420b0c42564`（已推送 `origin/work/TASK-0027`；CI run 39062695856 success）；其后为文档/证据提交（CI 亦成功），服务器 HEAD 已同步到最新分支 HEAD。部署镜像源 `339155d6b4fba88b2ccf60e53d6617d0de561f57`；`339155d` 之后 `src/contracts/deploy` 差异为 0。

### 1. 部署身份

- 服务器：阿里云 ECS `i-j6ccqpfriae57w0hkskn`，`/opt/tender-review`，公网 `https://47.83.132.211`。
- 源码/CI：最终 HEAD `c688232` 对应 [GitHub Actions run 39062695856](https://github.com/w186www/Tender-Review/actions/runs/39062695856) completed/success；此前 339155d 等提交的失败由 TASK-0028 evidence 指向 gitignored `.verification` 导致，已改为仓库内可查证据后 CI 转绿。
- API 镜像 `tender-review-api:task0030-339155d`，镜像 ID `sha256:522c88ee5296c41ec910e50ac97478f6550b356a4557b19ba4739cda3baecea2`。
- Web/nginx 镜像 `tender-review-web:task0030-339155d`，镜像 ID `sha256:9415c3715b9a93f620a07a886491d293a95ace9dd912159d49f233a900ceb29e`，构建期 `VITE_REVIEW_MODE=dec007-real-qwen`。
- 隔离 parser 镜像 `tender-review-parser:demo`，镜像 ID `sha256:b20d0aea7f0905a7a4afca02f4909babe610751466fea003398a3e9d22e0ab98`（`PARSER_IMAGE` 已固定）。
- 数据库迁移 `202610172000`；`review_model_call`、`document_external_authorization`、`model_execution_policy`、`model_budget_account`、`model_budget_reservation` 已存在。
- 运行单元：api、review-worker、worker、nginx 均为 `task0030-339155d`；postgres/minio/clamav 保持原健康状态；api health 200。

### 2. 迁移/恢复演练

- 全量备份 `/opt/tender-review-backups/20261017T174508Z`：`database.dump`、`deploy-config.tgz`、`modelstate.tgz`、`miniodata.tgz`、`db-counts.txt`、`SHA256SUMS`；`sha256sum -c` 全部 OK。
- 隔离 `postgres:16` 恢复：document=24、review_engine_run=15、review_result=9、review_decision=16、audit_event=358，与源库一致；28 张 RLS 表恢复。
- 隔离迁移演练：恢复副本从 `202610151000` 升级到 `202610172000`，原计数不变，`review_model_call`/`document_external_authorization` 等新表出现；随后才应用到生产库。
- 备份 modelstate 核对：LLM 25 次、Embedding 312 批、约 ¥0.1474435；索引 build `c7344cac…` 与线上一致。生产迁移后账本未重置。

### 3. 公网浏览器真实 PDF 验收（最终运行）

- 浏览器：Microsoft Edge（Playwright），真实公网 HTTPS；合成 PDF `evals` 外的本地样本 `.verification/acceptance/2026-10-18/synthetic-tender.pdf`（程序生成，不含真实企业/人员信息）。
- 项目 `7e5c341e-6306-4f5b-ae88-baeab1b24665`（政府采购/工程/北京市/招标/政府机关/工程，制度勾选招标投标+政府采购）；文档 `bdaa24e1-9221-4ba1-992d-cbb86556b5ca`；SHA-256 `0db33351…`。
- 流程：登录 200 → 上传 202 → `等待上下文确认` → 上下文确认 200 → `可用于审查` → 逐文件外发授权 201 → 发起审查 202（task `f47fa2d0-5ec0-5c7f-b408-a769cb8b8cb7`，run `33faaef9-9be9-50f2-835d-93c25c7a7113`）。
- 真实模型：discovery 3 次（父批次饱和 + 2 个 section 子批次，均成功）+ semantic 2 次（11 个候选分 2 批）；5 次调用全部 `settled/reported`，无 unknown。输入/输出 tokens 5559/4213，估算 ¥0.015822。
- 人工复核：6 条风险全部有服务端原文定位（citations 1–3 条/条），网页保存接受决定；发布结果 `6abcb16a-e125-4f08-8893-fc8ec6245122`。
- 报告：Word `80e976fc-a2d9-41e8-9c88-9c7f71c7a7e7`、PDF `7dae4afe-a265-4110-b9aa-17935354636b`；浏览器下载 SHA-256 分别为 `fd5d0bb1…`、`e4d4463a…`，与服务端 `content_hash` 完全一致。
- 报告内容核查（`check-report.py`，Word 10,376 字符 / PDF 10,726 字符）：标题、原文页码和 locator（`pdf/page/1/...`）、法规检索摘要（命中 160 项、可引用 0 项）、每条 3 个“检索候选”参考条款（含版本状态 `unverified` 和未确认原因）、部分完成/16 个未处理 section、真实模型 5 次/¥0.015822；未出现“构成违法/应认定为违法”。全部检查通过。
- 法规状态：运行上下文完整（制度、采购方式、采购人、标的、地区），所以检索实际执行；`2019` 实施条例的核验期限已在 2026-10-14 到期，其余 42 个版本未核验，规则—法规 binding 未人工签署，因此 160 个命中全部为参考候选、可引用正式依据为 0；模型未选择任何 `legal_evidence_id`。报告明确“可能相关依据（适用性未经确认，仅供参考，不计入已核验证据）”。这不是法律适用结论。
- 账本（DEC-007，服务器）：验收前 25 LLM / 312 Embedding / 约 ¥0.1474435；最终 55 LLM / 312 Embedding / ¥0.2419564（30 次新增真实 LLM 调用覆盖 6 轮验收/排错，全部 settled，unknown=0）。额度仍为累计 2000/2000/¥200，未新增 scope/账户/额度。
- 运行数据：15 个 `result_published`、5 个 `waiting_human`、1 个历史 `failed`；未删除/覆盖任何业务数据或账本。

### 4. 权限、TLS 与运行状态

- 真实 API 反向检查（同一公网入口）：reviewer 登录 200、auditor 登录 200；auditor 建项目 403；reviewer 创建法规草稿 403；reviewer 读取法规状态 200 且 `capabilities=[]`（只读，不能发布）；未知项目 404；匿名项目列表 401。未发现越权写入。
- TLS：Let's Encrypt 证书 `notBefore=2026-10-15`、`notAfter=2026-10-22`，`tender-certbot-renew.timer` 与 `tender-certbot-expiry.timer` 均为 active/waiting；本轮未改证书或续期配置。
- 容量：磁盘 40 GB 中已用 15 GB、可用 23 GB；内存 7.5 GiB、可用约 4.5 GiB；七容器运行，api/review-worker/worker/nginx 为新候选。
- 告警：`deploy/.env` 未配置 alert/webhook/SMTP 渠道；系统内 health 与任务状态可查，但外部告警投递缺口保留，未假装已送达。

### 5. 本轮观察到的限制

- 正式法律支持仍为 0：核验期限过期、42 个版本未核验、规则—法规 binding 未签署（D2）。因此“法规依据”只以参考候选呈现，不能作为违法/合规结论。
- 检索排名仍有噪声（例如付款期限命中招标投标法第二十二条、政府采购办法第二十八条、实施条例第五十七条）；报告限制为每条 3 个参考候选并标注“检索候选”，但 U09 的排序质量仍需冻结集评测。
- 同名/同义风险跨不同原文行时仍可能保留两条（例如“时间逻辑矛盾”和“开标时间早于截止时间”）；已实现同 locator+quote 的确定性合并，跨段语义合并不做自动猜测。
- 覆盖为 `partial`：16 个 section 因饱和/部分覆盖未完成；报告和网页均明确显示，不声称全部审查完成。
- 本轮为原生文本 PDF，未验证真实扫描件 OCR、复杂多栏/跨页表格、DOCX/PNG/JPEG 的公网路径；U06 的合成 OCR 基线仍是已知上限。
- 未执行多角色/越权/失败/取消/暂停/恢复的公网浏览器全矩阵；这些仍是 U11/U15 的条件。未配置外部告警渠道，D4 的告警投递缺口保留。

### 6. 结论

- 已在实际服务器网页完成“登录→上传受支持 PDF→解析/上下文→逐文件授权→真实模型审查→原文定位/参考法规→人工复核→发布→Word/PDF 下载”的端到端验收；报告哈希与服务器一致，数据/账本保留。
- 这不等于用户独立验收，也不等于正式法规依据/专业效果达标；D2 内容和 U15/U16 仍待用户决定。

## 2026-10-18 法规采用政策与真实文件质量准备（DEC-009 / ADR-0022）

**执行单元/TASK：** U07/U09/U10 的法规采用语义；U06 的真实表格质量修正。正式 U07/U09/U10 仍按依赖保留，不因采用政策提前标完成。

### 1. 本次完成

- 新增 `config/legal/adoption-policy.json`：冻结清单按 LF 规范化后的 SHA-256 `1cd46d8b…`（本地 CRLF 工作树与服务器 LF 检出曾暴露哈希差异，加载器已统一规范化）、43 个版本、3120 个片段、法规索引 `69d340d6…`，`policy_id=ADOPT-2026-10-18`，明确 `independent_legal_verification=false`。
- 新增 `config/legal/rule-law-bindings.json`：11 条工程配置的规则—法规关联，覆盖五类规则的资格/技术/评分/合同/程序规则；每条记录库内版本、条文、理由和 `source_reviewed=true`，`asserted_by=engineering-config`，不是专家或人工裁定。
- 新增 `legal/adoption.py`：加载并校验清单字节、版本集合、索引身份；政策/索引不一致失败关闭。规则—法规关联逐条检查规则 ID、版本、条文在冻结原文中出现。
- 法规命中新增 `adoption_status=project_adopted/not_adopted`；检索结果新增 `adopted_evidence`/`adoption_policy_id`。`citable_evidence` 仍只含独立核验且资格满足的命中；采用条文不并入正式证据集合。
- 语义请求的法规候选新增 `adoption_status`；Prompt 说明“项目采用但仍未独立核验”，允许模型把采用条文作为参考引用，不得称为已核验/已确认适用。
- 报告 v3 新增 `legal_adoption_policy`、采用参考数、工程配置关联数；Word/PDF/网页标注“项目采用库内版本（未经独立法律核验）”。旧报告/快照不改写。
- `TABLE_STRUCTURE_GAP` 收敛：不再因合并/标题行较少单元格误报；只有系统性额外单元格（异常行≥1/4 且宽度差>1，或单行超过多数行 2 格以上）才触发。真实天津地铁 DOCX 的复杂表格不再仅因合并单元格整体阻断。

### 2. 验证

- 新增 `tests/test_legal_adoption_policy.py`：政策/绑定身份、清单篡改拒绝、检索标注、快照不一致拒绝。
- 官方 Focused（法规/质量/报告/契约等 12 个文件）：**235 passed in 191.90s**；Ruff/Mypy/前端检查通过。
- 最终代码候选官方 Full 七阶段全部通过：后端 `924 passed, 6 warnings in 815.58s`，HTTP 与鉴权/项目生命周期阶段 PASS（`.verification/legal-adoption-full.log`）。
- 真实天津地铁3号线 DOCX（已授权，SHA-256 `506e9ec1…`）已核对：689,683 字节、1,483 个 section、两处空 OCR 页脚（已按 OOXML PAGE=36 校正）、复杂表格行宽；最终部署后的完整公网审查与 v3.2 报告见下一节。

### 3. 边界

- 采用政策不是独立法律核验：不改变任何 `verification`/`verified_through`，不生成专家标签，不把采用参考称为已核验依据。
- 规则—法规关联是工程配置，质量需人工抽检；正式违法认定仍需人工复核，不由系统自动作出。
- D2 的专业金标和用户独立验收仍未发生；U07/U09/U10 的正式状态不因采用政策自动提升。

## 2026-10-18 product-postgres 切换、真实文件与覆盖语义验证

**执行单元/TASK：** U05 产品权威源切换、U06 的真实扫描/图片路径、U08 覆盖语义、U10/U12 真实文件报告、U13/U14 备份/回滚/容量 smoke。正式单元状态不因这些证据提前提升；用户独立验收未发生。

### 1. 最终候选与部署身份

- 源码候选 `d3cb613c1b766239cc14bf6f107c3f1f203cae6f`（`work/TASK-0027`，已推送）；官方 Full 七阶段通过：后端 **928 passed, 6 warnings in 767.84s**，HTTP health=200/404 与登录/项目生命周期 PASS（本机日志 `.verification/final-full-d3cb613.log`，不随仓库提交）。
- 部署镜像 `tender-review-api:task0030-d3cb613`、`tender-review-web:task0030-d3cb613`；parser 镜像 `sha256:be158f24…`；数据库迁移 `202610172000`。api/review-worker/nginx 运行新候选，health 200。
- nginx 必须同时使用 `docker-compose.demo.yml` 与 `deploy/docker-compose.tls.yml`；只重建 base 服务会丢失 443 映射（本轮曾发生并由 TLS 叠加层恢复）。
- 本机到公网 API 的 50 请求/并发 10 smoke：50×200，p95 744.4ms、19.26 rps；这是 TLS/列表路径 smoke，不是完整 NFR 压测。

### 2. 备份、隔离恢复与 product-postgres 导入

- 切换前全量备份 `/opt/tender-review-backups/20261017T213903Z`：`postgres.dump`（SHA-256 `5b67f9a7…`）、`miniodata.tar.gz`（`56559fd4…`）、`modelstate.tar.gz`（`746a8b59…`）、manifest。`restore.sh --verify` 通过：数据库计数与源库一致（tenant=1、app_user=3、project=20、document=30、ingestion_job=30、review_task=26、review_result=16、review_report=34、review_report_content=17、audit=978），MinIO/modelstate 卷归档校验通过。
- 隔离库 `product_drill_20261017` 从该 dump 恢复后 provision 策略/账户并导入真实历史账本：460 条 reservation（148 LLM/312 Embedding、¥0.9496789）全部 settled、unknown=0；导入后账户 spent ¥0.9496789、reserved 0。演练库已删除，未影响生产。
- 生产库 provision：tenant-a、provider bailian、purpose external_review、limit ¥200、单次 LLM ¥0.25、Embedding 批 ¥0.10、授权 TTL 3600s；正式导入同一 460 条历史 reservation，生成 1 条 ledger_import 记录。
- 历史 JSONL registry 未导入：`dec007-synthetic-v1` 无对应文档，且同一真实 DOCX 有 2 条重复 approve；按整批失败关闭设计拒绝，未把陈旧/冲突授权写进产品库。产品模式的逐文件授权改由 API 新建，当前历史授权记录保持只读。
- 首次 product 启动暴露运行时角色缺少新表权限（`model_execution_policy` 查询 `InsufficientPrivilege` 导致 502）。`deploy/demo_init.py` 已增加 `SELECT ON model_execution_policy`、`SELECT,UPDATE ON model_budget_account`、`SELECT,INSERT,UPDATE ON model_budget_reservation`、`SELECT,INSERT,UPDATE ON document_external_authorization`，新增部署契约测试；服务器 `init storage` 幂等应用后产品模式正常启动。

### 3. product-postgres 真实文件验收

- 真实天津地铁 3 号线 DOCX（已授权，SHA-256 `506e9ec1…`，689,683 字节）此前完成 41 条风险、人工接受/发布；本轮用 v3.2 模板重新生成 Word/PDF，报告含 111 条项目采用参考、258 饱和/503 拒绝/0 未提交、0 正式可引用依据；41 个标题全部出现在 Word/PDF，下载 SHA-256 `25c3569c…`/`83ab6475…` 与服务端 `content_hash` 一致。
- 派生真实文本 PDF（35 页、1562 片段）在 product-postgres 下完成公网网页流程：项目 `35869b18-084e-43ea-9ebb-fabcf5667232`、文档 `21e20387-eb49-44d3-b2a0-7d05d98334f6`、task `a3e40c51-0547-5a0e-b40d-801ccbf707cf`、run `b05e858f-cd77-5c82-a2c3-3c9fb2b18bfc`、result `3227580c-f227-4387-9d3c-7f822b8ac847`。逐文件授权 201，13 条风险全部有服务端原文定位和采用法规参考，人工接受/发布；17 次真实 LLM 全部 succeeded/reported，Word/PDF 哈希 `87c8c15f…`/`96728496…` 与服务端一致；报告为 43 条采用参考、50 饱和/1423 拒绝/0 未提交、0 正式可引用依据。
- 账本：PG 账户 limit ¥200、spent ¥1.0400702、reserved 0、477 条 reservation；历史 148 LLM + 产品运行新增 17 LLM，Embedding 312 批；unknown=0。DEC-007 SQLite 保持只读历史 148 LLM/¥0.9496789，未改写。

### 4. 撤销、角色与回退

- 对已 ready 的真实文本 PDF 文档执行撤销（200）后立即发起审查返回 **403 FORBIDDEN**；重新登记授权返回 201。未登记授权的文件在上下文未确认前返回 422（先被状态门禁拒绝），状态门禁优先于外发门禁。
- auditor 创建项目 403；匿名项目列表 401；reviewer 访问法规只读能力与既有角色边界保持不变。
- 回退演练：切回 `authorized-real` 后 api/review-worker 正常启动、DEC-007 账本仍为 148 LLM、health 200；随后切回 `product-postgres`，两个进程均打印 product 模式与 ¥200 账户身份，health 200。PostgreSQL 授权/预算记录保留，未删除/重置。

### 5. 扫描与图片格式的真实限制

- 派生真实扫描 PDF（2 页，tesseract 5.3.0 chi_sim+eng）实际上传/OCR，产生 578 个碎片 section 和 `LOW_CONFIDENCE_NUMERIC`，状态 `needs_review`；高分辨率合成扫描 PDF 同样 OCR 后 362 个碎片 section、`LOW_CONFIDENCE_NUMERIC`；PNG/JPEG 上传均 202、解析成功、OCR 后转 `needs_review`。未进入审查，未声称扫描件/图片可直接可用。
- 这意味着中文扫描/图片的 OCR 段落切分与数字置信度仍需专门改进；质量门禁按设计阻止低质量文本进入真实审查。DOCX 的人工校正与上下文确认路径已在前一真实文件中验证。

### 6. 结论与边界

- product-postgres 已在实际服务器启用并完成真实文件端到端验收；PostgreSQL 是当前唯一授权/预算权威源，DEC-007 历史账本只读保留，回退路径可用。
- 正式法律支持仍为 0（无独立核验、无人工规则—法规签署）；扫描/图片 OCR 质量不足；覆盖为 partial；外部告警与完整 U11/U15 矩阵未完成。以上不等于用户独立验收，也不构成专业法律结论。
