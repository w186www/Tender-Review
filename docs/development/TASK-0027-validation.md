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


---

# 第三轮：验证入口强制索引身份 + 宿主机侧离线证据（2026-10-16）

本轮回答两条"最小修正"：① 预构建索引校验不许再是可选项、也不许未指定发布/修订；
② online/offline 不再只靠操作者人工标志，必须有宿主机侧实际检查的证据文件。
**未调用任何真实供应商、未访问百炼/DashScope、未设置真实 key、未触碰线上服务器 47.83.132.211、
未挂 Docker Socket、未给任何容器 Docker 权限**；本轮全部为本机代码与合成数据测试。

## 一、改了什么

1. `scripts/task0027_real_ai_validation_app.py`
   - `--publication-id` / `--revision-id` 变为 **argparse 必需参数**（缺席即用法错误、退出码 2），
     并且在 `run_preflight`/`verify_prebuilt_index` 内再次拒绝空值：**没有默认值，也没有
     "not pinned" 分支**（旧文案已删除）。
   - 新增 `verify_prebuilt_index`：读取 `modelstate` 卷内 `vector-manifest.json`，把传入的
     publication/revision 与 manifest 记录值**逐一比对**，并校验
     `legal_snapshot_sha256`（对冻结语料 `index_hash`）、`embedding_identity.identity_sha256`
     （对本装配的 embedding 身份，非 mock）、`item_count`（冻结语料 3112 且 pin 为常量）、
     `source_item_count`（3120 且 pin 为常量）、`coverage_sha256`（对计划条款集合），
     以及索引库中该构建的 `status=complete`、身份/发布/计数/`manifest_sha256` 一致、条目数相等。
     索引库以 SQLite `mode=ro` 打开：**不创建、不写入**（不改 `legal-vectors.sqlite3`，
     也不因缺文件而"初始化"它）。
   - 全部一致时 `--preflight` 打印一行可断言结果：
     `prebuilt index verified build_id=<64 位> item_count=3112 source_item_count=3120
     publication=<id> revision=<id>`，随后 `PASS: preflight complete; ...`。
     任一不一致 → 退出码 2、不启动、零供应商请求、**不打印该行**。
   - 新增 `verify_host_offline_evidence`：`--preflight` 现在**同时**要求人工标志与证据文件
     （缺任一项即退出码 2）；证据窗口 60–3600 秒、默认 600 秒，可用
     `--host-offline-evidence-max-age-seconds` 或 `DEC007_HOST_OFFLINE_EVIDENCE_MAX_AGE_SECONDS`
     调整；当前 api 容器 ID 取 `DEC007_API_CONTAINER_ID`/`--api-container-id`，compose 项目名取
     `DEPLOY_COMPOSE_PROJECT`/`--compose-project`，与证据比对。
   - 所有本地检查（含索引身份、证据）排在唯一一次只读健康探测之前：拒绝时**连探测都不发生**。
   - `make_probe_client()` 作为可注入的健康探测客户端工厂（CLI 与测试共用一条代码路径）。
2. 新增 `deploy/verify_api_offline_mode.sh` + `deploy/verify_api_offline_mode.py`（宿主机侧、
   标准库 only，兼容宿主机 python3.10）：只用只读 Docker 命令（`docker compose ... ps`、
   `docker ps`、`docker inspect`）产出证据 JSON；详见 3.、4.。
3. `docker-compose.demo.yml`：api 服务新增 `DEPLOY_COMPOSE_PROJECT: tender-review-demo`
   （与顶层 `name:` 相同、非密钥），一次性验证容器继承它；`tests/test_task0027_deploy_compose.py`
   固定该常量且其他服务零注入。
4. 文档：本文件、`deploy/README-demo.md` 8.4（证据步骤 + 必需项 + verdict/退出码）、
   `CHANGELOG.md`、`PROJECT_STATE.md`、任务 YAML（`TASK0027-009`）。

## 二、宿主机侧证据脚本：产出、白名单与判定

- 产物：`/opt/tender-review-private/evidence/api-offline-<UTC 时间戳>.json`（可用 `--evidence-dir` 改）。
  字段（**严格白名单，键集合由测试固定**）：`schema_version`、`script`、`docker_binary`、
  `checked_at`、`compose_project`、`compose_file`、`api`（service/容器名/64 位容器 ID/镜像引用/
  镜像 ID/**实际生效的 `DEPLOY_REVIEW_MODE`**/`APP_ENV`/入口/主进程命令/state/running/health）、
  `execution_instances`（扫描容器数 + `authorized-real` 实例列表）、`checks`、`failures`、`verdict`。
- **不打印任何密钥、不输出完整环境变量列表**：容器环境只在同一个循环里取出 `DEPLOY_REVIEW_MODE`
  与 `APP_ENV` 两个白名单值，其余丢在循环内；测试注入 `DASHSCOPE_API_KEY=sk-live-...` 与 `PATH=...`，
  断言证据文件与终端输出中**都不出现**这些值或键名。
- 判定与退出码：`ok`=0（mode 为 offline、容器 running、镜像与入口/命令为预期值、无第二个
  `authorized-real` 实例）；`untrusted`=3（api 以 authorized-real 运行 / 未运行 / 镜像或入口不符 /
  存在第二个 running 的 authorized-real 实例）；`unknown`=2（inspect 失败、字段缺失、容器不存在）。
  两种非 `ok` 都**立即停止、不得发起供应商调用**，证据文件仍写出以便审计。
- 只读性由测试固定：注入的执行器记录每次调用，断言全部满足 `is_read_only`（`compose ps`/`ps`/`inspect`）
  且参数中不出现 run/exec/create/start/stop/rm/kill/up/down。`--fixture-dir` 回放预置
  `compose-ps.json`/`docker-ps.json`/`inspect-<id>.json`（测试与离线复核用，`docker_binary` 记为 `fixture:<dir>`）。

## 三、新增/更新的反例测试（全部合成、无真实 Docker、无供应商）

