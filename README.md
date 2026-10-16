# Tender-Review · 招标文件智能合规审查 Agent

基于 **FastAPI + LangGraph + React** 的招标文件 AI 辅助审查系统：从文件安全接入、规则检查和法规检索，到真实大模型分析、原文定位、人工复核及 Word/PDF 报告，提供一条可演示、可追溯的审查流程。

> **请先看这里：最新完整实现位于 [`work/TASK-0027` 分支](https://github.com/w186www/Tender-Review/tree/work/TASK-0027)。** 当前 `main` 仅作为仓库首页与项目介绍入口，尚未合并该开发分支的功能代码。请勿直接用 `main` 判断项目最终完成度。

**快速入口：** [查看最新代码](https://github.com/w186www/Tender-Review/tree/work/TASK-0027) · [查看部署说明](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/deploy/README-demo.md) · [查看项目状态](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/PROJECT_STATE.md) · [查看验收记录](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/docs/development/TASK-0027-validation.md)

## 项目解决什么问题

人工审阅招标文件需要同时核对资格条件、限制性条款、评标要求与相关法规。Tender-Review 将这些步骤组织为一条可复核的辅助审查链路：

```text
项目创建与文件上传
        ↓
文件类型校验、ClamAV 扫描、隔离解析 / OCR
        ↓
原文结构化与采购上下文确认
        ↓
规则检查 + AI 疑点发现 + 法规检索
        ↓
证据与原文位置校验（不确定项保留待核验）
        ↓
人工接受 / 修改 / 驳回
        ↓
结果发布与 Word / PDF 报告下载
```

系统的目标是**辅助识别与解释疑似风险**，而非跳过法律核验或人工复核，自动断言某条款违法。

## 已实现的主要能力

| 模块 | 能力 |
| --- | --- |
| 安全接入 | DOCX/PDF 上传、文件校验、ClamAV、隔离解析、OCR 与原文定位 |
| 项目与权限 | JWT 认证、租户隔离、项目及文档版本、审查任务持久化与审计 |
| 审查编排 | LangGraph 组织规则、疑点发现、法规检索、语义分析与证据检查 |
| 真实模型 | 阿里云百炼 `qwen3.8-flash`；模型调用、Token 与费用可审计 |
| 法规参考 | 现有法规库、BM25 检索及预构建向量索引；未核验来源不作为已确认法律依据 |
| 人工闭环 | 审查员复核、结果发布、带引用与原文位置的 Word/PDF 报告 |
| 演示部署 | Docker Compose、PostgreSQL、MinIO、Nginx/HTTPS，以及故障回滚说明 |

## 已完成的验证与适用范围

在**受控服务器环境**中，冻结的合成 DOCX 样本已完成真实 Qwen 审查：2 次模型调用（无重试）、产生 2 条待人工核验的疑似风险，完成原文定位、人工复核、结果发布与 Word/PDF 下载；本次从发起审查到等待人工复核约 **64.95 秒**。这不是对任意大型真实招标文件的性能保证。

现有法规快照包含约 **3120 条条文**；其中 **3112 条**已建立持久向量索引，8 条保留 BM25 检索路径。**需要特别说明：上述受控真实 Qwen 验收中，Dense 向量检索尚未实际参与排名，法规候选主要来自 BM25。** 不将“索引已构建”等同于“混合向量检索已在该次审查中生效”。

法规有效性与适用范围尚未全面核验，因此系统会将相关引用标注为**待核验参考**，不会凭相似度直接作出违法认定。

本机还完成了前端工作台、超时后任务找回、幂等提交与报告内容的相关测试。公网实时演示状态及账号开放情况，以最终部署验收和交付通知为准；**代码测试通过不等于公网已完成上线**。

## 技术栈

- **后端**：Python 3.12、FastAPI、Pydantic、LangGraph
- **前端**：React、TypeScript、Vite
- **存储与隔离**：PostgreSQL（含 RLS）、MinIO、SQLite 模型预算/向量索引、Docker 隔离解析
- **检索与模型**：BM25、Embedding / 向量索引、阿里云百炼 Qwen
- **部署与测试**：Docker Compose、Nginx、HTTPS、Pytest、Ruff、Mypy、GitHub Actions

## 如何查看最新实现

```bash
git clone --branch work/TASK-0027 --single-branch https://github.com/w186www/Tender-Review.git
cd Tender-Review
```

安装、配置、容器部署、环境变量及回滚步骤请查看 **[开发分支的部署文档](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/deploy/README-demo.md)**。请使用实际需要的独立环境变量文件，**不要将密钥、测试账号密码或真实招标文件提交到公开仓库**。

项目设计与运行细节：
- [最新开发分支](https://github.com/w186www/Tender-Review/tree/work/TASK-0027)
- [当前项目状态](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/PROJECT_STATE.md)
- [阶段验收与已知限制](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/docs/development/TASK-0027-validation.md)
- [架构与文档索引](https://github.com/w186www/Tender-Review/blob/work/TASK-0027/docs/index.md)

## 演示与安全边界

- 优先使用**合成或明确获准处理的招标文件**。将真实文件内容发送给第三方模型前，需要文件处理权限及明确外发授权；上传不自动等于同意外发。
- 未核验法规仅用于提示和人工参考，风险项及报告不得将其写成已确认违法结论。
- 模型费用与请求应保留审计；演示并非对法律结论、商业场景或生产级负载的保证。
- `main` 未合并最新实现；审查代码和复现步骤请使用 `work/TASK-0027`。
