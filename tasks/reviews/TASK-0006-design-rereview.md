# TASK-0006 独立设计复审

- 审查者：独立 design_review 代理；未参与方案编写或业务实现。
- 日期：2026-10-14（Asia/Shanghai）。
- 实际候选/checkout：`91b4c1b8297ceae0f0b743dae5623ae358de988f`，`work/TASK-0006`。
- 最新本地 main / origin/main 基线：`bd2da2da984b6d1c34f3cfdb7da69e21661523be`；已实际验证其为候选祖先。本审查未 fetch 或推送。
- 接手工作区干净；实施者/root 明确停止写入。本代理唯一写入是本文件，不修改方案、代码、契约或正式任务，不代实施者填写批准。
- 本轮具体纠正设计结论：**changes_requested**，先处理 R01/R02 并提交新设计 SHA 复审。三个纠正方向可行，不要求重做原始草案全部实现。
- 完整 TASK-0006 结论：**仍 changes_requested / in_progress**；即使本轮修复设计通过，也不能据此关闭原 D01–D07 余项或归档。

## 新候选必修项

| ID | 位置 | 问题与影响 | 必修及复审条件 |
|---|---|---|---|
| R01 | ADR-0010-legal-snapshots.md:9、23；correction-design.md:10–11 | ADR 仍规定全部法规契约 v1alpha1 和“无数据库迁移”，而本轮修订新增运行表、迁移 202610141200 和 v1alpha2。这使跨模块/持久化实施依据相互矛盾。 | 同步 proposed ADR：明确哪些 DTO/Schema 升级、manifest/index 保持旧版；说明运行表、显式迁移、历史数据处理/降级数据损失、权限和 RLS。实施前正式契约同步，不静默接受旧 result 为新版。无需把整个 ADR 或原任务宣布通过。 |
| R02 | correction-design.md:9–10 | “完整输入”和“输出哈希”方向正确，但未规定输入快照是否包含完整项目上下文、结果哈希是否包含自身、规范序列化的固定规则。仅保存 context_version/hash 而不冻结内容，或结果同时携带自身 result_hash，会使追溯/复验无法落实。 | 明确 request_snapshot 冻结完整项目 context、version、review_date/来源/actor、原始请求及规范查询和算法/索引版本；固定 JSON 规范序列化与 SHA-256 边界。可令持久表 result_hash 对完整 RetrievalResult 计算，而 RunSnapshot 只含 request_hash、不含 result_hash 自身。读回同时复核请求与结果完整性，说明一致性关联。补上下文变更后旧运行不变、重开 Session 复现及输入/结果篡改拒绝验收。 |

## 本轮修复的代码验收要求

以下是复审方向与代码门禁，不是已实现或已通过的证据。

1. 在效状态明确依赖 review_date：带终止日且日小于 effective_to 的 verified 在效版本为 verified_current；终止当日/次日必须被排除。起日前、起日、终止日前/当日/次日及无终止日均有反例。核验状态与有效日期不得互相替代。
2. 地区采用注册表校验 CN/省/市全部分段，已知别名只映射到确定代码；福建九市与广州/深圳的有限覆盖可接受，未支持地区必须 context_incomplete，不能静默为 CN 或空结果。错误父子关系、额外层级、空值、自由文本未知值不得调用 Embedding。合法异地、时间或采购范围不匹配明确记录 excluded 及原因。语料 jurisdictions 也必须符合相同规范，避免规范查询仍匹配坏索引。
3. 显式操作者输入作为基准日来源可以接受，前提是落库绑定 actor 与项目完整快照；不得改称法规确认日或项目发布日期。同一项目不同日期生成独立运行，读取旧 run 不重新按当前项目上下文计算。context_incomplete 也持久化并审计。
4. 新表须用 tenant 复合 FK 绑定项目/操作者；上下文版本必须可关联对应的项目历史，或完整快照与哈希自足且校验一致性。租户设置必须在 PostgreSQL 读取身份/项目/运行之前完成，每次事务重新设置。服务读取重验 active/session/角色撤销和项目访问；跨租户 run 查不到且不得触发适配器。
5. FORCE RLS、WITH CHECK、非 superuser/NOBYPASSRLS runtime、INSERT/SELECT 最小授权和拒绝 UPDATE/DELETE 触发器均须真实检查。运行与 audit 同事务，失败回滚不能留下孤立成功记录。SQLite 外键与禁止更新/删除也须真实迁移验证。增量升级旧基线、重复 upgrade、元数据一致性及降级数据损失说明不能遗漏。触发器保护不应声称防御数据库管理员。
6. 新 DTO 需拒绝 success+context_error、context_incomplete+可确认 hits、缺少项目运行来源、悬空/不一致快照等矛盾输入；旧 result 不静默迁移。CLI 纯检索不伪造租户 run；未建立正式 EvidenceRef 映射的结果不能直接进入最终 finding。
7. 完整 `./scripts/verify.ps1` 和真实 PostgreSQL 检查必须记录实际候选、命令、失败/未执行项。测试计划已有 SQLite/持久化/跨租户/撤权覆盖方向；代码审查还须查看真实调用链，不能以自测数量代替。不得放宽检查或跳过失败项。

## 原 D01–D07 的独立判断