- `tests/test_task0027_host_offline_evidence.py`（20 项，新建）：ok / untrusted（第二个 authorized-real
  实例、api 为 authorized-real、停止或镜像不符、ENTRYPOINT 被覆盖）/ unknown（缺 mode 字段、
  inspect 失败、api 容器不存在）三类 verdict；只读调用审计；fixture 文件名映射；真实 subprocess
  执行器对失败 docker 二进制的容错；白名单键集合；密钥不外泄；以及 consumer 侧严格加载器
  （非 ok verdict、过期、未来时间、容器/项目不一致、多余字段、缺字段、窗口越界、无证据路径、
  非法 JSON、无时区时间戳）。
- `tests/test_task0027_validation_entry.py`（28 项）：原有用例迁移到"合成语料 + 真实构建的预构建索引 +
  真实生成的宿主证据"夹具；新增 publication/revision **必需**（空值/缺参）、
  `prebuilt index verified` 的 CLI 打印断言与**反例不打印**断言、manifest 的发布/修订/快照/身份/
  `item_count`/`source_item_count` 不一致各自被拒（用 `VectorIndexManifest.create` 造出**摘要自洽**的
  篡改清单，避免只测到 digest 校验）、缺 manifest / 缺索引库**不创建任何文件**、
  索引检查对账本/manifest/索引库**零写入**、`publication/revision` 与 manifest 不一致时
  **连健康探测都没有发生**（零请求）等。
- `tests/test_task0027_deploy_compose.py`：新增 compose 项目名常量与顶层 `name:` 一致、其他服务零注入。

## 四、真实命令与真实数字（本机）

```
$ "D:/自由项目/招标审核/bidding-compliance-agent-TASK-0021/.venv/Scripts/python.exe" -m ruff check src scripts tests
All checks passed!

$ ... -m ruff check src scripts tests deploy     # 额外把 deploy 也纳入（官方门禁不含 deploy）
deploy\demo_init.py 与 deploy\verify_deployment.py 共 9 条**既有**告警（本轮未触碰这两个文件）；
本轮新增/修改的 deploy/verify_api_offline_mode.py、scripts/、tests/ 全部 0 告警。

$ ... -m mypy src
Success: no issues found in 104 source files

$ ... scripts/verify_repo.py
PASS: contracts, examples, generated State and scoped task evidence

$ ... -m pytest --basetemp=.verification/t27-min2-15 \
    tests/test_task0027_validation_entry.py tests/test_task0027_host_offline_evidence.py tests/test_task0027_deploy_compose.py
55 passed in 88.53s

$ ... -m pytest --basetemp=.verification/t27-min2-13 tests/test_task0027_validation_entry.py \
    tests/test_task0027_round_limits.py tests/test_task0027_budget_boundaries.py \
    tests/test_task0027_per_file_authorization.py tests/test_task0027_deploy_compose.py \
    tests/test_task0027_full_vector_index.py
79 passed in 111.66s

$ ... -m pytest --basetemp=.verification/t27-min2-14 tests/test_task0023_embedding.py \
    tests/test_semantic_batching.py tests/test_model_gateway_security.py tests/test_model_gateway_contracts.py \
    tests/test_legal_vector_index.py tests/test_model_adapter_conformance.py tests/test_real_ai_runtime.py \
    tests/test_task0021_online_gateway.py
90 passed in 6.56s
```

官方入口（`scripts/verify.ps1`，日志 `.verification/t27-focused3.log`）：

```bash
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Focused \
  -TestPaths @('tests/test_task0027_round_limits.py','tests/test_task0027_validation_entry.py', \
               'tests/test_task0027_host_offline_evidence.py','tests/test_task0027_budget_boundaries.py', \
               'tests/test_task0027_per_file_authorization.py','tests/test_task0027_deploy_compose.py') \
  -PythonExecutable '<venv python>'"
```

实测：`[1/7]` 契约/生成/任务证据 PASS；`[2/7]` ruff `All checks passed!`；
`[3/7]` mypy `Success: no issues found in 104 source files`；`[4/7]` 前端
（`Checked 21 files in 47ms`、2 文件 6 用例、`built`）；`[5/7]` **82 passed in 115.46s**
（同一命令前一次运行为 `82 passed in 125.00s`，两次都在本轮最终代码上）；
输出 `PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence.`

> 按用户当次指令只跑 `ruff` / `mypy` / 新增测试与相关 Focused，**未重跑 Full**（上一轮 Full 702 项
> 对应上一提交）。因此不得把本轮称为"最终代码候选已通过 Full"。

## 五、CLI 端到端实测转录（本机合成语料，无供应商）

合成轮次（3 条条款的冻结语料 + 真实构建的预构建索引 + 由宿主脚本生成的证据，
`.verification/t27-cli2/round`）：

```
=== A) 合法预检查 ===
prebuilt index verified build_id=b6a3b0569d55df93fdd6925c1ef85eaf391ee450f3a46dd8a0e1da50e1740a90 item_count=3 source_item_count=3 publication=pub-2026-10-16 revision=rev-2026-10-16
PASS: preflight complete; nothing was reserved, sent or written.        exit = 0

=== B) 出版/修订与 manifest 不一致 ===
STOP: the prebuilt index belongs to publication/revision (pub-2026-10-16, rev-2026-10-16),
      not to the requested (pub-other, rev-2026-10-16)                     exit = 2（无 verified 行）

=== C) 缺 --revision-id ===
usage: ... error: the following arguments are required: --revision-id     SystemExit = 2

=== D) 只有人工标志、没有证据文件 ===
STOP: the host offline evidence is not acceptable: the host offline evidence is absent at
      ...\gone.json; run deploy/verify_api_offline_mode.sh on the host first   exit = 2

本轮健康探测替身收到的请求数：1（只有 A 通过后到达探测；B/C/D 均为本地拒绝，零网络）
```

宿主机脚本单机实测（fixture 回放，未调用真实 Docker）：正常离线 → `verdict: ok`、退出码 0；
api 的 `DEPLOY_REVIEW_MODE=authorized-real` → `verdict: untrusted`、退出码 3；
缺 `DEPLOY_REVIEW_MODE` → `verdict: unknown`、退出码 2。三种情形都会写出证据文件，
输出中不含注入的 `DASHSCOPE_API_KEY` 值。

