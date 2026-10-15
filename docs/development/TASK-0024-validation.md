# TASK-0024 验证记录：AI 风险与法律法规自动对应

2026-10-15。基于 TASK-0023 稳定提交 `bac36ba`。本轮目标是解决"AI 风险与真实有效法规之间的对应"，
**优先离线验收，未新增任何供应商调用**。

## 一、CONTEXT_INVALID 根因（只读核查结论）

用实际代码与数据核查，不依赖推测。

**1. 为什么天津地铁项目的法规检索返回 CONTEXT_INVALID？**

`services/legal.py::query_from_context` 调用 `RetrievalQuery` 校验；`contracts.py::consistent_context`
对 `procurement_type == "enterprise"` 且 `procurement_method == "non_tender"` 推导出空框架，随后
`if not frameworks` 抛出 `CONTEXT_INVALID: confirmed consistent legal frameworks required`。
实测（真实天津地铁上下文）：

```
查询构造失败(即 CONTEXT_INVALID): Value error, CONTEXT_INVALID: confirmed consistent legal frameworks required
```

**2. 法律适用框架未确认时，系统是否直接拒绝所有法规检索？**

**是**。该异常发生在 `query_from_context`，因此 `retriever.search(query)` 从未执行——连 BM25 都不跑，
返回 `status=context_incomplete`、`context_error=CONTEXT_INVALID`、`hits=()`。

此外即使放行查询，还有第二层阻断：`applicability_exclusions` 把"查询框架为空"判定为
`framework_mismatch`，而 `clause_exclusions` 又会直接排除带该原因的条款，所以候选仍为空。

**3. 现有法规库是否包含与三类风险相关的条款？**

包含。真实快照 3120 条款、43 个法规版本，与本轮三类风险相关的包括《中华人民共和国民法典》
（合同违约责任）、《中华人民共和国招标投标法》及实施条例、《中华人民共和国政府采购法》及实施条例、
《评标委员会和评标方法暂行规定》《政府采购需求管理办法》等；"黑名单"无同名法规，按条文内容检索。

**4. 法规条款是否有可核查的来源、条款号、生效日期和核验状态？**

有，但**核验状态严重不足**：`config/legal/manifest.json` 记录 source_uri、captured_on、verification、
verified_through、expected_articles、applicability；实测 43 个版本中 **42 个 `unverified`**，
唯一 `verified` 的《招标投标法实施条例》`verified_through=2026-10-14`，而审查日为 2026-10-15，
已超出核验期限。

**5. 模型候选是否已经能够正确触发对应的法规检索工作项？**

能触发工作项（每个候选产生一个 `retrieval_topic` 与查询），但**触发后在查询构造阶段即被拒绝**，
所以 19 个工作项全部得到 `CONTEXT_INVALID`，没有产生任何候选法条。

**6. Evidence Checker 为什么将全部候选标记为 `insufficient_evidence`？**

因为法律侧证据为空：检索被拒 → `verified_laws` 为空 → `has_confirmable_legal_support` 为假 →
`evidence_status_for_support(document_valid=..., legal_valid=False)` 得出 `insufficient_evidence`。
标书原文侧核验本身是有效的（19/19 定位与哈希通过），失败点完全在法律依据一侧。

实测法规侧能力上限（即便构造出合法查询）：

```
confirmation_reason 分布: {'unverified': 3036, 'outside_verification_horizon': 84}
valid 条款数 = 0
```

**结论：当前没有任何条款可以成为"已核验适用"依据，这是数据状态而非检索算法问题。**

## 二、修复：两级法律适用判断

保持"不推断框架"的安全语义，同时允许检索可能相关依据。

| 位置 | 变更 |
|---|---|
| `legal/contracts.py::consistent_context` | 空框架不再视为错误：企业非招标/其他采购保持空框架并允许检索；显式框架与推导冲突、重复框架、主体/采购人不一致仍拒绝 |
| `legal/retrieval.py::applicability_exclusions` | 查询框架为空时不再判 `framework_mismatch`（未知 ≠ 不匹配），其余适用性检查（method/buyer/subject/jurisdiction/生效期）不变 |
| `legal/retrieval.py::confirmation_reason` | 新增：无已确认框架或法规未声明适用范围时返回 `applicability_unverified`，**永不返回 `valid`** |
| `legal/retrieval.py::applicability_state` | 新增四级投影：`applicable_verified` / `potentially_relevant` / `applicability_unknown` / `not_applicable` |

**安全边界**：放行检索只影响"能否看到候选"，不影响"能否作为依据"。`eligible_for_confirmation`
仍要求 `reason == "valid"`，而 `valid` 需要 版本已核验 + 未超核验期 + 条款已核验 + 已定位 +
已提取 + 适用性已声明且与项目框架相交。当前快照下该链条不可达成。

