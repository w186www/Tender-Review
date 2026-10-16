# TASK-0027 验证记录（DEC-007 完整能力 · 验收前阻断问题处置）

工作树：`bidding-compliance-agent-TASK-0027`，分支 `work/TASK-0027`，基线 HEAD `fced54b`
（本轮改动未提交，由用户复核后自行提交）。

- 环境：仓库工作树内无 `.venv`，统一使用
  `D:/自由项目/招标审核/bidding-compliance-agent-TASK-0021/.venv/Scripts/python.exe`；
  `PYTHONPATH=<repo>/src;<repo>/scripts`（Windows 分号）。
- 所有测试都在 `--basetemp=.verification/<id>` 下执行；无任何真实付费供应商调用
  （未访问百炼/DashScope），未执行任何部署或容器操作（唯一一次 compose 相关动作是只读的
  `docker compose config` 本地解析，见第二节），线上 `https://47.83.132.211`
  保持 `DEPLOY_REVIEW_MODE=offline` 未被触碰。
- 无 Live 网络：所有供应商交互都走显式 `httpx.MockTransport` / 合成 `BaseTransport`。

## 一、本轮改动的验收点与对应测试

| # | 验收前阻断问题 | 实现 | 测试证据 |
|---|---|---|---|
| 1 | compose 注入真实模型变量 | `docker-compose.demo.yml` 新增 `x-real-model-environment` 锚点，仅合并进 `api.environment`（worker/init/nginx 不注入）；全部值 `${VAR:-}` 可选，留空仍离线启动；`deploy/demo.env.example` 补注释占位 | `tests/test_task0027_deploy_compose.py`（5 项：api 全变量、其余服务零注入、模板无真实值、离线入口不受影响、前端模式串） |
| 2 | 线上真实模式必须要求预构建索引 | `real_embedding_runtime.require_prebuilt_vector_index()`；`AuthorizedRetrieverFactory(allow_build=False)` 为默认，API 装配显式传 False；维护命令 `scripts/prebuild_legal_vectors.py` 仍直接构建/续建 | `tests/test_task0027_full_vector_index.py`（缺索引 → `RuntimeError`、未完成/校验失败 → `ValueError`，均零 transport 调用、零账本消耗；维护命令 dry-run 仍可规划全量） |
| 3 | 预构建与 API 的身份一致性校验 | `planned_build_id` 绑定 embedding 身份+发布版本+条款覆盖；API 侧再校验 manifest 的 identity/publication/revision/coverage；账本 scope 仍绑定静态白名单与注册表路径 | 同上（发布版本、embedding 身份、modelstate 卷、账本 scope 四种不一致各自被拒） |
| 4 | 撤销授权真正生效 | `FileAuthorizationRegistry` 按文件 mtime/size 重读（`threading.Lock`）；`RealRuntimeAuthorization.allowed_document_source` 提供实时视图；`_freeze_run`/`_invoke` 与 `AuthorizedTenderMinimizer` 每次判定重解析 | `tests/test_task0027_per_file_authorization.py`（进程内注册表看见外部 approve/revoke；engine 冻结门禁与共享门禁；minimizer 下一次调用拒绝；gateway 级：撤销后第二次请求 0 次供应商外发、账本 llm_calls 仍为 1） |
| 5 | 前端在线模式说明 | `src/frontend/src/app.tsx` 新增 `dec007-real-qwen` 分支（授权范围 + 逐文件白名单 + 本地检索/人工复核），保留 `offline-deterministic`/`online-qwen`/`dec005-real-qwen`；`Dockerfile.web` 与 `deploy/demo.env.example` 注释同步 | 见第四节前端检查；`tests/test_task0027_deploy_compose.py` 固定模式串存在 |
| 6 | 800 批上限边界 | `AUTHORIZATION_LIMITS[DEC-007].embedding` 400 → 800 | `tests/test_task0027_budget_boundaries.py`（800 允许/801 拒绝；LLM 300/301；¥30 耗尽即拒绝；失败与未知用量保留预留且不自动补发） |
| 7 | 文档补齐 | 本文件、`DEC-007` 修订（800 批、不拆分建库/查询账本、不重置 DEC-005/006）、`deploy/README-demo.md` 逐文件授权运维步骤、`PROJECT_STATE.md`、`CHANGELOG.md`、任务 YAML 证据 | `scripts/verify_repo.py`（任务证据路径存在性） |