## 六、边界与未做到/不确定的部分（本轮新增）

- **证据是内容不是签名**：能运行 `deploy/verify_api_offline_mode.sh` 的人也能写出同样的 JSON；
  预检查校验 verdict、新鲜度与容器/项目标识与当前部署一致，但**操作者仍是被信任的一环**
  （与人工标志同一信任假设）。没有做 HMAC/远程签名：容器内没有可用的可信秘密，
  加了也只会是在同一信任级别上的"防伪"表演。
- **"当前实际"的来源**：容器内不可能读取宿主 Docker 状态（也不允许挂 socket），所以当前 api
  容器 ID 与 compose 项目名分别由 `DEC007_API_CONTAINER_ID`/`--api-container-id`（操作者从
  `$D ps -q api` 或证据文件复制）与 compose 注入的 `DEPLOY_COMPOSE_PROJECT` 提供；
  机器校验的是"证据 ↔ 当前声明"一致、时间新鲜、mode 为 offline。**不宣称**这是纯技术门禁。
- **第二个实例的扫描范围**：脚本枚举 compose 项目容器（`docker compose ps -a --no-trunc --format json`）
  与 `docker ps -aq` 的宿主全部容器，逐只 `docker inspect` 只读**两个**白名单环境值；
  判定"以 authorized-real 模式且 running"。扫描与判定之间的状态变化属常规 TOCTOU 风险，
  以证据时间戳与窗口（默认 10 分钟）收敛。
- **`item_count`/`source_item_count` 常量**：本轮按冻结语料固定为 3112/3120（与
  `tests/test_task0027_full_vector_index.py` 的语料计数一致）；语料变更必须重新测量并修改常量，
  而不是让预检查自动放宽。
- **未执行的**：Full 与远程 CI（用户要求本轮不重跑 / 本轮未提交）；任何容器构建或
  `docker compose run`（任务禁止容器操作）；任何真实供应商调用（**本轮零付费调用**）；
  线上 `--publication-id/--revision-id` 与线上 `modelstate` 卷的实机校验；
  在真实宿主上执行 `deploy/verify_api_offline_mode.sh`（本机只有 fixture 回放）。
- **仍不确定**：线上 ECS 宿主机的 python3 版本（脚本按 3.10 兼容编写，未在宿主验证）；
  证据 JSON 字段后续若扩充，必须同步更新白名单常量与加载器（两侧当前共用同一模块的常量）。

---

# 第四轮：第二实例检测覆盖启动命令/镜像 + 逐文件授权 CLI 改用验证镜像（2026-10-16）

本轮只做用户当次指定的**两处最小修正**（全部本机合成测试：**零付费调用、未触碰线上服务器
47.83.132.211、未挂 Docker Socket、未给任何容器 Docker 权限**）。不做 git 提交，等待复核。

## 一、改了什么

1. **第二个真实模型实例的检测不再只看环境变量**（`deploy/verify_api_offline_mode.py`，
   逻辑同时被 `deploy/verify_api_offline_mode.sh` 调用）。消除已确认盲区：隔离验证容器由
   `scripts/task0027_real_ai_validation_app.py` 启动，其 `DEPLOY_REVIEW_MODE` **可能仍是
   `offline`**，旧判定会漏掉它。现在检查对象是宿主上由只读 `docker ps -aq --no-trunc` 枚举、
   逐个只读 `docker inspect` 的容器（**按容器 ID 排除预期的线上 api 容器本身**：docker 报告的
   api 服务容器 ID 与其 inspect 到的 ID 都排除），除原有“实际生效 `DEPLOY_REVIEW_MODE` 为
   `authorized-real`”外，以下任一条件成立即判 `untrusted`（每条例外写入证据的 `reason`）：
   - 入口/命令中出现 `task0023_real_ai_app`（authorized-real 装配；同时覆盖 `<name>.py` 与
     `<name>:app` 两种写法）；
   - 入口/命令中出现 `task0027_real_ai_validation_app`（隔离验证入口，**即使该容器仍是
     `offline`**）；
   - 入口/命令中出现 `api_entry.py` **且**该容器 `DEPLOY_REVIEW_MODE=authorized-real`；
   - 镜像引用带验证镜像标签（`task0027-validation`）。
2. **无法读取执行身份时判 `unknown`，不再声称“不存在第二个真实模型实例”**（用户明确要求）：
   任一容器的 `docker inspect` 失败/无 JSON/无文档、容器 ID、镜像引用或入口+主进程命令读不到、
   `State.Running` 读不到，或命令是 `api_entry.py` 而 `DEPLOY_REVIEW_MODE` 读不到 →
   新增检查 `checks.all_running_containers_identified: false` 且判定 `unknown`（退出码 2、
   提示停止）。已证明**未在运行**的容器不在范围内（`Running=false`，它无法发起调用）。
   `State.Running` 缺失不再被当成 `false`（`container_facts` 用 `None` 表示“读不到”）。
3. 证据格式随之升版 `schema_version: v1alpha1 → v1alpha2`：`execution_instances` 的键由
   `authorized_real_instances` 改为 `second_real_model_instances`，每条为
   `{container_name, container_id, reason}`；新增检查键
   `all_running_containers_identified`（`no_second_authorized_real_instance` →
   `no_second_real_model_instance`）。加载器（`load_evidence`）同步改名并保持“非空即拒绝、
   非 `ok` 即拒绝”；旧版脚本写出的证据会因版本不符被明确拒绝，而不是按不同语义读入。
4. **README 逐文件授权 CLI 不再依赖公网旧镜像**（`deploy/README-demo.md` 8.2 与 8.4 第二步）：
   `manage_authorization.py approve/list/revoke` 原来用 `$D exec api ...`，依赖运行中的
   `:demo` 镜像（尚未更新的公网 TASK-0026 镜像，**里面没有该脚本**）。改为
   `IMAGE_TAG=task0027-validation $D build api` 构建独立标签镜像 +
   `docker compose run --rm --no-deps api python deploy/manage_authorization.py ...`
   一次性容器（复用 api 服务环境变量、网络与 `-modelstate` 读写挂载），并写明：不影响运行中的
   api/worker/nginx 与 `offline` 模式、`IMAGE_TAG` 只作用于该条命令、`$D up -d` 仍解析为
   `tender-review-api:demo`（不覆盖 `:demo`）；同时提示这些一次性容器运行的那几秒内镜像带
   验证标签，宿主证据脚本会把它当作第二实例（`untrusted`），因此要先完成 approve/revoke
   并确认容器已退出再跑证据脚本。

