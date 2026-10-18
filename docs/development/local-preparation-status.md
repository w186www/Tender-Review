# 本地准备状态与真实阻塞（2026-10-18）

本文件回答“哪些工作现在可做、哪些仍受授权或资产限制”，不改变正式单元状态。正式依赖以 `roadmap.yaml` 为准；本地准备不等于单元完成或用户验收。D1—D4 的授权范围见 [DEC-008](../decisions/DEC-008-product-delivery-d1-d4-authorization-20261018.md)。

## 2026-10-18 接续修正

- DEC-009/ADR-0022 已按用户明确决定采用现有冻结法规库；法规逐条独立核验/人工绑定签署不再作为继续工程实现的前置。报告保留 independent legal verification=false 和正式核验依据数 0，不伪造法律结论。
- 专家标签仍为 0，precision/recall 必须保持 `not_measured`，只限制相关效果验收，不停止 U06/U08/U09/U10/U11/U12 等独立工程工作。
- 生产已启用 product-postgres 及费用/余额是上次记录；本轮 workbench daemon 未运行，Docker Linux Engine API 返回 Access denied，未能重新核对 ECS、数据库/备份/在途任务，也未部署本地候选。
- 历史 DOCX/PDF 的 `rejected_units=503/1423` 是 partial 批次 section_count 累加（可能重复），不是被拒候选数。本地可查 JSON/JSONL 未发现候选统计工件；服务器端待连接后核对。
- 生产/预发布 `authorized-real` 回退会开启独立的旧 DEC-007 账本，不能与 PostgreSQL 消费/撤权/unknown 统一核账。当前代码已新增非 development/test 禁止启动门禁；Focused 105 项定向回归通过。Full 后端 939 passed，2 个沙箱内 Git clone 权限失败；两项沙箱外重跑通过，API health 和鉴权/项目生命周期 smoke 通过。线上配置尚未复核。

## U03｜评测资产（已恢复，专业裁定待办）

- **已恢复**：`_backups/worktrees-uncommitted-20261017T080625Z/task0019` 中的评测器/测试/两份历史结果/原 TASK 文件已接入当前仓库；原始 SHA-256 与暂停清单一致。
- **已重新生成**：缺失的法规检索报告输出到 `.verification/task0019-legal/u03-character-baseline-20261018.json`；核心指标与历史一致（Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中）。
- **身份与分区**：五案例/阈值/OCR/检索报告的 CRLF 与 LF 规范化身份、规则集、评测器原/适配哈希记录在 `evals/capability_baseline/dataset_registry.yaml`。
- **待裁定材料**：`evals/capability_baseline/labels/pending-adjudication.yaml` 与 `docs/development/u03-label-adjudication-drafts.md` 为每个案例列出原文位置、候选规则、拟用条文、适用前提、理由、不确定性和待确认问题。
- **效果限制（不阻止其他工程）：** 专家确认标签从未具备，风险 precision/recall 保持 `not_measured`；五个案例仍是开发候选，不进入冻结验收分母。冻结验收集、真实文件样本和安全攻击标签集仍待建立。

## U06｜支持范围（D1 已批准，效果验收待 U03/D2）

- D1 首版范围已写入 [摄取支持矩阵](ingestion-support-matrix.md)：PDF/DOCX/PNG/JPEG、10 MiB、300 页、OCR 30 页、五类审查能力。
- 边界由 `tests/test_task0029_support_scope.py` 覆盖：四种格式可解析、超 10 MiB/300 页/30 OCR 页拒绝、文本不可靠转人工、无 OCR 文本转人工。
- 结构质量信号、容量前检、校正版本失效和合成 OCR 回归已有实现与 Full 证据。
- 真实文件补充：天津地铁 DOCX 完成两处空 OCR 页脚校正、复杂表格处理和完整审查；派生真实扫描 PDF（2 页）实际 OCR（tesseract 5.3.0）后产生 578 个碎片 section 和 `LOW_CONFIDENCE_NUMERIC`；高分辨率合成扫描 PDF、PNG、JPEG 也均 OCR 后转 `needs_review`。质量门禁按设计阻止低质量文本进入审查。
- **待验收：** 中文扫描/图片的 OCR 段落切分和数字置信度仍未满足用户要求的清晰扫描件全链；本轮新增词级坐标、置信度和段落重建，但因 Docker API 不可达，未重新运行隔离真实扫描端到端。不能宣称扫描件可直接可用；U06 保持 `in_progress`。

## U08/U09/U10｜真实模型与检索（D3 已授权，真实效果待验收）

- U08：每批饱和标记、覆盖摘要、父子覆盖和缓存复用已有实现；接续实现深度 3/额外批次 16 上限、长单 section 有界拆分及候选拒绝原因/唯一源单元/恢复统计。旧 DOCX/PDF 的 503/1423 是 `rejected_units` 的 partial 批次 section_count 累计值，不是候选拒绝数；本地没有旧候选级覆盖工件，ECS 端待核对。新代码需 Full 和真实运行专项后才可确认。
- U09：预构建向量索引、Embedding 身份（3112/3120，build `c7344cac…`）、BM25/Character 融合、参考排名与正式证据资格分离已在真实服务器运行；索引/快照身份仍由采用政策校验。
- U10：法规候选和受限 evidence_id 已真实进入语义请求；服务端继续重核原文/发布/引用/资格。真实天津 DOCX 41 条风险/111 条采用参考，真实文本 PDF 13 条风险/43 条采用参考，均为 0 条正式可引用依据；报告 v3.2 和 findings API 暴露覆盖/部分完成/unknown 调用。
- **效果限制（不阻止实现）：** 专家标签仍为 0，真实效果不能等同于引用真实或法律适用正确；冻结集未建立，因此相关指标未测量。DEC-009 允许现有法规库作为采用参考，不把独立核验依据数 0 当作工程阻塞。

## U13/U14｜部署与恢复（D4 已授权）

- 新全量备份 `/opt/tender-review-backups/20261017T213903Z` 已生成并通过 `restore.sh --verify`：数据库计数与源库一致（document=30、run=26、result=16、report=34、audit=978），MinIO/modelstate 卷校验通过。
- 上次记录：product-postgres 已在生产启用；迁移时 DEC-007 460 条 reservation/¥0.9496789 导入后，历史账户记录 spent ¥1.0400702、reserved 0。当前服务器值本轮未复查。
- 旧回退演练只证明 `authorized-real` 能启动且 health=200，当时 DEC-007 仍为 148 LLM，不能证明它与 PG 后续消费/撤权/unknown 的预算或授权一致。本轮加了 production/staging 启动门禁；安全回退为兼容 `product-postgres` 候选或 `offline`。Docker/ECS 不可达，PG 隔离复测/线上门禁部署尚未验证。
- TLS 使用 `deploy/docker-compose.tls.yml` 叠加层；证书 notAfter 2026-10-22，renew/expiry timer active；50 请求/并发 10 smoke 全部 200，p95 744.4ms。外部告警渠道仍未配置。
- **待办**：完整 U11/U15 故障、取消、恢复、多租户矩阵；外部告警；扫描/图片 OCR 质量改进。D4 授权不等于用户独立验收。

## 结论

上次记录中的 `d3cb613` Full（928 passed）、备份/隔离恢复、product-postgres 切换与真实文件验收仍作为历史证据。本轮 TASK-0029 接续候选尚未 Full、未部署；ECS/Docker 连接恢复后继续核对当前服务器和专项。仍不能声称：专家金标、precision/recall 已测量、独立核验法律依据（当前 0）、扫描件全链通过、真实模型效果达标或用户独立验收通过。
