# TASK-0005 验证记录

任务范围：安全接入、隔离解析、原文定位、质量复检和人工上下文确认。关联 FR-002/003、SEC-003/004；以下为局部验收，不将 AC-001/002 或生产安全总体标为完成。

## 本地实证

2026-10-13，Windows、Python 3.12.14、用户安装的 PowerShell 7.6.6、Docker Linux Engine 29.2.1。

- `scripts/check_parser_sandbox.py` 实际通过：UID65532、只读根目录、断网、无 capabilities、no-new-privileges、不可执行 tmpfs、512MiB 内存、32 PID 限制。镜像基于固定 Python 摘要，不挂载宿主目录或 Docker socket，不传业务秘密。
- `scripts/check_ingestion_containers.py` 实际通过：真实 MinIO/S3、ClamAV 新鲜病毒库、合成 EICAR 检出、PDF/DOCX/PNG 上传、真实隔离解析和 Tesseract OCR、202/持久作业、人工上下文确认、鉴权下载字节一致、跨租户404、主动内容PDF拒绝、日志无运行时秘密。测试后仅自己的服务和容器已清理。
- `scripts/check_postgres.py` 在独立临时 PostgreSQL16 实际通过：增量升级/重复升级/ORM一致、受限角色API上传、作业RLS隔离、租户复合FK、并发幂等/版本更新、追加触发器、上下文清除、超级用户运行拒绝、空库降级再升级。测试容器已清理。
- 修复后完整 verify.ps1 通过：185项测试、0失败/0错误/0跳过，Mypy检查41个源文件，Ruff/契约/State漂移检查通过；真实HTTP健康200/404和请求编号、登录/项目版本/登出撤销均通过。一个pypdf 6.x合成主动内容测试使用弃用API的警告，不是失败或跳过，依赖已锁定在7以下。
- 首轮源码d137acf0fe37e24e407c5715cf1b2c48e9f191f6，CI运行38421983074的S3验证镜像拉取失败（minio/minio公共镜像不可获取），未通过。已改为固定官方源码归档与Go镜像摘要构建真实MinIO，保留许可证，不跳过真实S3检查。修正后的远程CI待推送独立核验。
- 补充真实扫描PDF：PDFium渲染与Tesseract识别成功，保留原始页1与PDF点坐标；文字PDF、DOCX、PNG及扫描PDF均完成HTTP→S3→扫描→解析→人工确认→下载一致流程。

新增租约测试曾发现 SQLite 时间类型导致 ORM 在 Python 中比较时区不同的时间而报错。已改由数据库执行租约条件、fetch 同步 ORM；保留重复领取/接管后旧 Worker 不得发布的回归测试，最终门禁复验。

## 局部验收证据

| 检查 | 可复现文件和范围 |
|---|---|
| TASK0005-001 非法格式/超限拒绝 | tests/test_ingestion.py 的 invalid_upload、malicious_docx、unsafe_pdf、raw_upload_body_limit；API不解压解析文件 |
| 强制扫描和不可绕过拒绝 | scan_failure、worker_rechecks 测试；真实容器脚本扫描干净与恶意合成输入 |
| 解析受控环境 | Dockerfile.parser、ingestion/sandbox.py、check_parser_sandbox.py 实际系统探针；超时与有界输入输出 |
| Worker 持久作业安全 | 租约重复领取、接管、提交者处理前/发布前撤权、哈希篡改、最多三次失败；文档与作业同事务 |
| TASK0005-002 原文定位 | native_pdf、docx_preserves、docx_footer 测试；真实PDF/DOCX/PNG片段哈希和定位验证 |
| 低质量不能静默继续 | 空OCR页/字体映射损坏、Word图片占位、人工修正后重新门禁、未确认上下文不能ready |
| 人工修订与版本控制 | 生命周期/quality correction 测试，保留automatic、追加effective和上下文快照，过期版本409 |
| 权限与存储 | reviewer写/其他角色读、跨租户404、原始附件复验哈希；真实S3私有桶和日志秘密扫描 |
| 契约闭合 | 生成Schema漂移检查、结果/错误互斥、表格索引必填、未知字段与坏哈希反例 |

## 交付边界

Word 内嵌图片当前保留定位并要求人工转录，不声称自动识别完成。DOCX 外部关系采用严格拒绝策略，包含外部超链接。扫描质量阈值不是招标合法性结论；复杂中文版面准确率和正式业务黄金样本另行评估。本任务没有审查或修改用户的真实招标文件、法规和Word。

单元测试替身与真实服务检查分开记录。当前 Worker 是可执行的单作业处理器和持久化作业表，持续调度/Redis/服务管理、保留期、备份、TLS、全套漏洞与许可证门禁按后续任务实现。LangGraph审查、法规检索、模型分析、报告和界面尚未实现。

启动、配置、状态、角色、升级和有损回滚要求见 secure-ingestion-start.md。API 不自动建表；生产 API/Worker 使用受限数据库身份，解析器没有存储/数据库秘密。