## 二、反例测试（用户指定必测，全部沿用 fixture 注入，未调用真实 Docker）

`tests/test_task0027_host_offline_evidence.py` 由 20 项扩到 **28 项**，新增：

- 运行中、`DEPLOY_REVIEW_MODE=offline` 的第二容器，命令指向
  `scripts/task0027_real_ai_validation_app.py` → **`untrusted`**（已确认盲区的直接反例）；
  同时断言 `all_running_containers_identified` 仍为 `true`（“识别到了，它就是实例”）。
- 命令匹配 `task0023_real_ai_app.py` 与 `scripts.task0023_real_ai_app:app`（参数化 2 项）→
  **`untrusted`**（mode 仍为 offline，证明判定与 mode 无关）。
- 镜像引用为 `tender-review-api:task0027-validation`（命令是无害的账本脚本、mode offline）→
  **`untrusted`**。
- 命令为 `deploy/api_entry.py` 且 mode 为 `authorized-real` → **`untrusted`**（reason 含
  `api_entry.py`）。
- 边界：另一个 `deploy/api_entry.py` 但 mode 为 `offline` → `ok`（无法外发，不算实例）；
  已停止（`Running=false`）的验证入口容器 → `ok`（不在“正在运行”范围内）。
- 某个运行容器的 inspect 不可读 → **`unknown`**：分别覆盖 (a) `docker inspect` 失败、
  (b) 入口/命令读不到、(c) `State.Running` 读不到、(d) `deploy/api_entry.py` 但
  `DEPLOY_REVIEW_MODE` 读不到；四者均断言 `all_running_containers_identified: false`，
  且 (a) 额外断言 `no_second_real_model_instance` 仍为 `true` 但 verdict 是 `unknown`
  （不得据此声称不存在第二实例）。
- 原有 `second_real_model_instances` 加载器反例改为新键与新实例结构（非空即拒绝）。

## 三、真实命令与真实数字（本机）

```
$ "D:/自由项目/招标审核/bidding-compliance-agent-TASK-0021/.venv/Scripts/python.exe" -m ruff check src scripts tests
All checks passed!

$ ... -m ruff check deploy/verify_api_offline_mode.py     # 额外（官方门禁范围不含 deploy）
All checks passed!

$ ... -m mypy src
Success: no issues found in 104 source files

$ ... -m mypy --strict deploy/verify_api_offline_mode.py   # 额外（不是官方门禁范围）
Success: no issues found in 1 source file

$ ... -m pytest --basetemp=.verification/t27-min4-9 tests/test_task0027_host_offline_evidence.py
28 passed in 0.66s

$ ... -m pytest --basetemp=.verification/t27-min4-7 \
    tests/test_task0027_host_offline_evidence.py tests/test_task0027_validation_entry.py \
    tests/test_task0027_round_limits.py tests/test_task0027_budget_boundaries.py \
    tests/test_task0027_per_file_authorization.py tests/test_task0027_deploy_compose.py
90 passed in 121.54s (0:02:01)

$ ... -m pytest --basetemp=.verification/t27-min4-8 tests/test_task0023_embedding.py \
    tests/test_semantic_batching.py tests/test_model_gateway_security.py tests/test_model_gateway_contracts.py \
    tests/test_legal_vector_index.py tests/test_model_adapter_conformance.py tests/test_real_ai_runtime.py \
    tests/test_task0021_online_gateway.py
90 passed in 6.50s
```

官方入口（`scripts/verify.ps1`，日志 `.verification/t27-focused4.log`）：

```bash
pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Focused \
  -TestPaths @('tests/test_task0027_round_limits.py','tests/test_task0027_validation_entry.py', \
               'tests/test_task0027_host_offline_evidence.py','tests/test_task0027_budget_boundaries.py', \
               'tests/test_task0027_per_file_authorization.py','tests/test_task0027_deploy_compose.py') \
  -PythonExecutable '<venv python>'"
```

实测：`[1/7]` 契约/生成/任务证据 `PASS`；`[2/7]` ruff `All checks passed!`；
`[3/7]` mypy `Success: no issues found in 104 source files`；`[4/7]` 前端
（OpenAPI 类型一致、Biome `Checked 21 files in 40ms`、tsc、vitest `2 passed (2)` /
`6 passed (6)`、`built in 307ms`）；`[5/7]` **90 passed in 127.74s**；
输出 `PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence.`
（Focused 模式按设计在 `[5/7]` 后返回，`[6/7]`/`[7/7]` 的真实启动 smoke 只在 Full 执行。）
按用户当次指令**未重跑 Full**。

## 四、CLI 端到端转录（本机 fixture 回放，未调用真实 Docker、无供应商）

`.verification/t27-cli3/`（合成 Docker 输出；api 容器为 offline + `:demo`）：

```
=== A) 第二容器：DEPLOY_REVIEW_MODE=offline，命令 = task0027_real_ai_validation_app.py ===
STOP: the deployment contradicts the offline precondition. Stop immediately; do not launch supplier calls.
evidence: .verification\t27-cli3\evidence-a\api-offline-20261016T033234Z.json
verdict: untrusted
api container: tender-review-demo-api-1 (1111...1111) mode=offline state=running image=tender-review-api:demo health=none
  - another real-model execution instance is running: tender-review-demo-api-run-verify (3333...3333):
    the start command runs the isolated validation entry (task0027_real_ai_validation_app)     exit=3
（该证据的 second_real_model_instances 条目含 reason；all_running_containers_identified=true）

=== B) 第二容器的 inspect 不可读（inspect fixture 缺失） ===
STOP: the review mode or the execution identity of a running container could not be established.
      Stop immediately; do not launch supplier calls.
verdict: unknown
  - docker inspect failed for the container 3333...3333; its execution identity could not be read   exit=2

=== C) 正常离线宿主（api + 离线 worker，无第二实例） ===
verdict: ok
PASS: the public API runs in offline mode and no second real-model execution instance runs.     exit=0
```

