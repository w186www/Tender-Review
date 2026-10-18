# TASK-0006 验证证据（原自测与本轮纠正分开）

历史自测日期：2026-10-14，原恢复分支未提交候选。下述215项及旧索引哈希只属于原自测；自审completed已撤销，不能作为本轮独立审查通过证据。

## 当前最终候选验收（2026-10-14，单写入者自检）

源码：5347b110a8c3561c72086afd455755810de59abf，work/TASK-0006。接手实际HEAD为b8ed12d4bbac8836922a80c2816cb975829f679a，工作区干净且与远程一致；不是直接沿用聊天中的f0bd827。D01/D07/D04/D05/D02依赖顺序分别提交d9aa320/4241f4e/baf6ac5/0556869/5347b11。main保持bd2da2da984b6d1c34f3cfdb7da69e21661523be，保全stash不动，无代理、跨软件审批或后续任务。

| 问题 | 最终实现与验收证据 | 当前局部结论 |
|---|---|---|
| D01 | end_status区分未知与核实无终止，条款窗口与父法规取交集；局部废止当日仅排除对应条款，其他有效条款保留。test_legal_lifecycle.py 17项涵盖起日前/日、终止前/当日/后、仅终止日、未知上界、核验截止和替换 | 本期缺陷关闭 |
| D02 | 独立不可变revision/来源/稳定law_id，双序号CAS和完整CorpusBundle；发布/停用/回滚/审计同事务、幂等绑定内容。test_legal_publications.py 19项；真实PostgreSQL并发及REVOKE审计INSERT失败回滚、特权历史删除拒绝 | 本期缺陷关闭 |
| D03 | 保留正式EvidenceRef与集合/资格/哈希/定位校验；Result5继续重验效力/范围/框架，历史运行hash先验证再对照不可变发布 | 原修复保持并加固 |
| D04 | 项目API/context/query方法/主体/对象版本化；未知上下文零Embedding、双框架保留、版本/条款范围交集；test_legal_applicability.py 24项及原地区/上下文变更测试 | 本期缺陷关闭，有限范围不等同全部生产法规适用性 |
| D05 | 独立5类global capability、live身份/会话/grant；tenant admin拒绝、跨租户run拒绝、撤权及真实FORCE RLS/最小权限。test_legal_authorization.py 13项和两套真实PG专项 | 本期缺陷关闭 |
| D06 | 无公共/租户结果缓存，每次独立run并冻结所有输入，不跨项目/日期复用；原test_legal_runs.py保持 | 无缓存边界保持；将来缓存另验 |
| D07 | 原始HTML字节/实体与清洗字符映射，PDF页框/glyph覆盖、目录/页脚排除、generated头禁引用、重复/丢失条号拒绝；test_legal_sources.py 10项及真实隔离84条/15页PDF专项 | 本期缺陷关闭；大面积扫描PDF失败关闭，不虚称OCR完整覆盖 |

TASK0006-001通过：未核实、未知上界、超核验日、未知范围、无完整定位均不可确认；显式参考仍有原因，已知过期/地区/方式/条款不适用不返回。TASK0006-002通过：完整可信项目上下文和基准日生成query，返回原文/条号/来源/哈希/框架/证据定位，冻结publication/revision/index/context/actor和审计，真实原字节可重现。

最终本地./scripts/verify.ps1 Full退出0，JUnit413 tests/0 failures/0 errors/0 skipped；169.51秒，Ruff与Mypy54文件、全部契约/生成及实际HTTP健康、登录/项目/版本/撤销通过。相对旧D03的323项增加90项：D01 17、D07 10、D04 24、D05 13、D02 19及7项正式管理契约正反例。只有两项pypdf合成恶意JS拒绝样本弃用警告，无放宽/删除/跳过测试。

