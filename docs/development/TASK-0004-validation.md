# TASK-0004 验证记录

日期：2026-10-13。对应 TASK0004-001/002、SEC-001/002/007。关联 AC-008 不表示完整生产安全已经验收。

## 本地完整门禁

`./scripts/verify.ps1` 全部通过：契约/正反例/任务追踪/State生成、Ruff、严格Mypy（27个源文件）、152项Pytest（0失败/0跳过）、真实HTTP健康检查、真实进程身份与项目业务检查。独立环境重新安装可编辑项目并执行pip check，无依赖冲突。

业务进程从显式迁移后的隔离SQLite库启动，实际HTTP登录、项目创建/读回/版本更新/历史、登出后401；服务进程已经停止，测试库与XML保留在忽略的.verification目录。本地SQLite不能作为PostgreSQL验收证据。

## 局部验收覆盖

| 检查 | 证据 |
|---|---|
| TASK0004-001 空库迁移、重复迁移、ORM契约一致 | tests/test_identity_projects.py 的 migration 测试；固定Alembic迁移 |
| 项目租户范围、版本历史、幂等重放/冲突 | 同文件 lifecycle、cross_tenant、idempotency 测试；scripts/smoke_identity.py 实际HTTP |
| TASK0004-002 租户与角色越权拒绝 | 跨租户读/写/历史统一404、伪造body422、伪造header无效；三个非审核角色写403 |
| 当前身份、会话安全 | issuer/audience/过期/签名/缺失声明/none算法拒绝，登出撤销，账号/租户停用与角色变更即时生效 |
| 无秘密进入日志与响应 | 密码、签名密钥、完整Token的日志/响应回归；真实进程输出扫描；统一独立安全诊断沿用 |
| 数据层边界 | 文档复合FK拒绝跨租户项目，历史追加触发器拒绝删除；PostgreSQL专门门禁另验证RLS |

## 真实PostgreSQL门禁

新增 `.github/workflows/verify.yml` 的 postgres 作业，PostgreSQL16临时服务；固定验证库名 task0004_verification，拒绝对已有tenant库运行。`scripts/check_postgres.py`使用独立非超级用户/非BYPASSRLS运行API，验证升级/重复升级/ORM漂移、实际登录与项目接口、六路并发创建幂等、并发版本更新、事务后租户上下文清除、原始SQL的RLS隔离与写拒绝、复合FK、追加触发器、超级用户运行API失败、空库降级再升级。

最终代码远程验收：提交5dca2e341b97ce08d830a91936ca4d3d0f511aaa，运行https://github.com/w186www/Tender-Review/actions/runs/38393126223；baseline与postgres均completed/success。从baseline-test-results制品下载JUnit核验：152 tests、0 failures、0 errors、0 skipped。本地与远程结果独立核对，未从本地通过推断远程成功。该链接对应明确代码版本，本证据文档后续提交另触发CI，不将该SHA称作后续HEAD。本机Docker Linux Engine管道不存在，未将本机PostgreSQL验证记为通过。

初次实现提交5e31bea9c21e8ae58f0999ac892cf7e46e4877c8的145项与PostgreSQL作业也已成功（运行38392061114），但最终代码验收以以上5dca2e3及152项制品为准。

最终复核补充：即使签名正确，Token里的role也不构成授权；篡改tenant不匹配会话而401。同一幂等键在两个租户产生独立项目；数值字段不接受字符串和布尔隐式转换。服务层拒绝写操作前设置事务租户范围；非幂等唯一冲突的数据库异常保留原始原因进入安全诊断。数据库初始化与账号CLI的驱动配置异常采用固定错误与安全诊断，合成敏感驱动名不会泄露。任务移入completed后已重新运行完整门禁。

## 未交付范围

文档/审查任务表是后续功能的数据基础，不表示上传、Worker、LangGraph审查或报告已实现。网页身份授权审批、TLS、认证限流、完整运维防篡改审计和数据保留仍按后续任务交付。生产模型和法规效力尚未验收。
