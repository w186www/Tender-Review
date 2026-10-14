# PROJECT_STATE

更新时间：2026-10-14
架构基线：ADR-0012本期法规生命周期/来源映射接受；Word V2.0 + ADR-0011开发验证替代ADR-0009，ADR-0010法规方案proposed；业务ADR-0001至0008保留 / 开发契约v1alpha3
当前里程碑：M1基础退出检查已通过；M2退出条件已满足并完成；M3进行中，TASK-0009本地验收已通过，远端CI待执行

## 已完成

- 建立模型无关的仓库协作规则与文档入口。
- 建立需求 ID、验收 ID、安全 ID 和非功能需求 ID 的追踪机制。
- 建立 LangGraph 状态、风险、证据、任务事件和 OpenAPI 初始契约。
- 建立模型网关协议与供应商适配边界。
- 初始纳入42份法规全文及来源索引；TASK-0006已完成版本化摄取（新增1份新版）。
- 建立统一仓库验证脚本。
- TASK-0003修正：正式契约校验、State生成、流程依赖、分离风险状态、局部验收证据、锁定环境和CI配置。
- 已建立M0至M6七个里程碑与17个任务；53个需求/验收ID均已分配阶段，尚未全部实现。
- TASK-0002：可启动FastAPI/Uvicorn后端、健康检查、环境配置、请求追踪、统一错误和结构化安全日志。
- TASK-0015：夹具位置、独立诊断、错误码契约、模型数据策略、秘密扫描与文档冲突修复；首次Git提交已推送、CI已成功。

- TASK-0004：显式数据库迁移、可撤销JWT身份、租户/RBAC、版本化项目与事务幂等；PostgreSQL真实CI通过。
- TASK-0005：安全文件上传、持久作业、ClamAV强制扫描、受限Docker解析、PDF/DOCX/扫描件定位、人工质量/上下文版本、鉴权下载；真实容器与远程三作业CI通过。

- TASK-0006已完成并归档：43版本/3120片段，D01–D07本期缺陷全部解决/边界保持；效力与条款适用分开、完整HTML/PDF来源映射、独立全局授权、不可变核验/发布/双CAS/回滚/审计，Result5。源码5347b110a8c3561c72086afd455755810de59abf本地/远程Full413项与全部真实集成/汇总成功。旧42文本保持未核实，法规能力不替代最终违规判断。

- TASK-0017：单Codex实施、Quick/Focused/Full与失败关闭CI已完成；修复跨平台CRLF检出，最终源码68d67a80943e9c531f58ced7557d0c24938d84e9本地/远程Full279项与PostgreSQL、ingestion、汇总门禁通过，归档记录用Quick。

- TASK-0007已完成并归档：五类无模型确定性Skill、版本化规则与候选发现契约、原文定位/稳定去重及法规检索主题。源码236d2a6e231be030f719b0bbabc3f2b0a50039b3 Focused 30项、最终Full448项本地通过（0失败/错误/跳过），真实HTTP/身份/租户集成检查通过；远程38516913371适用作业及汇总门禁成功。详见TASK-0007-validation.md。

## 正在进行

- TASK-0009源码提交`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`：TASK0009-001/002本地证据、Focused13、Full500和真实PostgreSQL恢复/并发/事务故障专项均通过。任务保持in_progress，因受限环境的`git ls-remote`返回`getaddrinfo() thread failed to start`，尚未推送、运行远程CI或归档。详见`docs/development/TASK-0009-validation.md`。
- M2正式退出条件按证据核实：TASK-0007候选追溯、TASK-0006检索过滤、TASK-0008适配器合规均满足；roadmap.yaml标记M2 completed、M3 in_progress。局部任务完成不代表AC-003或M3完整闭环通过。
- TASK-0009生产模型仍受DEC-002禁用；TASK-0008预算账本仍仅具单进程一致性；TASK-0010未启动。

## 下一步

1. 远端访问恢复后核对`origin/work/TASK-0009`，普通推送`git push -u origin work/TASK-0009`并核验源码/归档提交的`verify-required`及所有适用GitHub Actions作业；不得强推或覆盖已有远端提交。
2. 法规库42份旧文本继续unverified，另3份未收录；逐项官方核验后才能支持确定依据，不从模型/索引标注推断效力。
3. 2019《实施条例》工程招标范围核验截止2026-10-14，未来基准日需新核验或显式参考。未知地区/采购上下文及大面积扫描正文映射失败关闭。
4. 等待TASK-0009远程CI后再完成其归档；不自动启动TASK-0010。人工审核管理、报告、界面、部署和M3端到端退出按后续正式任务执行。

