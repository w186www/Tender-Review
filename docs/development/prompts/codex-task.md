# 单Codex接手提示词

接手仓库D:\自由项目\招标审核\bidding-compliance-agent。
先读AGENTS.md、PROJECT_STATE.md、docs/index.md、docs/development/development-workflow.md及当前正式TASK和必要引用。核对实际分支、HEAD与未提交内容。

由当前Codex直接完成必要设计、契约、实现、测试、排错、自检和任务收尾，保留已有成果并依据验收解决已知问题。用户未要求时不创建其他模型/软件/代理接力或审批循环。自检如实标自检。

过程文档用Quick，模块代码用Focused指定相关测试；最终代码候选Full与必要专项。完整通过后仅归档或更新记录，核对差异并Quick，引用实际源码证据，无需再全测。代码/契约/数据/配置/依赖/测试/脚本变化，或新失败/疑点才重新完整验收。

当前先收尾TASK-0017，再继续TASK-0006。两者均in_progress。接手先读两份任务文件及docs/development/TASK-0017-validation.md：已推送源码0016b306550f341f514f2d35a62c2385e968f612，本地Full277项通过；远程运行https://github.com/w186www/Tender-Review/actions/runs/38446832736 最终failure：baseline/ingestion成功，postgres/verify-required失败。已取得日志并定位旧42份法规CRLF哈希与Linux LF检出不一致；检出规则修复后84项Focused及真实PostgreSQL16通过，最终Full与新源码远程CI待最新记录核对。不先盲目重复全测；需要环境审批时遵守审批。状态记录可能存在未提交更新，保留它们。

既有检索实现和D01–D07等问题不因流程撤销自动通过。按实际问题继续处理；只有局部验收满足、完整代码门禁及必要专项真实通过才归档，更新PROJECT_STATE和CHANGELOG。不要将未收尾TASK-0006合入main，不启动后续任务。
