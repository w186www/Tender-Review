# 给另一软件中DeepSeek的启动提示词

请打开仓库 D:\自由项目\招标审核\bidding-compliance-agent；如果这是另一台电脑，请使用该仓库的本地checkout。远程仓库为 https://github.com/w186www/Tender-Review.git 。

先读取AGENTS.md、PROJECT_STATE.md、docs/index.md、docs/development/multi-model-workflow.md、tasks/active/TASK-0006-legal-retrieval.yaml和tasks/dispatch/TASK-0006.md，以及派工单引用资料。检查当前分支、HEAD SHA和未提交改动，遇到其他人正在写入时停止写入并报告。

领取TASK-0006当前discovery阶段，登记负责人、实际base SHA和分支，将正式任务设in_progress。按照派工单做法规资料盘点、契约草案、实施设计和验收样本计划；此阶段只写指定工程文档，不修改业务代码、正式契约、原始法规或Word。不凭记忆认定法规现行有效；明确区分已有来源、核验结果与待核实资料。

把结果写到docs/development/TASK-0006-design.md和tasks/handoffs/TASK-0006.md。运行完整./scripts/verify.ps1；失败应修复本阶段造成的问题，环境导致未执行则如实记录，不宣称通过。提交后交接单记录确切方案提交SHA和变更范围，将派工阶段设design_review，保持TASK in_progress。停止写入，等待仓库内指定设计审查者的审定记录；不能自称审查通过或把任务归档。

不用携带其他聊天记录。若派工单已进入下一阶段，按其最新阶段执行；实施前必须存在绑定确切方案版本的设计审查通过记录。只输出实际完成、文件、提交、验证与待审查事项，不将计划冒充实现。
