# 招标文件智能合规审查 Agent

面向真实招标文件的智能合规审查系统。项目采用 LangGraph 编排规则检查、法规检索、模型语义分析、证据校验和人工复核，目标是交付可部署、可审计、可替换模型、可持续维护的完整系统。

## 当前阶段

**TASK-0021 真实 Qwen 在线审查演示已完成本地验收，代码提交的远端 Full CI 已通过，归档 CI 正在收尾。** TASK-0020 离线演示基线保持不变；TASK-0021 在独立工作树通过 DEC-002 授权的一次百炼 Qwen 合成数据在线 Edge E2E（5/5 浏览器用例，含上传、解析、审查、人工复核及 Word/PDF 导出）。唯一请求授权已消耗，不授权额外调用、重试或重跑；本地 Focused、Full、PostgreSQL/Checkpoint 证据复用并通过。代码提交 SHA `19a29fa0e62b6dc57d4493dc111f56194199e51c` 已推送，GitHub Actions Run 38707492669 所有适用 Full Job 成功。当前仅待归档状态提交的 Quick/CI 复核；TASK-0019 保持 planned，原工作树不参与本任务。状态见 [PROJECT_STATE.md](PROJECT_STATE.md)、[在线演示安全配置说明](docs/development/model-gateway-online-demo.md) 和 [TASK-0021 验证记录](docs/development/TASK-0021-validation.md)。

## 新开发者或 AI 的入口

默认使用单Codex按正式TASK直接实施、自检与收尾，见[开发与验证规则](docs/development/development-workflow.md)和[接手提示词](docs/development/prompts/codex-task.md)。默认跨软件和独立代理关卡已撤销，既有代码及问题记录保留。

1. 阅读 [AGENTS.md](AGENTS.md)。
2. 阅读 [PROJECT_STATE.md](PROJECT_STATE.md)。
3. 从 [docs/index.md](docs/index.md) 找到需求和架构。
4. 先阅读 [里程碑与任务依赖](docs/development/roadmap.md)，只处理依赖已完成的当前任务。
5. 准备Python 3.12和项目独立环境：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.lock
./.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
```

6. 最终代码候选运行（默认Full；过程文档用-Mode Quick，模块改动用-Mode Focused -TestPaths相关测试文件）：

```powershell
./scripts/verify.ps1
```

校验包括JSON Schema、OpenAPI、正反例、任务证据与依赖、State生成一致性、Ruff、Mypy和Pytest。空测试集失败。本地和CI使用同一锁文件与检查脚本。

## 启动后端

```powershell
./scripts/start.ps1
```

访问 `http://127.0.0.1:8000/api/v1/health`；开发接口文档在 `/docs`，Ctrl+C停止。日志约定见 [后端启动说明](docs/development/backend-start.md)。登录和项目接口的迁移、账号引导及权限步骤见 [身份与数据启动说明](docs/development/identity-data-start.md)；健康接口不依赖模型或数据库连接。

统一验证现已包含真实后端启动与本机HTTP烟雾检查，检查后自动清理自己的测试服务。

实际文件上传与 Worker 操作见 [安全文件接入启动说明](docs/development/secure-ingestion-start.md)。需要 Docker Linux Engine、受控解析镜像和 ClamAV；CI 另强制验证真实 S3、杀毒、OCR 与解析隔离。开发本地存储不适用于生产。

离线与在线审查模式及 DEC-002 批准前置条件见[在线 Qwen 演示指南](docs/development/model-gateway-online-demo.md)。在线演示只面向生成的合成 DOCX，不包含法规原文外发，不具备生产预算账本或公网部署能力。

前端工作台的 API 代理、Node/npm 版本、构建和浏览器 E2E 前置条件见[前端工作台说明](docs/development/frontend-workbench.md)。

若使用的打包Python没有ensurepip，可用支持虚拟环境的标准Python，或由已有pip执行 `python -m pip --python .venv/Scripts/python.exe install -r requirements-dev.lock` 后安装项目。不要把其他项目的site-packages加入本项目环境。

当前通过范围仅为开发基线；生产安全、性能、模型替换和业务验收在M1至M6执行。Word V2.0与当前架构差异登记在docs/reference/README.md。

## 目录

```text
config/                 非秘密配置样例
contracts/              OpenAPI、事件、领域和数据库契约
docs/                   需求、架构、ADR、开发与交付文档
evals/                  黄金样本、期望结果与质量阈值
knowledge/legal/        法规原文及来源索引
scripts/                统一验证和工程脚本
src/                    应用源代码
tasks/                  可执行任务与完成记录
tests/                  单元、契约、集成和安全测试
```

## 技术方向

- Python 3.12（当前本地与CI验证版本）
- FastAPI
- LangGraph
- PostgreSQL + pgvector
- Redis 与异步 Worker
- S3 兼容对象存储
- 可替换的 LLM、Embedding、Reranker 和 OCR 适配层

正式开发与交付方案位于 [docs/reference](docs/reference/README.md)。Word 文档用于评审和交付，仓库内的 Markdown、YAML、OpenAPI 与 JSON Schema 用于实际开发。

## TASK-0006 法规能力

法规摄取、不可变索引和混合检索启动见[法规检索说明](docs/development/legal-retrieval-start.md)。新版司法部法规快照与原始资料分别保留，待核实版本默认不能作为确定依据。