三种情形的证据文件里都**没有**注入的 `DASHSCOPE_API_KEY` 值或键名；证据 `schema_version`
为 `v1alpha2`。

## 五、边界与未做到/不确定的部分（本轮）

- **未在真实宿主运行该脚本**：本机只有 fixture 回放；线上 ECS 的 Docker 版本、`docker ps -aq`
  实际能列出多少容器（含历史一次性容器）、compose ps 的 JSON 字段仍需实机核对。
- **“正在运行”的范围**：只有 `Running=true` 的容器被计入实例；已停止的容器不算（它无法发起
  调用），但**它仍会被 `docker ps -aq` 枚举并 inspect**，因此其身份读不到时同样判 `unknown`。
- **判定是启动命令的字符串匹配**：用 `task0023_real_ai_app` / `task0027_real_ai_validation_app` /
  `api_entry.py` / `task0027-validation` 子串匹配（覆盖 `.py` 与 `:app` 写法）。把真实模型装配
  改名、或用 shell 拼接成不含这些名字的间接启动（例如把路径变量化后 `exec`），当前规则会漏；
  这类规避需要改脚本常量并重新评审，不在本轮声称的覆盖范围内。
- **验证镜像标签规则会同时命中一次性的辅助容器**（如用验证镜像跑
  `manage_authorization.py` / 账本基线 / 预检查的那几秒）→ 那一刻判 `untrusted`。这是**有意的
  失败关闭**：README 8.2/8.4 已写明“先完成 approve/revoke、确认一次性容器已退出，再跑证据脚本”。
- **TOCTOU 与信任链不变**：扫描与判定之间的状态变化仍靠证据时间戳与 10 分钟窗口收敛；
  证据仍是**内容不是签名**（能运行宿主脚本的人也能写出同样的 JSON），操作者仍是信任链一环。
- **未做的**：任何容器构建 / `docker compose run` / `$D exec`（任务禁止容器操作）；任何真实
  供应商调用（**本轮零付费调用**）；线上部署或切换到 `authorized-real`；git 提交与远程 CI
  （用户自行提交）；Full（用户要求本轮不重跑）。
- **本轮未改但同类的问题（留作待办）**：`deploy/README-demo.md` 8.1 第 3 条的预构建命令仍写作
  `$D exec api python scripts/prebuild_legal_vectors.py`，同样依赖运行中的 `:demo` 镜像；
  按用户本轮明确范围（逐文件授权 CLI）未改动 8.1。线上 api 切到新代码镜像时应一并处理。

# 第五轮：阶段二调整后的交付项（2026-10-16，未提交、未部署、零付费调用）

本轮把阶段一实测到的 **modelstate 真实布局**固定进正式装配与部署配置，为 120 秒超时后的
任务找回与幂等提供可复现证据，补齐阶段二公网切换/回滚方案，并在**内部验证实例**（本机
回环 compose 栈，非公网 47.83.132.211）上完成真实浏览器验收与 Word/PDF **正文**断言。
**未做任何法规核验、未改任何 `verification` 状态、未删除/重建/重置 3112 条向量索引与
DEC-007 账本、未触碰线上服务器、未扩大真实模型外发授权、未发起任何供应商调用。**

## 一、交付 1：统一 modelstate 正式部署路径（不动数据）

- 正式装配与部署默认 private root 从 `…/private/TASK-0023`（本部署不存在）改为**卷根**
  `…/private`：`scripts/task0023_real_ai_app.py`、`scripts/task0027_real_ai_validation_app.py`、
  `scripts/prebuild_legal_vectors.py`、`scripts/task0027_ledger_baseline.py`、
  `deploy/manage_authorization.py`（未配置时解析到同一个默认注册表并在 stderr 打印实际路径）。
- `deploy/demo.env.example`、`docker-compose.demo.yml`、`deploy/README-demo.md` 写明三个
  DEC-007 路径就是卷根文件（留空即用默认值），并说明换路径会与账本 scope 冲突
  （`existing DEC ledger has a different scope`），而 scope 冲突的"唯一修复办法"是删账本——
  正是 DEC-007 禁止的额度重置。
- 新增**只读一致性核对** `scripts/task0027_identity_check.py`（全部 `mode=ro`/只读解析，
  缺失即报告绝不创建；退出码 0 一致 / 2 停止）：核对 DEC-007 授权 ID、账本自身记录的 scope
  与当前配置重新计算的 scope（注册表路径是 scope 的一部分）、private root/账本/模型审计/
  注册表路径、模型审计存在性与账本-审计连续性、法规 publication/revision（与索引
  `vector-manifest.json` 及可选数据库行交叉核对）、向量索引 build_id/条目数/覆盖率/
  每个条目都有完好的缓存向量。`--print-scope` 只打印配置绑定的路径与 scope，不读账本。
- 新增 `scripts/task0027_index_plan.py`（只读、本地、零请求）：从冻结语料重算 build id
  （纯函数，可先于任何卷读取核对记录值），并逐条给出新快照的增删/文本变化/缓存命中，
  判断重建是否**完全由持久缓存服务**（0 新批次）。

### 实测结果（真实命令与数字）

1) 索引身份链（本机对仓库内冻结语料重算，非读取服务器数据）：

```
$ python scripts/task0027_index_plan.py \
    --publication-id 977826ab-948a-4681-9001-4866c7da3bc2 \
    --revision-id fa2407bb-1dff-4da8-b828-bcc846df76ad \
    --expect-build-id c7344cac5f45933fb7408701cb63ab2095206600aca952dcf4457130c85865d2
publication: 977826ab-948a-4681-9001-4866c7da3bc2  revision: fa2407bb-1dff-4da8-b828-bcc846df76ad
legal_snapshot_sha256: 69d340d65f5e9114c8a2e76f8b3b524b67f47d0cbc0088c4e01d80b7db8729fd
clauses: 3112/3120 embeddable (8 overlong), 312 batches
embedding identity: 8b05650d7f2d1bd4d089459f957bdd49b6340ddcda388719952e465fae16a723 (online)
planned build_id: c7344cac5f45933fb7408701cb63ab2095206600aca952dcf4457130c85865d2
PASS: the frozen corpus, the embedding identity and the publication/revision produce exactly
the expected build id; the durable cache covers every planned clause (no new embedding batch).
```

