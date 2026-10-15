# TASK-0021 本地验证记录

- 状态：`in_progress`；源码门禁、一次真实 Qwen 在线 Edge E2E 已通过。代码提交、推送、远端 CI 和最终归档仍待完成。
- 日期：2026-10-15。
- 工作树：独立 `work/TASK-0021`，基线 HEAD `0a5e3bdb25535a44ac213090a53ea8965fb09133`。
- 真实供应商状态：DEC-002 的唯一一次请求已于 2026-10-15 在本地隔离 Edge E2E 中成功执行。密钥值未读取、输出或记录；没有真实业务数据或法规正文外发。

## 验证候选身份

最终 Focused/Full 源码与测试候选指纹：`407a0564c2d8508bde52cee3626394f50a8a5a3c82c934c5d9a0e2204442fd1d`。

算法：对以下 14 个路径按相对路径排序，每行使用 `路径<TAB>文件原始字节 SHA-256`，以 UTF-8（无 BOM、含最终换行）构成 manifest，再对 manifest 求 SHA-256。文档记录更新不改变该源码/测试指纹。

```text
scripts/assert_task0021_qwen_e2e.py
scripts/run_task0011_e2e.py
scripts/run_task0021_online_e2e.py
scripts/task0021_online_e2e_app.py
scripts/task0021_online_runtime.py
src/bidding_compliance/api/reviews.py
src/bidding_compliance/graph/review.py
src/bidding_compliance/model_gateway/adapters/__init__.py
src/bidding_compliance/model_gateway/adapters/bailian_qwen_adapter.py
src/frontend/e2e/workbench.spec.ts
src/frontend/src/app.tsx
src/frontend/src/styles.css
tests/test_bailian_qwen_adapter.py
tests/test_task0021_online_gateway.py
```

## TASK0021-001：百炼 Chat 适配器

- Focused 覆盖固定北京 Workspace Chat Completions endpoint、`qwen3.8-flash`、`enable_thinking: false`、严格 JSON Schema、`max_completion_tokens`、完整本地 Schema 二次验证、`uniqueItems` 只从供应商副本移除、HTTP 错误/超时/格式失败和秘密清理。
- 本轮预算/外发边界变更后两个相关测试文件 Focused：25 passed；无失败/错误/跳过。

## TASK0021-002：外发最小化、预算与审计

- MockTransport 证明未授权调用不会触达供应商；输入仅接受允许 SHA 绑定的合成引用，剔除项目上下文和法规检索正文；完整规范化白名单 JSON 超过 2,048 UTF-8 字节时在供应商请求前拒绝；审计只保存元数据；单次 ledger 对完整 ¥0.10 上限先行预留并拒绝第二次调用。
- 新增 503 测试证明 Gateway 只发一个百炼请求、写入失败审计后失败退出，没有 Mock fallback。
- 官方北京单价按 2026-10-15 核对为输入 ¥0.8/百万 tokens、输出 ¥2.7/百万 tokens。按 8,192 输入和官方提示的最多 1,034 输出 tokens 计，费用上限估算 ¥0.0093454；用户批准的硬预算为 ¥0.10，运行 ledger 调用前预留 ¥0.10。价格和授权已于 2026-10-15 再核对。

## TASK0021-003：本地模式和回归门禁（部分满足）

