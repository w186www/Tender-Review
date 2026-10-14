# TASK-0006 验证证据（原自测与本轮纠正分开）

历史自测日期：2026-10-14，原恢复分支未提交候选。下述215项及旧索引哈希只属于原自测；自审completed已撤销，不能作为本轮独立审查通过证据。

## 局部验收

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


## 2026-10-14 单Codex续建D03（当前记录）

本节覆盖历史默认独立代理/跨软件关卡；依据ADR-0011由当前Codex设计、实现、自检。历史真实发现及失败记录保留。TASK-0017先完成：源码68d67a809、远程38496768950全部适用作业/汇总门禁成功，279项远程JUnit0失败/错误/跳过。TASK-0006仍in_progress。

- 已实际复现D03：原DTO/正式JSON Schema均接受reason/version_status=unverified、eligible_for_confirmation=true。此次先修Result正式契约至v1alpha3（Query v1alpha2、Manifest/Index v1alpha1不变），引用现有EvidenceRef $id；旧Result v1alpha1/v1alpha2明确拒绝，不重写追加写历史，无生产数据、无DDL变化。
- LegalHit校验资格/原因/状态、条号/起日、引用UTF-8 SHA-256、字符区间及EvidenceRef所有关联字段。Result校验唯一hit ID、按hits顺序列出的完整可引用集合、参考模式、地区/日期/运行一致性；服务读取增加输入/输出版本关联。任意EvidenceRef、悬空/重复/遗漏/未核实引用、重标资格、错版本/日期等反例保留。
- EvidenceRef以artifact://legal-text/<text_hash>与text_hash/字符区间指同一文本制品；hit保留原始官方URL/HTML哈希。corpus.resolve_evidence仅通过冻结索引解析受限路径、核验来源/文本/引用字节，并重新判断日期、地区、采购类型、项目类型、核验期限和参考资格，不信任调用方路径/标志。真实司法部HTML与清洗正文分别保留正确哈希，返回条款逐一复现。
- 过程Focused最终95项通过，Ruff、Mypy48源文件及Quick前置门禁通过。新增39项证据反例/真实复现检查；契约正反例清单增加完整正式引用正例及4个矛盾反例。过程中首次Quick因旧结果fixture版本未同步失败，修复fixture版本后通过；Focused曾因3处101字符行超出Ruff上限失败，换行修复后通过，未关闭静态规则/断言。
- 真实一次性PostgreSQL16运行修改后的scripts/check_postgres.py退出0：原有增量/重复迁移、元数据一致性、并发/租户复合FK、FORCE RLS/WITH CHECK、最小授权、运行读取/撤权、追加写触发器、完整降级/重建均保留；新增持久化返回证据集合及制品逐项解析。日志.verification/task0006-evidence-postgres.log，测试容器已清理。
- 最终代码候选Full退出0：323项、0失败/0错误/0跳过，JUnit已复核；Ruff、Mypy48源文件、契约/生成一致性与两项真实HTTP检查全部通过，仅原pypdf合成拒绝样本弃用警告。相对TASK-0017的279项增加39项证据专项及5项正式契约fixture。此后仅工程记录变化用Quick，不重复Full；此次源码SHA/远程CI另行补记，不复用TASK-0017 CI。

### 当前自检问题状态

| 问题 | 本次真实处理 | 剩余事项 |
|---|---|---|
| D01 | 原半开区间与历史基准日在效状态修复保留 | 未知上界/核实无终止区分、局部废止门禁仍未完成 |
| D02 | 原内容寻址索引与完整运行输入冻结保留 | 独立核验修订实体、全局publication/current原子发布、并发/回滚仍未完成 |
| D03 | 本轮实现正式EvidenceRef、资格矛盾拒绝、集合引用完整性、制品/适用性解析，95项专项与真实数据库通过 | 最终Full323项通过；源码CI全部适用作业成功；完整法律适用性仍取决D04，不能直接输出最终finding |
| D04 | 原地区注册映射、上下文显式错误、基准日/项目运行冻结保留 | 采购方式、交叉法律框架及条款级范围仍未完成 |
| D05 | 原业务鉴权、跨租户/撤权与真实RLS保留 | 全局运维授权及发布/停用/回滚审计仍未完成 |
| D06 | 每次独立run，无公共/租户结果缓存 | 启用缓存前须重新设计全部输入键和授权；不声称缓存性能验收 |
| D07 | 本轮解决EvidenceRef URI/hash/locator同一文本制品，真实引用可解析；原字节哈希/84条/长条切片保留 | HTML清洗到原始字节映射、真实PDF覆盖/目录排除仍未完成 |

此表为当前Codex自检，不虚称独立审查。未关闭项保留具体验收要求，TASK-0006不归档、不合入main、不启动后续任务。

本轮D03最终源码候选f0bd8270d990d5e5dc6897f329a770d7db332099（分支work/TASK-0006），本地Full323项及真实PostgreSQL专项绑定该提交中的代码/契约/测试/脚本。远程新运行https://github.com/w186www/Tender-Review/actions/runs/38498549575最终completed/success：impact/baseline/postgres/ingestion/verify-required全部success，quick仅因Full选档不适用。已下载远程baseline-test-results并核验323 tests、0 failures、0 errors、0 skipped。源码之后只更新工程证据，Quick，不重复Full；之前TASK-0017的成功CI不冒作此源码证据。保全stash仍在，main未修改。

最终证据记录相对f0bd827仅PROJECT_STATE、任务/自检/验证/CHANGELOG和提示文本变动，无代码/契约/数据/配置/依赖/测试/脚本变化；Quick通过。D03的本轮引用契约/解析修复有真实证据，D07仅关闭同一文本制品引用部分；全任务仍in_progress。下一步为D01未知上界/局部废止，再依次处理表中各项剩余验收，不合入main、不启动后续任务。

## 本轮D01过程验证（完整收尾前）

实际接手HEAD b8ed12d，任务实际文件TASK-0006-legal-retrieval.yaml，工作区干净且远程一致。旧源码323项结果不冒作新代码证据。ADR-0012明确效力/适用性/来源/发布边界。D01新增end_status与ClauseEffect：unknown上界仅参考；confirmed_open仍受核验截止日约束；局部废止在当日只排除相应条款，其他已核实条款保留；条款修订不能指不存在条号。Manifest/Index v1alpha2与Result v1alpha4；已知终止日但起日未知的旧资料仅参考且终止当日强制排除，不可确认。Focused112项通过，Ruff/Mypy48文件/契约检查通过；新增17项D01正反/日期/局部废止/替换测试。过程中契约fixture算法版本未同步、5处行宽静态错误和1处未核实参考的未知起日边界失败均已修正，未删除/跳过断言。最终Full与真实集成将在全部缺陷修复后的最终候选执行。
