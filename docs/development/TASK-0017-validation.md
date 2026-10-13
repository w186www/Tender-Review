# TASK-0017 验证记录

2026-10-14。范围仅工程规则、验证脚本、CI与对应回归测试；TASK-0006业务代码、契约、依赖和法规原文未改动，既有D问题未自动关闭。默认跨软件与独立代理关卡由用户指令撤销，自检如实标自检。

## 本地实证

- Focused对本次验证策略测试运行：26项、0失败，测试约8.98秒；Ruff、Mypy48源文件和Quick前置检查通过。局部JUnit独立保存，结果不冒称完整验收。
- 最终脚本/CI候选Full：277项、0失败/0错误/0跳过，Mypy48源文件、Ruff、所有契约/生成一致性检查及健康/身份/项目/撤销两个实际HTTP检查通过。原pypdf测试有一条已登记弃用警告。
- 实际Git临时仓库验证push/PR差异；普通文档Quick，改名时删除的src仍识别为Full；未知、首次分支、无法比较历史均Full。源码/契约/配置/数据/依赖/脚本/CI/安全规则变化不获文档豁免。
- PowerShell实际验证Focused缺选择/越界/非测试文件及Full带缩小选择全部失败；Quick不调用Pytest/启动服务且不覆盖已有完整JUnit。空测试集仍由Pytest非零状态阻断。
- CI结构解析检查通过：Full三作业保留，Quick分开，verify-required总是运行并要求适用作业成功。尚未将本地结果冒充远程执行。

## 验收映射

| 检查 | 证据 |
|---|---|
| TASK0017-001 单Codex恢复、保留实际问题 | AGENTS§8、ADR-0011、development-workflow.md、TASK-0006任务及历史问题入口；仅角色关卡撤销 |
| TASK0017-002 完整门禁保留、档位不冒称完整通过 | scripts/verify.ps1、verification_impact.py、test_verification_modes.py、CI verify-required；实际26项Focused和277项Full |

Full后只更新这类记录和任务归档，核对没有代码/配置/数据/契约/测试/脚本变化，再Quick即可；不再全测相同源码。远程CI按确切提交核验，当前分支work/TASK-0006，未把未收尾法规任务合入main。
