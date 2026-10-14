# 模型网关设计

## 目标

业务逻辑只依赖统一协议，开发和运行时均可替换模型。模型差异由适配器和配置处理，不渗透到 LangGraph 节点。

核心调用：

```python
generate_structured(request, output_schema, policy) -> ModelResponse
```

## 统一能力

- 结构化输出和 JSON Schema 校验；
- 超时、有限重试、熔断和供应商降级；
- Token、费用、延迟、缓存和错误统计；
- 输入最小化、字段脱敏、日志裁剪和数据驻留策略；
- 按任务类型选择模型档位，不在业务代码中写模型名；
- 记录 provider、model、参数、Prompt 版本和响应哈希。

## 能力配置

`config/model_profiles.example.yaml` 按用途定义 `fast_extract`、`reasoning_review`、`evidence_check` 等 profile。生产配置通过配置中心或 Secret Manager 注入。

## 适配器合规测试

每个适配器必须通过：结构化结果、超时、取消、限流映射、敏感日志、Token 统计、空响应、非法 JSON 和降级行为测试。只有通过测试的适配器才能进入路由表。

Embedding、Reranker、OCR 使用各自协议，禁止假设与 LLM 使用相同供应商。

## 当前实现范围

TASK-0008实现了统一 `ModelGatewayService`、OpenAI Responses 与 Anthropic Messages 两个独立 REST 适配器、profile 路由、授权、Schema 校验、成本预留/结算、有限重试/熔断、脱敏入口及元数据审计。适配器端点固定为供应商 HTTPS URL，禁用重定向和环境代理；没有工具接口，也不从业务输入接受地址。

外发默认关闭。服务端必须配置路由、tenant 的 provider allowlist、provider 的可处理数据分类、批准的 Prompt 版本、具体模型、价格版本/费率/调用上限、预算账本和可信调用绑定（call_id→tenant/task/node）。请求 metadata 不参与授权。非 public 输入必须有服务端 minimizer；DEC-002 批准前不得配置 confidential/restricted 外发授权。官方结构化输出不是本地校验替代品，输出仍执行完整 Draft 2020-12 Schema 检查，拒绝远程 `$ref`。

UTF-8 字节上界（含系统 Prompt、输入、Schema 和包装开销）用于保守限制输入，供应商报告的 token 数用于后验上限检查、计费及审计。费率未知、token ceiling 缺失或预算 ledger 不可用时失败关闭。重试或降级前重新鉴权并重新预留；费用不确定的失败尝试按预留上界结算。Profile 未显式允许 fallback 时只使用首个候选。

`InMemoryBudgetLedger` 使用进程锁原子预留，仅用于单进程验证。它没有多进程一致性，也不适用于生产部署。生产路由保持禁用，直到持久化共享 ledger 提供事务/原子预留并通过并发集成验收。真实供应商 smoke test 未执行，不代表 DEC-002、生产供应商、模型型号、价格、驻留或跨境传输获批。局部验收与在线验证分别记录于 `docs/development/TASK-0008-validation.md`。

