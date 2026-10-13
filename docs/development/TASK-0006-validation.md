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
