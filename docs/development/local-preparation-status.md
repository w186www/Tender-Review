# 本地准备状态与真实阻塞（2026-10-18）

本文件回答“哪些工作现在可做、哪些仍受授权或资产限制”，不改变正式单元状态。正式依赖以 `roadmap.yaml` 为准；本地准备不等于单元完成或用户验收。D1—D4 的授权范围见 [DEC-008](../decisions/DEC-008-product-delivery-d1-d4-authorization-20261018.md)。

## U03｜评测资产（已恢复，专业裁定待办）

- **已恢复**：`_backups/worktrees-uncommitted-20261017T080625Z/task0019` 中的评测器/测试/两份历史结果/原 TASK 文件已接入当前仓库；原始 SHA-256 与暂停清单一致。
- **已重新生成**：缺失的法规检索报告输出到 `.verification/task0019-legal/u03-character-baseline-20261018.json`；核心指标与历史一致（Recall@5/10=1.0、MRR@10=0.4867、nDCG@10=0.6141、77 个未核验参考命中）。
- **身份与分区**：五案例/阈值/OCR/检索报告的 CRLF 与 LF 规范化身份、规则集、评测器原/适配哈希记录在 `evals/capability_baseline/dataset_registry.yaml`。
- **待裁定材料**：`evals/capability_baseline/labels/pending-adjudication.yaml` 与 `docs/development/u03-label-adjudication-drafts.md` 为每个案例列出原文位置、候选规则、拟用条文、适用前提、理由、不确定性和待确认问题。
- **真实阻塞**：专家确认标签从未具备，风险 precision/recall 保持 `not_measured`；D2 逐条确认未发生；五个案例仍是开发候选，不进入冻结验收分母。冻结验收集、真实文件样本和安全攻击标签集仍待建立。

## U06｜支持范围（D1 已批准，效果验收待 U03/D2）

- D1 首版范围已写入 [摄取支持矩阵](ingestion-support-matrix.md)：PDF/DOCX/PNG/JPEG、10 MiB、300 页、OCR 30 页、五类审查能力。
- 边界由 `tests/test_task0029_support_scope.py` 覆盖：四种格式可解析、超 10 MiB/300 页/30 OCR 页拒绝、文本不可靠转人工、无 OCR 文本转人工。
- 结构质量信号、容量前检、校正版本失效和合成 OCR 回归已有实现与 Full 证据。
- 真实文件补充：天津地铁 DOCX 完成两处空 OCR 页脚校正、复杂表格处理和完整审查；派生真实扫描 PDF（2 页）实际 OCR（tesseract 5.3.0）后产生 578 个碎片 section 和 `LOW_CONFIDENCE_NUMERIC`；高分辨率合成扫描 PDF、PNG、JPEG 也均 OCR 后转 `needs_review`。质量门禁按设计阻止低质量文本进入审查。
- **真实阻塞**：U03 冻结样本和 D2 专业标签未完成，U06 正式仍 `planned`；中文扫描/图片的 OCR 段落切分和数字置信度不足，不能宣称扫描件可直接可用。

## U08/U09/U10｜真实模型与检索（D3 已授权，真实效果待验收）

- U08：每批饱和标记、覆盖摘要、按 section 二分、深度 2/额外批次 8 上限、父子覆盖和缓存复用已实现。真实天津 DOCX 报告为 258 饱和/503 候选拒绝/0 未提交/0 实际截断；真实文本 PDF 产品运行为 50 饱和/1423 拒绝/0 未提交。报告不再把饱和称为“完全未处理”。
- U09：预构建向量索引、Embedding 身份（3112/3120，build `c7344cac…`）、BM25/Character 融合、参考排名与正式证据资格分离已在真实服务器运行；索引/快照身份仍由采用政策校验。
- U10：法规候选和受限 evidence_id 已真实进入语义请求；服务端继续重核原文/发布/引用/资格。真实天津 DOCX 41 条风险/111 条采用参考，真实文本 PDF 13 条风险/43 条采用参考，均为 0 条正式可引用依据；报告 v3.2 和 findings API 暴露覆盖/部分完成/unknown 调用。
- **真实阻塞**：D2 的法规内容核验/正式支持资格未签署；U03 冻结集未建立；U10 的真实效果不能等同于引用真实或法律适用正确。

## U13/U14｜部署与恢复（D4 已授权）

- 新全量备份 `/opt/tender-review-backups/20261017T213903Z` 已生成并通过 `restore.sh --verify`：数据库计数与源库一致（document=30、run=26、result=16、report=34、audit=978），MinIO/modelstate 卷校验通过。
- product-postgres 已在生产启用：历史账本 460 条 reservation/¥0.9496789 导入，PG 账户 spent ¥1.0400702、reserved 0；历史 registry 因无对应文档/重复 approve 整批拒绝，逐文件授权改由 API 记录。运行时角色新表权限缺失导致首次启动 502，已在 `demo_init.py` 修复并幂等应用。
- 回退演练：切回 `authorized-real` 后 DEC-007 账本仍为 148 LLM、health 200；再切回 `product-postgres`，api/review-worker 均打印产品模式与 ¥200 账户。
- TLS 使用 `deploy/docker-compose.tls.yml` 叠加层；证书 notAfter 2026-10-22，renew/expiry timer active；50 请求/并发 10 smoke 全部 200，p95 744.4ms。外部告警渠道仍未配置。
- **待办**：完整 U11/U15 故障、取消、恢复、多租户矩阵；外部告警；扫描/图片 OCR 质量改进。D4 授权不等于用户独立验收。

## 结论

2026-10-18 已完成：最终候选 `d3cb613` 的 Full（928 passed）、提交/推送、服务器新备份/隔离恢复、product-postgres 切换与真实文件验收、v3.2 报告重新生成、撤销门禁与回退演练。仍不能声称：专家金标、法规内容已签署、正式法律支持（0 条）、扫描件可直接可用、真实模型业务效果达标、用户独立验收通过。
