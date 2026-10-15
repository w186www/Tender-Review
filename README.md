# 招标文件智能合规审查 Agent

面向真实招标文件的智能合规审查系统。项目采用 LangGraph 编排规则检查、法规检索、模型语义分析、证据校验和人工复核，目标是交付可部署、可审计、可替换模型、可持续维护的完整系统。

## 当前阶段

**TASK-0023 真实 Qwen 业务验收已完成，TASK-0024 法规检索解阻已交付。** 分支 `work/TASK-0023`。

### 真实运行证据（调用真实供应商，已记账）

- **TASK-0023 / DEC-006 完整闭环**：天津地铁 11 号线 DOCX 经正式网页完成上传、正式校正、上下文确认、
  真实 AI 审查、19 项人工复核、结果发布与 Word/PDF 生成下载。模型为阿里云百炼 `qwen3.8-flash`，
  10 次调用、费用 ¥0.062695；7 批风险发现覆盖 1207 个非空片段，确定性 Skills 候选 0 项而**模型独立发现
  19 个候选**，19/19 原文定位一致、**0 条违法断言**、全部 `insufficient_evidence` 待核验；下载报告
  SHA-256 与服务端 `content_hash` 一致。
- **TASK-0023 / DEC-005 真实供应商验证**：真实 `text-embedding-v4` 取得 1024 维在线向量并完成 SQLite
  索引与 BM25+向量 RRF 融合（缓存复用不重复付费，覆盖度如实 10/3120）；真实 Qwen 独立发现 41 个候选。
  该轮 30 次 LLM／3 批 Embedding、费用 ¥1.081571，因 `semantic_analysis` 单请求超时阻断，已在下轮修复。
- 两条授权在同一 SQLite 账本分别累计，历史互不重置；失败或未知用量按整笔预留记账。

### 离线测试与静态检查证据（未调用供应商）

- **TASK-0024 法规检索解阻**：查明 `CONTEXT_INVALID` 根因是查询构造阶段对企业非招标采购推导出空框架即抛错，
  且空框架被判为 `framework_mismatch` 二次阻断。现按"未知框架 ≠ 不匹配"处理：不推断框架、允许检索参考候选，
  但 `confirmation_reason` 在无已确认框架或法规未声明适用范围时返回 `applicability_unverified`，永不返回 `valid`。
- **参考候选展示**：风险详情页与 Word/PDF 均展示"可能相关法规（适用性未经确认，仅供参考，不计入已核验证据）"，
  含条款号、来源、版本核验状态与未确认原因；渲染验证基于**提取后的 DOCX/PDF 文本**，不是数据结构。
- **三案例排名**：生产检索**已是逐候选查询**（`category + problem_key + matched_reason + 原文摘录`）；
  《民法典》第五百八十五条在逾期违约金案例中排第 7，追加中文法律领域词后第 6。
- Focused 143 项、Ruff、Mypy 104 源文件、前端 lint/typecheck/单测/build 与 `verify_repo` 通过。

### 已知限制

- **法规库 42/43 版本未核验**且缺生效日期与适用范围声明，唯一已核验版本已超核验期，因此
  **已核验适用法规数为 0**，任何风险都不能被判定为违法；需法律专业核验后才能改变。
- 法规库 `source_uri` 多为转载地址；参考候选的排序精度仍有提升空间（语义检索覆盖仅 10/3120）。
- 未知上传文件不继承既有授权；本机 `test_verification_modes.py` 的 Quick 用例因 PowerShell 输出编码失败
  （移除本轮变更后同样失败，属既有环境问题）。

TASK-0021 的真实 Qwen 在线演示仍为历史归档证据，其 DEC-002 授权已消耗。

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

