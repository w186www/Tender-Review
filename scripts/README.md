# 统一工程入口

- `verify.ps1`：默认Full；普通文档用`-Mode Quick`，编码过程用`-Mode Focused -TestPaths`明确相关测试文件。完整代码验收与专项检查保留，见docs/development/development-workflow.md。
- `verification_impact.py`：CI选档，仅白名单普通文档/任务元数据Quick；代码/安全/未知影响或缺对比历史Full。

`verify.ps1` 是所有开发者、AI 模型和 CI 的开发基线入口，自动优先使用项目.venv。安装方式见README。

当前实际执行：

1. 正式解析YAML并拒绝重复键，校验JSON Schema元Schema、引用、OpenAPI规范及manifest列出的全部正反例（当前34个）。
2. 检查State生成一致性、任务状态、局部证据、需求引用和依赖；法规文本计数仅检查资料数量，不检查效力。
3. Ruff（含静态安全规则）、Mypy严格应用类型检查和Pytest回归测试。空测试集和任何非零退出码均阻断。
4. 真实启动TASK-0002后端，并通过本机随机端口检查health、404及请求编号；最后清理自己的子进程。受限环境必须允许本机回环网络，不能跳过此步骤。

`generate_state.py` 从唯一JSON Schema生成State，`--check`验证生成文件未漂移。不要直接修改生成文件。

测试临时目录被限定在项目内`.verification`，每次使用新ID；JUnit结果保存在`.verification/pytest-result.xml`且不提交。测试目录不是生产数据目录。

源代码中的疑似秘密扫描只是轻量辅助。依赖漏洞、许可证、镜像、完整安全测试、性能和黄金集门禁在TASK-0012/0013加入发布验收，当前绿色结果不代表这些项目已经通过。