修复后同一上下文（真实天津地铁上下文，`legal_frameworks=()`）：

```
查询构造成功（此前 CONTEXT_INVALID）
命中数: 10 | 可引用依据: 0 | 任何命中被标为可确认: False
```

## 三、三个真实风险的检索与核验验收

案例来源：TASK-0023 真实 AI 审查的 19 项候选（离线检索使用真实法规快照与真实标书原文，
未硬编码期望法规；验收数据 `.verification/private/TASK-0024/offline-case-retrieval.json`）。

| 项 | 案例 A | 案例 B | 案例 C |
|---|---|---|---|
| 风险 | 逾期违约金标准过高 | 集团内部黑名单作为资格条件 | 报价得分计算方法未明确 |
| 标书原文位置 | `ooxml/body/718/paragraph` | `ooxml/body/1207/paragraph` | `ooxml/body/601/paragraph` |
| 检索状态 | complete | complete | complete |
| 命中条数 | 8 | 8 | 8 |
| 可引用依据 | 0 | 0 | 0 |
| 适用状态 | 全部 `applicability_unknown` | 全部 `applicability_unknown` | 全部 `applicability_unknown` |
| 主要命中方向 | 民法典合同编（第 781、782、881、884 条等） | 政府采购法实施条例第二十条、政府采购需求管理办法第十八条等 | 政府采购法第六十四条、实施条例第三十二条、评标委员会和评标方法暂行规定第二十九条等 |
| 版本核验 | 全部 `unverified` | 全部 `unverified` | 全部 `unverified` |

每条命中均带法规名称、条款号、条文原文、来源 URL、版本与生效信息、核验状态、适用状态、
检索方式与得分，且 `eligible_for_confirmation=False`。

**验收结论**：
- 案例 A 命中的是**民事合同法律**方向（民法典），与"违约金过高"的民事性质一致；
- 案例 B 与 C 命中政府采购类法规，但系统**没有**把它们当作适用依据：天津地铁是企业非招标采购，
  而法规快照中这些版本未声明适用范围，因此一律标为 `applicability_unknown` 而非"适用"；
- 三个案例的可引用依据均为 0，`Evidence Checker` 状态保持 `insufficient_evidence`，
  **没有为了凑命中而降低校验标准，也没有把"未找到依据"伪装成命中**。

**未取得**：法规条款级别的"已核验适用"。原因是快照中 42/43 版本未核验、唯一已核验版本已超期，
以及相关法规未声明适用范围。这是法规库状态问题，需要法律专业核验后才能改变。

## 四、测试与限制

- `tests/test_legal_applicability.py`：原有"未知或冲突上下文不能被推断"保留（仍拒绝主体/采购人/框架冲突等 7 类），
  新增"无已确认框架时保持空框架且不阻断检索"用例。
- 全量后端测试：仅 `tests/test_verification_modes.py::test_quick_mode_preserves_existing_full_test_evidence`
  失败，**移除本轮变更后同样失败**（本机 PowerShell 输出非 UTF-8 导致子进程解码错误），属既有环境限制。
- 真实 Embedding 覆盖仍为 **10/3120**；本轮检索为 BM25（`bm25-char-cosine-rrf-5`），未宣称整库神经检索。

## 五、未完成能力（如实报告）

1. **LLM 法规关联分析（TASK-0024 第四阶段）未执行**：需要新的真实调用，而 DEC-006 的剩余额度
   （5/15）按授权仅限"semantic_analysis 分批修复及完整 AI 审查 E2E"。未取得新增授权前不发起调用。
2. **报告与页面端到端未重跑**：法规证据链的渲染路径已存在（TASK-0023 报告含"文档与法规证据引用"），
   但要在真实运行中体现新的参考候选，需要一次完整审查（预计 10–13 次 LLM 调用）。
3. **法规快照核验状态未改善**：本轮未修改 `knowledge/legal/**` 与 `config/legal/**`（属禁止变更范围），
   因此没有任何条款能成为 `applicable_verified`。

## 六、恢复能力说明（不伪造历史证据）

- TASK-0023 的运行数据库随一次性容器删除，19 项候选的**结构化记录（candidate_id、哈希）已丢失**。
- 保留可用证据：Word/PDF 报告（含 19 项标题、描述、原文摘录、定位、证据状态、复核决定）、
  解析片段快照（`sections.json`）、法规快照、真实现金账本与模型审计。
- 本轮三案例的**标书原文与定位取自上述真实留存**，检索针对真实法规快照执行，未重建或伪造历史运行记录。
