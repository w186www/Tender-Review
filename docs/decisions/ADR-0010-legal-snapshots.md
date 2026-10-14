# ADR-0010：法规快照、有效区间与本地混合检索

- 状态：历史proposed；本期已实施选择由ADR-0012接受，长期生产方案仍未批准
- 日期：2026-10-14
- 任务：TASK-0006

本文件下文保存D03及更早候选的历史版本/待办描述。当前有限效力、范围、全局发布和来源映射决策以ADR-0012及legal-retrieval-start.md为准；ADR-0011取消额外代理审批，不自动批准pgvector、外部Embedding、完整生产性能或最终违规判断。

## 决策

2026-10-14续建依据ADR-0011由当前Codex实施及自检，不要求额外角色批准。D03结果契约补充：Result为v1alpha3、Query仍v1alpha2；正式EvidenceRef使用同一清洗文本的artifact URI/hash/字符定位，官方URL与原始来源hash独立保留。可引用集合只含对应hit的可确认evidence_id，DTO及冻结索引解析复核关联、资格、日期/范围与制品；旧Result v1alpha2拒绝且不重写历史，无新DDL。下文原D01/D02/D04/D05/D07未完成方案仍proposed，不因这一具体修复自动接受全部长期方案。

Manifest/Index维持v1alpha1，Query/RunSnapshot为v1alpha2，Result经D03续建为v1alpha3（闭合契约）；不修改State或现有EvidenceRef。每个版本同时冻结文本与原始来源快照的SHA-256、来源URL、核验说明、核验截止日、半开有效区间[from,to)、地区、采购制度和项目类型。未核实、超出核验截止日、无条号的结果不能支持确定结论。核验截止日不等于失效日；超过该日期只能作为参考。

公共法规库不含租户正文。TASK-0006提供离线摄取CLI和纯检索能力，服务入口先按现有数据库身份与项目边界鉴权，再从已授权项目上下文构造检索范围。未来LangGraph通过该服务调用，完整编排由TASK-0009负责。不得从模型参数信任租户或覆盖项目范围。

首期使用内容寻址的不可变JSON索引，加载时重新验证原始文件哈希、条款切分与索引内容；不存在静默覆盖发布。BM25与本地字符二元组余弦向量两路召回，过滤后RRF融合，固定排序与版本。向量通过Embedding端口调用；本地适配器无网络或SDK，不声称神经语义召回效果。返回完整条款与精确字符定位，超过8000字符按同条号分段，不截断遗漏正文。

用户2026-10-14明确授权更新法规库，覆盖任务原来的knowledge/legal禁止修改约束。保留42份旧文本；新增官方来源快照和新版正文。不能凭索引标注批量宣布42份已核实。

## 备选方案

直接采用旧索引的“现行”标注无法保证时效；LLM自行生成条款无法复现。立刻强依赖pgvector和外部Embedding会引入尚未确定的部署与数据策略；本期采用可独立验收的本地实现，后续扩展存储/向量适配器须同契约与评估门禁。

## 后果

新增显式增量迁移202610141200 legal_retrieval_run：按租户/项目/操作者复合外键、FORCE RLS、最小INSERT/SELECT权限与追加写触发器。旧数据不回填；降级移除检索运行历史，必须停止写入并备份。无生产发布或外部模型调用。服务不对外新增HTTP路由。原始HTML作为不可信数据保存且不执行。官方网页的修订沿革用于版本核验，新版核验范围止于2026-10-14；后续审查需更新核验日期或使用参考模式。生产规模性能、人工法规审批发布、pgvector与黄金召回率属于后续里程碑。

## 本轮基准日与运行冻结

每次已鉴权的业务调用保存完整request_snapshot：原始请求（text/review_date/include_references/limit）、完整项目context及version、tenant/project/actor/run标识、review_date_source=explicit_actor_input、规范查询（失败时null）、索引/检索/地区映射版本。时间来源不冒充项目发布日期。规范JSON为json.dumps(sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)的UTF-8字节，日期/时间先转换ISO字符串。request_hash计算整个request_snapshot；result_hash计算完整RetrievalResult规范JSON（包含run_snapshot/request_hash但不包含result_hash自身）。持久表分别保存请求/结果及哈希，读回复核两者并交叉校验run、tenant、project、actor、context_version/hash、query、index、review_date/来源及算法。运行与审计同事务，失败全部回滚。

修复方案待独立复审；完整D01–D07仍按修订设计逐项保留，不将本轮局部批准等同全任务通过。