## 二、compose 注入边界的真实解析证据（本机 compose 仅解析，未创建任何容器）

```bash
docker compose -f docker-compose.demo.yml --env-file deploy/demo.env.example --profile init \
  config   # exit 0
```

解析结果（`docker compose config` 输出，含 `--profile init` 以纳入 init 服务）：

- 7 个服务（api/worker/init/nginx/postgres/minio/clamav）全部可解析，退出码 0；YAML 合并锚点
  `<<: [*app-environment, *real-model-environment]` 被接受。
- **仅 api** 持有 10 个真实模型变量（`DASHSCOPE_API_KEY`、`BAILIAN_WORKSPACE_ID`、
  `DEC007_AUTHORIZATION_ID/REGISTRY/LEDGER_PATH/MODEL_AUDIT_PATH/ACTOR`、
  `DEC005_AUTHORIZATION_ID/ALLOWED_DOCUMENT_SHA256/ALLOWED_SYNTHETIC_SHA256`），
  且全部解析为**空字符串**（模板未设值时可选、不报错）。
- worker / init / nginx / postgres / minio / clamav：真实模型变量 **0 个**。
- `DEPLOY_REVIEW_MODE` 只出现在 api，值为 `offline`。

未执行 `docker compose up` / `run` / 任何容器或部署操作；线上 `47.83.132.211` 未触碰。

## 三、后端测试真实结果
命令模板（Git Bash，`$PY` 为上述 venv python）：

```bash
PYTHONUTF8=1 PYTHONPATH="$PWD/src;$PWD/scripts" "$PY" -m pytest \
  --basetemp=.verification/<id> -q <测试文件…>
```

| 运行 | 文件 | 结果 |
|---|---|---|
| 1 | `tests/test_task0027_budget_boundaries.py` | 5 passed（最慢一项 800 批边界 9.03s） |
| 2 | `tests/test_task0027_deploy_compose.py` | 5 passed |
| 3 | `tests/test_task0027_per_file_authorization.py` | 14 passed |
| 4 | `tests/test_task0027_full_vector_index.py` | 17 passed（含维护命令 dry-run 实测全库 3120 条 → 3112 可嵌入、8 条超长、312 批） |
| 5 | 回归批次：`test_real_ai_runtime.py`、`test_authorized_runtime.py`、`test_task0023_embedding.py`、`test_semantic_batching.py`、`test_model_gateway_security.py`、`test_model_gateway_contracts.py`、`test_legal_vector_index.py`、`test_model_adapter_conformance.py` | 96 passed |

静态检查：

```bash
"$PY" -m ruff check src scripts tests   # All checks passed!
"$PY" -m mypy src                       # Success: no issues found in 104 source files
"$PY" scripts/verify_repo.py            # PASS（修复任务证据路径后）
```

（首轮 ruff 报 5 项（2×E501、B007、2×S608）已按规则修正：参数化 SQL、去掉未用循环变量、折行。
首轮功能失败 2 项（minimizer 全量撤销消息、sqlite WITHOUT ROWID 无 rowid）已在测试中修正。）

## 四、前端检查真实结果

目录 `src/frontend`（现有 `node_modules`，未执行 `npm ci`）：