## 最近验证

- TASK-0009本地源码候选`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`：Focused13、最终Full500（0失败/错误/跳过）、Ruff、Mypy80文件、契约/生成/秘密检查及真实HTTP/认证/项目撤权检查通过；真实PostgreSQL专项覆盖Checkpoint新进程恢复、双Worker并发恢复与状态/副作用、人工授权、RLS/快照拒绝、提交前数据库失败回滚、真实提交后确认丢失和新会话幂等重试。Full仅有两个既有pypdf `add_js`弃用警告。远端只读分支核对因`getaddrinfo() thread failed to start`未成功；按安全限制未升级网络、未推送或声称CI成功。任务保持in_progress，详见`docs/development/TASK-0009-validation.md`。

- TASK-0007最终代码源码236d2a6e231be030f719b0bbabc3f2b0a50039b3：Focused 30项通过；Full 448项、0失败/0错误/0跳过，Ruff、Mypy64源文件、契约生成检查及真实HTTP/身份/项目/撤权/租户隔离验证通过。Full在本机回环网络授权下执行，JUnit `.verification/pytest-result.xml`；两个既有pypdf `add_js`弃用警告。远程https://github.com/w186www/Tender-Review/actions/runs/38516913371 对应该源码，impact/baseline/postgres/ingestion/verify-required全部success；远端JUnit artifact已生成，但下载接口需认证，未声称远端测试数量。代码提交与证据绑定；后续文档/任务归档改动仅Quick，不重复Full，不合入main、不启动TASK-0008。详见docs/development/TASK-0007-validation.md。

- TASK-0006最终源码5347b110a8c3561c72086afd455755810de59abf：一次Full413项、0失败/错误/跳过，Ruff/Mypy54源文件与契约/生成、两个实际HTTP通过；真实PostgreSQL原迁移/RLS/复合FK/增量降级及全局核验/发布竞争、最小权限、撤权、失败事务回滚/历史重现通过。最终固定Docker官方PDF84条/15页、隔离、MinIO/ClamAV/OCR/HTTP全部通过，测试容器清理。远程https://github.com/w186www/Tender-Review/actions/runs/38510406707 completed/success，impact/baseline/postgres/ingestion/verify-required全部success，下载远程JUnit413/0/0/0。归档/证据后仅Quick，源码无变化，不重复Full。

- TASK-0006历史D03续建：95项Focused、真实PostgreSQL16及最终Full323项通过（JUnit0失败/0错误/0跳过，Ruff、Mypy48文件、正式契约/生成与两项实际HTTP检查）。修复Result v1alpha3正式EvidenceRef/资格矛盾/引用集合与冻结制品解析；D07同文本制品引用部分修复，原始清洗映射等余项保留。最终源码f0bd8270d990d5e5dc6897f329a770d7db332099已推送，远程https://github.com/w186www/Tender-Review/actions/runs/38498549575 completed/success，baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验323/0/0/0，后续仅工程记录Quick，无重复Full；TASK-0006继续in_progress。

- TASK-0017已归档：初始0016b306源码本地Full277项，但远程38446832736最终failure；日志确认旧42份法规CRLF哈希与Linux LF检出不一致。修复源码68d67a80943e9c531f58ced7557d0c24938d84e9，84项Focused、真实PostgreSQL16专项和最终Full279项通过（0失败/0错误/0跳过，Mypy48源文件及两个真实HTTP检查）。远程https://github.com/w186www/Tender-Review/actions/runs/38496768950 completed/success：baseline/postgres/ingestion/verify-required全部成功，下载远程JUnit核验279/0/0/0。仅记录/归档变动后Quick通过，未重复Full。完成规则ADR-0011，证据TASK-0017-validation.md；TASK-0006没有自动完成。

- TASK-0006本轮纠正：最终完整verify.ps1通过251项、0失败/0错误/0跳过（JUnit已核对），Mypy48文件；真实HTTP健康/身份/项目/撤销通过。56项法规专项、109项组合检查通过；临时PostgreSQL16增量/重复迁移、RLS/WITH CHECK、最小权限、运行读取/撤权/触发器/完整回滚实证通过，容器已清理。两次中间失败保留在TASK-0006-validation.md；无远端CI新证据。

- TASK-0006历史恢复分支自测（不是独立审查）：25项通过；Mypy46源文件无错误；真实43版本/3120条款摄取、新版84条完整提取与政府工程投标保证金检索通过。归档后最终完整verify.ps1通过215项、0失败/0错误/0跳过（JUnit已核对），真实HTTP健康及身份/项目/撤销流程通过；Ruff与契约/生成一致性通过。见docs/development/TASK-0006-validation.md。

