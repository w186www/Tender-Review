# TASK-0018 法规检索评测集

`snapshot.lock.json` 固定本轮仓库语料清单、43版本/3120片段索引哈希和核实来源。评测脚本必须先复建索引并校验这些身份；索引产物只写入 `.verification/task0018-*`，不得改写法规原文或发布快照。

`queries.json` 的10个固定查询将目标精确到唯一法条。唯一可用的确定标签来自司法部已核验的2019年修订《招标投标法实施条例》官方文本。标签只表示“这条已核实原文是该查询的检索目标”，不表示完整法律意见、风险确认或违法结论。42个未核实版本可以在 `include_references=true` 的检索结果中作为候选观察，但不能成为准确率正例。

`applicability_cases.json` 独立验证语料中已核实法规适用范围和核验时间门禁；其混淆统计不与召回/准确率分母混合。`unconfirmed_candidates.json` 是专家未确认风险的独立集合；目前没有经用户或专家提供的候选，计数为0，不是模型“无误”的结论。

指标在相同的索引哈希、查询文件哈希、review date、context 和 top-k 下运行。报告包含 Recall@5、Recall@10、MRR@10、nDCG@10、平均/P95检索延迟、进程峰值RSS、索引重建时间及过滤混淆矩阵。TASK-0018 只测量原有 CharacterEmbedding/BM25/RRF；合成 SQLite 向量用于协议和索引工程测试，绝不进入检索质量分数。BGE 部署不属本任务范围。

已保存的同日运行依次为 `results/character-baseline-20261015.json`、`results/character-repeat-20261015.json` 和 `results/character-repeat-final-20261015.json`。三次排序指标相同；延迟差异保留在各份报告中，运行状态不同的延迟不作生产性能承诺。重跑命令应写入 `.verification` 或另一个新的报告路径，不覆盖已有证据。
