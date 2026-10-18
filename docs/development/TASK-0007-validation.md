# TASK-0007 验收记录

## 范围

实现五类无模型确定性 Skill、固定规则注册与版本化候选发现。输出保持为待复核 `candidate`，不生成法律结论，不修改 Risk Schema 或 LangGraph State。实现位于 `domain/rules`、`domain/skills` 和 `services/candidate_discovery.py`；服务端复用身份、项目与文档服务，仅读取 ready 且上下文已确认的指定文档版本。

Candidate Discovery v1alpha1 绑定项目上下文摘要、文档原始文件哈希、解析/上下文版本、有效片段集合摘要、规则集摘要及引擎版本。每个 Skill 均有覆盖状态及检索主题；无适用范围会记为 `not_applicable`，解析不完整或歧义会显式记录 incomplete，异常会记为 failed。候选保留原始/人工修订后的有效片段定位、文本摘要、文档版本、规则与 Skill 版本及完整 provenance。输入摘要、候选 ID、去重键和结果摘要均为稳定规范化 SHA-256。

## Skill 与边界

| Skill | 确定性检查 | 失败关闭边界 |
|---|---|---|
| qualification | 资格范围内，投标人被要求在指定本地行政区域注册或设立分支机构 | 项目实施地点为本地但未限制投标人注册地时不命中 |
| technical | 技术范围内明确排他品牌/型号 | 同等替代或仅供参考不命中；排他与等效措辞冲突时记 incomplete |
| evaluation | 单一、完整、矩形且单位一致的结构化评分表，精确计算分项与明示总分 | 缺单元格、格式/单位不明或出现多张评分表时记 incomplete，不作违规判断 |
| contract | 合同/协议范围内关键付款、价款、违约、履约保证金或质保字段的占位值 | 其他章节或无关备注中的“待定”不命中 |
| procedure | 同一文档内唯一投标截止与开标时间的先后比较 | 日期/时间不完整、时区缺失/冲突/无效、重复事件或多轮程序时记 incomplete |

法规检索主题按每个实际调度 Skill 稳定生成，即使无候选或不适用也保留；不伪造检索命中。

## 契约与测试

- 新增类型源和生成 Schema：`rule-definition.schema.json`、`skill-definition.schema.json`、`candidate-discovery-document-request.schema.json`、`candidate-discovery-input.schema.json`、`candidate-discovery-result.schema.json`。
- `generate_rule_contracts.py --check` 纳入 Quick/Focused/Full；正反 Schema 夹具与五个合成黄金样本通过。
- `tests/test_rules_skills.py` 覆盖五类正反例、范围不适用、信息不足、时区/评分表歧义、精确定位与哈希、跨文档隔离、稳定性、重复命中合并、等价规则 provenance、规则版本变化及 Skill 失败记录，并验证 GC-0001 只产生候选。
- `tests/test_candidate_discovery.py` 覆盖真实 SQLite 身份/项目/已确认文档服务到五类实际 Skill 的集成，以及撤销身份、跨租户项目读取拒绝和文档版本陈旧拒绝。

## 验收证据

- 代码提交：`236d2a6e231be030f719b0bbabc3f2b0a50039b3`。
- Focused：`./scripts/verify.ps1 -Mode Focused -TestPaths tests/test_rules_skills.py,tests/test_candidate_discovery.py`，30 passed；全仓 Ruff 与 Mypy 64 个应用源文件通过。
- 最终 Full：`./scripts/verify.ps1 -Mode Full -PythonExecutable .venv/Scripts/python.exe`，448 passed、0 failures、0 errors、0 skipped；Ruff、Mypy 64 个应用源文件、契约/生成检查及两个真实本地 HTTP/身份生命周期检查通过。JUnit：`.verification/pytest-result.xml`。两个既有 pypdf `add_js` 弃用警告，不影响结果。
- Full 在受限 Windows 环境中需允许本机回环访问：`TestClient` 的 ASGI 生命周期在沙箱权限下停滞；启用本机回环后原门禁无改动通过。
- 远程 GitHub Actions：[运行 38516913371](https://github.com/w186www/Tender-Review/actions/runs/38516913371)，绑定源码 `236d2a6e231be030f719b0bbabc3f2b0a50039b3`；`impact`、`baseline`、`postgres`、`ingestion`、`verify-required` 全部 success。baseline JUnit artifact 已生成；远端 artifact 下载 API 要求认证，因此本记录只引用可验证的作业结论，不单独声称远端测试数量。

## 限制

本任务只提供候选发现与下游法规检索主题，不验证法规现行效力或项目适用性，不融合其他候选来源，不作最终法律判断。规则采用明确的有限文本模式；复杂排版、跨段落表格、无法辨明采购程序/评分体系等情况保守标为未覆盖或 incomplete，需后续任务处理。没有新增数据库持久化结果记录或候选发现 HTTP 端点；结果由当前服务调用返回，持久审查运行属于后续工作。
