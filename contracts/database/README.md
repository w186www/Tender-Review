# 数据库契约与迁移规则

迁移文件进入 `contracts/database/migrations/`，命名为 `YYYYMMDDHHMM_<description>`。迁移必须可审查、向前兼容，并写清升级、数据回填和回滚策略。

核心表计划：tenant、user、role、project、document、document_section、review_task、graph_run、finding、evidence、human_review、report、rule_version、legal_source_version、model_call、audit_event。

所有业务表包含 `tenant_id`；外键、唯一键和查询索引必须包含租户边界。软删除不能代替数据保留策略。审计事件采用追加写入，业务更新不得覆盖历史证据。