同一源码真实集成全部退出0：
- .verification/task0006-final-baseline-pg.log：原迁移/重复/增量/元数据、身份/项目API、RLS、租户复合FK、运行读取撤权及完整降级/重建。
- .verification/task0006-final-lifecycle-pg.log：全局grant最小权限/真实RLS、并发核验及发布/回滚各一胜、相同文本独立修订、幂等、冻结字节重现、越权/撤权、审计失败原子回滚、停用/恢复追加历史、特权DELETE拒绝。
- .verification/task0006-final-parser.log/.verification/task0006-final-sources.log：重新构建最终固定镜像，UID/只读/无网络/权限/资源限制，真实官方PDF84条15页与glyph覆盖。镜像配置sha256:e82ac6a5b0ee7bd90853afd4642bebf28667f25b73081594e738e8d6d3824faf。
- .verification/task0006-final-ingestion.log：既有真实MinIO、ClamAV良性/恶意门禁、PDF/DOCX/图片/扫描PDF OCR、HTTP/上下文/下载/租户隔离。全部自有测试容器已清理，无现有数据库改动。

远程候选运行：https://github.com/w186www/Tender-Review/actions/runs/38510406707 ，head_sha必须等于上列源码。已核对completed/success：impact/baseline/postgres/ingestion/verify-required全部success，quick因Full选档不适用。下载.verification/task0006-final-remote-junit/pytest-result.xml，远程JUnit413 tests、0 failures、0 errors、0 skipped；179.012秒，与本地相符。完整CI与JUnit绑定上述实际源码，非旧f0bd827证据。

契约升级Manifest3/Index4/Query3/Result5、OpenAPI0.5.0，新增管理/来源DTO；显式迁移1600/1700，旧身份/项目/检索历史不改写。无生产数据，旧结果须原消费者。正文/来源/核验字节冻结不进入State。新业务入口只读当前已发布快照，历史入口重新鉴权，CLI不自动授予全局能力。

剩余边界不是被放宽的门禁：42旧文本仍unverified，新增2019工程招标范围核验只到2026-10-14；未支持地区/未知项目上下文/无法完整映射扫描正文失败关闭。全库效力核验、3份缺失资料、pgvector/神经召回/性能、规则、模型、前端、完整LangGraph和M2/M5全局验收尚未实现。没有已知未解决的本期D01–D07阻断；全部本期条件、最终Full、真实集成和源码远程CI均已满足，TASK-0006达到局部退出条件并归档；M2整体未完成。源码之后仅任务/文档证据记录，用Quick，不重复Full。

归档第一次Quick失败：TASK-0017证据清单仍引用active/TASK-0006路径。已将该纯任务元数据引用同步为completed路径，未删证据/放宽检查；重新Quick通过，代码/契约/数据/配置/依赖/测试/验证脚本均与5347b110相同，不重复Full。

以下各节保留历史候选及中间失败，不作为当前源码的验收结果。

## 历史局部验收

| 验收 | 证据 | 结果 |
|---|---|---|
| TASK0006-001 未核实版本不能支持确定结论 | tests/test_legal_retrieval.py::test_references_cannot_confirm、test_unlocated_notice_is_reference、test_real_corpus_official_extraction_and_verified_retrieval | 默认排除参考；显式参考模式返回unverified与不具备确认资格；超核验截止日降级 |
| TASK0006-002 按基准日、地区、采购类型返回原文、条号、来源 | tests/test_legal_retrieval.py::test_exact_article_source_and_determinism、test_scope_filter_before_ranking、test_end_date_exclusive_and_current_at_review_date、test_project_authorization_precedes_embedding_and_uses_database_scope | 来源/引用哈希、字符定位一致；范围过滤先于召回；撤销会话不得触发Embedding |

新增25项专项测试全部通过。首次完整verify.ps1：211项、0失败/0跳过，Mypy46源文件无错误，Ruff、契约生成/正反例、真实HTTP健康及身份/项目/撤销均通过。归档后最终verify.ps1全通过：215项、0失败/0错误/0跳过，JUnit汇总已核对；Mypy46源文件、Ruff、契约/生成一致性和两项真实HTTP启动检查均通过。仅既有pypdf合成JavaScript拒绝样本有一条弃用警告，不影响验收。受限沙箱完整测试停滞后已停止，允许回环网络的同一门禁通过，没有跳过或降低测试。

## 真实资料与复现

