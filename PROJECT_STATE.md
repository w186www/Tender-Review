# PROJECT_STATE

更新时间：2026-10-13  
架构基线：Word V2.0 + ADR-0001 至 ADR-0008 / 开发契约v1alpha2
当前里程碑：M1后端与文件接入（TASK-0002/0004已完成，0005进行中）

## 已完成

- 建立模型无关的仓库协作规则与文档入口。
- 建立需求 ID、验收 ID、安全 ID 和非功能需求 ID 的追踪机制。
- 建立 LangGraph 状态、风险、证据、任务事件和 OpenAPI 初始契约。
- 建立模型网关协议与供应商适配边界。
- 纳入 42 份法规全文及来源索引，等待摄取管道处理。
- 建立统一仓库验证脚本。
- TASK-0003修正：正式契约校验、State生成、流程依赖、分离风险状态、局部验收证据、锁定环境和CI配置。
- 已建立M0至M6七个里程碑与15个任务；53个需求/验收ID均已分配阶段，尚未全部实现。
- TASK-0002：可启动FastAPI/Uvicorn后端、健康检查、环境配置、请求追踪、统一错误和结构化安全日志。
- TASK-0015：夹具位置、独立诊断、错误码契约、模型数据策略、秘密扫描与文档冲突修复；首次Git提交已推送、CI已成功。

- TASK-0004：显式数据库迁移、可撤销JWT身份、租户/RBAC、版本化项目与事务幂等；PostgreSQL真实CI通过。

## 正在进行

- TASK-0005收尾：安全上传、持久作业、隔离解析、OCR与可定位片段、人工上下文/质量修正已实现；完整门禁和远程三作业CI复验后归档。

## 下一步

1. 执行TASK-0005：安全文件接入、解析、原文定位和上下文确认。
2. 基于TASK-0004的Principal与租户复合键接入文件/任务，不从请求或模型取授权。
3. 按依赖建立法规检索、规则Skill和两个模型适配器。
4. 实现LangGraph完整流程、人工复核、报告、界面与部署。

## 最近验证

- TASK-0005本地：完整verify.ps1通过，185项、0失败/0跳过，Mypy41源文件；真实解析隔离、MinIO/ClamAV/OCR/HTTP及PostgreSQL增量迁移/RLS均通过。远程三作业CI待推送核验；详细范围见docs/development/TASK-0005-validation.md。

- TASK-0004本地最新：完整verify.ps1通过，152项测试、0失败/0跳过，Mypy检查27个源文件；真实HTTP身份与项目流程通过。
- TASK-0004最终代码远程实证：提交5dca2e341b97ce08d830a91936ca4d3d0f511aaa，https://github.com/w186www/Tender-Review/actions/runs/38393126223 的baseline与postgres均completed/success。已下载远程JUnit核验152 tests、0 failures、0 errors、0 skipped。链接对应明确的代码SHA；本证据文档提交自身另触发CI，不将代码SHA冒充后续HEAD。

- TASK-0015历史结果：按项修复后完整verify.ps1通过，121项测试、0失败；当时Mypy检查18个应用源文件，真实HTTP检查通过。分项记录见docs/development/TASK-0015-validation.md。
- 健康200、未知路径404、请求编号一致；临时服务已停止。默认启动方式：./scripts/start.ps1。
- 独立环境安装与pip check通过，实际版本已锁定；TASK-0002证据见docs/development/TASK-0002-validation.md，M0历史证据见baseline-validation.md。
- 远程CI已实际成功：提交1e744ed15e7d35934cbe536695ab2b8276b02980，运行https://github.com/w186www/Tender-Review/actions/runs/38388275001，状态completed/success。该链接核验对应源代码提交；证据提交会另行触发CI，不能将历史SHA冒充当前HEAD。
- 没有宣告业务审查、数据库就绪或完整生产安全验收。

## 已知问题

- 后端数据库/身份权限、项目读写、安全文件接入和独立单作业Worker已实现；持续队列调度、LangGraph业务审查、报告和前端尚未实现。
- Word内嵌图片需人工转录；DOCX外部关系含超链接严格拒绝；中文复杂版面质量仍需黄金集验收。详见secure-ingestion-start.md。
- 本机Docker Linux Engine已可用（29.2.1）；临时PostgreSQL16本机迁移/权限/RLS/并发/回滚检查通过，容器已清理。用户安装的PowerShell7.6.6运行完整门禁，152项全通过。
- Windows受限沙箱会阻断asyncio内部回环连接；完整验收须允许本机回环网络，不能跳过测试。
- 系统默认Python存在打包路径/ensurepip问题。已使用独立Python 3.12.14环境，统一脚本优先使用.venv；新环境按README创建，测试临时目录限定在项目内。
- 法规索引中有若干“未核实版本”；进入生产知识库前必须人工核验效力状态与发布日期。
- 《建设工程施工合同（示范文本）》等 3 项资料未收录，详见 `knowledge/legal/索引.md`。
- 默认OCR已按ADR-0008采用中英文Tesseract端口、存储提供S3和本地开发适配；首选模型、生产服务和部署环境仍待确定。

## 待决策

- DEC-001：首个部署目标（本地 Docker Compose、云主机或 Kubernetes）。
- DEC-002：首选 LLM 与数据出境约束。
- DEC-003：Tesseract为首期实现；生产扫描件性能预算与复杂中文版面效果待评估。
- DEC-004：前端技术栈与企业OIDC集成；首期本地认证已按ADR-0007落地。

## 数据与迁移

- 数据库迁移版本：202610131300（显式执行，API不自动建表）；降级移除新增解析历史，先备份并停止写入，见secure-ingestion-start.md。
- 契约集合版本：`v1alpha2`；事件信封和模型profile示例维持各自v1alpha1，详见contracts/VERSION.md。
- 生产数据：无。

