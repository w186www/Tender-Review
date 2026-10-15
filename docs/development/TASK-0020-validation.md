# TASK-0020 本地演示与验收记录

- 状态：`in_progress`；本地验收通过，推送 SHA 的远端 CI 和最终归档待完成。
- 分支：`work/TASK-0020`。
- 基线 HEAD：`00829851018612a275faca9ad6609e10fa38305d`。
- 范围：本机 loopback、合成数据、显式离线确定性 ReviewEngine；无在线模型调用、无远程部署、无真实招标/法规数据外发；不改变 M4/M5 或 TASK-0012/0013/0014 原验收条件。
- 经用户批准的最小扩围已先写入 TASK-0020 契约：生产代码只允许 `src/bidding_compliance/ingestion/schemas.py`，新增测试只允许 `tests/test_ocr_runtime_identity.py`（原有 Demo 测试为 `tests/test_demo_fixture.py`）；其他 `src/bidding_compliance/**` 与 `tests/**` 明确列入 `must_not_change`。契约 Quick 通过后才修改实现。
- 实现候选源码/测试指纹：`c5ec2a5a0e28d9c5317f6a9ae0d019131694b7d8673d7758991d469a1ff9cf7a`。算法：以下十个代码/测试路径按路径排序，每行写入 `相对路径<TAB>Git index blob 的 SHA-256`，对 UTF-8 manifest（含末尾换行）求 SHA-256：`scripts/generate_demo_fixture.py`、`scripts/run_offline_demo_worker.py`、`scripts/run_task0011_e2e.py`、`src/bidding_compliance/ingestion/schemas.py`、`src/frontend/e2e/workbench.spec.ts`、`src/frontend/src/app.tsx`、`src/frontend/src/pages/reviews.tsx`、`src/frontend/src/styles.css`、`tests/test_demo_fixture.py`、`tests/test_ocr_runtime_identity.py`。Focused/Full/E2E 实际运行在工作树；工作树与 index 逐文件比较仅 `scripts/run_task0011_e2e.py` 和 `schemas.py` 有 CRLF/LF 规范化差异，其余八文件字节一致，文本内容相同。本指纹绑定门禁对应的提交候选；提交 SHA 在提交后另记。

## 缺陷与修复

此前当前 TASK-0018 parser 的真实 Edge E2E（`5484f1c5d8564fd7aa40eb7204fae9ba`）在 `services/candidate_discovery.py` 将 PostgreSQL JSON 传给 `OCRRuntimeIdentity.model_validate()` 时返回 422：JSON 的 `model_ids` 为数组，严格 Python 模型要求 tuple。该失败记录保留为修复前证据。

修复仅在 `OCRRuntimeIdentity` 的 `mode="before"` 可信解析边界把 JSON list 表示转成 tuple。字段 Literal、条目严格类型、数量约束、模型 ID/模型摘要对应关系、身份哈希和外层 `FrozenParserIdentity` provenance 绑定仍由原校验器执行。没有重算或忽略存储哈希，没有放宽全局 Schema，也没有改数据库、生产审查策略或法规状态。

`tests/test_ocr_runtime_identity.py` 覆盖 JSON dump/load 到 Python dict 再 `model_validate()` 的 round-trip、严格条目类型与 Pydantic 错误类型、引擎身份不匹配、内容哈希篡改、身份哈希篡改和 FrozenParserIdentity 绑定不匹配。

## 最终候选验证结果（2026-10-15）

| 验证 | 实际结果 | 证据/限制 |
|---|---|---|
| 契约 Quick | 通过 | 首次默认 Python 解析到不存在的 Python 3.13 runtime 并缺 `jsonschema`；随后使用既有 `bidding-compliance-agent/.venv` 且禁用 pyc 写入，TASK-0020 契约 Quick 通过。TASK-0019 原工作树未执行命令或写入。 |
| Focused | 通过，`76 passed`、0 失败/错误/跳过，exit 0 | 明确选择 `test_ocr_runtime_identity.py`、`test_demo_fixture.py`、identity、ingestion、review configuration、report 六个文件；一条既有 pypdf `add_js` 弃用警告。 |
| Full | 通过，`545 passed`、0 失败/错误/跳过，exit 0 | 同一实现指纹；Ruff、Mypy 97 个源文件、前端 OpenAPI/Biome/TypeScript/6 项单测/build、真实 HTTP health/404/request ID 与登录/项目/撤权 smoke 全通过；两条既有 pypdf `add_js` 弃用警告。JUnit：`.verification/pytest-result.xml`。 |
| 真实 Edge E2E | 通过，5 项、0 失败/错误/跳过，Playwright exit 0 | `run_id=86521e79591241c19b28aaecf0988323`；manifest `.verification/task0011-e2e-86521e79591241c19b28aaecf0988323/run.json`。Microsoft Edge（Playwright `msedge` channel），当前 TASK-0018 parser SHA `2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597`、PostgreSQL 16、MinIO、ClamAV、真实 API/worker 和合成 DOCX；覆盖上传、自动解析、审核发起、人工复核/发布、Word/PDF 报告下载、权限/撤权。网关为显式 `OfflineReviewGateway`，不代表真实 LLM 语义质量。合成 DOCX SHA-256：`72886bc6a2c2cff68b71111ca1dec5edf1ce07248803ea35602e5ff0e581a584`。manifest 中 Git HEAD 是基线，实际源码候选身份以本节十文件指纹为准。 |
| PostgreSQL | 通过 | `check_postgres.py` 在一次性 PostgreSQL 16 数据库 exit 0：迁移、ORM、RLS、租户 FK、并发、检索运行和回滚。 |
| Checkpoint / 法规发布 | 通过 | 在完成 `check_postgres.py` 的同一空白 PostgreSQL 16 实例顺序执行 `check_legal_publications.py` exit 0：新进程 Checkpoint 恢复、离线 ReviewEngine、复核、重试/取消/撤权、快照拒绝、RLS、发布 CAS 和事务回滚。 |
| Parser sandbox | 通过 | `check_parser_sandbox.py` 对固定 parser image 验证非 root、只读、禁网、无权限提升、noexec tmpfs、512 MiB/32 PID 限制。 |
| 安全摄取专项 | 通过 | `check_ingestion_containers.py` exit 0：真实 ClamAV、MinIO/S3、PDF/DOCX/PNG/扫描 PDF、隔离解析、定位、租户隔离和下载；临时服务与容器已清理。 |
| `--serve` 启停 | 通过 | `run_id=9a9478a6b4dc4d8b9c1fd0e34b40f09c`；真实启动页与账号提示后 Ctrl+C，manifest 状态 `stopped`；精确检查 `task0011-pg/minio/clam-9a9478a6b4dc` 均已移除。 |
| npm / 锁文件 | 未变化 | 仅沿用独立 TASK-0020 工作树已经通过官方 `registry.npmjs.org` 安装的锁定依赖；未再次运行 `npm ci`；`package-lock.json` 仍为基线内容。 |

