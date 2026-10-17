# ADR-0013：受控模型网关与供应商适配器

- 状态：已接受（TASK-0008 首期技术架构；不构成生产供应商或数据外发批准）
- 日期：2026-10-14
- 任务：TASK-0008
- 关联：ADR-0003、ADR-0011、DEC-002

## 背景

仓库已有供应商无关的 `ModelGateway` 和请求/响应数据类，但没有供应商调用、可信路由、费用预留或结构化输出执行路径。任务要求至少两个不同供应商协议，且 DEC-002 尚未批准生产供应商或外发策略。

## 决策

1. 业务层只依赖 `ModelGateway`。OpenAI Responses API 与 Anthropic Messages API 各有独立适配器，请求、认证头、结构化输出参数、响应解析和使用量字段分别映射。
2. 供应商 HTTPS 端点为适配器常量，关闭重定向和环境代理；业务输入不能指定 URL、工具或凭据。凭据由运行环境/秘密管理器注入适配器。
3. Profile 路由、供应商 allowlist、数据分类、模型/价格版本、系统 Prompt 版本、token ceilings 和预算均来自服务端配置。网关要求可信 call context 与批准的 Prompt 版本，不采信 `ModelRequest.metadata` 的权限或预算值。
4. Structured Outputs 用于约束生成；输出仍通过 JSON Schema Draft 2020-12 完整校验。只接受本地 Schema 引用，拒绝远程 `$ref`。供应商支持的子集不替代本地完整校验。
5. 预算 ledger 必须先原子预留最坏情况调用费用，再调用外部适配器；供应商报告 usage 后结算。未知费用计满预留额度，未知价格、token ceiling、预算或 ledger 时失败关闭。
6. `InMemoryBudgetLedger` 仅为单进程原子参考实现及离线测试使用。TASK-0008 不声称其具备跨进程一致性；生产部署必须注入支持事务/原子比较更新的共享 ledger，且未接入前不得开启外发路由。
7. 配置示例的所有外发路由默认禁用。OpenAI 和 Anthropic 仅为可替换的技术候选；DEC-002 批准前 confidential/restricted 数据不外发，也不代表批准跨境传输。
8. 审计事件只保存必要关联、配置版本、响应哈希、供应商报告的 token、估算费用、延迟、重试与失败分类，不记录 Prompt、招标正文、输出正文、密钥或异常原文。

## 备选方案

- 在业务节点分别使用供应商 SDK：会使领域流程绑定供应商，并绕开授权、预算和审计；不采用。
- 以两个同协议 Mock/HTTP 包装类冒充不同适配器：不能验证真实协议差异；不采用。
- 默认启用一个或多个付费供应商，并把单进程预算实现当作全局账本：与 DEC-002 未决及多进程并发边界冲突；不采用。
- 生产接入先等待完整数据库预算层，当前不交付适配器：会阻塞离线契约实现。首期使用清晰的预算端口及单进程验证实现，生产外发继续关闭；采用。

## 依据与接口核验

- OpenAI Responses API Structured Outputs 使用 `text.format` 的 `json_schema` 配置；实现采用 REST API 结构，并检查完整输出状态和 usage。官方说明了支持模型/Schema限制及截断、拒答等异常：[Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)、[Responses API reference](https://developers.openai.com/api/reference/resources/responses)。核验日期：2026-10-14。
- Anthropic Messages API Structured Outputs 使用 `output_config.format`，响应包含 text block、`stop_reason` 和 token usage；官方文档明确外部 `$ref`、数值边界等限制，故适配器传输前不尝试删除安全约束，响应由本地完整 Schema 再校验：[Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。核验日期：2026-10-14。
- 当前在线接口格式已按官方文档核验；实际供应商账号、生产模型名称、价格、数据驻留、数据处理协议、保留策略及 DEC-002 尚未批准。没有进行真实供应商调用。

## 后果与限制

- 默认无允许供应商/预算/路由，因此配置未批准时无法调用外部模型。
- 同一原子预算实现若只在单进程中运行，不能跨 worker 防止超支；生产接入须实现共享持久化 ledger 并通过 PostgreSQL 并发专项验证。
- 价格必须由版本化可信配置提供，代码不内置模型价格或生产模型名。此任务不批准生产供应商、模型或跨境处理。
- OpenAI 和 Anthropic 的约束解码 Schema 子集存在差异；请求可能被供应商拒绝，本地验证依旧是最终接受条件。
