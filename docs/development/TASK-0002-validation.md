# TASK-0002 后端底座验收记录

日期：2026-10-13。环境：Windows、项目独立Python 3.12.14；FastAPI 0.143.0、Uvicorn 0.54.0，其余版本见requirements-dev.lock。

复查更正：原71项结果来自任务移动前；移动后仅复查结构，遗漏测试对active目录的依赖。本轮复现4失败/67通过后改用模板夹具，并增加任务移动回归。第1项修复后完整verify.ps1得到72通过、0失败，后续变更以TASK-0015验收记录为准。

TASK-0015本地最新为121项通过、0失败（包含后续诊断、契约和扫描回归）。远程CI已实际成功，提交SHA与运行链接独立记录于TASK-0015，不由本地通过推断。

## 实际验收

| 局部验收 | 实际结果 | 证据 |
|---|---|---|
| TASK0002-001 健康检查可启动且满足契约 | 真实TCP端口访问返回200、status=ok、version=0.1.0；健康正文通过仓库OpenAPI校验 | scripts/smoke_backend.py、tests/test_backend_foundation.py |
| TASK0002-002 请求ID与敏感日志 | 成功、404、405、422、HTTP异常和500保持响应编号；8个并发请求上下文隔离；输入、异常、配置凭据不回显 | tests/test_backend_foundation.py、src/bidding_compliance/core/logging.py |
| TASK0002-003 统一验证与启动说明 | 完整verify.ps1通过；PowerShell启动脚本语法检查通过；README和backend-start.md可按步骤启动 | scripts/verify.ps1、scripts/start.ps1、README.md、docs/development/backend-start.md |

第1项修复后完整运行：契约/示例/State/任务依赖、Ruff、Mypy（17个应用源文件）、Pytest（72项通过）和真实服务启动检查。JUnit结果为72 tests、0 failures、0 errors；该文件会被后续验证覆盖，最新结果见TASK-0015验收记录。

第1项复查烟雾检查临时端口60710；GET /api/v1/health返回200，GET /missing返回404，错误正文和响应头的请求ID一致。临时子进程已停止；该端口不作为日常服务地址。日常启动使用scripts/start.ps1的默认8000或明确配置端口。

依赖安装和pip check通过。源代码与契约之间没有修改接口正文格式；验证辅助工具补齐了OpenAPI paths中内联Schema的引用支持。

## 交付与范围

实现FastAPI应用工厂、环境配置、SecretStr连接配置、公开URL禁止夹带凭据、请求ContextVar、ASGI中间件、统一错误、字段允许列表JSON日志、CLI和PowerShell启动入口。

health是服务存活检查；不验证数据库、Redis、模型、OCR或存储就绪。当前只实现健康接口与基础错误处理，生产安全和业务端到端验收未完成。原TASK-0002阶段没有远程CI，TASK-0015已补充实际远程验证。

下一项TASK-0004：身份、租户、数据库迁移和项目资源。M1还需完成TASK-0004/0005才可进入阶段验收。

## 复现环境说明

当前受限沙箱会阻断Windows asyncio用于创建事件循环的内部回环连接，因此完整接口与真实HTTP验收已在允许本机回环网络的环境运行相同verify命令。没有跳过或mock掉接口与启动验证。