Checkpoint 首次单独使用尚未迁移的全新数据库时因 `tenant` 表不存在而失败；这是不符合仓库脚本顺序的测试环境编排错误，不是代码失败。随后在同一新 PostgreSQL 16 实例按 `check_postgres.py` → `check_legal_publications.py` 正确顺序重跑，两项均通过。正式结果使用正确顺序的记录。

真实 Edge E2E 与 `--serve` 启停结束后，本轮容器均按 run ID 精确停止。没有向供应商模型或外部服务发送真实业务数据；临时演示账号口令只显示在启动终端，不记录在本文件或 run manifest。

## 验收状态

| 检查 | 状态 | 证据 |
|---|---|---|
| TASK0020-001：演示差距、正常 API fail-closed、队列与适配器边界 | 本地满足 | `TASK-0020-demo-gap-assessment.md` |
| TASK0020-002：受控启动、loopback、临时服务和清理 | 本地满足 | `TASK-0020-demo-guide.md`；E2E 与 `--serve` manifest |
| TASK0020-003：合成文件上传、解析、审查、复核、发布和 Word/PDF | 本地满足 | Edge run `86521e79591241c19b28aaecf0988323`、JUnit |
| TASK0020-004：离线标识、报告标识、法规证据降级 | 本地满足 | UI、demo guide、Edge 报告下载案例及既有法规证据专项 |
| TASK0020-005：OCR JSON/provenance 严格性、本地门禁和远端 CI | 本地满足；远端待完成 | `tests/test_ocr_runtime_identity.py`、本节验证结果；推送 SHA 及 GitHub Actions 尚待运行 |
| TASK0020-006：重复启动/停止、能力限制和 DEC 边界 | 本地满足；远端待完成 | `TASK-0020-demo-guide.md`、`--serve` manifest；远端 CI 待核 |

TASK-0019 原工作树保护检查：`work/TASK-0019`、HEAD `00829851018612a275faca9ad6609e10fa38305d`；其 11 条状态路径、对应 12 个变更文件 SHA-256 与本轮开始快照相同。本轮未在该工作树执行验证、安装或写入。

## 可重复命令

以下验证使用项目既有 venv（当前 TASK-0020 隔离工作树没有 `.venv`），不在原 TASK-0019 工作树写入：

```powershell
./scripts/verify.ps1 -Mode Quick -PythonExecutable 'D:/自由项目/招标审核/bidding-compliance-agent/.venv/Scripts/python.exe'
./scripts/verify.ps1 -Mode Focused -PythonExecutable 'D:/自由项目/招标审核/bidding-compliance-agent/.venv/Scripts/python.exe' -TestPaths @('tests/test_ocr_runtime_identity.py','tests/test_demo_fixture.py','tests/test_identity_projects.py','tests/test_ingestion.py','tests/test_review_configurations.py','tests/test_review_reports.py')
./scripts/verify.ps1 -Mode Full -PythonExecutable 'D:/自由项目/招标审核/bidding-compliance-agent/.venv/Scripts/python.exe'
./.venv/Scripts/python.exe scripts/run_task0011_e2e.py
./.venv/Scripts/python.exe scripts/run_task0011_e2e.py --serve
./.venv/Scripts/python.exe scripts/check_postgres.py
./.venv/Scripts/python.exe scripts/check_legal_publications.py
$env:PARSER_VERIFY_IMAGE='sha256:2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597'; ./.venv/Scripts/python.exe scripts/check_parser_sandbox.py
$env:PARSER_VERIFY_IMAGE='sha256:2c440c708069a207cb08dde06bd6be35efe7c11c39dae5c228b1ac00a41bb597'; ./.venv/Scripts/python.exe scripts/check_ingestion_containers.py
```

本地门禁和真实 E2E 已通过；TASK-0020 与 M3 保持 `in_progress`，直到本地候选被逐项审查、提交推送后的适用 GitHub CI 全部完成且成功，再按仓库治理更新归档。