| 检查 | 命令 | 结果 |
|---|---|---|
| Biome | `npm run lint` | `Checked 21 files in 37ms. No fixes applied.` |
| TypeScript | `npm run typecheck` | 通过（无输出） |
| 单元测试 | `npm run test` | `Test Files 2 passed (2)` / `Tests 6 passed (6)`，2.14s |
| 生产构建 | `npm run build` | `dist/assets/index-ByR32IT9.js 348.06 kB │ gzip: 105.33 kB`、`dist/assets/index-DhBYvR6a.css 17.96 kB`、`built in 223ms` |

## 五、官方验证入口（`scripts/verify.ps1`）真实结果

两条命令都在仓库根执行，前置 `PATH` 加入 venv 的 `Scripts`（`tests/test_verification_modes.py`
会跑内层 `verify.ps1`，需要 PATH 上的 python 具备 `jsonschema`，这是既有环境要求）：

```bash
VENVPY=D:/自由项目/招标审核/bidding-compliance-agent-TASK-0021/.venv/Scripts/python.exe
# Focused（本轮改动的 4 个测试文件）
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Focused \
  -TestPaths @('tests/test_task0027_full_vector_index.py', \
               'tests/test_task0027_per_file_authorization.py', \
               'tests/test_task0027_budget_boundaries.py', \
               'tests/test_task0027_deploy_compose.py') \
  -PythonExecutable '$VENVPY'"
```

Focused 实测：`[1/7]` 仓库/契约/任务证据 PASS；`[2/7]` ruff `All checks passed!`；
`[3/7]` mypy `Success: no issues found in 104 source files`；`[4/7]` 前端（api:check / lint /
typecheck / 2 文件 6 用例 / build）通过；`[5/7]` **41 passed in 20.41s**；
输出 `PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence.`

```bash
# Full（默认门禁）
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Full -PythonExecutable '$VENVPY'"
```

Full 实测（日志 `.verification/task0027-full.log`，退出码 0）：

| 步骤 | 结果 |
|---|---|
| `[1/7]` 契约/示例/State/任务证据（含 legal·ingestion·rule 生成一致性） | PASS |
| `[2/7]` ruff | `All checks passed!` |
| `[3/7]` mypy `src` | `Success: no issues found in 104 source files` |
| `[4/7]` 前端：OpenAPI 客户端一致、lint、typecheck、单元测试、build | `Checked 21 files` / `2 passed (2) files, 6 passed (6) tests` / `built` |
| `[5/7]` 后端全量回归 | **702 passed, 6 warnings in 373.77s (0:06:13)** |
| `[6/7]` 真实启动 + loopback HTTP | `PASS: live HTTP health=200, missing=404, request IDs matched; port=51143` |
| `[7/7]` 真实鉴权后端与项目生命周期 | `PASS: real HTTP login, project create/read/version, logout/revocation; child stopped` |

6 条 warning 均为 `tests/test_verification_modes.py` 在 Windows 下读取内层 `pwsh` 子进程输出时的
`UnicodeDecodeError` 线程告警（子进程输出编码），测试本身全部通过；这是既有环境现象，本轮未改动
验证脚本。

文档变更（`TASK-0027-validation.md`、`PROJECT_STATE.md`、`CHANGELOG.md`、任务 YAML 证据）发生在
Full 之后，按 `docs/development/testing-standard.md` 只补跑 Quick 核对：见第六节。

## 六、文档变更后的 Quick 核对

在 Full 之后仅发生工程记录/证据类文档变更（本文件、`PROJECT_STATE.md`、`CHANGELOG.md`、任务 YAML
证据路径），按 `docs/development/testing-standard.md` 只补跑 Quick：

```bash
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Quick -PythonExecutable '$VENVPY'"
```

实测输出：`PASS: contracts, examples, generated State and scoped task evidence` +
`PASS: Quick repository/contract/secret checks only; no runtime tests or startup checks executed.`
（代码/契约/依赖/测试/脚本在 Full 之后未再变化。）

Full 之后另有一次 **compose 注释**修改（把锚点说明改写为"`${VAR:-}` 未设置即空值、无告警无报错"
的准确表述），因此额外补跑与被改文件直接相关的两项：

