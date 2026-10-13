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

当前只有统一Protocol、请求/响应数据类和边界校验测试；尚未实现供应商调用、脱敏、路由、预算或两个适配器合规测试。TASK-0008负责实际实现和AC-010验收。接口存在不等于可替换能力已经通过验收。

