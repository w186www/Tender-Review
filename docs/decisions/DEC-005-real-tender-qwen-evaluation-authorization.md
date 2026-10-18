# DEC-005：本轮受控真实 Qwen 与 Embedding 授权

状态：**approved，用户于 2026-10-15 本轮明确批准**。执行任务：TASK-0023。

本记录取代本分支此前的待批准单次提案。用户已委托技术负责人确定本轮合理范围，不需逐次确认。TASK-0022原工作树和历史任务不改写；DEC-002仍已消耗，不复用。本授权不涵盖后续未知上传文件。

| 范围 | 强制限制 |
|---|---|
| 供应商 | 阿里云百炼，北京HTTPS固定Workspace endpoint，禁止重定向和环境代理 |
| LLM | qwen3.8-flash，本轮最多30次，并发1、超时60秒；单次输入≤65,536tokens、输出≤16,384tokens，关闭thinking、工具、自动重试和回退 |
| Embedding | text-embedding-v4，固定1024维；本轮最多200个HTTP批次，每批≤10条、每条≤8192tokens；并发1、超时有界、无重试 |
| 费用 | 两类请求累计≤¥20；SQLite原子预留，每次LLM预留¥0.25，Embedding最多¥0.10；失败或未知结果保留完整预留，重启不清零；覆盖官方输出最多+10tokens计数误差 |
| 文件 | 用户指定天津地铁11号线DOCX及明确登记的合成评测数据；服务端固定SHA白名单，未知文件禁止外发 |
| 文本 | 仅经扫描、隔离解析、质量与上下文确认后的必要分段，顺序覆盖；联系人、电话、邮箱、账号等脱敏。不发送二进制、整个仓库/数据库、密钥文件或无关本机文件 |
| 法规 | 仅项目具备使用权限的法规快照片段可Embedding，固定模型/维度/法规版本/片段集绑定SQLite索引，准确报告覆盖度 |
| 证据 | 摘录必须精确存在于发送分段并映射本地原文，服务端计算哈希和稳定ID；无有效适用法规只能待核验，不强设政府采购框架 |
| 审计 | 仅存身份、模型、哈希、tokens、费用、耗时和状态，不记录Key或请求/响应正文。真实文件及详细报告仅留忽略目录 `.verification/private/TASK-0023` |

任何授权、脱敏、预算或证据门禁不满足即失败关闭。人工参考答案不进入Prompt。Key仅由后端环境注入，不进入源代码、日志、Prompt、前端或GitHub。

官方复核：[Qwen模型与价格](https://help.aliyun.com/zh/model-studio/qwen3-8-flash) 北京输入¥0.8/百万tokens、输出¥2.7/百万tokens；[Embedding模型价格](https://help.aliyun.com/en/model-studio/text-embedding-v4) 输入¥0.5/百万tokens；[Embedding接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)；[地域域名](https://help.aliyun.com/zh/model-studio/regions)；[Chat参数与token误差](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。不假定免费额度。
