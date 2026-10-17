# ADR-0017：百炼 Qwen 聊天模型适配器与隔离演示路由

- 状态：accepted for TASK-0021 implementation; DEC-002 authorizes one bounded synthetic-data request only
- 日期：2026-10-15
- 相关任务：TASK-0021

## 背景

ModelGateway 已有供应商无关的结构化聊天协议，但现存百炼适配只提供 Embedding，不能承担聊天分析。OpenAI 适配器使用 OpenAI 固定地址及 Responses 协议，不能通过改模型名复用于百炼。TASK-0021 需要在保留 `semantic_analysis` 和完整本地 JSON Schema 校验的同时，实现受控的 Qwen Chat Completions 路由。

## 决策

1. 新增不依赖供应商 SDK 的 HTTPS REST 适配器，供应商标识独立为 `bailian`；只实现官方 Chat Completions JSON Schema 响应，不调用 Embedding API 或工具接口。
2. Workspace ID 来自本地秘密环境；运行时只构造固定北京地域 Workspace endpoint。禁用重定向、环境代理及 URL 覆盖，不支持把请求路由到 OpenAI endpoint 或其他地域。
3. 适配器把 Gateway 提供的 Schema 转成百炼文档支持的 strict JSON Schema 子集；完整仓库 Schema 不变，Gateway 仍执行完整的本地校验。供应商输出不能通过本地校验时必须拒绝。
4. 仅使用 `ModelGatewayService` 的 server-owned route、prompt allowlist、AuthorizationPolicy、输入最小化、预算预留、并发限制和元数据审计。LangGraph 不直接导入/调用适配器或供应商 SDK。
5. 在线 Qwen 只能由 TASK-0021 隔离 runner 显式启用。TASK-0020 offline 模式保持独立；在线调用失败不得回退到离线/Mock 结果。
6. 真实请求许可、允许外发字段、地域、单次费用上限和本地处理边界由 DEC-002 单独请求批准。当前 ADR 不授予真实调用权或业务数据外发权。

## 备选方案

- 复用 OpenAI 适配器：拒绝；其端点及请求/响应协议固定为 OpenAI Responses。
- 把百炼 Embedding Provider 改作聊天：拒绝；Embedding 和聊天协议及结果契约不同。
- 在 LangGraph 节点直连供应商 SDK：拒绝；绕过授权、预算、Schema 和审计边界。
- 允许在线失败切换离线输出：拒绝；会使真实与 Mock 证据混淆并造成静默误导。

## 后果

增加独立适配器与 MockTransport 契约测试；演示环境按单进程、单调用和低费用上限限制。该一次性运行控制不被视为生产共享预算账本。地理 endpoint 不能单独证明服务端留存或合规性质，用户须在 DEC-002 批准时评估官方条款及本地政策。