```bash
docker compose -f docker-compose.demo.yml --env-file deploy/demo.env.example --profile init \
  config --quiet   # exit 0（仅解析）
"$PY" -m pytest --basetemp=.verification/task0027-final1 -q tests/test_task0027_deploy_compose.py
# 5 passed
```

补充实测：`${VAR:-}` 形式的 10 个新变量在**完全没有 env 文件**时也不产生
`variable is not set. Defaulting to a blank string` 告警（对照：仓库既有的 `${VAR}` 形式变量会告警），
即"全部留空 → 无告警、无报错、离线启动"。

## 七、与本轮改动相关的边界与如实说明
- **未执行**：远程 GitHub Actions（本轮未提交、未推送，CI 结果不存在）；任何真实付费供应商
  调用（任务禁止）；任何容器/部署操作（任务禁止）；Playwright 浏览器 E2E（需要隔离后端与
  真实浏览器，属独立验收项，未在本轮运行）。
- **DEC-007 授权本身仍为 proposed**：本轮只完成代码、测试与文档；首次真实调用需单独批准。
- **本地账本不是防回滚方案**：`verify_ledger_continuity` 只挡住"审计存在而账本被删/空"的
  明显情形，协调回滚两者无法检测（既有结论，未变）。
- **compose 未实际启动**：`docker-compose.demo.yml` 的注入边界由解析 YAML 的测试与本机
  `docker compose config`（只读解析，退出码 0）固定；未执行 `docker compose up` / `run`，
  未创建任何容器（任务禁止容器操作）。

---

# 第二轮：本轮硬门禁接线 + 独立隔离验证入口（2026-10-16）

基线 HEAD `37e380f`（第一轮改动已在上一提交中）；本轮改动同样**未提交**，由用户复核后自行提交。

- 用户 2026-10-16 批准方案 A：现有 SQLite 原子预算账本 + 装配层固定本轮额度；
  **不新增租约锁、不修改账本表结构、不永久写入收紧上限**。
- 本轮上限（累计口径，写进隔离验证入口的常量，不改授权总额度）：
  `llm_limit=4`、`embedding_limit=322`（312 已用 + 最多新增 10）、`total_cny=Decimal("2")`
  （含已结算的 ¥0.1035070）。
- **零供应商调用 / 零容器操作 / 零部署**：未访问百炼或 DashScope，未设置真实
  `DASHSCOPE_API_KEY`，未触碰 `47.83.132.211`、未改动线上容器或镜像、未删除或重置任何
  `modelstate` 账本与索引。唯一的网络动作是本机回环 `127.0.0.1:8124` 上的健康探针替身
  （已停止，见第五节）。

## 一、改了什么

| 文件 | 改动 | 性质 |
|---|---|---|
| `src/bidding_compliance/services/real_ai_runtime.py` | `create_dec005_gateway` 新增 `llm_limit` / `embedding_limit` / `total_cny` 三个可选参数并透传到 `Dec005BudgetLedger`；省略即等于授权上限（构造期上界仍是 `AUTHORIZATION_LIMITS[DEC-007]` 的 300/800/¥30） | 装配层传参，账本语义未改 |
| `scripts/task0027_real_ai_validation_app.py`（新增） | 一次性容器用装配：同一 `-modelstate` 卷、同一发布/修订与 embedding 身份与授权 scope、`allow_build=False`（缺索引即拒绝）；上限固定为代码常量；`--preflight` 本地/只读预检查；拒绝非 DEC-007 身份、缺凭据、基线不符、scope 不符、公网 API 不可达、缺操作者确认 | 新入口 |
| `scripts/task0027_ledger_baseline.py`（新增） | 只读账本核对（`file:...?mode=ro`）：输出 LLM 次数 / Embedding 批数 / 累计费用 / 未结算预留，期望值不符退出码 2 并提示不得重置账本 | 新运维工具 |
| `tests/test_task0027_round_limits.py`（新增，8 项） | 六组反例（见第二节） | 测试 |
| `tests/test_task0027_validation_entry.py`（新增，16 项） | 上限常量不可放宽、基线脚本只读、预检查各拒绝路径、装配接线 | 测试 |
| `tests/test_task0027_deploy_compose.py` | 新增 1 项：`IMAGE_TAG` 是可选的按命令覆盖，默认仍是 `:demo`（验证镜像不会替换线上镜像） | 测试 |
| `deploy/README-demo.md` | 新增 8.4：三步顺序、独立镜像命令、基线核对、方案 A 边界 | 文档 |
| `tasks/active/TASK-0027-real-ai-full-capability.yaml` | 新增局部验收 `TASK0027-008` 与 handoff 记录 | 任务记录 |

