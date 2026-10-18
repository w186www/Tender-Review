# TASK-0006 修订设计与D01–D07回应

## 当前收尾自检入口（2026-10-14）

本轮依据ADR-0011/0012由当前执行者独立实施和自检，不声称独立代理审查。源码5347b110a8c3561c72086afd455755810de59abf已完成D01/D02/D04/D05/D07全部本期必修条件，D03/D06保持并加固；逐项证据见TASK-0006-validation.md当前最终候选节。本地Full413项和真实PostgreSQL/Docker/官方PDF/文件接入均通过。远程38510406707 completed/success，所有适用作业及verify-required成功；下载JUnit413/0/0/0。TASK-0006达到本期退出条件并归档，不合入main、不启动后续任务。历史问题的本期整改结论由当前自检表给出，不改写原审查。

下文旧pending/changes_requested与角色分工均为当时历史记录，原真实问题保留，不恢复已撤销审批。当前状态以本节与正式任务/验证记录为准。


## 历史D03候选设计与具体修复

本节依据ADR-0011由当前执行者设计与自检，覆盖下文已撤销的角色关卡；历史发现和独立审查原文保留。任务仍in_progress。

已复现DTO与JSON Schema同时接受reason/version_status=unverified而eligible_for_confirmation=true。修复先落正式契约：Result升v1alpha3，Query维持v1alpha2，Manifest/Index维持v1alpha1；新增正式EvidenceRef引用及citable_evidence（evidence_id集合）。Schema拒绝资格/原因/版本状态矛盾；关联字段、引用/文本哈希、字符区间、日期和集合完整性在LegalHit/RetrievalResult服务校验，不能只信Schema结构。

EvidenceRef.source_uri使用artifact://legal-text/<text_hash>，source_hash同一清洗文本制品的SHA-256，locator=chars=start:end；原始官方网页URL/来源快照哈希继续独立保留在LegalHit，避免HTML哈希与清洗文本字符定位混用。读取证据须对照已冻结索引找到文本路径，受限读取并重新核验字节、定位与引用，不访问官方URL、不信任任意路径。kind由法规authority映射law/policy，未核实和未定位仍不能进入citable_evidence；双框架、局部适用等D04余项不因此关闭，最终finding仍受Evidence Checker约束。

Result旧v1alpha2不能静默升级。无生产数据、无需更改表DDL；持久快照记录新结果版本。旧运行历史保留，在消费者升级前明确拒绝不兼容版本，不重写旧行。新Schema通过外部$ref引用正式evidence.schema.json，并以正式Schema校验全部生成证据。Focused覆盖法规/运行/契约与新反例；最终候选Full及真实PostgreSQL专项，不修改既有检查。

本轮处理D03和D07中的同制品引用问题，D01/D02/D04/D05及D07原始HTML/PDF清洗映射余项仍需实现；不把单项修复当作TASK-0006整体完成。

2026-10-14；状态：本轮修复方案c232e4bb经独立设计复审approved；完整任务仍changes_requested。原changes_requested保留在tasks/reviews/TASK-0006.md；旧草案不是已批准实现依据。此次纠正实施者自行归档，不用215项自测代替独立审查。ADR-0009为协作关卡，法规方案使用ADR-0010。

## 本轮具体设计

1. `version_status`在审查基准日解释：有终止日但review_date < effective_to仍为verified_current；终止当日起不再适用。检索过滤保留半开区间，状态计算明确比较日期，不能用是否填写终止日判断。
2. 地区规范化是闭合注册映射，不从自由文本猜地区。国家CN、全部省级名称及确定别名可映射；首批市级映射限定福建九市和广东广州/深圳。未知省、市、错误层级或空文本返回context_incomplete；不触发Embedding，不产生可确认依据。纯检索query也执行同一校验。匹配只按CN/省/市的完整分段祖先。有效但不匹配时保留excluded，区分时间/地区/采购制度/项目类型/未核实/核验超期/无条号，不用无说明空结果。
3. 基准日仍可由已鉴权操作者显式选择，但每次业务调用生成独立UUID检索运行，落库冻结review_date及来源explicit_actor_input、actor_id、project_id/context_version/context_hash、完整输入、规范化查询、索引哈希、算法版本与输出哈希。两次不同日期产生两个运行，不复写。离线CLI结果只用于公共语料诊断，不冒充项目运行。
4. 新增`legal_retrieval_run`表（显式迁移202610141200）：tenant/run复合主键，租户项目/操作者复合外键、上下文版本、输入/结果JSON、结果哈希、创建时间。PostgreSQL FORCE RLS及事务级tenant范围；SQLite同应用鉴权。禁止UPDATE/DELETE的数据库触发器，回滚需先备份与停止写入；降级会移除运行记录。读取run必须重新校验会话并按tenant查找、检查project权限、复核结果哈希。成功与context_incomplete均入库并同事务产生审计。新增表不改已有业务表/接口。
5. DTO增加Excluded与RunSnapshot、result.status/context_error/run_snapshot，query允许context_incomplete时为null。由Schema生成器同步，兼容性升级为法规契约v1alpha2；索引/manifest保持v1alpha1。新旧result不静默迁移。索引文件不经Git文本转换（.gitattributes -text）以固定原始字节。

## 原设计问题逐项回应（实施者，不是审查结论）

