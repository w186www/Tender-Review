# 法规摄取与检索启动（TASK-0006）

依据：ADR-0010；契约：`contracts/schemas/legal-{manifest,index,query,result}.schema.json`。DTO先生成契约后实现消费者；生成器`--check`进入统一验证。新增显式迁移202610141200，只新增租户检索运行历史；升级/回滚见contracts/database/README.md。现有State和EvidenceRef保持兼容，Query为v1alpha2，Result续建升v1alpha3。检索结果的`eligible_for_confirmation`只表示法规依据符合本模块门禁，不代表风险已确认为违规；最终原文与推理强度门禁由后续Evidence Checker执行。

D03续建新增`LegalHit.evidence`，正式Schema直接$ref到EvidenceRef；`citable_evidence`为按hits顺序列出的全部可确认evidence_id，服务拒绝悬空、重复、遗漏和未核实条目。资格/原因/版本状态、原文SHA-256、字符区间、日期与证据关联在DTO边界检查。原始官方URL和来源快照哈希仍由hit.source_uri/source_hash保留；EvidenceRef.source_uri=artifact://legal-text/<text_hash>、source_hash=text_hash、locator=chars=start:end指向同一清洗文本制品。`corpus.resolve_evidence(root,index,hit,query)`从冻结索引查找路径，复核法规适用性、原始/文本字节和引用定位，拒绝调用方替换路径或改标资格。

Result v1alpha1/v1alpha2显式拒绝，旧追加写运行记录保留，不静默迁移或改写。没有生产数据，不改变表DDL；消费者升级时须使用新版本，旧历史需使用其原版本消费者读取。原始HTML/PDF到清洗文本的映射仍属D07余项，不把同制品引用修复当作其完整关闭。

## 构建与查询

仓库根目录使用PowerShell：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe scripts/legal_corpus.py build
# build输出内容寻址文件名；用该文件名（不含.json）的64位哈希替换下面占位值。
.venv/Scripts/python.exe scripts/legal_corpus.py query --index .verification/legal/<哈希>.json --hash <哈希> --query config/legal/query.example.json
```

产物位于`.verification/legal`，不提交生成索引；可以重复构建，原文件不会被覆盖。查询用显式索引和预期哈希，加载时检查原始文本、来源快照、条款哈希和字符定位。修改正文、元数据、算法均产生新快照；旧审查固定旧哈希且必须保留当时的原始资料。日志不打印租户正文；CLI仅适用于管理员本地公共法规检索，不作为模型工具直接开放。

`config/legal/manifest.json`收录43个版本：42份原始文本均保持待核实，其中HTTP来源只用于保留历史出处，不发起网络请求；1份司法部新版是已核验行政法规。旧文本作为采集快照，不冒充原始网页HTML。新版同时保留HTML与可复现的纯文本；运行`extract_legal_snapshot.py`可重现提取过程，不执行HTML中的脚本。

## 范围与门禁

- 有效区间`[effective_from,effective_to)`，终止日不包含。核验截止日包含当天；翌日即使没有失效日期也只作为参考。
- 地区使用regions.py固定注册映射：全国CN及省级、福建九市、广州/深圳，确定别名（如福建省福州市）规范化为CN/福建/福州。未支持市、未知省、错误父子关系或额外层级返回context_incomplete+excluded并落库，不能静默为空。合法异地/时间/采购不适用在excluded保留全部原因。
- 采购制度沿用`government/enterprise/other`，项目类型沿用`works/goods/services`，分别过滤。新增《实施条例》仅审定工程范围，货物与服务暂不提供其确定依据，不从标题推断完整法律适用性。
- 默认不返回未核实、超出核验截止日、无条号的参考；`include_references=true`才显式返回并标注原因。已知失效/未生效、地区或采购范围不匹配始终不返回。
- 结果含标题、条号、版本、原文、官方URL、来源/文本/引用哈希、字符定位、有效期、证据资格与索引哈希。中文条号切分保留全部条款，长条款分片沿用条号，通知无条号不伪造条号。

混合检索为BM25与本地字符二元组余弦向量的RRF融合。Embedding只经端口调用，固定适配器/算法版本，未使用外部模型。无神经语义召回率或生产规模性能承诺。新增Embedding或pgvector须独立版本、预算控制和评估。

`services/legal.retrieve_for_project`在调用检索/Embedding前重新核对租户、用户、角色、会话有效性，并按租户查项目；范围来自数据库上下文，调用方不得覆盖。已有身份入口负责JWT验证，本任务未新增HTTP路由；LangGraph接入由TASK-0009负责。公共索引不得摄取租户招标正文。

## 更新法规

用户已授权本任务更新法规库。旧42份原文保留；新版本新增到`knowledge/legal/versions`，来源HTML新增到`snapshots`，同步修改manifest并计算原始字节SHA-256。核验必须记录来源、修订链、有效时间、审定范围及核验日期，不能只提高`verification`字段。先检查新网页结构及完整条数，再构建与测试；法规审批发布/回滚由后续管理任务实现。本期只更新《实施条例》作为真实端到端样本，其余法规的效力核验仍是明确待办。

## 可追溯基准日与检索运行

review_date由已鉴权操作者显式指定，来源标为explicit_actor_input，不冒充项目发布日期。每次业务调用生成独立run UUID并在legal_retrieval_run冻结完整项目context/version、原始请求与规范查询、身份、日期来源、索引/算法/地区映射版本、输入/输出规范JSON哈希。RunSnapshot不含result_hash自身；规范JSON固定sort_keys/无空白/UTF-8/禁止NaN，读回校验双方哈希及关联字段。改变日期或上下文产生新运行，旧运行通过read_run重验会话与项目权限读取，不重新按现行上下文计算。context_incomplete同样记录并审计。

先前实施者自行归档已撤销。原D01–D07逐项回应及当前自检见TASK-0006-correction-design.md/TASK-0006-validation.md，历史独立设计复审见tasks/reviews/TASK-0006-design-rereview.md；完整任务保持in_progress，当前依据ADR-0011由单Codex实施。D03引用和同制品映射已修，采购方式、双框架与条款级适用、未知上界/局部废止、全局授权/发布/回滚、原始HTML/PDF清洗映射等余项尚未关闭，检索结果不能直接替代最终确定违规结论。
