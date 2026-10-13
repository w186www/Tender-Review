# 部署架构

开发环境优先使用 Docker Compose；验收环境与生产保持相同服务边界。生产可部署到 Kubernetes 或等效容器平台。

API、Worker、OCR Worker 独立扩缩容。PostgreSQL、Redis 和对象存储优先使用高可用托管服务。部署必须包含数据库向前兼容迁移、健康检查、灰度、可回滚镜像、备份验证和告警。

环境分为 `development`、`test`、`staging`、`production`。禁止将生产密钥或未脱敏数据复制到低环境。

