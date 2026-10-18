# TASK-0020 本地离线演示指南

> **当前状态（2026-10-15）：演示主流程尚未通过验收。** 用 TASK-0018 parser 上传合成 DOCX 后，安全解析完成，但创建审查因 OCR provenance 的 JSON list 与严格 tuple 模型不兼容而返回 422。详情见 [TASK-0020 验收记录](TASK-0020-validation.md)。在此问题解决前，不要把该流程当作可用的面试演示。

## 演示边界

该入口只提供本机 loopback 演示，使用临时 PostgreSQL、MinIO、ClamAV、隔离解析器、真实 FastAPI/ReviewEngine 和现有前端。审查节点显式注入 `OfflineReviewGateway`，输出是固定确定性测试结果，不是在线 Qwen/DeepSeek 语义分析。页面顶部会一直显示离线模式说明，报告下载文件名以“离线确定性演示”开头。

默认生产 API 入口保持 fail closed；未注入经授权的 ReviewEngine 时，审查接口仍返回 503。演示入口不改变用户认证、租户隔离、Evidence Checker 或法规证据状态。

## 启动

首次准备前端依赖时仅使用官方 npm registry 和锁文件：

```powershell
Set-Location src/frontend
npm ci --no-audit --no-fund --registry=https://registry.npmjs.org/
Set-Location ../..
```

确保 Docker Desktop 可用，然后从项目根目录运行：

```powershell
./.venv/Scripts/python.exe scripts/run_task0011_e2e.py --serve
```

脚本只绑定 `127.0.0.1`，为临时服务生成随机凭据，并在终端提供管理员/审核员账号和登录地址。合成演示 DOCX 保存在本次 `.verification/task0011-e2e-<run-id>/synthetic-tender.docx`。口令只显示在启动终端，不写入运行清单。

## 网页操作

1. 以管理员登录“配置版本”，创建并发布当前法规快照与演示审查配置。演示数据不代表真实项目。
2. 以审核员登录，创建一个“合成演示”政府采购项目，项目类型选货物，地区填写“合成测试地区”。
3. 上传启动脚本生成的合成 DOCX。隔离 worker 会消费已持久化的 `ingestion_job` 并调用正式 `process_document.py`；若页面要求确认上下文，先人工确认。
4. 发起审查。页面顶部离线说明在所有业务页可见；检查候选、原文定位、法规版本/核验状态和 Evidence Checker 证据等级。
5. 完成人工复核并继续持久化工作流，发布结果后生成并下载 Word/PDF。下载文件名保留“离线确定性演示”标识。

固定网关可能稳定生成预设候选；它只用于演示 LangGraph、证据绑定、Checkpoint、权限、人工复核和报告闭环，不测真实 LLM 的判断能力。法规库中未核验版本仍显示为待核验，系统不能据此给出确定违法结论。

## 停止与限制

演示完成后在启动终端按 Ctrl+C。脚本会停止子进程并移除一次性容器；`.verification` 下的运行日志、状态清单和合成 DOCX 保留用于本机诊断，不进入 Git。

该页面当前只能由运行机器本机打开。远程面试访问、TLS/访问控制方案、数据留存和持续费用须先确定并批准 DEC-001。任何真实供应商模型调用均须先批准 DEC-002；本指南不包含外发调用。
