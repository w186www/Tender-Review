# TASK-0017 验证记录

2026-10-14。范围仅工程规则、验证脚本、CI与对应回归测试；TASK-0006业务代码、契约、依赖和法规原文未改动，既有D问题未自动关闭。默认跨软件与独立代理关卡由用户指令撤销，自检如实标自检。

## 本地实证

- Focused对本次验证策略测试运行：26项、0失败，测试约8.98秒；Ruff、Mypy48源文件和Quick前置检查通过。局部JUnit独立保存，结果不冒称完整验收。
- 最终脚本/CI候选Full：277项、0失败/0错误/0跳过，Mypy48源文件、Ruff、所有契约/生成一致性检查及健康/身份/项目/撤销两个实际HTTP检查通过。原pypdf测试有一条已登记弃用警告。
- 实际Git临时仓库验证push/PR差异；普通文档Quick，改名时删除的src仍识别为Full；未知、首次分支、无法比较历史均Full。源码/契约/配置/数据/依赖/脚本/CI/安全规则变化不获文档豁免。
- PowerShell实际验证Focused缺选择/越界/非测试文件及Full带缩小选择全部失败；Quick不调用Pytest/启动服务且不覆盖已有完整JUnit。空测试集仍由Pytest非零状态阻断。
- CI结构解析检查通过：Full三作业保留，Quick分开，verify-required总是运行并要求适用作业成功。尚未将本地结果冒充远程执行。

## 远程核验与接手状态

- 分支work/TASK-0006，已推送源码0016b306550f341f514f2d35a62c2385e968f612，运行：https://github.com/w186www/Tender-Review/actions/runs/38446832736。
- 最近已取得的状态为impact成功、ingestion成功、postgres失败；失败步骤为Verify actual PostgreSQL security and migration。baseline当时仍运行，最终作业与总门禁状态尚未核对。此记录是最近观测，不能代表实时状态。
- 尝试下载失败日志时自动审批因额度限制未能完成，命令未执行；尚无失败日志，也未定位根因。这不是对操作安全性的否定，不得绕过审批取日志。
- TASK-0017和TASK-0006均保持in_progress。接手先查失败日志并核对最终CI，按原因选择专项检查；必要代码或脚本修复后进行最终Full与专项验收。此次仅更新交接记录，不重复同一源码的Full。
- 交接文档更新后直接运行./scripts/verify.ps1 -Mode Quick通过，未运行运行时测试。首次通过LOCALAPPDATA定位用户PowerShell入口失败（沙箱环境变量指向隔离目录），脚本未启动；随后在当前PowerShell中直接执行成功。本轮交接更新尚未提交。

## 2026-10-14接手排错与修复

- 接手分支work/TASK-0006、HEAD=0016b306550f341f514f2d35a62c2385e968f612；三处已有文档未提交改动保留。远程main仍bd2da2da984b6d1c34f3cfdb7da69e21661523be，任务分支没有合入main。
- 已通过GitHub API核对上述运行最终completed/failure：impact、baseline、ingestion成功，postgres与verify-required失败，quick因Full选档不适用。失败日志已用现有Git凭据只读下载至.verification/task0017-postgres-failure.log，凭据未输出或写入文件。之前的未知原因记录保留为历史观测。
- 根因：check_postgres.py:185调用ingest，在corpus.py:82抛出legal source hash mismatch。42份旧法规清单按原CRLF字节计算哈希，Git文本自动转换使仓库blob为LF；Windows检出恢复CRLF因而通过，Linux检出LF失败。逐份比较42/42均复现：本地匹配，blob不匹配，恢复CRLF后匹配。新版HTML/正文已有-text保护，未受影响。
- 修复属于TASK-0017跨平台验证工程：允许路径补.gitattributes，旧法规.txt明确text eol=crlf，新版snapshots/versions继续-text。未改法规原文、manifest/hash、业务代码或哈希检查。新增真实Git隔离仓库fresh clone回归，分别core.autocrlf=false/true并core.eol=lf，检查43版本全部来源/文本哈希、完整索引/字符定位一致；追加篡改字节仍抛原哈希错误。
- 修复过程Focused（verification_modes、legal_retrieval、legal_runs）84项通过、Ruff/Mypy48文件/Quick通过；真实一次性PostgreSQL16原有scripts/check_postgres.py退出0，含增量/重复迁移、最小权限、FORCE RLS/WITH CHECK、并发、运行读取/撤权、追加写触发器及完整回滚。容器已清理。
- 最终修复候选Full通过：279项、0失败/0错误/0跳过，JUnit已核对；Ruff/Mypy48文件、全部契约/生成检查、两个真实HTTP检查通过。仍仅原pypdf样本弃用警告。修复源码远程CI待核对；完整源码验收后的文档记录仅Quick。

## 验收映射（保持原检查）

| 检查 | 证据 |
|---|---|
| TASK0017-001 单Codex恢复、保留实际问题 | AGENTS§8、ADR-0011、development-workflow.md、TASK-0006任务及历史问题入口；仅角色关卡撤销 |
| TASK0017-002 完整门禁保留、档位不冒称完整通过 | scripts/verify.ps1、verification_impact.py、test_verification_modes.py、CI verify-required；实际26项Focused和277项Full |

Full后只更新这类记录和任务归档，核对没有代码/配置/数据/契约/测试/脚本变化，再Quick即可；不再全测相同源码。远程CI按确切提交核验，当前分支work/TASK-0006，未把未收尾法规任务合入main。
