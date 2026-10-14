# TASK-0011 本地验证与验收记录

- 更新时间：2026-10-15
- 当前状态：两个局部验收项及源码 CI 已通过；验收记录提交 `750833cf1ffdd99f889676ec93575498479d1851` 的 Quick CI <https://github.com/w186www/Tender-Review/actions/runs/38603582949> 已通过。正式归档 CI 尚待完成，因此当前进入归档候选阶段。
- 分支：`work/TASK-0011`
- 最终源码候选：`57d2515c6e4f2d6816bf94c2ed04e82759acd6c4`（`fix: pin frontend files to LF for Biome`）
- 前端与 FR-013 实现：`a8c43454138c2867d735402d1f330869fa18ba16`
- OpenAPI Windows 修复：`57d3a833f59a09e9c938837671a8769d91c7fc5b`
- 源码 CI：<https://github.com/w186www/Tender-Review/actions/runs/38600922153>，对应最终源码 SHA；`impact`、Windows `baseline`、PostgreSQL、`ingestion` 和 `verify-required` 均成功。`quick` 按 Full 选档规则跳过。
- 关键门禁：[Windows baseline](https://github.com/w186www/Tender-Review/actions/runs/38600922153/job/115979718302)、[PostgreSQL](https://github.com/w186www/Tender-Review/actions/runs/38600922153/job/115979718348)、[ingestion](https://github.com/w186www/Tender-Review/actions/runs/38600922153/job/115979718096)。

## FR-013 配置版本管理

TASK-0006 的法规发布快照、TASK-0007 的规则/Skill 版本身份继续作为来源；TASK-0011 增加持久化的审查配置修订，用一个不可变配置快照引用这些现有能力，不另造法规、规则或 Skill 版本体系。

配置修订有稳定 `revision_id`、父修订、规范化快照哈希和草稿/已发布状态。快照绑定法规 publication、启用的 Skill 与版本、规则版本和规则集哈希，以及无凭据的模型执行策略。管理员通过正式 API 创建草稿、发布、停用和回滚；租户/角色在服务端校验，状态变更使用序列/CAS 防并发覆盖，失败返回冲突，成功和拒绝操作写入审计事件。数据库迁移增加不可变修订、活动/草稿指针和事件表；前端提供对应配置管理页面。

新审查在创建运行时解析当前活动配置，并将 `configuration_revision_id` 与配置快照哈希写入 ReviewEngine 冻结快照。之后发布新配置、停用或回滚只影响新运行；执行中或已发布运行仍绑定原快照。回滚引用此前已发布的修订，不改写旧修订。

模型配置只含供应商无关的 profile、超时、重试、token 限额、温度和数据策略，不含 API Key、供应商路由或真实凭据；服务端还会限制策略不能超过已注入执行器的运行边界。DEC-002 仍未批准在线模型或数据外发，未连接真实在线模型。没有配置 ReviewEngine 时仍返回 503，不生成模拟审查结果。

主要实现与验证：

- API/契约：`src/bidding_compliance/api/configuration_management.py`、`src/bidding_compliance/api/configuration_schemas.py`、`contracts/openapi.yaml`。
- 版本/快照/授权与审计：`src/bidding_compliance/domain/review_configuration.py`、`src/bidding_compliance/services/review_configurations.py`、`contracts/database/migrations/202610142000_task0011_review_configurations.py`。
- ReviewEngine 冻结绑定：`src/bidding_compliance/services/review_engine.py`、`src/bidding_compliance/graph/review.py`。
- 管理页面：`src/frontend/src/pages/configuration.tsx`。
- 回归：`tests/test_review_configurations.py` 的发布/回滚与历史冻结、管理员/租户/哈希/追加写约束、模型密钥与运行边界测试；FR-013 Focused 共 69 项通过。

## 真实浏览器 E2E

最终通过记录在本机 `.verification/task0011-e2e-827cc1b8a63c41b4a9d13f1334ae7574/`：Playwright 使用 Microsoft Edge，连接真实 FastAPI、PostgreSQL 16、MinIO、ClamAV 和真实文档处理 worker；审查器为显式注入的 `scripts/check_review_engine.py::OfflineReviewGateway`，网络限定 loopback，没有在线模型。JUnit 为 5 tests、0 failures、0 errors、0 skipped，Playwright 进程退出码 0，运行约 46 秒。运行清单记录 `repository_head=5ffe1b6197f12ae92e722eb5dbab9ec7bdf5f8a8`；该次运行发生在实现提交 `a8c4345` 之前，最终实现与 E2E 代码随后提交于 `a8c4345`，本轮之后仅 `.gitattributes` 发生变化。原始清单、JUnit、Playwright 日志均保留在本机 `.verification` 目录（该目录不纳入 Git）。

五个浏览器场景：

1. 错误凭据由真实 API 返回 401，页面显示中文错误。
2. 管理员创建并发布法规/配置修订；用键盘 Enter 操作表单、制造并识别 409 并发冲突；页面不显示 API Key，随后通过正式 API 读回草稿和发布状态。
3. 审核员创建项目、上传合成 DOCX、运行真实 worker 和离线 ReviewEngine、查看状态与风险、查询服务端精确引文并回查/下载原文、保存人工决定、发布结果并下载 Word/PDF。独立持久化断言核对文档状态、已发布 ReviewEngine run、报告格式和配置修订 ID；对话框 Escape 键盘关闭也通过。
4. 审计员执行真实审计查询并验证审计事件持久化；操作员配置管理/报告权限返回 403，跨租户项目访问返回 404；无 ReviewEngine 的独立服务返回 503，且审查 run 数没有增加。
5. 管理员撤销账号后，已有浏览器会话立即失效。

验收产物：`src/frontend/e2e/workbench.spec.ts`、`scripts/run_task0011_e2e.py`、`scripts/assert_task0011_e2e.py` 和上述本机 `playwright-junit.xml`、`run.json`。此前有 8 次未通过的实现迭代，失败集中在登录/配置断言、文档处理或审查流程未到达完成状态；审计用例依赖前一审查流程创建的共享状态，当前序列化最终运行中全部通过。未将早期失败计入 5/5 结果。

## PostgreSQL、Full 与前端验证

- PostgreSQL 16 本地专项：`scripts/check_postgres.py` 与 `scripts/check_legal_publications.py` 通过，覆盖迁移、RLS/租户隔离、并发/CAS、事务回滚，以及配置发布/回滚、审计与 ReviewEngine 历史快照。最终源码 CI 的 PostgreSQL job 也成功。
- 本地 Full：源码 SHA `57d3a833f59a09e9c938837671a8769d91c7fc5b` 上 510 passed、0 failed、0 errors、0 skipped，用时 297.44 秒；Ruff 通过，Mypy 94 个源文件通过，前端 API/lint/typecheck/6 个单测/build、真实 HTTP 和身份烟雾通过。保留两个既有 `pypdf.add_js` 弃用警告。
- 最终 SHA `57d2515c6e4f2d6816bf94c2ed04e82759acd6c4` 与上述 Full 之间没有应用、测试、契约或依赖改动，只有前端 Git 检出换行属性扩展；当前 SHA 的完整 Windows baseline 已在源码 CI 成功。远端 JUnit artifact 下载接口要求认证，故这里只引用 baseline 成功，不虚报远端测试计数。
- OpenAPI 根因与修复：`npm run api:generate` 与正式 `contracts/openapi.yaml` 生成内容字节一致（`schema.d.ts` SHA-256 `48048466326aa6df0342864a688d0580659ee31f4d60f2b6ce67612a90fbc0a8`），不是类型过期、生成器版本或路径错误。Windows `core.autocrlf=true` 使 CI 工作树中的前端文件为 CRLF，而 Biome 期望 LF。第一次只为生成的 `.d.ts` 加 LF 属性后，CI 的 API 检查通过、lint 随即暴露其余 21 个前端文件的相同换行差异。最终 `.gitattributes` 规定 `src/frontend/** text eol=lf`，没有关闭或弱化检查，也没有改动生成类型内容。
- 本轮当前 SHA 上 `verify.ps1 -Mode Quick` 和 Git 属性检出检查通过。为本机重跑 frontend 套件执行 `npm ci` 时，Windows 对 `node_modules/@rolldown/binding-win32-x64-msvc/rolldown-binding.win32-x64-msvc.node` 返回 `EPERM`（文件占用）；没有把该尝试记为成功。改动后的真实 Windows CI baseline 成功完成锁定依赖安装、lint、类型、前端测试/构建和完整 Full 门禁。

## 验收映射

| 检查 | 结果 | 主要证据 |
|---|---|---|
| TASK0011-001：无需开发者终端操作即可完成关键流程 | 通过；真实浏览器 5/5，状态与持久化结果经真实后端核验 | 本记录、`src/frontend/e2e/workbench.spec.ts`、`scripts/assert_task0011_e2e.py` |
| TASK0011-002：键盘、中文状态/错误和服务端权限 | 通过；键盘/中文/401/403/409/503/撤权/跨租户场景均执行 | 本记录、`src/frontend/e2e/workbench.spec.ts`、`tests/test_identity_projects.py` |
| FR-013：法规、规则、Skill 和模型策略配置版本化管理 | 通过；持久化 API/页面、授权操作、审计、哈希、发布/停用/回滚、冻结快照均有实现和测试 | 本记录、`tests/test_review_configurations.py`、`scripts/check_legal_publications.py` |

所有审查输出仍受 Evidence Checker 和原有证据门禁约束；没有修改 `knowledge/legal/**`、`docs/reference/*.docx`，没有接入在线模型或加入 TASK-0012。当前等待本验收记录提交 CI 与正式归档/归档 CI 完成后，再把任务状态改为 `completed`。
