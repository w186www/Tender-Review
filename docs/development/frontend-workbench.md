# 前端工作台

前端位于 `src/frontend`，由 React、TypeScript、Vite 和 React Router 构成。请求/响应类型来自 `contracts/openapi.yaml`，使用 `npm run api:generate` 更新，再用 `npm run api:check` 校验。不要手工维护第二套服务端 Schema。

## 启动

先按[身份与数据库启动说明](identity-data-start.md)启动 FastAPI、数据库并准备账号。Vite 将 `/api/v1` 代理到 `http://127.0.0.1:8000`；可用 `BIDDING_API_TARGET` 指定其他本机 API 地址。

```powershell
Set-Location src/frontend
npm ci
npm run dev
```

支持 Node.js 20.19+、22.12+ 或 24.x，以及 npm 10/11。令牌仅放在当前标签页的 `sessionStorage`，页面启动后向后端核验身份。前端角色判断只用于呈现，敏感操作仍由 API 授权。

## 验证

仓库统一的 `./scripts/verify.ps1` 在 Focused 和 Full 档位运行 API 生成一致性、Biome、TypeScript、Vitest 与生产构建；Quick 只做仓库/契约/秘密检查。若全新环境还没有 `node_modules`，脚本会使用锁文件执行 `npm ci`。

```powershell
npm run api:check
npm run lint
npm run typecheck
npm run test
npm run build
```

Playwright 浏览器流程位于 `e2e/workbench.spec.ts`，默认使用本机已安装的 Microsoft Edge（无需联网下载浏览器）。正式 E2E 只能指向 loopback 隔离环境，并要求三种测试身份（reviewer、auditor、operator）、真实 FastAPI/数据库/文档解析与扫描 worker，以及测试专用且明确注入的授权离线审查执行器。配置缺项时 `npm run e2e` 会失败关闭；不得使用远程环境、生产身份或生产模型通道。若改用 Chromium，可用 `npm run e2e:install` 安装浏览器文件。

TASK-0020 的本地交互演示复用上述隔离服务装配，运行 `python scripts/run_task0011_e2e.py --serve`。该模式只绑定 `127.0.0.1`，启动一次性 PostgreSQL/MinIO/ClamAV、显式注入的离线 `ReviewEngine`、本地 Vite 和一个消费合成租户持久化 ingestion queue 的 worker；按 Ctrl+C 会停止子进程和临时容器。前端仅在启动变量 `VITE_REVIEW_MODE=offline-deterministic` 时显示固定离线演示标识。不要把此模式改为普通 API 默认值或公网监听。

TASK-0020 当前候选已用真实 Microsoft Edge 完成上传合成 DOCX、TASK-0018 parser 扫描解析、审查、人工复核/发布和 Word/PDF 报告下载（5/5）。PostgreSQL JSON 将 `model_ids` 序列化为数组时，只在严格 `OCRRuntimeIdentity` 读取边界规范化为 tuple；原身份与 provenance 哈希校验保持。`--serve` 的本机启动和 Ctrl+C 精确清理也通过。演示使用显式 `OfflineReviewGateway`，不代表真实模型语义质量；推送 SHA 远端 CI 成功前任务仍未归档。证据与任务差距见[TASK-0020验收记录](TASK-0020-validation.md)和[差距核查](TASK-0020-demo-gap-assessment.md)。
