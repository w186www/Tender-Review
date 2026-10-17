# ADR-0014：中文业务工作台的前端架构

- 状态：accepted，TASK-0011
- 日期：2026-10-14

## 背景

TASK-0011 需要把现有 FastAPI 认证、项目、文件解析、LangGraph 审查、人工复核、不可变发布、报告和审计能力连接为浏览器工作流。仓库此前没有前端工程。前端类型必须从正式 OpenAPI 契约生成，不能维护第二份后端类型。

## 决策

- 使用 React + TypeScript + Vite 构建单页工作台，React Router 负责路由；自建少量语义 HTML/CSS 组件，不引入会遮蔽证据和业务状态的大型视觉组件库。
- 使用 `openapi-typescript` 从 `contracts/openapi.yaml` 生成 `src/frontend/src/api/schema.d.ts`，使用 `openapi-fetch` 按生成的 `paths` 调用 API。契约或生成器改变时，`api:check` 在临时输出上重新生成并逐字比较已提交产物。
- 前端工程、依赖清单、锁文件、源代码、构建和浏览器测试配置均放在 `src/frontend/**`。Vite 开发服务器将 `/api/v1` 代理到本地 FastAPI。正式运行的托管部署不属于 TASK-0011。
- `package.json` 使用兼容范围并提交 npm 锁文件；CI 和本地复现使用 `npm ci`。支持 Node 20.19+、22.12+ 与 24.x，避开不受支持的奇数主版本；npm 10/11 可用。仓库当前 Node 24.14 满足要求。
- JWT 继续使用后端 Bearer 契约。浏览器只在 `sessionStorage` 保存短期令牌以支持同一标签页刷新；应用启动后调用 `/auth/me` 验证当前会话，401 清除会话，注销调用服务端撤权。令牌不写入 URL、日志或构建产物；不使用 Cookie，因此前端不引入基于 Cookie 的 CSRF 流程。权限按钮只用于呈现，服务端逐次授权仍是边界。
- UI 将服务端风险字段作为文本显示，不解释为 HTML；原文定位使用服务端引用身份和校验接口，不在浏览器中全文搜索生成位置。没有后端可靠百分比时只显示实际阶段，不合成进度。
- 请求可通过 `AbortSignal` 取消，所有请求有 120 秒超时；业务写请求不自动重试。由用户重复提交时复用同一个 `Idempotency-Key`，并以服务端返回更新界面。401、403、404、409、422、429、5xx 映射为中文错误，并保留可公开的 `request_id`。
- 组件/API 交互使用 Vitest 与 Testing Library；主业务浏览器流程使用 Playwright，走真实 FastAPI 和数据库，并在隔离测试配置中显式注入离线授权执行器。生产默认不注入模型路由。

## 最小契约补充

代码审计发现 `contracts/openapi.yaml` 已描述但 API 代码未实现审查创建/状态读取；前端闭环还需要项目文档/审查列表、已生成报告列表和只读审计查询。TASK-0011 在正式契约中补充这些端点，查询由现有租户、项目、结果、身份服务层执行。审计查询只允许当前租户的 `auditor`，导出继续调用现有逐请求授权服务。新审查只在已授权 `ReviewEngine` 注入时启动，默认服务返回 503；不会生成假结果。

## 备选方案

- Vue：成熟可用，但仓库团队没有既有前端资产；React/TypeScript 与 OpenAPI 生成客户端更贴近现有交接要求。
- 服务端模板：依赖少，但复杂的复核、并发冲突、文件下载和证据面板会把交互状态放回服务端页面拼装，难以复用可测试的 API 客户端。
- 手写 TypeScript 请求/响应接口：拒绝，长期会与 FastAPI/Pydantic 契约漂移。
- 长期令牌放入 `localStorage`：拒绝。短期会话只保存在当前标签页的 `sessionStorage`，并由服务端查询当前身份和撤权状态。

## 后果

新增一个由 npm 锁文件固定的前端工具链和一个 OpenAPI 生成产物；开发与 CI 需要 Node.js/npm。API 查询能力有少量正式契约扩展。默认审查执行器仍关闭，完整端到端审查只能在隔离的、显式注入离线执行器的测试环境验证。

## 验证与依据

React 官方文档说明其组件可直接使用 TypeScript；Vite 官方当前指南要求 Node.js 20.19+ 或 22.12+；OpenAPI TypeScript 官方文档支持从本地 YAML/JSON 生成静态类型，并与 `openapi-fetch` 组合使用。来源：[React TypeScript](https://react.dev/learn/typescript)、[Vite 指南](https://vite.dev/guide/)、[OpenAPI TypeScript](https://openapi-ts.dev/about)。

