# TASK-0008 本地验收记录

- 日期：2026-10-14
- 代码验收分支：`work/TASK-0008`
- 代码验收 SHA：`4d1f59f69143c63c7d4273958a12da19ecf5acdf`
- 基线：归档提交 `6edea37c071cfcec6cf8354b9d74f92fbcaba0a5`，包含 TASK-0007 验收源码 `236d2a6e231be030f719b0bbabc3f2b0a50039b3`。
- 本地工作区：代码验收时干净；TASK-0006 历史和既有 stash 保留。

## TASK0008-001：两家协议适配器与结构化输出

通过。`tests/test_model_adapter_conformance.py` 使用 HTTPX 离线虚拟传输分别执行 OpenAI Responses API 和 Anthropic Messages API 的请求序列化与响应解析，不 Mock 最终统一响应对象。覆盖不同认证/Schema 请求格式、嵌套 Draft 2020-12 输出校验、token/finish reason/延迟、空/异常/重复键 JSON、Schema 缺项/枚举/远程引用、供应商超时/取消/429/5xx/认证失败/截断、响应大小限制及无敏感日志。所有输出仍经本地完整 Schema 校验。

## TASK0008-002：调用授权、预算与注入安全

通过本地验收范围。`tests/test_model_gateway_security.py` 证明无可信 call context、无 provider allowlist、restricted 未授权、缺预算、预算耗尽及非 public 缺 minimizer 时网络调用数为零；文档注入和伪造 metadata 不改变批准 Prompt、租户/任务绑定、路由或工具权限。测试覆盖限额内同进程并发原子预留、调用失败费用保守结算、重试预算重留、总超时、fallback 重新授权、合法 Anthropic fallback 和断路器打开。

`InMemoryBudgetLedger` 的并发证据仅适用于单一 Python 进程。TASK-0008 没有实现或声称跨进程 PostgreSQL 一致账本；生产路由默认禁用，接入共享事务账本和多进程专项仍是生产前置条件。

## 验证结果

| 命令/范围 | 结果 |
|---|---|
| Focused：gateway/adapters/contracts 四个测试文件 | 54 passed，0 failed/error/skipped；`.verification/pytest-focused-result.xml` |
| Focused：仓库 Quick、Ruff、Mypy | 通过；Mypy 75 个源文件 |
| Full：`./scripts/verify.ps1 -PythonExecutable ./.venv/Scripts/python.exe -Mode Full` | 487 passed，0 failed/error/skipped；`.verification/pytest-result.xml` |
| Full：契约/生成/秘密、Ruff、Mypy | 通过；Mypy 75 个源文件 |
| Full：真实本机后端健康 HTTP 与认证/项目版本/注销撤权 | 通过；子进程已停止 |

Full 有两条既有 `pypdf.add_js` 弃用警告，未影响结果。

## 在线调用、生产限制与远程 CI

- 没有对 OpenAI 或 Anthropic 发起真实 API 请求；没有使用真实招标文件、凭据或付费调用。离线协议兼容不等同在线/生产验收。
- OpenAI/Anthropic 官方结构化输出格式按 ADR-0013 链接于 [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) 和 [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 核验。
- DEC-002（生产供应商与数据出境）仍待批准。生产模型名、费率、驻留、数据处理/保留、共享持久化预算和供应商账号均未配置。
- 用户随后明确授权仅向 `https://github.com/w186www/Tender-Review.git` 推送本任务分支；核对远端 URL、`work/TASK-0008` 分支、干净工作区及提交内容后，普通 `git push -u origin work/TASK-0008` 成功，未使用强制推送。
- 源码提交4d1f59f及其验收记录提交5b9b9f1触发 GitHub Actions [运行 38521959503](https://github.com/w186www/Tender-Review/actions/runs/38521959503)。最终状态 success；`impact`、`baseline`、`postgres`、`ingestion`、`verify-required` 全部成功，`quick` 按 Full 选档跳过。运行绑定提交`5b9b9f1bf68b245abb05b75cd855d07d30497d2a`，其祖先包含源码验收提交4d1f59f。
- TASK0008-001和TASK0008-002是本任务正式 acceptance_checks，证据均满足；任务文件注明仅 acceptance_checks 决定任务完成，因此不把“真实调用”步骤扩大解释为未列出的局部验收门槛。在线供应商调用仍未执行，不能视作在线或生产验证。工程记录/归档变更仅运行 Quick，不重复同一源码的 Full。
- TASK-0009 未启动。TASK-0008 局部 Full 通过不代表全局 AC-009/AC-010 或 M2 已完成。

## 归档

TASK-0008 已按正式局部验收归档；源码提交SHA：`4d1f59f69143c63c7d4273958a12da19ecf5acdf`。源码及验收记录提交的完整CI结果见运行 [38521959503](https://github.com/w186www/Tender-Review/actions/runs/38521959503)。任务归档提交及其工程记录 Quick CI 状态由本次归档记录提交和最终汇报确认。
