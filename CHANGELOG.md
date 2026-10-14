# Changelog

本项目遵循语义化版本；正式发布前使用 `0.x`。

## [Unreleased]

### Added

- TASK-0009 本地归档候选：TASK0009-001/002正式验收、本地 Full 500、Focused 13、真实 PostgreSQL 恢复/并发/事务故障专项通过。源码`c62673e2ff12a810d40aa6b81d19e35e5c73ce1e`和验证记录提交`99ce00f7b7bef09285e280b9b909143022c847b4`已推送且必要远程CI由用户确认成功；本次归档提交的远程CI待核验，全部适用作业及`verify-required`成功后方正式完成。DEC-002仍待批准、生产模型路由禁用、预算账本仅单进程一致性、法律证据最高为suspected；未进行真实供应商调用，未启动TASK-0010。详见 `docs/development/TASK-0009-validation.md`。

- TASK-0008 archived after formal TASK0008-001/002 checks, local Focused 54 and Full 487, real local HTTP/identity checks, and GitHub Actions run 38521959503 succeeded for impact/baseline/postgres/ingestion/verify-required. Added a provider-neutral gateway, OpenAI Responses and Anthropic Messages adapters, strict structured output validation, server-side routing/authorization, budget reservation, bounded retry/circuit breaker, and audit metadata. No live OpenAI/Anthropic calls were made. DEC-002 remains pending, production routes remain disabled, and the in-memory budget ledger provides single-process consistency only; shared persistence and multi-process production safety remain prerequisites.

- TASK-0007：实现五类无模型确定性Skill、版本化规则/Skill/候选发现契约、失败关闭覆盖、可追溯原文定位、稳定去重与法规检索主题。源码236d2a6e本地Focused30及Full448全通过，远程38516913371所有适用作业成功；任务已归档，M2仍待TASK-0008及整体退出验收。

- TASK-0006 D01/D02/D04/D05/D07：明确未知有效期与局部废止；采购方式/主体/对象及双框架、条款范围交集；原始HTML字节和PDF页框与清洗文本映射；独立全局grant及鉴权CLI；不可变来源/核验修订、稳定法规身份、双CAS发布/停用/回滚和原子审计。Manifest3/Index4/Query3/Result5、OpenAPI0.5.0、迁移1600/1700；旧法规核验状态及原文保留。源码5347b110的本地/远程Full413项及真实PostgreSQL/Docker/官方PDF/文件接入成功，D01–D07本期退出条件满足并归档；证据38510406707，远程JUnit413/0/0/0。后续记录Quick，不重复Full、不合入main、不启动后续任务。

- TASK-0006 D03续建：Result v1alpha3正式EvidenceRef与完整citable_evidence关联校验，拒绝未核实却可确认、引用/哈希/定位/日期矛盾；证据URI/hash指同一清洗文本，冻结索引解析复核来源及适用性，新增39项回归。旧结果版本显式拒绝，历史记录保留，无DDL变更；其余D问题和任务in_progress保持。

- TASK-0017：verify.ps1增加Quick/Focused并保留默认Full；显式测试路径防越界、独立局部JUnit、失败关闭的CI选档及verify-required汇总门禁。

- TASK-0006纠正：在效版本状态按基准日比较；注册地区映射、context_incomplete与excluded原因；新增202610141200检索运行快照/基准日来源/哈希、读取重新鉴权、RLS和追加写触发器，Query/Result v1alpha2。

- TASK-0006：法规来源/文本哈希、有效区间、核验截止日及范围契约；不可变索引、精确条款定位、BM25与字符向量混合检索，服务端身份/项目范围检查。
- 用户授权法规更新：保留42份原文，新增司法部2019修订《实施条例》与来源HTML，43版本/3120片段；旧资料保持待核实，新增25项回归与ADR-0010及启动说明。

- TASK-0005：鉴权上传与持久化解析作业、固定镜像隔离、强制ClamAV、S3/本地开发存储、PDF/DOCX/中英文OCR定位。
- 人工文本修正与质量复检、上下文确认/版本历史、鉴权附件下载；OpenAPI 0.4.0与增量迁移202610131300。
- 真实Docker隔离/S3/杀毒/OCR/HTTP CI门禁，文件接入启动说明；租约重入和权限撤销回归。

- TASK-0004：Argon2账号引导、短期JWT与可撤销会话、数据库即时身份/RBAC校验。
- 显式Alembic核心迁移、租户复合外键、PostgreSQL FORCE RLS、不可覆盖历史与审计。
- 项目创建/分页查询/版本更新/历史、事务幂等与乐观锁；真实业务HTTP启动检查和独立PostgreSQL CI门禁。
- 工程治理基线、需求追踪、架构决策记录和跨模型交接机制。
- OpenAPI、领域 Schema、事件 Schema 与模型网关协议草案。
- 统一仓库验证入口与初始黄金评估样本。
- 法规全文库及来源索引。
- M0至M6里程碑与14个任务，局部验收证据、依赖顺序和显式范围。
- JSON Schema与OpenAPI正式校验、正反例、State生成检查、Ruff、Mypy和Pytest门禁。
- Python 3.12独立环境与已解析依赖锁文件。
- TASK-0002：FastAPI应用工厂、健康接口、Pydantic环境配置、请求编号与统一错误响应。
- JSON日志字段允许列表、秘密配置隐藏、公开URL禁止夹带凭据、开发文档按环境开关。
- Uvicorn启动入口、PowerShell启动脚本、后端接口测试和真实HTTP启动检查。

### Changed

- TASK-0006 D03源码f0bd827：95项Focused、真实PostgreSQL及最终Full323项通过；远程38498549575完整门禁成功，下载JUnit323/0/0/0。记录更新仅Quick，TASK-0006保留in_progress及具体D余项，未合入main。

- TASK-0017已归档：源码68d67a809的本地/远程279项Full、真实PostgreSQL、ingestion及verify-required均通过；远程JUnit0失败/错误/跳过。TASK-0006仍进行中，D问题保留。

- TASK-0017远程PostgreSQL故障定位：旧42份法规的CRLF哈希与Linux默认LF检出不一致。固定跨平台检出字节并增加真实Git克隆/全部语料哈希与定位回归，保留原文及严格哈希断言。

- 用户要求恢复单Codex直接实施/自检/收尾，ADR-0011替代默认跨软件/独立代理审批；既有TASK-0006代码和问题保留。纯记录/归档改动Quick，代码候选Full，取消相同源码反复全测。

- TASK-0006实施者自行归档已撤销；迁移work/TASK-0006并恢复ADR-0009独立审查关卡，正式任务in_progress。

- TASK-0005局部验收完成并归档；M1基础退出检查通过，下一项为TASK-0006。源码CI三作业成功，186项远程JUnit与本地归档后门禁已核验。

- TASK-0005：文本转录与上下文确认并发时返回409且保留既有快照；SQLite租约时间条件由数据库判断。

- TASK-0015：修复任务移动后的测试夹具依赖，更正历史验收记录。
- 增加独立安全异常诊断、错误码契约/正反例、data_policy枚举及秘密扫描回归。
- 补齐ADR备选方案、数据流/部署索引和Word差异登记；首次main提交已推送并获得GitHub CI成功实证。

- 初始开发契约升级至v1alpha2：修正项目响应组合，分离证据状态与人工复核决定。
- 主链按候选发现→法规检索→基于证据分析执行；人工解析修正后复检；发布结果快照后渲染报告。
- State类型从Schema生成，阻断字段与必填定义漂移。
- TASK-0001完成范围修正为初始治理，不表示两个适配器或生产交接已验收。

