# 目标 ECS 部署手册（阿里云 Ubuntu 22.04）

适用实例：中国香港 B、Ubuntu 22.04 64 位、2 vCPU / 8 GiB、公网 IP `47.83.132.211`。
镜像与编排的实测依据见 [TASK-0026 验证记录](TASK-0026-validation.md)；
日常运维、HTTPS、备份恢复与安全说明见 [`deploy/README-demo.md`](../../deploy/README-demo.md)。

**本文所有命令尚未在目标主机上执行过。** 本地 Docker Linux 引擎上的等价验证已完成，
但目标主机仍是"未实测"状态，首次执行后必须逐项核对。

## 一、内存预算（基于实测，不是估算）

本机空闲稳态实测合计约 **1.64 GiB**：ClamAV 964.7 MiB、API 417.8 MiB、PostgreSQL 94.9 MiB、
MinIO 89.3 MiB、worker 59.9 MiB、nginx 13.8 MiB。

8 GiB 实例足够，但仍需注意两点：

- 装配里 `--memory=3g` 是审查过的 ClamAV 硬约束，**不得下调**；峰值时其余进程要给 3 GiB 让路。
- 镜像构建（尤其 MinIO 的 Go 编译）会短暂占用较多内存与磁盘，建议先加 swap：
  `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

首轮构建需要下载约 5 GB 镜像层（含 golang 构建镜像），60 GB 磁盘足够；实际磁盘容量登录后核对。

## 二、首次连接后的只读检查

```bash
whoami
uname -a
lsb_release -a
free -h
df -h /
nproc
docker --version || echo "docker: absent"
docker compose version || echo "compose: absent"
```

确认无误后再做任何变更。

## 三、Docker 安装（若缺失）

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"   # 重新登录后生效
```

`systemctl enable --now docker` 确保重启后 Docker 自启。

## 四、部署

```bash
git clone https://github.com/w186www/Tender-Review.git
cd Tender-Review
git checkout work/TASK-0026

./deploy/bootstrap.sh init
```

`init` 会自动完成：生成 `deploy/.env` 随机密钥 → 构建隔离 parser 镜像并固化镜像 ID →
构建 api/web 镜像 → 拉起 PostgreSQL/MinIO/ClamAV → 迁移与建号建桶 → 等待病毒库 → 拉起应用 →
发布法规快照 → 打印演示账号。

首次执行时间较长（镜像构建 + ClamAV 首次下载约 250 MB 病毒库）。

## 五、安全组与访问

| 端口 | 用途 | 建议 |
|---|---|---|
| 22 | SSH（或 Workbench） | 仅放行你的出口 IP |
| 80 | HTTP | 仅用于申请证书与跳转，证书就绪后可关闭 |
| 443 | HTTPS | 对面试官开放 |
| 5432 / 9000 / 3310 / 8000 | 数据库、对象存储、杀毒、API | **一律不放行**；compose 也未发布这些端口 |

## 六、HTTPS

未启用 HTTPS 前不要把地址发给面试官：登录口令会明文传输。

1. 把域名解析到 `47.83.132.211`（香港地域无需备案）。
2. 申请证书（两种方式选一）：
   - 宿主机用 certbot：`sudo apt-get install -y certbot && sudo certbot certonly --standalone -d <域名>`
     证书落在 `/etc/letsencrypt/live/<域名>/`。
   - 阿里云数字证书服务申请后下载 Nginx 格式，手工放到同一目录。
3. 在 `deploy/.env` 中设置：
   ```
   TLS_CERT_DIR=/etc/letsencrypt/live/<域名>
   PUBLIC_BASE_URL=https://<域名>
   ```
4. 启用 TLS 覆盖层：
   ```bash
   D="docker compose --env-file deploy/.env -f docker-compose.demo.yml -f deploy/docker-compose.tls.yml"
   $D up -d nginx
   ```

## 七、部署后的业务验收

```bash
set -a; . deploy/.env; set +a
python3 deploy/verify_deployment.py --base-url https://<域名>
```

脚本会真实走完：登录 → 建项目 → 上传合成标书 → ClamAV 扫描 → 隔离解析 → 上下文确认 →
LangGraph 审查 → 风险与证据 → 人工复核 → 结果发布 → Word/PDF 下载并核对哈希。
输出 JSON 证据到 `.verification/task0026-deploy/`。

配合浏览器手工确认：登录页出现「离线确定性演示」提示、项目页文档显示"可用于审查"、
任务页显示"实际 AI 运行记录"且模式为 `offline-deterministic`（这是如实标注，不是缺陷）。

## 八、数据持久化与备份

四个卷 `tender-review-{pgdata,miniodata,clamdb,modelstate}` 在 `docker compose down` 后依然保留。
仅 `down -v` 或手工 `docker volume rm` 会删除数据。

```bash
./deploy/backup.sh /srv/backups/$(date -u +%Y%m%d)
./deploy/restore.sh /srv/backups/20261016 --verify     # 非破坏性演练
```

建议在演示前做一次 `--verify` 演练；确认可用后再考虑 `--confirm` 全量恢复路径。

## 九、Qwen 真实审查：当前不可用及其条件

当前部署为 `DEPLOY_REVIEW_MODE=offline`：全流程真实，但模型分析由确定性的协议网关产生，
页面与报告都如实标注"未调用真实 LLM"。**这不是 Mock 冒充成功，而是受授权限制的既有模式。**

要在目标主机上启用真实 Qwen，除密钥与授权外还有一个**部署层面的硬前提**：

法规检索的语料向量与查询向量都存放在本地 SQLite 缓存（`legal-vectors.sqlite3`）中，
且缓存优先（`legal/vector_index.py::embed_query`、`::build`）。历史真实运行之所以能在
`DEC-006` 的 **0 批 Embedding** 上限下完成，是因为复用了开发机上已填充的缓存。

**全新主机上没有这份缓存**，一旦启用真实检索就会立即产生 Embedding 请求；若授权额度的
Embedding 上限为 0，检索会因额度不足失败。因此新授权必须包含 Embedding 批次，
或者显式选择不挂载真实检索器（只把法规检索留在本地字符向量实现，仅语义分析走真实模型）。
后者需要在 `deploy/api_entry.py` 中按既有的可选参数组装，属于部署层选择，不需要改业务代码。

详细申请见 [DEC-007 申请草案](../decisions/DEC-007-demo-real-qwen-authorization.md)。

## 十、演示结束

```bash
D="docker compose --env-file deploy/.env -f docker-compose.demo.yml"
$D down          # 保留数据
$D down -v       # 清空演示数据
```

阿里云控制台停止或释放实例；如使用弹性公网 IP，一并释放以免继续计费。
