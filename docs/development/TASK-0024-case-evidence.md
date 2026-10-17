# TASK-0024 三案例检索证据摘要（可公开）

本文件是私有运行记录 `.verification/private/TASK-0024/offline-case-retrieval.json` 的**脱敏摘要**，
供公开仓库复核 TASK-0024 的验收结果。

**不含内容**：招标文件正文、个人信息、私有日志与数据库、模型原始请求或响应。
**含内容**：标书定位坐标（locator，不复制正文）、命中法规的公开条文、版本与适用性状态。

复现方式：在本机私有目录执行 `case_retrieval.py` 与 `case_ranking.py` 可得到同样结论。

## 一、三案例检索结果

| 案例 | 标书定位 | 命中 | 可引用依据 | 适用状态分布 |
|---|---|---|---|---|
| A 逾期违约金标准过高 | `ooxml/body/718/paragraph` | 8 | 0 | `applicability_unknown`×8 |
| B 集团内部黑名单作为资格条件 | `ooxml/body/1207/paragraph` | 8 | 0 | `applicability_unknown`×8 |
| C 报价得分计算方法未明确 | `ooxml/body/601/paragraph` | 8 | 0 | `applicability_unknown`×8 |

## 二、命中法规明细（公开发布的法律文本）

### 案例 A：逾期违约金标准过高

| 序 | 法规 | 条款 | 版本核验 | 适用状态 | 未确认原因 |
|---|---|---|---|---|---|
| 1 | 中华人民共和国民法典 | 第八百八十四条 | unverified | `applicability_unknown` | `unverified` |
| 2 | 中华人民共和国民法典 | 第八百八十一条 | unverified | `applicability_unknown` | `unverified` |
| 3 | 中华人民共和国民法典 | 第七百八十二条 | unverified | `applicability_unknown` | `unverified` |
| 4 | 中华人民共和国民法典 | 第七百八十一条 | unverified | `applicability_unknown` | `unverified` |
| 5 | 中华人民共和国民法典 | 第五百八十五条 | unverified | `applicability_unknown` | `unverified` |
| 6 | 中华人民共和国民法典 | 第八百八十二条 | unverified | `applicability_unknown` | `unverified` |
| 7 | 中华人民共和国民法典 | 第八百七十三条 | unverified | `applicability_unknown` | `unverified` |
| 8 | 政府采购合作创新采购方式管理暂行办法 | 第三十条 | unverified | `applicability_unknown` | `unverified` |

来源示例：https://www.gzrd.gov.cn/xwzx/rdyw/202006/t20200602_77652025.html

### 案例 B：集团内部黑名单作为资格条件

| 序 | 法规 | 条款 | 版本核验 | 适用状态 | 未确认原因 |
|---|---|---|---|---|---|
| 1 | 中华人民共和国政府采购法实施条例 | 第二十条 | unverified | `applicability_unknown` | `unverified` |
| 2 | 政府采购需求管理办法 | 第十八条 | unverified | `applicability_unknown` | `unverified` |
| 3 | 政府采购货物和服务招标投标管理办法 | 第十四条 | unverified | `applicability_unknown` | `unverified` |
| 4 | 政府采购合作创新采购方式管理暂行办法 | 第三十九条 | unverified | `applicability_unknown` | `unverified` |
| 5 | 中华人民共和国招标投标法 | 第十八条 | unverified | `applicability_unknown` | `unverified` |
| 6 | 中华人民共和国招标投标法实施条例 | 第三十二条 | unverified | `applicability_unknown` | `unverified` |
| 7 | 政府采购需求管理办法 | 第十四条 | unverified | `applicability_unknown` | `unverified` |
| 8 | 政府采购需求管理办法 | 第三十七条 | unverified | `applicability_unknown` | `unverified` |

来源示例：https://www.gov.cn/zhengce/zhengceku/2015-02/27/content_9504.htm

### 案例 C：报价得分计算方法未明确

| 序 | 法规 | 条款 | 版本核验 | 适用状态 | 未确认原因 |
|---|---|---|---|---|---|
| 1 | 中华人民共和国政府采购法 | 第六十四条 | unverified | `applicability_unknown` | `unverified` |
| 2 | 中华人民共和国政府采购法实施条例 | 第三十二条 | unverified | `applicability_unknown` | `unverified` |
| 3 | 政府采购货物和服务招标投标管理办法 | 第三十一条 | unverified | `applicability_unknown` | `unverified` |
| 4 | 评标委员会和评标方法暂行规定 | 第二十九条 | unverified | `applicability_unknown` | `unverified` |
| 5 | 中华人民共和国政府采购法实施条例 | 第十三条 | unverified | `applicability_unknown` | `unverified` |
| 6 | 中华人民共和国政府采购法实施条例 | 第三十四条 | unverified | `applicability_unknown` | `unverified` |
| 7 | 政府采购货物和服务招标投标管理办法 | 第六十八条 | unverified | `applicability_unknown` | `unverified` |
| 8 | 政府采购货物和服务招标投标管理办法 | 第四十五条 | unverified | `applicability_unknown` | `unverified` |

来源示例：https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_47b5807c40c040368eb5f13b489d6c43.html

## 三、排名评测（生产查询 vs 风险级查询）

| 案例 | Skill 级主题首位 | 生产候选级首位 | 风险级首位 |
|---|---|---|---|
| A | 中华人民共和国民法典第四百五十八条；585=未命中 | 中华人民共和国民法典第八百八十四条；585=7 | 中华人民共和国民法典第八百八十四条；585=6 |
| B | 中华人民共和国招标投标法第二十六条；585=未命中 | 中华人民共和国政府采购法实施第二十条；585=未命中 | 中华人民共和国政府采购法实施第二十条；585=未命中 |
| C | 政府采购货物和服务招标投标管第六十四条；585=未命中 | 政府采购货物和服务招标投标管第三十一条；585=未命中 | 中华人民共和国政府采购法第六十四条；585=未命中 |

**结论**：生产检索已经是逐候选查询；《民法典》第五百八十五条在生产候选级查询下排第 7（命中 8 条内），
追加中文法律领域词后第 6。所有命中一律标注未确认的适用状态，可引用依据为 0。

## 四、边界声明

- 本摘要不构成任何法律意见，不代表任何条款已被核验适用。
- 法规快照 43 个版本中 42 个未核验，唯一已核验版本已超核验期，因此当前不存在可用于确认的法规依据。
- 未为取得命中而修改法规数据、硬编码条款号或降低校验标准。
