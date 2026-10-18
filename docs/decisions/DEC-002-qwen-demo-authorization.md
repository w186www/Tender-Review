# DEC-002：TASK-0021 合成数据在线 Qwen 演示授权（已批准，单次受限演示）

状态：**approved — 仅授权一次受控在线 Edge E2E 和其中一次真实 Qwen 请求**
批准日期：2026-10-15
适用任务：TASK-0021；不构成生产接入、真实业务数据外发或公网部署许可。

## 请求批准的唯一在线演示配置

| 项目 | 拟议限制 |
|---|---|
| 供应商与模型 | 阿里云百炼 Chat Completions；`qwen3.8-flash`。仅用于真实 Qwen 在线演示。 |
| 地域与端点 | 华北2（北京，`cn-beijing`）；使用该 Workspace 专属的 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`。Workspace ID 仅由本地环境注入；不允许自定义 URL、重定向、环境代理、OpenAI 固定端点或供应商回退。 |
| 请求协议 | 官方 Chat Completions JSON Schema structured output（`strict: true`），并显式 `enable_thinking: false` 以避免默认推理模式挤占有限输出预算；供应商请求 Schema 仅移除其文档明确不支持的关键字，本地继续按原始完整 Schema 校验。无 tools/function calling。 |
| 允许外发字段 | 仅程序生成、SHA-256 已允许列表绑定的合成 DOCX 解析数据：合成样本标识、文档 SHA、候选 ID、Skill/规则代码、非敏感页/段定位及原文片段。服务端输入最小化器必须执行字段白名单和样本哈希绑定；对规范化后的完整白名单样本 JSON（含上述全部字段）按 UTF-8 计字节，总量不得超过 2,048 字节，原文片段合计也单独不得超过 2,048 字节。原始文件、隐藏文档属性、任意项目上下文、法规检索正文/标题/引文、账户/个人/客户数据均不外发。 |
| 单次请求边界 | 本次批准只覆盖一次完整的 TASK-0021 在线 Edge E2E 运行；其中 semantic_analysis 的唯一真实 Qwen 请求同时作为 API smoke 与 LangGraph 联调，不另发独立探测请求。调用并发 1，Gateway 与语义节点不重试，不降级或回退；失败或无效输出即停止，不自动重跑。最多输入 8,192 tokens、请求输出上限 1,024 tokens。百炼文档提示实际输出 token 与 `max_completion_tokens` 可能相差最多 10 个；预算覆盖到 1,034 输出 tokens。任何额外在线运行或请求都需新的明确授权。 |
| 费用 | 官方页面当前列价（2026-10-15 核验）：输入 ¥0.8/百万 tokens，输出 ¥2.7/百万 tokens。按 8,192 输入和 1,034 输出计算本次唯一请求费用最多 ¥0.0093454；用户已将本次总硬上限批准为 ¥0.10 CNY。Gateway 调用前预留完整 ¥0.10；请求一旦可能已到供应商，失败时按全额预留核算。实际计价、免费额度、税费或价格变化不视作零成本，运行前重新核价。 |
| 预算实现与隔离 | 仅限专用的一次性本机 TASK-0021 runner/Worker 进程；采用任务专用的单调用 ledger/one-shot guard 包裹 Gateway 预算端口，最多一个 reservation，设置并发为 1，并由调用计数器在任何后续请求前拒绝。进程退出销毁。既有 `InMemoryBudgetLedger` 不被描述为共享账本或生产保护；不得用于生产、多 Worker 或公网。 |
| 凭据 | 用户在本机安全环境变量中注入 `DASHSCOPE_API_KEY` 与 `BAILIAN_WORKSPACE_ID`；不写入仓库、命令历史、截图、日志或聊天。实现者不读取/回显密钥值；运行前只检查变量存在且非空。 |
| 审计 | 通过 ModelGateway 原有审计回调记录一次调用的关联 ID、供应商/模型、Prompt/Profile/价格配置版本、输入/输出 token、估算费用、延迟、响应哈希及失败分类；不记录密钥、请求原文、法规正文或模型原文。审计写入本地受限的一次性演示证据文件，不作为防篡改生产审计或共享存储。 |
| 保留与运行 | 仅在本地隔离测试数据库、生成的合成文件及本机 Edge 会话执行；不部署公网。请求和响应按百炼服务条款/账户设置处理，不能仅凭北京地域推定数据驻留、零保留或无跨境处理。用户需自行确认账户权限、数据处理条款和组织政策。 |

## 官方依据（执行前应重新核对价格和产品状态）

- [qwen3.8-flash 模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)：模型 ID、地域能力和定价。
- [模型计费说明](https://help.aliyun.com/zh/model-studio/model-pricing)：北京地域按 token 计费。
- [地域与 Workspace 专属 endpoint](https://help.aliyun.com/zh/model-studio/regions)：地域 Workspace 的 endpoint/key 规则。
- [Qwen 结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)：JSON Schema strict 能力和关键字边界。
- [OpenAI 兼容 Chat Completions](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)：`enable_thinking`、`max_completion_tokens` 和请求协议。
- [API Key 管理](https://help.aliyun.com/zh/model-studio/get-api-key/)：按地域管理密钥；密钥不得进入代码/日志。

## 批准请求

用户已明确批准本方案，并将单次硬预算从 ¥0.01 调整为 ¥0.10。唯一真实 Qwen 请求嵌在完整审查流程中，兼作 smoke 与 LangGraph 联调；仅限一次请求。本批准不授权任何真实招标文件、法规正文、个人信息、客户数据、其他模型/地域、其他外发字段、额外请求、失败后的重跑或超出 ¥0.10 的费用。可在本地安全设置上述环境变量后重启本机终端或执行进程；不要把 Key 粘贴到聊天或仓库。

## 北京 Workspace ID 配置说明

本次授权选定的 Workspace 专属 endpoint 格式为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/...`，所以请求主机名必须包含 Workspace ID。可在阿里云百炼控制台的**业务空间管理**页面复制 **API Host**；主机名中 `llm-xxx.cn-beijing.maas.aliyuncs.com` 的 `llm-xxx` 部分就是 Workspace ID。请将其作为本地环境变量 `BAILIAN_WORKSPACE_ID` 设置，并将北京地域 API Key 设置为 `DASHSCOPE_API_KEY`。官方文档仍注明旧版 `dashscope.aliyuncs.com` 域名可正常使用且仅需 API Key，但它属于存量兼容入口；本次不切换到该共享域名，因为已批准配置明确限定 Workspace 专属 endpoint。

用户已批准上述单次演示范围，并确认本机 Key 属于华北2（北京）地域。唯一请求已于 2026-10-15 通过本地隔离 Edge E2E 执行（run `30180d4e152040ccb9f805634617b456`）；调用审计与结果见[TASK-0021 验证记录](../development/TASK-0021-validation.md)。本授权现已消耗，不授权额外调用、失败重跑或更宽数据范围。任何后续真实请求均须新的明确批准。