| 验证 | 结果 |
|---|---|
| `scripts/verify.ps1 -Mode Focused -TestPaths tests/test_bailian_qwen_adapter.py tests/test_task0021_online_gateway.py` | 25 passed；Ruff 全项通过、Mypy 98 个源文件通过、前端契约/Biome/TypeScript、6 个前端单测及 Vite build 通过。JUnit：`.verification/pytest-focused-result.xml`。 |
| `scripts/verify.ps1` | 最新候选 Full 570 passed、0 failed/0 errors/0 skipped，2 条既有 pypdf `add_js` 弃用警告；Ruff、Mypy、前端 6 项、生产 build、HTTP health/404/request-id、真实登录/项目生命周期 smoke 均通过。JUnit：`.verification/pytest-result.xml`。 |
| 文档/任务证据 Quick | 更新本验证记录和任务证据路径后通过；只检查仓库合同、秘密扫描和任务治理，不代替运行时验证。 |
| PostgreSQL 16 + Checkpoint/法规生命周期专项 | 通过：在一次性、仅 loopback、本机缓存官方 PostgreSQL 16 镜像上依次运行 `check_postgres.py` 和 `check_legal_publications.py`；迁移、RLS、租户隔离、Checkpoint 新进程恢复、审查/人工决定、重试/取消/撤权、发布并发和事务回滚通过；临时容器及卷已清理。 |
| TASK-0020 离线 Edge 回归 | 通过，5/5 浏览器案例、0 失败/错误/跳过；run `617af9223b8843a7862d19a1ace68b6a`。合成 DOCX SHA-256 `645fce45f6e54ef94908152959373f7b14564a57040ba731e6eac510a3b0ef3d`；上传、解析、离线审查、人工复核、报告下载流程通过。此结果是 `OfflineReviewGateway`，不代表真实模型能力。完整 manifest/JUnit 位于 `.verification/task0011-e2e-617af9223b8843a7862d19a1ace68b6a/`。 |
| npm 依赖 | 仅在独立 TASK-0021 `src/frontend` 使用官方锁文件 `npm ci --no-audit --no-fund`；新增 184 包。`src/frontend/package-lock.json` 与基线无差异；未在 TASK-0019 工作树安装。 |

本轮 Full 在普通沙箱中的一次候选运行有 567 passed、2 failed；两项都在 `tests/test_verification_modes.py` 的临时本地 Git `clone --no-local` 阶段返回 exit 128。获准以 `require_escalated` 重跑后，该预算候选为 569 passed；随后增加完整白名单 JSON 2,048 字节上限及负向测试，最新候选再次以 `require_escalated` 完整 Full 通过，570 passed。首次失败发生于本地 Git 临时克隆，与 TASK-0021 预算/外发逻辑无关。

在线浏览器执行不自动重试：本地 Playwright `CI` 未设置，重试数为 0；Gateway 与语义节点 `max_attempts=1`。本次仅有一次真实审查动作和一条模型审计事件。

## TASK0021-004：唯一一次真实 Qwen 在线 Edge E2E

