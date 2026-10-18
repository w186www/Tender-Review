# TASK-0021 在线 Qwen 演示指南

## 模式边界

- `offline-deterministic`：TASK-0020 的离线确定性演示，不发起模型请求；其运行标识和行为保持不变。
- `online-qwen`：TASK-0021 独立隔离模式。UI 标识阿里云百炼 `qwen3.8-flash`，请求只经 `ModelGatewayService` 到 `semantic_analysis`。任何凭据、授权、预算、输入边界或在线请求失败均使审查失败，不返回离线/Mock 结果。

在线模式不作为普通后端默认项，不应在通用 `start.ps1` 中启用。使用本任务的一次性 runner 和独立本地验证数据库、对象存储、Worker、Edge 会话及审计目录。Runner 的模型 HTTP 并发固定为 1、每次运行只允许一次请求；这不是多进程共享账本或生产预算控制。

## 授权状态

DEC-002 已获批且唯一一次 Qwen 请求已于 2026-10-15 在本地隔离 Edge E2E 中成功执行（run `30180d4e152040ccb9f805634617b456`）；该请求同时作为 API smoke 和 LangGraph 联调，没有额外探测请求。此次授权已消耗，失败后的重跑或任何额外请求均需新的明确授权。完整授权范围和官方链接见[DEC-002](../decisions/DEC-002-qwen-demo-authorization.md)。本次使用北京官方列价，预算运行时在调用前预留完整 ¥0.10 CNY；实际 token 用量与估算费用见[TASK-0021 验证记录](TASK-0021-validation.md)。不得按免费额度假定零成本。

## 凭据注入

通过 Windows 的“用户环境变量”安全设置为当前用户添加 `DASHSCOPE_API_KEY` 与 `BAILIAN_WORKSPACE_ID`，不要把值输入 PowerShell/CMD 命令行、`.env`、脚本或聊天。Workspace 专属 endpoint 的 Workspace ID 可在百炼控制台“业务空间管理”页面的 API Host 中查看；本次授权使用该专属 endpoint，因此两个变量都必需。优先使用限定到 `qwen3.8-flash` 的短时 API Key；百炼官方文档说明临时 Key 最长 1,800 秒，并建议避免在不可信环境中使用长期有效 Key。配置后完全退出并重启 Codex，使 runner 进程继承环境变量；任务验证完成后删除该 Key。运行前程序只检查变量存在，不显示其内容。缺少任一变量时在线 runner 关闭。

## 外发白名单

适配器只能获得经服务端输入最小化器处理的结构化对象：合成数据集标识、已允许列表绑定的合成文档哈希、Skill/规则代码、候选 ID、不含真实项目信息的定位及原文片段。规范化后的完整白名单样本 JSON（包括所有上述字段）UTF-8 总字节数最多 2,048，原文片段字节合计也单独受 2,048 限制。上传二进制、文档属性、自由项目上下文和完整法规 RAG 命中不得发送；RAG 仍在本地运行并交给原有 Evidence Checker。真实招标文件、个人/客户数据、法规正文一律不允许进入在线请求。

原始数据库 payload 不是白名单。任何文档 SHA 不匹配、未知字段、超长片段或非 `public` 数据分类均在 adapter 请求前失败关闭。

## 费用、重试和审计

线上 profile 设置最多 8,192 输入 tokens、1,024 输出 tokens，并对 Qwen 显式关闭默认思考模式以保留结构化回答预算；单次调用费用 ¥0.10 硬上限。Gateway 调用前预留完整上限，覆盖百炼文档提示的最多 10 个输出 token 计数差异；未知费用的已发请求按 ¥0.10 全额计费。一次性 one-shot guard 再拒绝第二个预留。Prompt/JSON 错误、限流、服务端错误和超时都不重试、不切换 Mock。

ModelGateway 审计回调写入本地受限的一次性审计文件，只记关联 ID、provider/model、Prompt/Profile/pricing/config 版本、token 数、费用、延迟、响应哈希和失败类别；不记 API Key、请求原文、法规正文或模型响应内容。该文件供本机演示核验，不构成生产防篡改审计。

在线页面与报告可标识真实供应商/模型，但真实评测证据必须来自调用审计和对应分析 artifact，并绑定实际运行 SHA；MockTransport、离线 Demo、非真实语义结果均单独标注。