2) 部署配置身份（在**本 Worktree 构建的容器**内运行，等于线上同一配置的解析结果）：

```
$ COMPOSE_PROJECT_NAME=tender-review-t27 docker compose --env-file deploy/.env \
    -f docker-compose.demo.yml run --rm --no-deps \
    -e DEC007_AUTHORIZATION_ID=DEC-007-2026-10-16 api \
    python scripts/task0027_identity_check.py --print-scope
{
  "authorization_id": "DEC-007-2026-10-16",
  "ledger_path": "/app/.verification/private/dec007-budget.sqlite3",
  "ledger_read": false,
  "mode": "scope-only",
  "model_audit_path": "/app/.verification/private/dec007-model-audit.jsonl",
  "private_root": "/app/.verification/private",
  "registry_path": "/app/.verification/private/authorization-registry.jsonl",
  "scope_sha256": "a3d2e9d06ed85ced833146d13b8de53d94de7f868ba49935d8a630287c88ccd9"
}
scope-only: the ledger was NOT read; this is the scope the current configuration binds.
```

3) 本地（本机回环栈）无 DEC-007 数据 → **失败关闭**（证据链不伪造本地数据）：

```
$ ... python scripts/task0027_ledger_baseline.py        # 期望 2/312/¥0.1062161/0 的只读入口
STOP: the DEC ledger is absent at /app/.verification/private/dec007-budget.sqlite3; stop and
report instead of initialising a fresh quota.                                    exit=2
$ ... python scripts/task0027_identity_check.py --expected-scope a3d2e9d0... \
      --publication-id 977826ab-... --revision-id fa2407bb-... --build-id c7344cac...
STOP: the DEC-007 ledger is absent at /app/.verification/private/dec007-budget.sqlite3;
stop and report instead of initialising a fresh quota.                           exit=2
```

**身份一致的实测边界（必须如实说明）**：线上账本记录值（scope、计数、审计文件、索引
条目）**只有宿主操作员能读**——本机既无该卷也不允许访问服务器，因此本机证明的是
①索引身份可由冻结语料 + 记录发布/修订**离线重算并完全一致**（含 build_id、snapshot、
3112/3120、312 批、在线 embedding 身份）；②正式装配在容器内解析到**卷根路径**且 scope 由
当前配置唯一确定；③工具在数据缺失时拒绝而不是编造。账本侧四项（scope 记录值 = a3d2e9d0…、
LLM 2 / Embedding 312 / ¥0.1062161 / 未结算 0）需由操作员在宿主上以 8.4 的命令核对（**未执行**）。

## 二、交付 2：120 秒超时后的任务找回与幂等

### 2.1 前端最小引导修正（不重构后台、不改幂等语义）

`src/frontend/src/pages/project.tsx` 原来对 `AbortError` 只显示通用错误文案，用户可能误以为
任务丢失。现在创建审查请求被 120 秒客户端超时中断时：清空错误、显示
`REVIEW_TIMEOUT_NOTICE`（新增于 `src/frontend/src/utils.ts`）：说明"不代表任务丢失……请在
本页下方「审查任务」列表查看真实状态；再次点击「发起审查」会复用同一幂等键，不会重复创建
任务，也不会产生新的模型调用"，并立即 `reload()` 刷新持久化任务列表。幂等键沿用既有
`intentKey`（sessionStorage，只在成功时 `clearIntentKey`），后台任务的创建/持久化/幂等
语义**零改动**。

### 2.2 测试（自包含、回环、无供应商）`tests/test_task0027_timeout_recovery.py`

```
$ pytest --basetemp=.verification/t27-timeout tests/test_task0027_timeout_recovery.py
4 passed in 8.08s
```

覆盖：
1. `test_the_browser_aborts_the_review_request_after_120_seconds`：从 `client.ts` 断言
   **120_000 ms** abort 与 `REVIEW_TIMEOUT_NOTICE` 出现在超时分支（场景绑定真实常量）。
2. `test_the_same_idempotency_key_returns_the_task_and_executes_once`：同一 `Idempotency-Key`
   第二次提交返回 **202 且响应字节等同**首次（同一 review_task_id/run_id/status），
   执行器 `start` 只被调用 **1 次**、`review_engine_run` 只有 **1 行**、
   真实 `Dec005BudgetLedger` 文件**字节不变**且摘要不变（`llm_calls=1`）。
3. `test_the_same_key_with_a_different_document_set_is_a_conflict_and_executes_once`：
   同键不同文档集 → **409**，执行器仍只 1 次、账本不变；换新键 → 新任务、执行器 2 次
   （证明抑制来自幂等键而非全局阻塞）。
4. `test_a_client_timeout_still_finds_the_running_task_and_its_result`：**真实 Uvicorn 回环
   HTTP**，客户端 0.25 秒超时（对 1.5 秒执行，缩放后的 120 秒 abort 语义）后，
   `GET /projects/{id}/reviews` 立刻显示 `running`，随后轮询到 `result_published`；
   同键重提返回同一已完成任务且执行器仍只 1 次。

边界：执行器是**记录型替身**（在 API 唯一调用边界 `engine.start` 上，用同一 ORM 行与真实账本
记账）；真实 `ReviewEngine` 的 LangGraph 持久检查点要求 PostgreSQL，本机自包含测试未启动它；
生产路径上的真实实例证据见 2.3。

### 2.3 内部验证实例（本机回环 compose 栈）真实输出

