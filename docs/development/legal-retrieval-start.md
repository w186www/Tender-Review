# 法规摄取、发布与检索启动（TASK-0006）

当前决策：ADR-0011单写入者开发与ADR-0012法规生命周期/来源映射；ADR-0010保留历史方案和长期未实施边界。正式契约由DTO经scripts/generate_legal_contracts.py生成，禁止手改生成文件。Manifest v1alpha3、Index v1alpha4、Query v1alpha3、Result v1alpha5；OpenAPI 0.5.0补充项目上下文。State/EvidenceRef兼容。旧法规契约版本显式拒绝，旧追加写历史保留并需其原版本消费者，不静默改写；无生产数据。迁移202610141600/1700显式执行，见contracts/database/README.md。

## 效力与适用性

文本效力、条款效力、项目适用性分别校验。有效期采用半开区间；end_status=unknown不可确认，confirmed_open仍受verified_through约束，confirmed_end必须给出结束日。ClauseEffect只限制指定条款，局部废止不排除其他有效条款，修订替换需稳定law_id、独立version及不重叠有效区间。未核实、未知上界、超出核验截止日、无条号或未核实适用范围仅在include_references=true时显式参考；已知日期/范围不适用始终排除。

项目数据库上下文必须确认地区、采购制度、项目类型、采购方式、采购主体和采购对象；旧API输入允许unknown但法规入口失败关闭、记录context_incomplete且不调用Embedding。政府工程招标可同时保留政府采购与招投标框架，非招标政府采购工程仅政府采购；enterprise/other按明确上下文约束，不能由模型猜测。版本和ClauseScope范围取交集，hit框架必须是query框架子集。此映射不判断必须招标义务、不替代规则引擎或最终违规判定。

地区注册表支持全国/省级、福建九市及广州/深圳。未支持地区/错误父子关系拒绝明确返回，不能泛化未知地区。已有43版本：42份旧文本保持unverified且原字节不变；仅司法部2019《实施条例》已核验至2026-10-14并启用工程招标范围，未扩展货物/服务。后续基准日需重新核验或参考模式，不能沿用过期核验。尚缺3份资料见knowledge/legal/索引.md。

## 来源与证据

原始来源、清洗正文、核验页面分别保留原字节/hash。HTML清洗字符映射至原始UTF-8字节（含实体/内联标签）；PDF原文映射至页码/glyph框，目录与数字页脚显式排除，生成头不得成为法律证据。全部正文条号和非空字符必须有覆盖，长条切分不丢内容。大面积扫描主体即使有文字页头也失败关闭，需另行人工核验OCR映射；本期没有新增法规OCR自动确认。PDF摄取通过固定Docker镜像、无网络/只读/UID65532/预算隔离，禁止把不可信PDF直接放入服务进程解析。

EvidenceRef URI/hash/locator指同一清洗文本；hit同时保留官方URL/原始来源hash。corpus.resolve_evidence与evidence_origins重验冻结索引、效力/范围、原始/正文/引用hash及定位。业务resolve_published_evidence读取不可变数据库CorpusBundle内字节，不依赖当前目录内容，历史版本与定位可复现。真实HTML/PDF回归来源、hash和用途见config/legal/validation-sources.json；PDF解析样本不构成新增效力核验。

## 全局法规管理

legal_operator_grant由数据库运维独立配置ingest/verify/publish/disable/rollback能力；租户admin没有隐含权限，运行数据库账号无grant写权限。服务每次复核签名身份、当前用户/会话/角色及grant，RLS与状态触发器再检查实际操作。不存在租户HTTP自授权或模型工具授权。日志/审计不记录密码，CLI使用getpass登录既有账号。

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe scripts/manage_legal.py --help
# 使用已配置数据库与既有账号；先查看state，按明确序号提交。
.venv/Scripts/python.exe scripts/manage_legal.py --tenant <租户> --username <用户> state
.venv/Scripts/python.exe scripts/manage_legal.py --tenant <租户> --username <用户> revision --expected-draft-sequence 0 --reason '官方核验更新'
# revision默认config/legal/manifest.json及verification-sources.json，输出不可变revision ID。
.venv/Scripts/python.exe scripts/manage_legal.py --tenant <租户> --username <用户> publish --expected-sequence 0 --expected-draft-sequence 1 --revision-id <ID> --reason '启用已核验快照'
```

修订捕获完整公共knowledge/legal字节、索引和官方核验证据；verified资料必须具备冻结核验来源与verify权限，不信任模型或仅提高字段。核验日期不得来自未来。同文本新核验产生独立revision；稳定law_id注册表防换来源/删除重加绕过版本关系。draft_sequence和publication_sequence独立CAS，发布必须引用当前draft，幂等request_id绑定完整请求/内容hash。历史revision/publication/identity不可更新/删除，发布、停用、回滚与状态/审计同事务，失败全部回滚。rollback引用已有发布并创建新publication，disable停止当前检索但不删除历史。

业务入口services/legal_management.retrieve_published_for_project只读取当前已发布快照，先鉴权项目再按数据库上下文构造query；请求冻结publication/revision/index/context/date/actor/hash。read_run重新核对身份、项目、运行hash及冻结发布绑定，历史不按新上下文重算。公共法规可跨租户读取，项目运行隔离不变；公共库不得摄取私有招标正文或路径链接。TASK-0009的LangGraph审查图已消费该服务，检索结果绑定冻结发布/修订、项目范围和审查基准日；证据校验在发布前重新解析引用。此处仍未新增法规管理前端/HTTP路由；TASK-0009远程CI尚待执行，详见其validation记录。

## 本地诊断与边界

scripts/legal_corpus.py build/query保留离线公共索引诊断，不能作为未授权业务入口。构建产物位于.verification/legal；显式hash加载，不能覆盖旧索引。BM25和本地字符二元组余弦向量RRF混合检索通过Embedding端口，无外部模型、缓存、神经召回率或生产规模性能承诺。D06保持每次独立run，未来缓存必须另行设计完整输入键和授权。

局部验收和源码绑定证据见TASK-0006-validation.md。Full、真实PostgreSQL、Docker来源/文件接入以及远程全部适用CI通过后才能归档；不等同M2/M5完整生产验收，不自动启动后续任务，不合入main。
