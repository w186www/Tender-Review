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

## 七、第二阶段：法规召回质量与来源核验（2026-10-15 续）

### 三案例召回质量

**案例 A（逾期违约金）— 585 条并未缺失，排名由查询构造决定。**

| 查询构造 | 命中 | 民法典第五百八十五条排名 |
|---|---|---|
| 仅标书原文片段 | 8 | **未命中** |
| 原文 + 法律领域词（当前实现） | 8 | 第 6 位 |
| 法律术语主导（`违约金过分高于造成的损失`） | 8 | **第 1 位** |

- 库内确有《民法典》第五百八十五条，原文完整（含"约定的违约金过分高于造成的损失的……
  可以根据当事人的请求予以适当减少"）。
- 主要失败原因**不是**过滤或缺失，而是查询与法条术语差异：标书原文用"逾期违约金""服务费用"，
  与《民法典》服务合同（881/884）与承揽合同（781/782）条款的字符 bigram 重合更多；
  而 585 条使用"过分高于造成的损失""适当减少"等法律术语。
- 检索分词为**字符 bigram + BM25**（`legal/retrieval.py::terms`），无语义扩展；
  因此"文本相似"与"法律相关"不完全一致。加入法律领域词后 585 从未命中升到第 6，
  用法律术语主导升到第 1 —— 说明**查询构造是可控杠杆**，且当前实现已使用候选描述与领域词。
- 未硬编码任何法条编号：领域词来自风险类别与描述，不含条款号。

**案例 B（集团内部黑名单资格条件）— 库内有更贴近的规范，但为采购用词所掩盖。**
- 当前命中政府采购类法规，原因是查询用词（"供应商资格条件""排斥潜在供应商"）与
  《政府采购法实施条例》第二十条文本高度重合。
- 库内**确实存在**更贴近该风险的规范：《公平竞争审查条例》《公平竞争审查条例实施办法》
  《招标投标领域公平竞争审查规则》《反不正当竞争法》《反垄断法》。
- 未将它们提升为"适用"：该采购为企业非招标，且这些版本未声明适用范围，因此一律
  `applicability_unknown`。**没有**套用政府采购的供应商资格限制规定。

**案例 C（报价得分计算不明确）— 应先看采购文件自身规则。**
- 标书原文为评分表选项"方法三：采购人确定的其他方法。"，问题实质是**文件自身是否给出可执行的量化规则**，
  属文件内部明确性/一致性问题，而非直接违反法定评标程序。
- 检索命中的政府采购与评标规定仅作参考候选（`applicability_unknown`），不默认适用。

### 法规库质量画像（43 个版本）

| 元数据项 | 缺失数量 |
|---|---|
| `verification == unverified` | 42 |
| 缺 `effective_from` | 42 |
| 缺 `applicability`（未声明适用范围） | 42 |
| 缺 `expected_articles` | 42 |
| `version` 标注"未核实" | 15 |

来源域名以官方为主：`www.gov.cn` 24、部委域名（mofcom/cac/samr）8，其余为地方转载。
被三案例命中的关键法规（民法典、招标投标法及实施条例、政府采购法及实施条例、评标规定等）
**同时缺失生效日期与适用范围声明** —— 这正是 `applicability_unknown` 无法收敛为
`applicable_verified` 的直接原因。

### 关键条款来源核验（技术比对，非法律签署）

对《民法典》第五百八十五条完成技术比对：

- 库内条文与官方文本**逐字一致**（三款完整，含"过分高于……适当减少"与迟延履行违约金条款）；
- 通过机关与时间：2020-05-28 第十三届全国人民代表大会第三次会议通过；
- 官方建议来源为全国人大网（npc.gov.cn）或新华社受权发布全文；
- **库内 `source_uri` 指向地方人大网站转载**（gzrd.gov.cn），权威性弱于全国人大网，属待改进项；
- 审查日 2026-10-15 的有效性：库内 `verified_through` 为 `None`，**未核验**；
- 适用前提：民法典为民事基本法律，适用面广，但仍需按具体合同性质与约定核验。

**核验边界**：以上为程序化技术比对（文本一致性、来源可达性、元数据完整性），
**不构成法律专业人员对现行有效性的签署确认**。本轮未修改任何法规数据
（`knowledge/legal/**` 与 `config/legal/**` 属禁止变更范围），因此 `verified` 状态保持 42/43 未核验、
唯一已核验版本已超核验期。**待批准更新清单**见下节。

### 参考候选展示（第三阶段）

核查结论：**原实现不会展示参考候选**。`SEMANTIC_PROMPT` 要求模型输出的 `legal_evidence_ids` 为空，
而 `merge_findings` 只把已确认法规写入 `finding["evidence"]`，未核验候选因此被静默丢弃。

已做最小修复（不降低任何门禁）：

- `graph/review.py`：为每条风险附加 `legal_references`，逐条经 `verify_legal_hit` 重新校验
  （检索运行可重读一致 + publication/revision 绑定 + 引用可解析且与条文一致），
  标注 `confirmation_reason`、`version_status`、`applicable: false`；
- `contracts/schemas/risk.schema.json`：按既有 `conflicts` 风格新增 `legal_references`
  （`array` of `object`），契约生成检查通过；
- Word 与 PDF 报告新增"可能相关依据（适用性未经确认，仅供参考，**不计入已核验证据**）"段落，
  每项显示法规名称、条款号、版本状态与未确认原因及条文原文。

**门禁未变**：`legal_references` 不进入 `evidence`、不进入 `sources`、不参与
`has_confirmable_legal_support`，因此不提升 `evidence_status`，也不改变"未确认不得作为违法依据"的约束。

### 待批准更新清单（需法律专业人员签署）

以下改动**本轮未执行**，需要有权人员批准后由具备法规变更权限的任务实施：

1. 为《民法典》等被高频命中的版本补充 `effective_from`、`applicability`（采购类型/主体/标的/框架）
   与 `expected_articles`，使其能够进入适用性判定而不只是被标为未知。
2. 将 `source_uri` 从地方转载替换为全国人大网/中国政府网等权威原文地址。
3. 在有权核验后更新 `verified_through`（不得由自动比对代替签署）。
4. 评估是否补入司法文件（如违约金调整参照标准）与竞争法类规范的可引用条款。