栈：`tender-review-t27`（本 Worktree 的 `docker-compose.demo.yml` + `Dockerfile.api/web`
构建，`tender-review-api:task0027-t27` / `tender-review-web:task0027-t27`），
`DEPLOY_REVIEW_MODE=offline`、`VITE_REVIEW_MODE=offline-deterministic`，仅发布
`127.0.0.1:8090`；卷 `tender-review-t27-*`（全新，未触碰任何既有卷）。脚本
`.verification/t27-acceptance/timeout_recovery_check.py`（真实登录 → 建项目 → 上传合成 DOCX →
上下文确认 → 客户端 0.2 秒超时中断创建审查 → 列表找回 → 同键重提 → 跨项目同键 409）：

```json
{
  "client_abort_seconds": 0.203,
  "document_status_before_confirmation": "needs_confirmation",
  "document_status_after_confirmation": "ready",
  "review_task_id": "0af70a7c-e2e1-5eb5-b3e3-0d792b4ea18f",
  "status_timeline": [{"status": "running"}, {"status": "waiting_human"}],
  "task_found_after_abort": true,
  "duplicate_status": 202,
  "duplicate_same_task": true,
  "same_key_other_project_status": 409,
  "task_count_in_project_after_duplicates": 1,
  "frontend_abort_milliseconds": 120000
}
```

即：真实离线 LangGraph 审查在客户端中断后继续执行（`running → waiting_human`），任务始终
可从项目页的任务列表找回；重复提交不产生第二个任务。离线模式下不存在付费调用；
本机 DEC-007 账本不存在、未创建（本脚本不触碰任何 DEC-007 数据）。

## 三、交付 5：内部实例的真实浏览器验收与 Word/PDF 正文断言

### 3.1 真实浏览器（Microsoft Edge / Playwright，非公网）

`.verification/t27-acceptance/browser_acceptance.mjs` 在 `http://127.0.0.1:8090` 全流程实测
（8 张全页截图在 `.verification/t27-acceptance/browser/`）：登录 → 新建项目 → 真实上传
→ 确认上下文 → 发起审查（202）→ 审查任务详情（`等待人工复核`）→ 风险卡片
`待核验：Synthetic location requirement for human review` + `查询服务端精确定位`
（1 条引用，含 SHA-256 与 `ooxml/body/3/paragraph` 定位）→ 保存复核决定 →
人工复核历史（2 行）→ 继续审查流程（`结果已发布`）→ 生成并下载 Word 与 PDF →
项目页任务列表显示该任务 `结果已发布`：

```json
{
  "review_status_code": 202, "review_initial_status": "waiting_human",
  "review_detail_status_badges": ["等待人工复核", "待复核"],
  "finding_count": 1, "exact_citation_count": 1, "human_review_history_rows": 2,
  "project_task_list_status": "结果已发布",
  "reports": {"docx": {"sha256": "a7dd45f1…b3926"}, "pdf": {"sha256": "6573299b…c6717"}}
}
```

### 3.2 Word/PDF 内容抽查（不看哈希，抽正文）

**替代品声明**：阶段一的真实 AI 报告在 `/opt/tender-review-private/evidence/task0027-report-*.{docx,pdf}`，
**只在服务器上，本轮不允许访问服务器**，未取得；下方断言对象是**本机内部实例（离线确定性
模式）由真实报告流水线生成并经浏览器下载的 Word/PDF**，是明确的替代品，不代表阶段一真实
AI 报告的逐字内容。

`.verification/t27-acceptance/report_content_check.py`（python-docx 抽 DOCX 正文 1697 字符、
pypdf 抽 PDF 2 页）断言并全部成立：

- **风险标题**：`待核验：Synthetic location requirement for human review`（两种格式均有）；
- **原文摘录**：`投标人必须在本市注册。该条款仅供离线演示和软件流程验证使用。`；
- **证据状态**：`证据状态：insufficient_evidence`（独立 Evidence Checker 结果）；
- **法规参考的适用性提示**：`法律适用框架尚未确认`、`未完成有效适用性匹配`、
  `未包含可引用的法规条款` / `未提供可引用条款`（不补造条文）；
- **不存在违法认定**：文本中 `认定违法`/`构成违法`/`属于违法`/`确认违法`/`违反了《`/`系违法行为`
  全部不出现；`违法认定` 只出现在否定句（`尚无法律违法认定依据`、`不得据此认定确定性法律违规`）。

```
PASS: Word and PDF report content assertions held
```

## 四、交付 4：阶段二公网切换与回滚方案（文档，未执行）

`deploy/README-demo.md` 新增 **8.5**（8.1 第 5 条同步补充"构建期参数、两镜像分别构建"）：
- 8.5.1 **两个镜像分别构建**：API `$D build api` 与前端 `$D build nginx` 用同一提交/同一
  `IMAGE_TAG`；`VITE_REVIEW_MODE=dec007-real-qwen` 是 Vite **编译期**常量，不重建 nginx
  则文案不生效；前端模式必须与 `DEPLOY_REVIEW_MODE` 一致。
- 8.5.2 切换 `authorized-real` 的**前置逐项**：预构建索引 pinned 校验（`task0027_index_plan.py
  --expect-build-id`）、宿主 offline 证据新鲜（`verify_api_offline_mode.sh` → `verdict: ok`）、
  账本基线（2/312/¥0.1062161/0）、注册表路径=卷根且与 scope 绑定一致
  （`task0027_identity_check.py --print-scope`）、身份一致性退出码 0、8.4 受控验证轮已完成、
  逐文件白名单非空且**面试官新上传文件不会自动授权**。
- 8.5.3 切换步骤：先备份 → 改 `deploy/.env`（模式 + 前端模式 + 标签）→ 分别构建 → 先 api 后
  nginx → 只读复核（并说明切换后宿主证据脚本对线上 api 本身必然报 `untrusted`，它只能用于
  切换**之前**证明基线离线）。**HTTPS、`tender-certbot-*.timer` 自动续期、审计账本与数据库
  全程不动**。
- 8.5.4 **回滚**：改回 `offline` + `VITE_REVIEW_MODE=offline-deterministic` → `$D up -d
  --force-recreate api`（环境变量变化必须重建）→ 重建 nginx → 宿主证据复核 `ok`；**账本不重置**
  （不得删/替换/用备份覆盖）、索引与数据卷保留（不 `down -v`）、`revoke` 立即生效（注册表
  append-only，运行中 API 每次判定重读）。