`knowledge/legal/**`、`config/legal/**`、`contracts/**`、`tests/completed/**`、
`legal/retrieval.py`、`services/evidence_checker.py`、`AUTHORIZATION_LIMITS` 均未改动。

## 二、反例测试与验收要求的对应

| # | 要求 | 测试 | 关键断言 |
|---|---|---|---|
| 1 | 第 5 次 LLM 预留被拒（前 4 次允许） | `test_four_llm_requests_are_allowed_and_the_fifth_is_refused_before_any_transport` | 4 次经真实 `create_dec005_gateway` 成功且 transport 恰好 4 次；第 5 次 `count exhausted` 且 transport 仍为 4（**门禁在供应商请求之前**） |
| 2 | 第 11 次新增 embedding 被拒（第 322 次累计） | `test_eleventh_new_embedding_batch_is_refused_at_322_cumulative` | 宽上限实例先写入 312 批历史（结算合计 ¥0.1035070），收紧实例 10 批允许、第 11 批 `count exhausted`、transport 仍为 10 |
| 3 | 累计 ¥2 耗尽即使次数仍有余量也拒绝 | `test_cumulative_two_yuan_refuses_even_while_the_counts_still_have_headroom`、`test_the_cumulative_ceiling_is_inclusive_and_binds_before_the_embedding_count` | 已花 ¥1.95 时 LLM（0/4）与 embedding（300/322）双双以 `budget exhausted` 拒绝；¥1.80 时两批各 ¥0.10 恰好到 ¥2.00 允许、第三批拒绝（含边界语义） |
| 4 | 失败/未知用量保留且不自动补发 | `test_failed_and_unknown_usage_reservations_consume_the_round_quota_without_a_resend` | 首次传输失败、第二次响应无 usage：transport 各 1 次（**无自动重发**），两次预留保留在额度内（322 批只余 8 批），`unsettled_requests=2` |
| 4b | 计数跨实例/重启共享、失败不清零 | `test_counters_survive_new_instances_and_failures_in_one_shared_file`、`test_the_last_llm_slot_is_granted_to_exactly_one_of_two_instances` | 新实例/重开实例看到同一累计（4 次 LLM、¥0.751）；两个进程竞争最后一个名额时恰好一个 `granted`、另一个 `budget_exceeded`，上限从不被突破 |
| 5 | 不允许绕过（方案 A 的边界如实记录） | `test_option_a_boundary_wide_and_tight_instances_share_one_counter_file` + `test_no_environment_variable_or_cli_option_can_raise_the_round_ceilings` + `test_a_ceiling_that_is_not_strictly_tighter_than_dec007_is_refused` | 收紧实例拒绝后，宽上限实例确实仍能打开同一账本（**这就是已记录的边界**，靠运维规则约束），但两实例共享同一计数且**账本只增加 `authorization`/`requests` 两张表、没有写入收紧上限**；本轮装配上限不由环境变量或命令行决定，且拒绝不比 DEC-007 更严的取值 |
| 6 | 门禁在任何供应商请求之前生效 | 同 #1、#2 | 拒绝时 transport 调用数不增加、账本计数不增加 |
| 7 | 额外：装配层确实透传（不是只在账本层可用） | `test_serving_assembly_binds_the_round_ceilings_and_refuses_to_build_the_index` | 隔离入口的 `build_app` 把 4/322/¥2 交给真实 `Dec005BudgetLedger`、`allow_build=False`、账本/审计/注册表路径来自环境解析，引擎拿到可调用的实时白名单视图 |

