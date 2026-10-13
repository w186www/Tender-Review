# PROJECT_STATE

更新时间：2026-10-14
架构基线：Word V2.0 + ADR-0001 至 ADR-0009 / 开发契约v1alpha2
当前里程碑：M1基础退出检查已通过；M2进行协作准备，法规模块尚未实现

## 已完成

- 建立模型无关的仓库协作规则与文档入口。
- 建立需求 ID、验收 ID、安全 ID 和非功能需求 ID 的追踪机制。
- 建立 LangGraph 状态、风险、证据、任务事件和 OpenAPI 初始契约。
- 建立模型网关协议与供应商适配边界。
- 纳入 42 份法规全文及来源索引，等待摄取管道处理。
- 建立统一仓库验证脚本。
- TASK-0003修正：正式契约校验、State生成、流程依赖、分离风险状态、局部验收证据、锁定环境和CI配置。
- 已建立M0至M6七个里程碑与16个任务；53个需求/验收ID均已分配阶段，尚未全部实现。
- TASK-0002：可启动FastAPI/Uvicorn后端、健康检查、环境配置、请求追踪、统一错误和结构化安全日志。
- TASK-0015：夹具位置、独立诊断、错误码契约、模型数据策略、秘密扫描与文档冲突修复；首次Git提交已推送、CI已成功。

- TASK-0004：显式数据库迁移、可撤销JWT身份、租户/RBAC、版本化项目与事务幂等；PostgreSQL真实CI通过。
- TASK-0005：安全文件上传、持久作业、ClamAV强制扫描、受限Docker解析、PDF/DOCX/扫描件定位、人工质量/上下文版本、鉴权下载；真实容器与远程三作业CI通过。
- TASK-0016：跨软件模型分工与仓库派工文档、TASK-0006第一阶段派工单、两端启动提示词、交接/独立审查模板。工程文档已完成，不代表自动多Agent或法规业务已实现。

## 正在进行

- TASK-0006（法规版本摄取与适用范围检索）：正式 TASK in_progress、owner=codex，分支 work/TASK-0006。用户于2026-10-14取消后续DeepSeek接力，下一轮由Codex GPT-6.1 Sol（中）完成设计修订与实现。本轮接手输入HEAD f1a088dbf1c009e49c4b61c70d83d83ccd629054，工作区原本干净；设计候选4e908713323805bf0a73345f2bfd352d51039ea3独立审查结论changes_requested。D01–D07及反例见tasks/reviews/TASK-0006.md；当前design_revision，无代码候选/正式法规契约/已接受ADR-0010。本聊天整理记录并提交后停止写入；历史DeepSeek产物保留，当前派工撤销。
- 当前42份法规资料均未做官方核验，设计草案按此把全部版本标为unverified：在完成核验前，检索证据只能支撑“疑似/证据不足”，不能支撑确定性结论（与TASK0006-001一致）。

## 下一步

1. 下一轮Codex GPT-6.1 Sol（中）按最新派工单接手，先解决设计审查D01–D07，固化ADR-0010与正式契约/正反例，再进入实施；无需重新资料盘点。
2. Sol 完成法规摄取、切分、版本索引、检索及权限/发布/回滚核心，提供实际专项验证和完整门禁证据。对自己实现的检查记为自检/维护者核验；独立审查必须另有未参与实现的实际审查者，不能把单模型自检称独立审查。
3. 加快官方效力核验（首批范围见DEC-0006-01建议）：无法核实版本的资料只能作为待核实参考，不作为确定结论依据；不修改knowledge/legal原始资料。
4. 按依赖继续TASK-0007规则Skill与TASK-0008两个模型适配器。
5. 实现LangGraph完整流程、人工复核、报告、界面与部署。

## 最近验证

- TASK-0006 本轮Sol设计审查（2026-10-14，输入HEAD f1a088d）：42份哈希全匹配；5个草案Schema结构合法但接受两类矛盾反例。受限环境完整门禁第1–3步通过（Mypy41源文件），测试阶段因asyncio回环创建超时中止；允许回环环境重跑完整verify.ps1六步通过：186 passed、0失败/0错误/0跳过（JUnit已复核），Mypy41源文件，真实HTTP健康/404/请求编号及登录/项目生命周期/登出撤销均通过。日志为.verification/TASK-0006-sol-design-review-verify-loopback.log。最终整理后另重跑verify_repo、Ruff、Mypy和git diff --check均通过；仅工程记录变动，无代码/契约变化。此为本轮开发基线检查，不是法规业务验收。本轮未核对远程最新/CI、未执行法规业务专项及正式效力/Embedding验收。

- TASK-0006 discovery阶段（2026-10-14，本机PowerShell 7.6.6 + .venv Python 3.12.14，允许回环网络）：完整verify.ps1通过，186项测试、0失败/0跳过（JUnit tests=186 failures=0 errors=0 skipped=0），Mypy 41个源文件，真实HTTP健康/登录与项目生命周期检查通过。此为文档草案提交的门禁结果，不代表法规效力已核验或检索能力已实现；详情与未执行项见tasks/handoffs/TASK-0006.md。

- TASK-0016本地完整门禁通过，186项、0失败/0跳过、Mypy41源文件，实际两个HTTP检查通过；远程本次文档提交需推送后实际核验，不能冒用TASK-0005的SHA。证据见docs/development/TASK-0016-validation.md。

- TASK-0005本地：完整verify.ps1通过，186项、0失败/0跳过，Mypy41源文件；真实解析隔离、官方源码MinIO/ClamAV/OCR/扫描PDF/HTTP及PostgreSQL增量迁移/RLS均通过。
- TASK-0005最终源码远程实证：4d6fca6b16fbae66aed82041e08097162a444468，https://github.com/w186www/Tender-Review/actions/runs/38424742422 的baseline/postgres/ingestion均completed/success；已下载JUnit核验186项、0失败/0错误/0跳过。详细范围见docs/development/TASK-0005-validation.md。本次归档证据提交另触发相同CI，链接绑定明确源码版本，不将该SHA冒充后续HEAD。
- TASK-0005归档提交远程实证：0c57333434c6e0ed6c964c2e983da9e47df12426，https://github.com/w186www/Tender-Review/actions/runs/38425907130 三个作业均success，远程JUnit186项、0失败/0错误/0跳过。后续协作文档改动不冒用这一SHA作为当前HEAD。

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
- 本机Docker Linux Engine已可用（29.2.1）；临时PostgreSQL16本机迁移/权限/RLS/并发/回滚与真实S3/扫描/OCR检查通过，仅测试服务已清理。用户安装的PowerShell7.6.6运行最新完整门禁，186项全通过。
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