- 明确边界：真实外发仅限已登记批准的合成文件；未核验法规的风险保持"待核验"，不得宣称违法。

## 五、交付 3：本轮代码候选的真实命令与数字（本机）

```
$ ruff check src scripts tests                     -> All checks passed!
$ mypy src                                         -> Success: no issues found in 104 source files
$ python scripts/verify_repo.py                    -> PASS: contracts, examples, generated State and
                                                      scoped task evidence
$ pytest --basetemp=.verification/t27-timeout tests/test_task0027_timeout_recovery.py
                                                   -> 4 passed in 8.08s
$ pytest --basetemp=.verification/t27-plan-fix2 \
    tests/test_task0027_index_plan.py tests/test_task0027_identity_check.py
                                                   -> 34 passed in 7.46s
$ cd src/frontend && npm run test                  -> 3 files, 8 passed (含新增 utils.test.ts 2 项)
```

官方 Focused（`scripts/verify.ps1 -Mode Focused`，8 个 TASK-0027 测试文件）：

```
[1/7] 契约/生成/任务证据 PASS；[2/7] ruff All checks passed!；
[3/7] mypy Success: no issues found in 104 source files；
[4/7] 前端（OpenAPI 一致、Biome Checked 22 files、tsc、vitest 8 passed、build）；
[5/7] 123 passed in 105.57s
PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence.
```

官方 Full：本轮**执行**了 Full（与第四轮"按用户指令未重跑 Full"不同——本轮改动含前端源码
与测试，必须重跑）。**既有环境前置（第一轮已记录，本轮复现）**：`tests/test_verification_modes.py`
会不带 `-PythonExecutable` 调内层 `verify.ps1`，因此必须把 venv 的 `Scripts` 目录前置到 `PATH`
（否则内层回退到 PATH 上无 `jsonschema` 的系统 python，该测试失败且内层 pwsh 输出的中文路径
会让读取线程抛 `UnicodeDecodeError`）。**第一次 Full 尝试（未前置 PATH）在 `[5/7]` 失败
`1 failed, 805 passed`，失败项正是该环境前置，不是本轮代码缺陷**；前置 PATH 后的权威结果：

```
$ export PATH="/d/.../TASK-0021/.venv/Scripts:$PATH"
$ pwsh -NoProfile -Command "& scripts/verify.ps1 -Mode Full     -PythonExecutable 'D:/.../TASK-0021/.venv/Scripts/python.exe'"
[1/7] PASS  [2/7] ruff All checks passed!  [3/7] mypy Success: no issues found in 104 source files
[4/7] 前端 OpenAPI 一致 / Biome Checked 22 files / tsc / vitest 8 passed / built
[5/7] 806 passed, 6 warnings in 486.12s (0:08:06)
[6/7] PASS: live HTTP health=200, missing=404, request IDs matched; port=62862
[7/7] PASS: real HTTP login, project create/read/version, logout/revocation; child stopped
PASS: development baseline checks; production acceptance is a separate milestone.
FULL-EXIT=0
```

JUnit 汇总（`.verification/pytest-result.xml`）：`tests=806, failures=0, errors=0, skipped=0,
time=486.085s`。6 条 warning 与第一轮相同：`tests/test_verification_modes.py` 在 Windows 下读取
内层 pwsh 子进程输出时的 `UnicodeDecodeError` 线程告警（子进程输出编码，测试本身通过），
属既有环境现象，本轮未改动验证脚本。完整日志 `.verification/t27-full.log`（含 `FULL-EXIT=0`）。

## 六、本轮修掉的上一轮遗留（不改变语义）

- `tests/test_task0027_index_plan.py`：① 空 egress 断言改为核对**守卫**先拒绝
  （`never reserves a supplier request`；transport 是永不触达的第二层）；
  ② 文本改写场景按实际语义断言——本合成语料的 clause_id 由文本决定，改写表现为
  `removed=3/added=3/changed_text=0`（而不是同 id 改文本），三项合计仍是 3 条需重新嵌入。
- 上一轮新增文件里的 ruff/密钥扫描问题：导入排序、超长行、未用导入、`/tmp` 字面量、
  占位凭据命名（`example-…` 前缀，仅存在于测试/计划脚本，transport 拒绝一切请求）。

## 七、边界与未做到/不确定（本轮）

- **未做**：任何法规官网核验、任何 `verification` 状态修改、任何 `valid` 认定；任何供应商
  调用（零付费）；任何线上操作（47.83.132.211 未触碰，公网 `DEPLOY_REVIEW_MODE` 仍
  `offline`）；未删除/重建/重置 3112 条索引与 DEC-007 账本（本机根本没有这两样数据，
  工具在缺失时失败关闭）；未 git 提交（用户自行提交）。
- **未在服务器上读取账本/索引**：交付 1 的"实测结果"分三层，其中账本记录值（scope、
  计数、审计、索引条目）**只能在宿主上核对**，本轮未执行；`status_timeline` 是列表轮询的
  采样，不是服务端事件流。
- **超出脚本覆盖的行为**：120 秒是前端常量（`client.ts` 已断言），pytest 与内部实例脚本
  用缩放后的超时复现同一语义（客户端放弃、服务端继续）；**未做真实 120 秒挂起**的回归测试
  （避免套件时长不可控），若需要可在宿主上以真实 120 秒复跑同一脚本。
- **浏览器验收是内部实例**（本机回环 compose，离线确定性模式）：不是公网、不是
  `authorized-real`，未上传任何真实标书；离线横幅与"固定测试网关"说明如实显示。
- **Word/PDF 内容断言的是替代品**（本机内部实例生成），阶段一真实 AI 报告未取得；
  两种格式的具体措辞不同，断言按各自实际正文逐条列出。
- **8.5 是方案不是执行记录**：索引 pinned 校验、宿主 offline 证据、账本基线、切换与回滚
  均**未在服务器上执行**；host 侧命令的实机可用性仍需切换当天核对。
- 本轮为本机验证额外跑起的 `tender-review-t27` compose 栈（回环、离线、全新卷）是**验收
  环境**，不是部署；验收后按 `$D down`（保留卷）停止，报告里如实说明其状态。
