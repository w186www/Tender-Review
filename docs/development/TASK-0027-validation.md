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