- 一次性命令：`Remove-Item Env:CI; .\.venv\Scripts\python.exe -m scripts.run_task0021_online_e2e --dec-002-approved`。第一次直接以脚本路径启动时在模块导入阶段失败，未创建 run 目录、未生成审计事件、未发出供应商请求；唯一有效 E2E 使用模块启动方式。
- 实际运行：run `30180d4e152040ccb9f805634617b456`，执行时仓库 HEAD `0a5e3bdb25535a44ac213090a53ea8965fb09133`，工作树源码/测试 manifest SHA-256 `407a0564c2d8508bde52cee3626394f50a8a5a3c82c934c5d9a0e2204442fd1d`。生成的合成 DOCX SHA-256 为 `c770a3576555fc9225b2612c98966e809cc087194e3bb2d3d7c3bfb05ed65341`；run manifest 记录该身份，输入最小化器将每条引用绑定该 SHA，并在发送前拒绝规范化白名单 JSON 超过 2,048 UTF-8 字节。
- Edge/Playwright：Microsoft Edge 真实浏览器 5/5 passed，0 failure/error/skip；审查用例完成上传、解析、五类 Skill、法规 RAG、人工复核决定持久化、结果发布，以及 DOCX/PDF 生成和下载。JUnit 与运行记录位于 `.verification/task0021-qwen-e2e-30180d4e152040ccb9f805634617b456/`。
- 真实调用审计：恰好 1 条成功事件；provider `bailian`、模型 `qwen3.8-flash`、北京 Workspace 专属 Chat Completions endpoint；Prompt `task0021-qwen-synthetic-v1`、配置 `task0021-dec002-v2`、价格版本 `bailian-cn-beijing-2026-10-15`；供应商报告输入 424 tokens、输出 420 tokens，估算费用 ¥0.0014732，延迟 10,125 ms；重试 0、回退路径为空、失败分类为空。响应 SHA-256 `5f462b27fa9cf59015a14db08bb411d76da24f617c8ac17ea8b51f3241e47dcb`。费用为按供应商 token 用量和官方单价计算的估算值，不等同于账户最终账单。
- 预算与外发：Gateway 在 provider adapter 调用前预留完整 ¥0.10；本次执行消耗不超过该硬上限。实际请求的规范化白名单 JSON 通过 2,048 字节上限检查；审计未保存请求正文、结构化回答正文、API Key 或法规内容。只有经 SHA 绑定的程序生成合成 DOCX 候选片段进入白名单，没有真实招标文件、个人/客户信息或法规正文外发。
- 结构化结果与流程证据：Qwen 响应通过供应商结构化输出及本地完整 Schema 校验；只读断言确认 `model_analysis` artifact 的响应哈希与该次审计一致，存在非空模型 findings，且至少一条已并入 merged findings；模型没有输出法律证据 ID。本地法规 RAG 仍执行且其结果保留在本地。Edge 流程的持久化断言确认运行状态 `result_published`、报告格式包含 DOCX/PDF；人工复核后恢复 Checkpoint，没有再次调用模型。
- 证据文件保存调用元数据和运行状态，不保存原始模型请求/响应内容。正式源码 Full 的 570 项证据继续有效：在线运行前后 14 个源码/测试文件 manifest 指纹不变；本次只需对之后的任务证据与状态文档执行 Quick。

## TASK0021-005：GitHub 交付与归档收尾

- 代码提交 `19a29fa0e62b6dc57d4493dc111f56194199e51c` 已推送至 `work/TASK-0021`。GitHub Actions [`verify` Run 38707492669](https://github.com/w186www/Tender-Review/actions/runs/38707492669) 对应的 `head_sha` 与提交完全一致，event 为 `push`，最终 `completed/success`：`impact`、`baseline`、`postgres`、`ingestion`、`verify-required` 全部 success；`quick` 在 Full 模式下按 workflow 条件合法 skipped。没有将运行中或跳过的 Job 计为通过。
- 代码提交的远端 Full CI 已通过（见上）。先行归档证据提交 `cbac7fcab2c21a509b8612ffdfe75d63290754a5` 对应 GitHub Actions [`Quick Run 38709453239`](https://github.com/w186www/Tender-Review/actions/runs/38709453239) `completed/success`：`impact`、`quick`、`verify-required` success；`baseline`、`postgres`、`ingestion` 按文档 Quick 条件合法 skipped。当前完成态归档提交将任务文件移入 `tasks/completed/`；其自身 Quick/CI 待核验，M3B 在核验成功前暂保持 `in_progress`。

## 可重复本地命令

```powershell
./scripts/verify.ps1 -Mode Quick
./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_bailian_qwen_adapter.py','tests/test_task0021_online_gateway.py','tests/test_model_adapter_conformance.py','tests/test_model_gateway_contracts.py','tests/test_model_gateway_security.py','tests/test_model_response_boundaries.py','tests/test_review_configurations.py')
./scripts/verify.ps1 -Mode Full
./.venv/Scripts/python.exe scripts/run_task0011_e2e.py
```

真实供应商流程仅在当前 Codex 进程能看到本机安全注入的北京地域 API Key 与 Workspace ID 后启动；只运行一次在线 Edge E2E，不额外 smoke、不重试、不重跑。见[DEC-002](../decisions/DEC-002-qwen-demo-authorization.md)与[在线演示指南](model-gateway-online-demo.md)。
