# Tender-Review · 招标文件智能合规审查

面向招标文件编制侧的 AI 辅助审查系统，提供文件接入、规则与模型分析、库内法规引用、原文定位、人工复核和 Word/PDF 报告。

当前版本是**产品工程验收候选**，已部署真实模型及 PostgreSQL 产品模式。用户独立验收和专业准确率评测尚未完成；运行事实、源码与镜像身份以 [PROJECT_STATE.md](PROJECT_STATE.md) 为准。

## 使用流程

1. 登录并创建项目，填写采购制度、方式、地区、主体和标的等上下文。
2. 上传文件，经过类型/大小/魔数校验、ClamAV 和隔离解析/OCR。
3. 检查解析质量；必要时校正并重新确认上下文。
4. 为该文件确认必要内容的外发授权，发起真实审查。
5. 查看风险线索、服务端精确原文定位及采用法规，接受、修改或驳回。
6. 发布不可变结果，生成和下载 Word/PDF 报告。

零候选需要明确确认；覆盖不完整、引用不足和无法确定的情况如实显示。上传成功不等于完整审查，人工接受也不等于系统认定违法。

## 范围与边界

| 项目 | 首版范围 |
| --- | --- |
| 文件 | PDF、DOCX、PNG、JPEG |
| 大小/页数 | 单文件 10 MiB、最多 300 页，其中 OCR 最多 30 页；另有实际文本及审查容量前检 |
| 角色与隔离 | admin、reviewer、auditor、operator；租户/资源权限在服务端检查 |
| 风险类别 | 资格、技术、评分、合同、采购程序 |
| 扫描件 | Tesseract OCR，保留词级置信度、原始坐标及段行结构；低质量转人工，不保证所有扫描件自动通过 |
| 输出 | 风险线索、原文位置、采用法规、覆盖限制、人工决定和版本化报告 |

详细限制见 [摄取支持矩阵](docs/development/ingestion-support-matrix.md)。本系统审查招标文件；投标响应性、材料缺项或废标风险的完整评审流程不在本版承诺中。

## 法规采用

本版按 [DEC-009](docs/decisions/DEC-009-legal-library-adoption-20261018.md) 直接采用冻结法规库：43 个版本、3120 个片段，3112 个片段已有向量工件，其余保留词法检索路径。

- 库内版本可参与分析并在报告中引用，不以重新人工核验作为工程交付前置。
- 引用仍校验条文 ID、原文、来源哈希、版本及项目适用条件。
- 项目采用与独立法律核验分开记录，不伪造 verified、核验日期或专家签名。
- 已采用参考与独立核验依据分别计数；后者为零不表示没有使用法规库。
- 不改写旧发布、旧报告或历史核验记录。

## 运行架构

React/TypeScript/Vite 工作台 → FastAPI → PostgreSQL 持久队列 → 独立 review-worker → LangGraph。
文件接入 worker 使用 MinIO、ClamAV 和固定镜像的隔离 parser；API 不持有 Docker Socket。
模型与 Embedding 通过网关接入；BM25、向量索引和法规发布身份可追溯。

### 运行模式

| 模式 | 用途 |
| --- | --- |
| `product-postgres` | 产品模式：PostgreSQL 是授权、预算和审计权威源，逐文件授权、撤销、预留和结算有效 |
| `offline` | 明确标识的离线验证；不代表真实模型审查 |
| `authorized-real` | 历史开发/测试入口；staging/production 拒绝启动，不能回退后重新使用旧额度 |

本轮受控测试累计上限为 ¥200 / 2000 次 LLM / 2000 批 Embedding，计入历史消费和未知预留，不因迁移或重启恢复额度。生产策略以实际配置和账本为准。

只处理有权使用且获必要外发同意的文件；凭据仅存受保护服务器配置，不进入前端、Git 或普通日志。

## 开发与验证

已有工作区复用 `.venv` 和 `src/frontend/node_modules`，不按 TASK 创建新目录或重装依赖。首次环境准备见 [开发流程](docs/development/development-workflow.md)。

```powershell
./scripts/verify.ps1 -Mode Quick
./scripts/verify.ps1 -Mode Focused -TestPaths @('tests/test_llm_candidate_discovery.py')
./scripts/verify.ps1 -Mode Full
```

Quick、Focused、Full、真实 PostgreSQL/容器、浏览器和供应商验证分别记录。有效证据可复用；最终代码候选仍须通过适用门禁。具体记录见 [产品交付验证](docs/development/product-delivery-validation.md)。

## 部署与恢复

部署、初始化、产品策略/预算、备份、恢复及安全回退见 [部署手册](deploy/README-demo.md)。

- HTTPS 部署必须同时采用 `docker-compose.demo.yml` 和 `deploy/docker-compose.tls.yml`。
- 发布前备份数据库、对象、索引、授权、预算、配置和审计，并在隔离目标验证恢复。
- 只重启必要应用服务，保全持久卷与历史数据。
- 回退采用兼容产品候选或 `offline`；未核账不得重新放行外发。

## 证据与交付状态

真实 DOCX、派生文字 PDF、扫描 PDF 的运行证据、费用、覆盖和限制集中在 [交付验证记录](docs/development/product-delivery-validation.md)，当前可执行验收步骤以 [PROJECT_STATE.md](PROJECT_STATE.md) 为准。

专家风险金标仍未建立，不宣称 precision/recall 已达标。单次容量观测不等于长期性能或可用性承诺；无外部通知渠道时不得声称告警已经送达。已知限制及未完成条件必须随交付候选一并提供。

贡献者入口：[AGENTS.md](AGENTS.md) → [项目状态](PROJECT_STATE.md) → [文档索引](docs/index.md)。正式需求、契约、ADR、任务和验收证据优先于历史聊天。