摄取命令：`.venv/Scripts/python.exe scripts/legal_corpus.py build`（PYTHONPATH=src）。实际43版本、3120条款片段；索引哈希`2add21ee626de048eb27600e63657d23134babd54976481bec0daa80dcbc4c12`。默认查询“投标保证金”，工程、政府采购、CN/福建/福州、2026-10-14：首条为2019修订《实施条例》第二十六条。实际资料测试确认84条完整提取、新版正文可从官方HTML重现、返回原文定位与哈希一致。

来源：[司法部国家行政法规库](https://xzfg.moj.gov.cn/front/law/detail?LawID=339&Query=)。2026-10-14下载保留原始HTML；页面沿革列出2011公布与2017、2018、2019修订，原始库中的2011文本未冒充2019版本。新版以2019-03-02为本版本生效起点，核验截止2026-10-14，启用工程范围。原始HTML、提取正文与哈希均在knowledge/legal及config/legal/manifest.json。现有42文本全部固定来源及采集哈希，无法逐项核实的条目保持unverified；这不宣告法规全库现行效力验收。

## 安全与限制

覆盖路径越界、大小限额、重复条号、重叠/重复版本、恶意来源URL、来源/索引/引用篡改、身份撤销和项目范围。查询不发起网络、无供应商SDK、无租户正文外传。HTML只保存/提取，不执行其指令。索引内容寻址、不可覆盖、加载时复建核验。

未验收：黄金召回质量、神经语义Embedding、pgvector、生产大规模性能、管理审批发布、完整LangGraph/Evidence Checker与全局AC-002/AC-004。无数据库迁移，无GitHub CI新证据，不复用历史CI冒充本次结果。

## 本轮用户指令纠正（2026-10-14）

分支work/TASK-0006包含git fetch origin main核对的最新main bd2da2da984b6d1c34f3cfdb7da69e21661523be。保全stash保留，未force push/reset。设计候选91b4c1b独立复审changes_requested；修订c232e4bb解决R01/R02，仅本轮三项修复方案approved，完整D余项仍changes_requested。审查者与实施者不同，记录见tasks/reviews/TASK-0006-design-rereview.md。

- 法规专项：56项真实通过，含带终止日在效状态、地区别名/未知/错误祖先、上下文不完整不调用Embedding、同项目两日期、改上下文后重开Session读取旧运行、跨租户/撤权、输入/输出/关联篡改、审计原子回滚与SQLite追加写触发器。
- 真实PostgreSQL16：使用已有镜像创建一次性127.0.0.1测试容器，运行scripts/check_postgres.py，退出0。验证旧基线增量/重复升级、ORM一致性、API/并发/复合外键、FORCE RLS/WITH CHECK、最小SELECT/INSERT权限（UPDATE/DELETE无权限）、持久运行跨会话读取、跨租户拒绝/撤权、特权账号UPDATE/DELETE被追加写触发器拒绝、完整降级/重建。测试容器已清理。此为本机实证，无新GitHub CI证据。
- 原始HTML重新获取并固定字节（Git-text转换曾改变保全文件，未伪装沿用旧来源哈希）。新版正文仍从该来源完整重现84条；当前43版本/3120片段索引哈希8b47ebd7923912bcd7b17ec0fe51ef0ccb0ac58271430f377268aaa58ea28954。原始快照作为不执行的字节制品固定-text/-diff，代码与契约检查不豁免。
- 完整verify.ps1首轮实际失败：245 passed / 1 failed（test_generated_legal_contracts_are_current），因实施者在测试进程已加载旧DTO后更新地区枚举/生成Schema，产生并发文件漂移。已固定代码/契约并重跑；没有修改或跳过该检查。之后补入5个新版契约反例，最终完整结果另行补记。

原D01–D07部分/已解决回应均独立列在修订设计及交接，剩余管理发布、采购方式/双框架/条款级适用、部分废止、EvidenceRef映射、原始HTML/PDF清洗映射等不合并成笼统“未验收”，任务不自行归档。

- 第二轮完整verify.ps1停在Mypy：地区枚举list[str]与Pydantic JsonValue类型不兼容（1处）。现已用显式list[JsonValue]修正，严格Mypy48源文件与Ruff均通过；生成Schema语义未改，无忽略/关闭类型检查。最终完整重跑待记录。

### 本轮最终自测结果（待独立代码审查）

固定代码与契约后完整pwsh -NoProfile -File scripts/verify.ps1退出0：251 passed、0失败/0错误/0跳过，JUnit已复核；Mypy48源文件、Ruff、契约/State/法规生成一致性、真实HTTP健康/404/请求编号与登录/项目版本/登出撤销均通过。历史失败两轮保留如上。只有既有pypdf合成拒绝样本弃用警告。专项56项及追加契约后组合109项通过，PostgreSQL真实脚本退出0。未执行远端CI，无新CI链接。

实施者只提交待审候选，不能将上述自测作为独立代码审查或归档依据。确切候选SHA在提交后的handoff文档提交记录，避免自引用。

本轮代码候选：a88f5171888a2ede21122332c243451446ad96f4；基线main：bd2da2da984b6d1c34f3cfdb7da69e21661523be。上述251项最终检查针对该候选提交的源文件/契约/测试，候选之后仅补交接/验证/阶段记录；实施者停止写入待独立审查。


## 历史D03单写入者续建记录

本节覆盖历史默认独立代理/跨软件关卡；依据ADR-0011由当前执行者设计、实现、自检。历史真实发现及失败记录保留。TASK-0017先完成：源码68d67a809、远程38496768950全部适用作业/汇总门禁成功，279项远程JUnit0失败/错误/跳过。TASK-0006仍in_progress。

- 已实际复现D03：原DTO/正式JSON Schema均接受reason/version_status=unverified、eligible_for_confirmation=true。此次先修Result正式契约至v1alpha3（Query v1alpha2、Manifest/Index v1alpha1不变），引用现有EvidenceRef $id；旧Result v1alpha1/v1alpha2明确拒绝，不重写追加写历史，无生产数据、无DDL变化。
- LegalHit校验资格/原因/状态、条号/起日、引用UTF-8 SHA-256、字符区间及EvidenceRef所有关联字段。Result校验唯一hit ID、按hits顺序列出的完整可引用集合、参考模式、地区/日期/运行一致性；服务读取增加输入/输出版本关联。任意EvidenceRef、悬空/重复/遗漏/未核实引用、重标资格、错版本/日期等反例保留。
- EvidenceRef以artifact://legal-text/<text_hash>与text_hash/字符区间指同一文本制品；hit保留原始官方URL/HTML哈希。corpus.resolve_evidence仅通过冻结索引解析受限路径、核验来源/文本/引用字节，并重新判断日期、地区、采购类型、项目类型、核验期限和参考资格，不信任调用方路径/标志。真实司法部HTML与清洗正文分别保留正确哈希，返回条款逐一复现。
- 过程Focused最终95项通过，Ruff、Mypy48源文件及Quick前置门禁通过。新增39项证据反例/真实复现检查；契约正反例清单增加完整正式引用正例及4个矛盾反例。过程中首次Quick因旧结果fixture版本未同步失败，修复fixture版本后通过；Focused曾因3处101字符行超出Ruff上限失败，换行修复后通过，未关闭静态规则/断言。
- 真实一次性PostgreSQL16运行修改后的scripts/check_postgres.py退出0：原有增量/重复迁移、元数据一致性、并发/租户复合FK、FORCE RLS/WITH CHECK、最小授权、运行读取/撤权、追加写触发器、完整降级/重建均保留；新增持久化返回证据集合及制品逐项解析。日志.verification/task0006-evidence-postgres.log，测试容器已清理。
- 最终代码候选Full退出0：323项、0失败/0错误/0跳过，JUnit已复核；Ruff、Mypy48源文件、契约/生成一致性与两项真实HTTP检查全部通过，仅原pypdf合成拒绝样本弃用警告。相对TASK-0017的279项增加39项证据专项及5项正式契约fixture。此后仅工程记录变化用Quick，不重复Full；此次源码SHA/远程CI另行补记，不复用TASK-0017 CI。

### 历史D03候选自检问题状态

| 问题 | 本次真实处理 | 剩余事项 |
|---|---|---|
| D01 | 原半开区间与历史基准日在效状态修复保留 | 未知上界/核实无终止区分、局部废止门禁仍未完成 |
| D02 | 原内容寻址索引与完整运行输入冻结保留 | 独立核验修订实体、全局publication/current原子发布、并发/回滚仍未完成 |
| D03 | 本轮实现正式EvidenceRef、资格矛盾拒绝、集合引用完整性、制品/适用性解析，95项专项与真实数据库通过 | 最终Full323项通过；源码CI全部适用作业成功；完整法律适用性仍取决D04，不能直接输出最终finding |
| D04 | 原地区注册映射、上下文显式错误、基准日/项目运行冻结保留 | 采购方式、交叉法律框架及条款级范围仍未完成 |
| D05 | 原业务鉴权、跨租户/撤权与真实RLS保留 | 全局运维授权及发布/停用/回滚审计仍未完成 |
| D06 | 每次独立run，无公共/租户结果缓存 | 启用缓存前须重新设计全部输入键和授权；不声称缓存性能验收 |
| D07 | 本轮解决EvidenceRef URI/hash/locator同一文本制品，真实引用可解析；原字节哈希/84条/长条切片保留 | HTML清洗到原始字节映射、真实PDF覆盖/目录排除仍未完成 |

此表为当前执行者自检，不虚称独立审查。未关闭项保留具体验收要求，TASK-0006不归档、不合入main、不启动后续任务。

本轮D03最终源码候选f0bd8270d990d5e5dc6897f329a770d7db332099（分支work/TASK-0006），本地Full323项及真实PostgreSQL专项绑定该提交中的代码/契约/测试/脚本。远程新运行https://github.com/w186www/Tender-Review/actions/runs/38498549575最终completed/success：impact/baseline/postgres/ingestion/verify-required全部success，quick仅因Full选档不适用。已下载远程baseline-test-results并核验323 tests、0 failures、0 errors、0 skipped。源码之后只更新工程证据，Quick，不重复Full；之前TASK-0017的成功CI不冒作此源码证据。保全stash仍在，main未修改。

最终证据记录相对f0bd827仅PROJECT_STATE、任务/自检/验证/CHANGELOG和提示文本变动，无代码/契约/数据/配置/依赖/测试/脚本变化；Quick通过。D03的本轮引用契约/解析修复有真实证据，D07仅关闭同一文本制品引用部分；全任务仍in_progress。下一步为D01未知上界/局部废止，再依次处理表中各项剩余验收，不合入main、不启动后续任务。

## 本轮D01过程验证（完整收尾前）

实际接手HEAD b8ed12d，任务实际文件TASK-0006-legal-retrieval.yaml，工作区干净且远程一致。旧源码323项结果不冒作新代码证据。ADR-0012明确效力/适用性/来源/发布边界。D01新增end_status与ClauseEffect：unknown上界仅参考；confirmed_open仍受核验截止日约束；局部废止在当日只排除相应条款，其他已核实条款保留；条款修订不能指不存在条号。Manifest/Index v1alpha2与Result v1alpha4；已知终止日但起日未知的旧资料仅参考且终止当日强制排除，不可确认。Focused112项通过，Ruff/Mypy48文件/契约检查通过；新增17项D01正反/日期/局部废止/替换测试。过程中契约fixture算法版本未同步、5处行宽静态错误和1处未核实参考的未知起日边界失败均已修正，未删除/跳过断言。最终Full与真实集成将在全部缺陷修复后的最终候选执行。

## 本轮D07过程验证

来源映射DTO/契约先生成；Index v1alpha3保存每段清洗字符到原始HTML字节/实体或PDF页码/字符框的对应及排除区。摄取复建全字符覆盖、条号完整性与引用范围，生成头不得供法律引用；目录排除，重复正文条号拒绝，长条切片原文不遗漏。PDF默认必须使用固定镜像DockerPDFExtractor，继承无网络、只读、UID65532、cap-drop、内存/PID/CPU/输出/时间限制；新入口不接受动态命令。

149项Focused通过（含原全部法规、D01、D03、运行和检出策略），Mypy50源文件/Ruff/契约通过。新增9项来源正反例及真实官方PDF：84条、15页，页框覆盖全部非空字符；官方样本无页脚数字，合成真实PDF验证数字页脚排除与原始框记录。文件与来源/哈希见config/legal/validation-sources.json；该PDF仅为解析回归，不据其页首版本标注提升效力。司法部HTML引用逐字符可追溯到原始字节；新保存北京官方现行状态页用于核验证据。

本机固定新解析镜像真实隔离专项及check_legal_sources.py均退出0；新增CI步骤保持原三作业门禁。过程中空白排除区、HTMLParser内部offset重名导致的映射失败已修复；误设官方PDF为10页及要求不存在页脚的测试假设按实际15页/无页脚纠正，实际glyph/条号完整断言保留，安全测试无跳过。最终整任务Full/集成/CI在剩余缺陷修复后执行。

## 本轮D04过程验证

采购方式/主体/对象进入版本化项目API与确认上下文，旧输入缺省unknown仍可读写，法规服务显式context_incomplete且不调用Embedding。已确认政府工程招标保留tendering与government_procurement两个框架；非招标政府工程只使用政府采购框架，企业货物招标不冒称政府采购；other必须显式确认框架，未知/矛盾失败关闭。法规及条款方法/对象/主体/地区/采购类型/项目类型/框架范围取交集，结果保留具体适用框架，原日期/效力门禁不变；历史读取重建完整冻结上下文。

237项涵盖API/身份/文件接入/契约/来源/法规的Focused通过，Mypy50/Ruff/生成检查通过；新增22项D04边界及交叉框架反例后法规Focused134项通过，最终Full/真实PostgreSQL/CI待全部模块修复后执行。没有提高旧42文本核验状态，没有删原测试或断言。

## 本轮D05过程实现

新增独立legal_operator_grant与显式迁移202610141600；tenant admin不隐含全局权限，ingest/verify/publish/disable/rollback逐项授权。每次先复核服务身份/会话/角色，再读取当前grant，无权限记录拒绝审计。PostgreSQL FORCE RLS只允许读取当前tenant/user grant，运行账号无写策略与grant写权限；全局权限仅数据库运维配置，非租户管理员HTTP自授权。既有租户RLS与复合外键不变。新增13项权限、撤权、跨租户/复合FK反例；Focused72项通过，Mypy52/Ruff/契约通过；真实PostgreSQL16 check_postgres.py退出0，包含独立grant读取、仅ingest禁止publish及运行账号INSERT/UPDATE/DELETE授权检查和实际UPDATE拒绝，原全部迁移/RLS/并发/撤权门禁保留。全局操作入口的完整事务测试将在D02完成后继续验证。


## 本轮D02过程验证与最终自检

原始/清洗/核验来源字节先一次性受限捕获，公开knowledge/legal命名空间及解析后路径都检查，禁止摄取私有上传/路径链接；完整CorpusBundle内容寻址。修订表独立于正文hash，核验元数据改变新增不可变revision；稳定标题/law_id注册表持续保留，换来源/移出再加入不能绕过身份和重叠版本检查。发布、停用、回滚追加历史并与双序号CAS/审计同事务，重复请求绑定完整请求hash，失败无孤立数据，已发布检索不读取当前可变目录；请求冻结publication/revision，历史读取对照索引/hash，停用当前不销毁旧运行。

D02/D05及原运行Focused60项通过；全部法规组合171项通过，Mypy54/Ruff/所有生成/契约通过。真实PostgreSQL16先执行原check_postgres.py，再check_legal_publications.py，均退出0：两次核验竞争仅一胜、同文本新核验独立修订、发布与回滚竞争仅一胜、幂等不重复、运行/来源重现、tenant admin禁止全局操作、真实FORCE RLS/WITH CHECK、运行角色受限、REVOKE审计INSERT触发全事务回滚、停用/恢复为新历史、特权历史DELETE拒绝、跨租户项目运行拒绝及global grant即时撤权。容器已清理；日志task0006-lifecycle-baseline-pg.log/task0006-lifecycle-pg.log。CI新增同等专项，原门禁不删除。

最终自检额外补齐：含文字页头的大面积扫描主体不能假装完整PDF映射；结果框架必须是查询框架子集且唯一；先校验运行hash再读取其发布绑定。81项相关Focused通过，旧安全/类型规则均保留。过程中新发布测试夹具注册错误已修正；所有真实事务/RLS断言保留。当前还未把过程结果冒称整任务最终Full/远程CI，任务仍in_progress，待最终候选验收。