隔离验证入口的其余拒绝路径（缺 DEC-007 身份、缺凭据、基线漂移、scope 不符、公网 API
不可达/非 200、缺操作者确认）各自在 `tests/test_task0027_validation_entry.py` 中单独断言；
基线脚本的只读性以**逐字节比对文件内容不变**证明，漂移时退出码 2 且文件不变。

## 三、真实命令与真实数字

```bash
VENVPY=D:/自由项目/招标审核/bidding-compliance-agent-TASK-0021/.venv/Scripts/python.exe
SRC=$(cygpath -w "$PWD/src"); SCR=$(cygpath -w "$PWD/scripts")
```

| 运行 | 命令 | 结果 |
|---|---|---|
| ruff | `"$VENVPY" -m ruff check src scripts tests` | `All checks passed!` |
| mypy | `"$VENVPY" -m mypy src` | `Success: no issues found in 104 source files` |
| 新测试 A | `pytest --basetemp=.verification/t27-round-10 -q tests/test_task0027_round_limits.py tests/test_task0027_validation_entry.py` | **24 passed**（8 + 16） |
| 相关回归 B | `pytest --basetemp=.verification/t27-round-16 -q tests/test_task0027_round_limits.py tests/test_task0027_validation_entry.py tests/test_task0027_deploy_compose.py tests/test_task0027_budget_boundaries.py tests/test_task0027_per_file_authorization.py` | **49 passed in 72.49s** |
| 相关回归 C | `pytest --basetemp=.verification/t27-round-15 tests/test_task0023_embedding.py tests/test_semantic_batching.py tests/test_model_gateway_security.py tests/test_model_gateway_contracts.py tests/test_legal_vector_index.py tests/test_model_adapter_conformance.py -o addopts= -v` | **75 passed in 6.31s** |
| 仓库检查 | `"$VENVPY" scripts/verify_repo.py` | `PASS: contracts, examples, generated State and scoped task evidence` |

官方入口（`scripts/verify.ps1`，日志 `.verification/t27-focused.log`）：

```bash
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Focused \
  -TestPaths @('tests/test_task0027_round_limits.py','tests/test_task0027_validation_entry.py', \
               'tests/test_task0027_budget_boundaries.py','tests/test_task0027_per_file_authorization.py', \
               'tests/test_task0027_deploy_compose.py') -PythonExecutable '$VENVPY'"
```

实测：`[1/7]` 契约/生成/任务证据 PASS；`[2/7]` ruff `All checks passed!`；
`[3/7]` mypy `Success: no issues found in 104 source files`；`[4/7]` 前端（
`Checked 21 files`、2 文件 6 用例、`built`）；`[5/7]` **49 passed in 74.19s**（最终代码；
该次之前另有一次 `49 passed in 72.74s` 的运行，两者都在本轮改动之后、仅差一处 CLI 默认值修正）；
输出 `PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence.`

> 本轮按用户当次指令只跑 `ruff` / `mypy` / 新增测试与相关 Focused，**未重跑 Full**（上一轮的
> Full 702 项对应上一提交）。因此不得把本轮称为"最终代码候选已通过 Full"。

## 四、两个入口的 CLI 实测（本机，全部本地/回环，无供应商）

用一次性合成账本 `.verification/t27-cli/dec007-budget.sqlite3`（312 批、¥0.1035070）与
本机回环健康探针替身（`127.0.0.1:8124`，已停止）实测：

