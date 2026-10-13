# TASK-0006 验证证据

日期：2026-10-14。基线：本地`restore/task-0005`；未pull、合并、切换或推送远端分支，未恢复TASK-0016或跨软件协作。

## 局部验收

| 验收 | 证据 | 结果 |
|---|---|---|
| TASK0006-001 未核实版本不能支持确定结论 | tests/test_legal_retrieval.py::test_references_cannot_confirm、test_unlocated_notice_is_reference、test_real_corpus_official_extraction_and_verified_retrieval | 默认排除参考；显式参考模式返回unverified与不具备确认资格；超核验截止日降级 |
| TASK0006-002 按基准日、地区、采购类型返回原文、条号、来源 | tests/test_legal_retrieval.py::test_exact_article_source_and_determinism、test_scope_filter_before_ranking、test_end_date_exclusive_and_historical_version、test_project_authorization_precedes_embedding_and_uses_database_scope | 来源/引用哈希、字符定位一致；范围过滤先于召回；撤销会话不得触发Embedding |

新增25项专项测试全部通过。首次完整verify.ps1：211项、0失败/0跳过，Mypy46源文件无错误，Ruff、契约生成/正反例、真实HTTP健康及身份/项目/撤销均通过。归档后最终verify.ps1全通过：215项、0失败/0错误/0跳过，JUnit汇总已核对；Mypy46源文件、Ruff、契约/生成一致性和两项真实HTTP启动检查均通过。仅既有pypdf合成JavaScript拒绝样本有一条弃用警告，不影响验收。受限沙箱完整测试停滞后已停止，允许回环网络的同一门禁通过，没有跳过或降低测试。

## 真实资料与复现

摄取命令：`.venv/Scripts/python.exe scripts/legal_corpus.py build`（PYTHONPATH=src）。实际43版本、3120条款片段；索引哈希`2add21ee626de048eb27600e63657d23134babd54976481bec0daa80dcbc4c12`。默认查询“投标保证金”，工程、政府采购、CN/福建/福州、2026-10-14：首条为2019修订《实施条例》第二十六条。实际资料测试确认84条完整提取、新版正文可从官方HTML重现、返回原文定位与哈希一致。

来源：[司法部国家行政法规库](https://xzfg.moj.gov.cn/front/law/detail?LawID=339&Query=)。2026-10-14下载保留原始HTML；页面沿革列出2011公布与2017、2018、2019修订，原始库中的2011文本未冒充2019版本。新版以2019-03-02为本版本生效起点，核验截止2026-10-14，启用工程范围。原始HTML、提取正文与哈希均在knowledge/legal及config/legal/manifest.json。现有42文本全部固定来源及采集哈希，无法逐项核实的条目保持unverified；这不宣告法规全库现行效力验收。

## 安全与限制

覆盖路径越界、大小限额、重复条号、重叠/重复版本、恶意来源URL、来源/索引/引用篡改、身份撤销和项目范围。查询不发起网络、无供应商SDK、无租户正文外传。HTML只保存/提取，不执行其指令。索引内容寻址、不可覆盖、加载时复建核验。

未验收：黄金召回质量、神经语义Embedding、pgvector、生产大规模性能、管理审批发布、完整LangGraph/Evidence Checker与全局AC-002/AC-004。无数据库迁移，无GitHub CI新证据，不复用历史CI冒充本次结果。