| ID | 状态 | 本轮判断与仍需处理 |
|---|---|---|
| D01 | 部分 | 半开窗口及状态修复方向可接受；局部废止、未知上界与核实无终止仍未解决，原阻断未关闭。 |
| D02 | 部分 | 内容寻址 manifest/索引及运行快照能约束本轮输入；全局 publication/current 原子发布、并发回滚、核验修订实体缺失，原阻断未关闭。 |
| D03 | 部分 | 现有 Pydantic 校验日期/权威与窗口；EvidenceRef 映射、引用完整性和确定性证据集合仍缺，新增结果契约须有矛盾输入拒绝测试，原阻断未关闭。 |
| D04 | 部分 | 地区显式失败与可追溯基准日解决本轮重点方向；采购方式、交叉法律框架、条款级范围仍缺，原阻断未关闭。 |
| D05 | 部分 | 当前项目鉴权可复用，新增运行需真实 RLS/撤权验证；本地 CLI 不构成全局运维授权与发布审计实现，原阻断未关闭。 |
| D06 | 已解决（无缓存这一当前设计边界） | 实际代码没有结果缓存，不存在原错误缓存键；新运行隔离仍待代码验收。将来启用缓存须另行审查全输入键，不据此宣称缓存性能验收。 |
| D07 | 部分 | 字节哈希、定位与稳定切片已有基础；HTML 清洗映射、真实 PDF 覆盖与目录排除、EvidenceRef URI/hash 同制品仍缺，原阻断未关闭。重新抓取来源所得新哈希不能复用旧索引/旧核验记录。 |

## 阅读与真实检查

- 已读 AGENTS、PROJECT_STATE、docs/index、正式 TASK-0006-legal-retrieval.yaml、dispatch/handoff、原独立审查 D01–D07、修订设计、proposed ADR-0010、ADR-0009，以及 roadmap、system/data-flow/security、相关 FR-006/NFR-008/SEC-009/AC-002/AC-004、contracts/VERSION。
- 查看现有 legal/contracts.py、retrieval.py、services/legal.py、persistence/models.py、database.py、services/projects.py 及 scripts/check_postgres.py；确认当前代码尚未实现此次纠正：仍以 effective_to 是否存在计算历史状态，region 仍自由文本，业务调用尚无持久检索运行。未把设计计划称为代码完成。
- 实际执行 git rev-parse HEAD、branch --show-current、rev-parse main/origin/main、merge-base --is-ancestor、status --porcelain 和 diff --check：SHA/分支如上，基线祖先检查成功，工作区干净，差异检查通过。
- 未执行业务测试、完整 verify.ps1、PostgreSQL 集成或在线法规效力核验。本轮仅独立设计复审，以上不构成代码或法规效力验收，也不沿用历史 215 项为新候选结果。

实施者处理 R01/R02 后停止写入、提交新 SHA；本代理复审具体纠正设计，随后由独立代码审查者审实现。正式 TASK 保持 in_progress，归档权不属于实施者。

## R01/R02 修订复审（2026-10-14）

- 实际 checkout/candidate：`c232e4bb1a4fa2483d6e5c6453d5ca7cf7f5ba95`，基线仍为 `bd2da2da984b6d1c34f3cfdb7da69e21661523be`。实施者/root 已明确停止写入，接手时 `git status --short` 空。
- 实际读取 `91b4c1b..c232e4b` 差异：仅 ADR-0010、correction-design 和本独立审查记录三个文件；无业务代码、契约、迁移或测试变更。`git diff --check` 通过。本轮未运行业务测试、verify.ps1 或 PostgreSQL，不宣称实现验收。
- R01：**已解决（设计层）**。ADR 已明确 Manifest/Index 保持 v1alpha1，Query/Result/RunSnapshot 为 v1alpha2；明确显式迁移 202610141200、无旧运行回填、FORCE RLS、最小 INSERT/SELECT 权限、追加写保护及备份/停写后的有损降级，与 correction-design 一致。
- R02：**已解决（设计层）**。完整 request_snapshot 冻结项目 context/version、原始请求、规范查询、身份与运行标识、日期来源及算法/地区映射/索引版本；规定固定 JSON 参数、ISO 日期与 UTF-8 SHA-256。结果哈希对完整 result 计算，RunSnapshot 不含 result_hash 自身；读取需复核两个哈希、context_hash 与关联字段，且旧运行不按当前 context 重算。输入/输出篡改与重开 Session 验收已明确。
- 本轮具体纠正方案结论：**approved**，范围仅为在效状态、地区规范化/显式失败排除、日期来源绑定及持久不可变运行，采用本候选中的方案并满足上文代码验收要求后可实施。本结论来自未参与实施的独立代理，不是实施者自审；不批准原始草案所有方案或完整 TASK 收尾，不把 ADR 的全部长期余项自动标为 accepted。
- 完整 TASK-0006：**仍 changes_requested / in_progress**。原 D01/D02/D03/D04/D05/D07 的部分余项不变；D06 当前无缓存边界的判断不变。每项余项必须保留，代码实现后仍需独立代码审查及真实完整门禁，实施者不得归档。

本代理完成追加后停止写入，将实施权交回 root；正式 Schema、数据库迁移与实现须按已批准的具体修复方案同步，代码候选变更后独立审查绑定新 SHA。