```bash
# A) 基线核对（与文档一致）
"$VENVPY" scripts/task0027_ledger_baseline.py --ledger .verification/t27-cli/dec007-budget.sqlite3
# llm_calls: 0 (expected 0) / embedding_batches: 312 (expected 312) /
# charged_or_reserved_cny: 0.1035070 (expected 0.1035070) / unsettled_requests: 0 (expected 0)
# PASS: the ledger matches the documented pre-round baseline.        exit=0

# B) 预检查（含操作者 offline 确认；本地 health 替身返回 200 {"status":"ok"}）
"$VENVPY" scripts/task0027_real_ai_validation_app.py --preflight \
    --online-api-url http://127.0.0.1:8124 --online-api-offline-verified
# round_limits: {"llm_limit": 4, "embedding_limit": 322, "total_cny": "2"}；ledger 四项=基线；
# vector_index: "not pinned in this preflight..."；PASS: preflight complete; nothing was
# reserved, sent or written.                                          exit=0

# C) 缺操作者确认
"$VENVPY" scripts/task0027_real_ai_validation_app.py --preflight --online-api-url http://127.0.0.1:8124
# STOP: operator confirmation missing: ... pass --online-api-offline-verified.   exit=2

# D) 人为漂移（新增 1 次未结算 LLM 预留）后核对基线
"$VENVPY" scripts/task0027_ledger_baseline.py --ledger .verification/t27-cli/dec007-budget.sqlite3
# STOP: ... llm_calls: observed 1, expected 0; unsettled_requests: observed 1, expected 0;
# charged_or_reserved_cny: observed 0.3535070, expected 0.1035070
# Stop the round and report ... Do not delete, replace or reset the ledger.      exit=2
```

预检查**不产生任何写入**：运行后仓库内 `.verification/private` 仍不存在（`ls` 报
`No such file or directory`），账本字节不变。

## 五、边界与未做到/不确定的部分

- **方案 A 的边界（用户要求如实记录）**：账本文件只存计数，上限是进程内参数。若某个进程被
  显式以 300/800/¥30 打开**同一账本**，账本本身不会阻止它；本轮靠"只有一个真实模型验证实例"
  的运维规则约束，**不提供**跨任意进程的全局收紧锁（选项 C 未实现，不得如此宣称）。
- **收紧上限不落盘**：本轮结束后同一账本上的 300/800/¥30 仍可用；测试以"账本仍只有
  `authorization`/`requests` 两张表 + 重开实例的 limits 仍是 300/800/30"固定这一点。
- **入口启动的前置**：隔离装配的出站最小化器要求至少一个已登记文件，因此 `manage_authorization.py
  approve`（第二步）必须早于启动验证实例；`--preflight` 本身在 approve 之前即可运行。
- **"公网 API 仍为 offline" 的确认方式**：容器内只能探测 `/api/v1/health` 是否可达且
  `status=ok`（本轮实测过不可达与非 200 两种拒绝）；"该进程是 offline" 由操作者用
  `docker compose ... exec api printenv DEPLOY_REVIEW_MODE` 人工确认后传入
  `--online-api-offline-verified`（无环境变量回退）。仓库不给未认证端点暴露运行模式，
  因此这一步**不是**纯技术门禁。
- **未执行的**：Full 与远程 CI（用户要求本轮不重跑/本轮未提交）；任何容器构建或
  `docker compose run`（任务禁止容器操作，文档已给出线上命令但未执行）；任何真实供应商调用
  （**本轮零付费调用**，未设置真实 DASHSCOPE_API_KEY，未访问百炼/DashScope）；
  预构建索引的实机校验（需要 `--publication-id/--revision-id` 与线上 `modelstate` 卷，未在本机运行）。
- **不确定**：`total_cny=2` 的"累计"口径按账本的"已结算 + 在途预留"求和解释（与
  `summary()["charged_or_reserved_cny"]` 一致），这也是 DEC-007 文档既有口径；若用户希望
  "仅已结算"口径，需要改账本语义，本轮未做。

