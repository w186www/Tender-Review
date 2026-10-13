# TASK-0003 基线修正验收记录

日期：2026-10-13。环境：Windows，Python 3.12.14，项目独立.venv；工具版本见requirements-dev.lock。

## 实际结果

- `./scripts/verify.ps1`：通过。
- JSON Schema元Schema、注册引用、OpenAPI规范和16个正反例：通过。
- State生成一致性、14个任务、7个里程碑、53个需求/验收ID及覆盖关系：通过。
- Ruff（源代码、验证脚本、测试）：通过。
- Mypy严格检查7个应用源文件：通过。
- Pytest：50项通过；错误YAML、重复键、非法Schema、缺失/外部引用、旧响应组合、State漂移、无证据任务、依赖循环、丢失需求/任务、空测试集均有负向用例。
- 项目无依赖/无构建隔离的editable安装与pip check：通过，未发现破损依赖。

## 局部验收与证据

| 局部项 | 证据 |
|---|---|
| BASELINE-001 契约、State与负向门禁 | tests/test_contract_validation.py、tests/test_repository_checks.py、scripts/verify_contracts.py |
| BASELINE-002 证据/人工状态与模型响应边界 | contracts/examples/manifest.yaml、tests/test_model_response_boundaries.py |
| BASELINE-003 统一命令、空测试失败和任务依赖 | scripts/verify.ps1、tests/test_repository_checks.py、docs/development/roadmap.yaml |

本地JUnit结果由脚本生成在`.verification/pytest-result.xml`，不纳入Git；CI工作流运行后上传对应制品。尚未推送远程仓库，因此不能把本地通过写成“GitHub CI已经通过”。

## 修正范围

修正项目响应Schema的封闭组合冲突；State从唯一Schema生成；先发现候选、再检索法规、最后基于证据分析；人工决定与证据判断独立；任务只按局部验收完成；所有需求与任务进入里程碑依赖表。

法规文本仍为42份，计数不证明效力。生产业务、供应商适配、越权、恶意文件、Checkpoint恢复、性能、供应链发布扫描和实际报告排版均待后续任务验收。AGENTS规则和证据文件存在不等于任何模型都必然遵守，仍需统一检查和评审。

Word V2.0保留为原始正式文档；与ADR-0005的差异已记录在docs/reference/README.md，正式交付前对齐。
