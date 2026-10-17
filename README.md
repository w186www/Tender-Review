# Tender-Review · 招标文件智能合规审查 Agent

> **当前整合候选：** 本地候选以 GitHub `main` 为基线，保留其项目介绍并通过普通合并纳入 `work/TASK-0027` 的交付实现。该说明针对当前本地候选；GitHub 分支状态以仓库实际引用为准。

一个面向**招标文件编制侧**的 AI 辅助合规审查演示项目。系统将安全文件接入、采购上下文确认、确定性规则、LLM 疑点发现、法规参考检索、原文证据追溯和人工复核整合为可运行的工作流，最终生成 Word / PDF 审查报告。

**项目入口：** [代码仓库](https://github.com/w186www/Tender-Review/tree/work/TASK-0027) · [技术与部署说明](deploy/README-demo.md) · [项目进度](PROJECT_STATE.md) · [TASK-0027 验收记录](docs/development/TASK-0027-validation.md) · [系统文档索引](docs/index.md)

## 1. 业务流程

```text
创建项目 / 设置采购上下文
            │
   上传 DOCX / PDF / 图片
            │
格式与安全校验 → ClamAV 扫描 → 隔离解析 / OCR
            │
确认文档质量、来源片段与项目上下文
            │
  规则 Skill + Qwen 疑点发现 / 语义分析
            │
 法规参考检索（BM25 / 条件满足时使用 Dense）
            │
    风险合并、证据状态与原文定位
            │
    审查人员接受 / 修改 / 驳回
            │
       发布结果 → Word / PDF
```

审查输出是**可核验的风险线索**，不是自动出具的法律意见。系统区分“模型判断”“规则发现”“原文证据”“法规适用性”，法规未经有效性与适用范围核验时只作为候选参考，不直接认定条款违法。

## 2. 主要功能

| 模块 | 已实现能力 |
| --- | --- |
| 文件安全接入 | 扩展名/MIME/魔数校验、ClamAV、容器隔离解析、Tesseract OCR、解析版本与来源哈希 |
| 用户与项目 | JWT 登录/撤销、角色权限、PostgreSQL 行级安全（RLS）、多租户隔离、项目上下文版本 |
| Agent 审查 | LangGraph 工作流、确定性 Skill、Qwen 候选发现与语义分析、风险融合与审计 |
| 法规检索 | 现有法规库、BM25、持久向量索引、候选条款适用性状态和引用回查 |
| 证据链 | 文档 SHA-256、OOXML 段落/片段位置、风险证据状态与人工复核记录 |
| 人工复核 | 接受、修改、驳回候选；复核后发布可追溯结果 |
| 报告交付 | Word / PDF 导出、内容哈希与下载校验 |
| 真实模型授权 | 审核员对**单个文件**确认外发授权、服务端核对文档 SHA-256、追加式授权与审计 |
| 审查超时恢复 | 任务持久化、同幂等键复用；前端等待超时后可从项目任务列表找回 |

### 真实模型与逐文件外发

- 在线模型：阿里云百炼 `qwen3.8-flash`；法规 Embedding：`text-embedding-v4`。
- `DEPLOY_REVIEW_MODE=offline` 使用确定性离线网关，**不代表真实 AI 语义审查**；`authorized-real` 使用真实 Qwen 网关，未满足授权前置时拒绝执行而非静默回退。
- 真实模式可由审核员在工作台对某个已上传文件点击“登记外发授权”，明确确认并填写理由。服务端从数据库取该文档哈希，写入审计注册表；**上传本身不等于外发授权**。
- 只允许处理具有合法使用权限且获明确外发同意的资料；避免上传真实商业秘密、身份信息或无权处理的文件。外发请求按最小必要内容组装。
- 模型账本记录调用和实际费用，保留历史记录与失败预留。**当前代码中 DEC-007 的累计硬上限为 2000 次 LLM、2000 批 Embedding、¥200**（该数值可在 `docs/decisions/DEC-007-demo-real-qwen-authorization.md` 中核对），不是“无限额”。

## 3. 真实验证情况

### TASK-0027：受控真实 Qwen 端到端验证

服务器上的冻结合成 DOCX 样本完成了如下流程：上传、解析、上下文确认、**真实 Qwen 调用**、2 条疑点发现与原文定位、人工复核、结果发布、Word/PDF 下载。

| 指标 | 该次实测 |
| --- | --- |
| 模型 | `qwen3.8-flash`（百炼，真实执行） |
| Qwen 调用 | 2 次：discovery + semantic_analysis；0 次自动重试 |
| Token | 输入 1007 / 输出 705（供应商回传） |
| 本次模型调用费用 | ¥0.0027091 |
| 发起审查至等待人工复核 | 64.95 秒（单页合成样本） |
| 风险处理 | 2 条疑点，均保留 `insufficient_evidence` 与“待核验”状态 |
| 结果 | 完成人工复核、发布、Word/PDF 生成与下载哈希核对 |

**范围说明：** 这是特定合成文件的服务器实测，不保证大型文件均可在同样时间内完成。阶段二另有本机回环浏览器/测试环境的报告正文验收；**阶段一服务器生成的真实 AI 报告，尚未在本次文档整理中取得额外的逐项正文复核证据**。最终公网部署是否已切换、是否在线可用，也不能仅凭代码或 CI 断言。

### 法规库与检索的准确边界

- 法规语料共 **3120 条**，其中 **3112 条**已完成真实 Embedding 建库，另 8 条因长度约束保留 BM25 路径。
- TASK-0027 上述真实审查中，因法规核验与适用性门禁，**Dense 查询并未实际参与排名，结果主要来自 BM25**；不把“向量库已建成”等同于“该次混合检索已生效”。
- 法规版本、有效期和适用性尚未全面核验；参考候选明确标注未确认原因，不升级为已核验证据，不作违法认定。

### 自动化与浏览器验证

- TASK-0027 最新开发阶段：本机 Full 报告 **810 passed**、Ruff、Mypy、前端检查及构建通过；对应提交的 GitHub Actions 已通过。具体证据与环境前置见 [验收记录](docs/development/TASK-0027-validation.md)。
- 已对审查请求超时后的任务查询、幂等键重试、文档集冲突（409）等路径进行测试。
- 本机 Edge/Playwright 已覆盖项目、上传、审查结果、人工复核和报告内容抽查；该结果**不能替代公网真实模型的最终验收**。

## 4. 技术架构

| 层次 | 技术 |
| --- | --- |
| Web 工作台 | React、TypeScript、Vite |
| 后端 API | Python 3.12、FastAPI、Pydantic |
| Agent 编排 | LangGraph、规则 Skills、模型网关 |
| 身份与业务数据 | PostgreSQL 16、RLS、JWT |
| 文件与解析 | MinIO（S3 兼容）、ClamAV、Docker 沙箱、Tesseract |
| 法规检索 | BM25、SQLite 持久向量索引、Embedding 缓存与检索融合 |
| 模型 | 阿里云百炼 Qwen、`text-embedding-v4` |
| 运维与质量 | Docker Compose、Nginx/HTTPS、Pytest、Ruff、Mypy、GitHub Actions |

模型凭据仅应配置在受保护的服务器环境，绝不能写进 Git 仓库、前端代码或日志。

## 5. 快速开始

获取**实际开发分支**：

```bash
git clone --branch work/TASK-0027 --single-branch https://github.com/w186www/Tender-Review.git
cd Tender-Review
```

### 本地验证（Windows / PowerShell）

需准备 Python 3.12，以及前端所需 Node.js 环境。按锁文件建立虚拟环境：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.lock
./.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
./scripts/verify.ps1 -Mode Full
```

Windows 上部分嵌套 PowerShell 测试要求将虚拟环境的 `Scripts` 目录前置到 `PATH`；详见验收记录。上面的完整验证**不等于自动部署真实 AI**。

### 容器演示与真实 Qwen 模式

完整的 Docker Compose 环境、服务依赖、初始化、模型授权、法规索引身份检查、镜像构建、HTTPS、备份和回滚步骤，统一见 **[deploy/README-demo.md](deploy/README-demo.md)**。

真实模式需要单独准备百炼账号凭据、原有持久账本和向量索引，并核验模型授权与文件逐项确认。前端 `VITE_REVIEW_MODE=dec007-real-qwen` 是 **构建期**参数；切换后必须重新构建对应前端镜像。不要把 `DEPLOY_REVIEW_MODE` 切换与前端横幅显示混为一谈。

## 6. 项目结构

```text
config/             规则、法规清单等非密钥配置
knowledge/legal/     法规语料及来源材料
contracts/           API、领域数据与事件契约
src/                 FastAPI 后端、Agent、前端工作台
deploy/              Compose、镜像、部署与备份说明
scripts/             验证、向量索引、身份检查与辅助脚本
tests/               单元、集成、安全、反例与业务验收
docs/                架构、决策、开发记录与技术文档
tasks/               项目治理及任务记录
```

新开发者可按 [AGENTS.md](AGENTS.md) → [PROJECT_STATE.md](PROJECT_STATE.md) → [docs/index.md](docs/index.md) 的顺序阅读。历史任务与某些归档文档可能记载旧阶段结果，请优先以本分支实际代码、最新提交与对应验收记录为准。

## 7. 已知限制与定位

1. **定位为 AI 辅助审查 Demo，不是自动法律裁判。** 未经法律专业核验的法规仅供人工参考。
2. TASK-0027 已有真实 Qwen 业务链路证据，但部分浏览器测试在本机隔离环境执行；生产级可靠性、任意大文件性能与实际公网状态仍需分别核实。
3. 现有 Dense 索引已预构建，但上述审查的有效法规门禁使实际排名主要使用 BM25。
4. 逐文件外发授权端点已实现并有测试，但**尚未同步进入主 OpenAPI 契约**；这是当前已知的契约一致性待办。
5. 部署环境的 Worker 仍需要 Docker Socket 执行隔离解析；该权限边界和对象存储最小权限是后续生产化事项。

**面试演示重点：** 一份招标文件如何从安全解析进入真实模型发现疑点，如何准确回查原文、控制法规断言，并最终由审查员复核生成可交付报告。
