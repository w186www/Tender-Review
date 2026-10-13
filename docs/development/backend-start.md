# TASK-0002 后端底座与启动

## 启动

在仓库根目录准备README规定的Python 3.12环境和锁定依赖后运行：

```powershell
./scripts/start.ps1
```

默认监听 `127.0.0.1:8000`。访问 `http://127.0.0.1:8000/api/v1/health`，返回 `{"status":"ok","version":"0.1.0"}`。开发环境接口文档为 `/docs`，生产与staging环境关闭文档入口。按Ctrl+C停止服务。

自定义本机端口：

```powershell
./scripts/start.ps1 -Port 8010
```

跨平台或直接使用Python：

```text
python -m bidding_compliance.api --host 127.0.0.1 --port 8000
```

## 配置

`.env.example`是模板，真实`.env`不提交。优先级为启动参数（host/port）>进程环境变量>.env>代码安全默认值。无有效配置时停止启动；不输出输入值或原始Pydantic错误。

APP_BASE_URL和OBJECT_STORAGE_ENDPOINT为公开基础地址，不允许账号、密码、查询参数或fragment；凭据应使用独立秘密配置，不能夹带在这些URL里。

| 字段 | 作用 | 默认 |
|---|---|---|
| APP_ENV | development/test/staging/production | development |
| APP_LOG_LEVEL | DEBUG/INFO/WARNING/ERROR/CRITICAL，大小写可规范化 | INFO |
| APP_HOST | 监听地址 | 127.0.0.1 |
| APP_PORT | 1至65535 | 8000 |
| APP_BASE_URL | 外部访问地址，当前只作为配置 | http://localhost:8000 |
| DATABASE_URL、REDIS_URL | 后续服务连接配置，按秘密处理 | 未设置 |
| OBJECT_STORAGE_ENDPOINT/BUCKET | 后续存储配置 | 未设置/bidding-compliance |
| MODEL_PROFILE | 后续模型路由profile | local-development |

## 接口和错误

- TASK-0002最初仅实现 `/api/v1/health`；TASK-0004新增认证和项目，TASK-0005新增安全文件接入及人工确认，见identity-data-start.md和secure-ingestion-start.md。业务审查仍为未来契约，运行时文档只列已实现路由。
- 健康返回版本是应用版本；OpenAPI文件的0.4.0是契约文档版本，含义不同。
- health为存活检查，不连接数据库、Redis、对象存储或模型，不证明这些依赖就绪。后续任务另行实现readiness。
- 每个HTTP响应返回X-Request-ID。合法UUID请求编号可沿用；任意其他文本会替换为新的UUID。
- 404、405、HTTP异常、422和未处理异常使用code、message、request_id、details统一格式；错误正文不回显输入和异常明细。
- 参数错误只返回错误数量。协议所需Allow、Retry-After、WWW-Authenticate头可保留；其他异常附加头不回显。

## 日志

启动入口配置JSON日志。请求日志只保存UTC时间、级别、事件、request_id、HTTP方法、路由模板、状态和耗时。未匹配路由用unmatched，不保存原始路径、查询、正文、Authorization、Cookie、数据库连接串、配置对象或traceback。

CLI关闭Uvicorn原始访问日志。常规stdout格式器仅输出允许的结构字段，不输出原始message、任意extra和exc_info。

500和响应中断另送独立stderr诊断通道（bidding_compliance.diagnostics，不传播到普通logger），记录请求ID、异常类型/模块、原因链及文件基名/行号/函数。该通道不记录异常消息、源代码行、完整磁盘路径、局部变量或请求正文。运维平台应独立收集并限制诊断sink访问，见ADR-0006；没有HTTP诊断查询接口。

## 验证与排错

```powershell
./scripts/verify.ps1
```

统一入口包含契约、Ruff、Mypy、Pytest和真实服务烟雾测试。最后一步创建自己的子进程，使用本机随机空闲端口检查200/404及请求编号，并清理该子进程。它不关闭其他服务。

Windows受限沙箱可能阻断asyncio内部回环连接；如测试停在创建事件循环，应在允许本机回环网络的环境运行同一命令，不跳过接口测试。端口冲突可换端口；依赖缺失按锁文件重新安装。TASK-0002不需要模型密钥或外部数据库。

## 后续工作

数据库、登录、RBAC、租户隔离和项目资源见TASK-0004；文件处理由TASK-0005实现。该底座未宣告完整生产安全或业务审查能力已验收。