| ID | 状态 | 本轮处理及证据计划 | 仍缺内容/下一步 |
|---|---|---|---|
| D01 | 部分 | 已有[from,to)并拒绝重叠verified窗口；修复在效带终止日状态，补起日/终止前/当日/次日及excluded测试 | 条款级局部废止、核验中“未知上界/已确认无终止”的独立记录未实现；未完成这类核验不能提升版本。完整任务仍受原阻断约束 |
| D02 | 部分 | 内容寻址索引冻结整个manifest、核验说明/范围和切分版本；运行固定索引哈希与项目上下文；同文本元数据变更产生新索引、旧索引保留 | 不提供global current/publication管理面；原子发布/并发回滚/核验修订实体待实现，不能宣称FR-013完成 |
| D03 | 部分 | Pydantic服务校验已要求verified日期/规范性权威、禁止重叠；新增result状态/运行/排除边界并列反例 | 尚无正式EvidenceRef内嵌映射与citable_evidence集合，不宣称其引用完整性验收；该结果不得直接作为最终finding输入，TASK-0009接入前需补契约与引用验证 |
| D04 | 部分 | 本轮解决地区映射、上下文错误显式状态、基准日与版本化项目/检索运行绑定，补同项目两日期/上下文变更/市级祖先与未知地区样本 | 采购方式/双框架/条款级范围未实现；现有简化范围不足以判定完整法律适用性。此次修复不批准全任务完成或确定违规输出 |
| D05 | 部分 | 业务检索/读取运行重新鉴权，项目/运行均按租户过滤、撤权前不调用Embedding，结果存FORCE RLS表且哈希复验 | CLI只是受控本地构建器，没有租户admin管理API；全局运维授权及发布审计仍待实现，不能当作法规发布权限 |
| D06 | 已解决 | 当前实现没有公共/租户结果缓存，不复用跨run结果；每次生成独立run并绑定全部请求/索引/上下文/算法；补两日期、两项目不可串run测试 | 未来启用缓存必须重新设计全输入键与读取授权；不得把无缓存称为缓存性能验收 |
| D07 | 部分 | 正文/来源/quote/索引哈希分开，字符定位复建、长条稳定切片与84条真实HTML重现；Git原始字节固定 | 原始HTML到清洗文本的字符映射、真实PDF清洗覆盖、目录排除完整性、EvidenceRef URI/hash同制品映射未完成；需在完整审查接入前落实 |

“部分/推迟”不是关闭阻断的理由。设计复审须分别给出本轮修复方案是否可实施、完整TASK-0006是否仍changes_requested；实施者不得将部分交付改为completed。完整法规核验、管理发布、pgvector/真实Embedding和原D问题余项保留明确待办，不能用“未验收”一句替代。

## 验证计划

完整verify.ps1；新增服务/DTO正反例、真实SQLite迁移/禁止更新删除、跨租户与撤权读取、两个日期运行持久化/重开Session重现、运行结果篡改拒绝、地区失败不调用适配器与excluded原因。涉及PostgreSQL RLS/触发器需运行真实check_postgres并补其表检查；没有真实结果则如实记录，不能宣告生产数据库验收。

## R01/R02设计复审回应

- R01已在ADR-0010同步Manifest/Index v1alpha1、Query/Result/运行v1alpha2及增量迁移、RLS、权限和有损降级。尚无运行历史，不需要旧数据回填；新result不静默兼容旧v1alpha1。
- R02：request_snapshot必须包含完整项目context而不是仅哈希，含context_version及其规范JSON SHA-256、原始请求与规范查询、actor/tenant/project/run、日期与explicit_actor_input来源、算法/地区映射版本及索引哈希。规范JSON固定sort_keys=True、ensure_ascii=False、separators=(",",":")、allow_nan=False，日期先转ISO；UTF-8字节SHA-256。RunSnapshot只含request_hash，不包含result_hash；表result_hash计算完整result序列化。读回复核request_hash、context_hash、result_hash及请求-结果关联字段一致性，禁止重新按当前项目上下文计算。补旧上下文变更后读取、重开Session、输入/输出篡改反例。

## 本轮实现对应证据（非自审通过）

- D01部分：scope_exclusions及review_date/effective_to比较；test_start_and_pre_end_are_current_not_historical/test_excluded_time_boundaries。局部废止及未知上界余项保留。
- D02部分：legal_retrieval_run冻结完整context和请求、索引哈希；test_two_dates_and_context_change_are_frozen_across_sessions。publication/current/并发回滚仍推迟，原阻断未关闭。
- D03部分：v1alpha2结果一致性模型/Schema及正反例；test_result_contradictions_and_old_version_rejected。正式EvidenceRef引用完整性仍推迟，不直接输出最终finding。
- D04部分：regions.py、服务context_incomplete持久化与excluded；注册/未知地区、错父子/额外层级、两日期/改上下文测试。采购方式/双框架/条款级适用仍推迟，原阻断未关闭。
- D05部分：require_identity/read_run、真实PostgreSQL FORCE RLS、撤权/跨租户/触发器与读取哈希验证。全局语料运维发布授权仍推迟，无租户admin管理面。
- D06已解决（当前无缓存）：每次独立run与完整输入，不跨run复用；两个日期/上下文产生独立运行并保存旧输出。启用缓存需新审查。
- D07部分：原始来源-text固定、各层哈希与正文字符定位；重新获取来源后生成新索引哈希。HTML/PDF清洗覆盖映射与EvidenceRef同制品仍推迟，原阻断未关闭。
