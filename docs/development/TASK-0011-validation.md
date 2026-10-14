# TASK-0011 本地验证与验收状态

更新时间：2026-10-14
状态：`in_progress`；未填 acceptance evidence，未归档。
分支：`work/TASK-0011`，基于 TASK-0010 归档提交 `7759e5f76d7b21d1bd99cc57ade2cb39a14ba00b`；源码候选提交：`b1d7ca9`（`feat: add TASK-0011 review workbench`）。

## 实施范围

- 新增 React 19 / TypeScript / Vite 8 / React Router 7 工作台，技术决策见 [ADR-0014](../decisions/ADR-0014-frontend-workbench.md)，启动方式见[前端工作台说明](frontend-workbench.md)。依赖使用兼容范围并由 `package-lock.json` 固定复现。
- `openapi-typescript` 依据 `contracts/openapi.yaml` 生成类型，`openapi-fetch` 发送带身份的请求；读请求支持 `AbortSignal` 与 120 秒超时，写请求不自动重试，业务重放使用后端幂等键。
- 页面接入本地登录/退出及身份刷新、项目创建和版本、文档上传与处理状态、审查任务、风险/证据回查、人工复核历史及理由、发布、DOCX/PDF 报告、审计筛选分页。
- 最小后端补充包括项目文档/审查列表、审查状态/创建、报告列表、审计查询、失败重试和精确引文读取。操作继续由服务端逐次授权；默认没有已授权 `ReviewEngine` 时 API 返回 503，前端不合成结果。

## 验证记录

- `npm run api:check`：通过，生成结果与正式 OpenAPI 一致。
- `npm run lint`：通过，Biome 检查 20 个前端源/配置文件，无警告。Playwright 默认使用本机 Microsoft Edge channel。
- `npm run typecheck`：通过。
- `npm run test`：通过，2 个测试文件、6 个测试，覆盖 401 会话清理、中文错误映射、读请求取消以及基础 UI 交互。
- `npm run build`：通过，Vite 8.3.4 生产构建完成；JS 约 332 KB 未压缩、101.5 KB gzip。
- `.\scripts\verify.ps1` Full：通过，506 passed、0 failed、0 skipped，运行 242.22 秒；Ruff 全通过，Mypy 检查 89 个 Python 源文件，契约/State/任务检查、前端完整门禁、真实 HTTP/身份烟雾均通过。两个既有 pypdf `add_js` 弃用警告保留。
- `scripts/verify_repo.py`：通过契约、生成状态和任务证据范围检查。
- 新增 TASK-0011 API 回归：项目文档/审查列表、默认执行器 503、审计租户过滤/审计员权限。回归通过；全量 Full 中 506 项整体通过。受限沙箱不允许 Starlette `TestClient` 创建 Windows asyncio socketpair，因此该 Full 在允许本机回环 socket 的受控执行中完成。
- PostgreSQL16 专项：使用本次创建的临时 `postgres:16` 容器，`scripts/check_postgres.py` 迁移/RLS/租户/并发/回滚/API 检查通过；`scripts/check_legal_publications.py` 的 CAS/审计/隔离及真实离线 ReviewEngine checkpoint、重试、恢复、撤权、RLS、并发发布检查通过。临时容器已删除；未连接生产库或外部模型。
- `npm run e2e`：未运行。Playwright 全流程仍要求隔离 FastAPI/PostgreSQL、文档扫描/解析 worker、三种测试身份及注入的离线 `ReviewEngine`。当前十个 `E2E_*` 服务/身份变量均未配置。系统 Edge 已设为默认 Playwright 浏览器；尝试安装 Chromium 时 Playwright CDN 返回 `ECONNRESET`。不得把 API/单测计作浏览器验收。
- GitHub Actions / 远程推送：未执行。TASK-0011 当前尚无远程写入授权；本地结果不冒称远程 CI。

## 验收映射与剩余工作

| 检查 | 当前证据 | 状态 |
|---|---|---|
| TASK0011-001：浏览器完成关键业务且连接真实 API | 源码候选 `b1d7ca9`；前端页面、API 客户端、后端回归和 Playwright 流程脚本已存在；全链路真实浏览器运行缺少隔离执行环境 | 未通过，保持 `in_progress` |
| TASK0011-002：键盘/中文/错误/服务端权限 | 语义表单、中文错误映射、键盘 Escape 关闭对话框、前端单测、服务端 RBAC/租户回归已实现；浏览器键盘及撤权 E2E 尚未运行 | 未通过，保持 `in_progress` |

FR-013 要求对法规、规则、Skill 和模型配置执行草稿、发布、停用、回滚及审计。当前代码中没有可复用的完整管理 REST API：法规生命周期主要是服务层/CLI，规则/Skill 配置和模型路由没有面向该 UI 的统一持久化版本 API。现有只读审计页不等于管理页。本次未造假数据或在浏览器拼接配置；这部分需补充正式服务、权限/审计设计、API 契约和持久化后才能验收。

因 E2E 与 FR-013 未闭环，`tasks/active/TASK-0011-frontend.yaml` 状态保持 `in_progress`、两个 acceptance evidence 保持空数组；不创建归档候选或宣称完成。远程推送、源码 CI 和归档 CI 也尚未完成。