- TASK-0005本地：完整verify.ps1通过，186项、0失败/0跳过，Mypy41源文件；真实解析隔离、官方源码MinIO/ClamAV/OCR/扫描PDF/HTTP及PostgreSQL增量迁移/RLS均通过。
- TASK-0005最终源码远程实证：4d6fca6b16fbae66aed82041e08097162a444468，https://github.com/w186www/Tender-Review/actions/runs/38424742422 的baseline/postgres/ingestion均completed/success；已下载JUnit核验186项、0失败/0错误/0跳过。详细范围见docs/development/TASK-0005-validation.md。本次归档证据提交另触发相同CI，链接绑定明确源码版本，不将该SHA冒充后续HEAD。

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
- 本机Docker Linux Engine已可用（29.2.1）；临时PostgreSQL16本机迁移/权限/RLS/并发/回滚与真实S3/扫描/OCR检查通过，仅测试服务已清理。TASK-0005历史PowerShell完整门禁186项全通过；当前任务结果见最近验证。
- Windows受限沙箱会阻断asyncio内部回环连接；完整验收须允许本机回环网络，不能跳过测试。
- 系统默认Python存在打包路径/ensurepip问题。已使用独立Python 3.12.14环境，统一脚本优先使用.venv；新环境按README创建，测试临时目录限定在项目内。
- 法规元数据已固定43个版本：42份旧文本仍未逐项核实，1份司法部2019修订《实施条例》核验到2026-10-14且仅启用工程范围。本期全局管理服务/鉴权CLI已实现；完整生产法规效力验收、pgvector、神经语义召回及管理前端仍待实施。
- 《建设工程施工合同（示范文本）》等 3 项资料未收录，详见 `knowledge/legal/索引.md`。
- 默认OCR已按ADR-0008采用中英文Tesseract端口、存储提供S3和本地开发适配；首选模型、生产服务和部署环境仍待确定。

## 待决策

- DEC-001：首个部署目标（本地 Docker Compose、云主机或 Kubernetes）。
- DEC-002：首选 LLM 与数据出境约束。
- DEC-003：Tesseract为首期实现；生产扫描件性能预算与复杂中文版面效果待评估。
- DEC-004：前端技术栈与企业OIDC集成；首期本地认证已按ADR-0007落地。

## 数据与迁移

- 数据库迁移版本：202610141800（TASK-0009持久审查run/制品/人工决定/不可变发布结果及PostgreSQL LangGraph Checkpoint；位于202610141700法规发布与授权迁移之后）；显式执行，API不自动建表，回滚会删除TASK-0009新增表及Checkpoint。
- 契约集合版本：`v1alpha3`；事件信封和模型profile示例维持各自v1alpha1，详见contracts/VERSION.md。
- 生产数据：无。


## 当前分支与审查基线

- 2026-10-14用户新指令覆盖之前的恢复分支限制：实现已保全迁移到work/TASK-0006；git fetch origin main核对最新main=bd2da2da984b6d1c34f3cfdb7da69e21661523be，当前任务分支已包含该提交。无force push/reset --hard，恢复分支和保全stash保留。
- 用户本次指令由ADR-0011记录，撤销ADR-0009默认跨软件/独立代理关卡；现有实现/问题与法规ADR-0010 proposed保留。Codex按实际验收自行收尾，不能假称独立审查或自动关闭问题。
- 不恢复DeepSeek派工或自动代理审批。当前无额外代理运行；保留历史审查的真实发现作为问题清单。

当前TASK-0007验收源码236d2a6e231be030f719b0bbabc3f2b0a50039b3；本地Focused30、Full448/真实集成和远程38516913371适用作业全部成功，任务已完成并归档。TASK-0008验收源码`4d1f59f69143c63c7d4273958a12da19ecf5acdf`（归档前工程记录提交`5b9b9f1bf68b245abb05b75cd855d07d30497d2a`）从归档提交`6edea37c071cfcec6cf8354b9d74f92fbcaba0a5`创建并包含TASK-0007验收源码；原stash@{0}仍保留。Focused54项、Full487项、真实本机后端/身份检查及源码提交远程CI运行`38521959503`（impact/baseline/postgres/ingestion/verify-required全部success）均通过。TASK0008-001/002按正式验收条件完成并归档；详见`docs/development/TASK-0008-validation.md`。生产预算仅实现单进程原子参考ledger，不能支持多进程生产一致性；DEC-002待批准、生产路由保持禁用，真实在线供应商调用未执行。TASK-0009源码SHA`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`的本地验收通过但远端CI待执行，保持in_progress；不启动TASK-0010。
