# 正式交付文档

- `招标文件智能合规审查Agent_完整开发与交付文档_V2.0.docx`：当前正式方案基线。

Word 文档提供完整背景、范围和交付设计。开发中的精确字段、接口和状态以 `contracts/` 为准；架构选择以已接受的 ADR 为准。

## 与Word V2.0的已登记差异

2026-10-13 / ADR-0005修正：主流程从三路直接并行调整为候选发现→法规检索→基于证据分析；人工解析修正后复检；人工复核后先发布不可变结果再渲染报告。风险的证据状态与人工决定分别保存，State由Schema生成。

这些调整以ADR-0005和当前契约为开发依据。本次保留原始正式Word，不声称其已同步更新；TASK-0014正式交付前必须对齐并重新检查排版。

## TASK-0015新增差异登记

| 差异 | Word V2.0位置与原表述 | 当前执行依据 | 处理 |
|---|---|---|---|
| 重复风险率 | §32.2：首版建议≤10% | evals/thresholds.yaml：duplicate_rate_max=0.05，即≤5% | 采用更严格的YAML门槛，禁止为发布放宽；TASK-0014更新Word |
| 实施里程碑 | §34：M0启动、M1文档底座、M2审查引擎、M3审核报告、M4工程化、M5验收优化、M6交付；附10周团队估算 | docs/development/roadmap.yaml：M0工程基线、M1后端与文件、M2法规规则模型、M3闭环界面、M4运维、M5验收、M6正式交付 | YAML按真实依赖和阶段退出条件执行，Word周期不作为当前承诺 |
| 仓库布局 | §21.1：apps/api、apps/worker、apps/web及packages/graph等monorepo建议 | 实际Python包src/bidding_compliance/api、core、graph、domain、model_gateway；后续模块按任务增加 | 当前采用Python包布局；尚未实现的Web/Worker不声明已存在，正式交付同步目录图 |

本表登记差异，没有改写正式Word原文件。事实源优先级依AGENTS.md/ADR-0001执行；差异收敛由TASK-0014验收。

