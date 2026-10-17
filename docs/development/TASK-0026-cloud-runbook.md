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
git clone --branch work/TASK-0026 --single-branch \
  https://github.com/w186www/Tender-Review.git /opt/tender-review
cd /opt/tender-review

./deploy/bootstrap.sh init
```

> **必须用 `--branch work/TASK-0026 --single-branch` 克隆。** 不要先克隆默认分支再
> `git checkout work/TASK-0026`：分支切换**不会**重新按属性重写已检出的文件，
> 而 `knowledge/legal/**/*.txt` 由 `.gitattributes` 固定为 CRLF（清单里的哈希是在 CRLF 文件上
> 记录的）。先克隆 `main` 会留下 LF 字节，法规库 86 个制品的哈希全部不匹配，
> 表现为部署后期一个难以定位的 `422`。`bootstrap.sh` 现在会在构建镜像前直接拦下这种情况
> 并给出修复命令。

`init` 依次完成，每一步都可重复执行：

1. 生成 `deploy/.env`（随机密码、签名密钥、MinIO 凭据；文件权限 600，且已在 `.gitignore` 里）。
2. 校验法规库换行与清单一致。
3. 构建**隔离 parser 镜像**，把 `docker image inspect` 得到的固定镜像 ID 写入 `PARSER_IMAGE`。
4. 构建 api 与 web 镜像。
5. 拉起 PostgreSQL、MinIO、ClamAV。
6. 执行 `deploy/demo_init.py storage`：跑迁移 → 创建**非超级用户、NOBYPASSRLS** 的应用角色并授权 →
   建租户与账号 → 建对象桶 → 等待 ClamAV 病毒库可用。
7. 拉起 api、worker、nginx，再执行 `deploy/demo_init.py legal`：
   通过真实鉴权 API 发布初始法规快照。
8. 打印账号名与访问地址（**不打印密码**）。

访问地址默认为 `http://127.0.0.1/`（`HTTP_BIND` + `HTTP_PORT`），**不对公网开放**。

## 五、安全组与访问

**默认部署不会对公网开放任何端口。** nginx 在基础 compose 里只绑定 `127.0.0.1`
（`HTTP_BIND`），因此登录页在 HTTPS 与访问保护就绪前不可能被外网访问。
需要外网访问时启用第五节之外的 TLS 覆盖层，它才会发布 80/443。

| 端口 | 用途 | 建议 |
|---|---|---|
| 22 | SSH（或 Workbench） | 仅放行你的出口 IP |
| 80 | HTTP | 仅用于申请证书与跳转；TLS 覆盖层会发布它 |
| 443 | HTTPS | 对面试官开放（由 TLS 覆盖层发布） |
| 5432 / 9000 / 3310 / 8000 | 数据库、对象存储、杀毒、API | **一律不放行**；compose 也未发布这些端口 |

## 六、HTTPS（Let's Encrypt 公网 IP 证书）

本部署用 **IP 地址证书**对外提供服务（无域名）。与域名证书的关键差别：

| 事项 | IP 证书的事实 |
|---|---|
| Profile | 只能用 **`shortlived`**（唯一接受 IP 标识符的 profile） |
| 有效期 | **160 小时（约 6 天）** |
| 验证 | 仅 `http-01` / `tls-alpn-01`；**无 DNS、无 CAA 检查** |
| 配额 | 同一 IP **每 7 天 5 张**；每 IP 每小时 5 次验证失败 |
| 客户端 | 系统 apt 的 certbot 1.21 **不支持**，用官方镜像 `certbot/certbot:v5.8.0` |

因为证书只有 6 天，**自动化续期是必需项**。续期阈值设为 2 天 → 约 1.5 张/周，
低于 5 张/周的配额；每天无条件续期则会直接耗尽配额。

### 日常操作

```bash
cd /opt/tender-review
./deploy/certbot.sh status         # 有效期、剩余小时、告警状态
./deploy/certbot.sh renew          # 检查并在到期前续期（定时器执行的就是它）
./deploy/certbot.sh check-expiry   # 剩余不足 48 小时则退出码非零并写标记
```

**定时器**（已安装并启用）：

| 单元 | 频率 | 作用 |
|---|---|---|
| `tender-certbot-renew.timer` | 每天 00:00 / 12:00（±1 小时） | 阈值门控的续期检查 |
| `tender-certbot-expiry.timer` | 每天 09:30 | 独立到期守护 |

告警途径：**没有配置任何外部通知渠道**（无邮件/短信/Webhook）。当前落地为
`systemctl --failed`、`journalctl -u tender-certbot-renew -u tender-certbot-expiry`，
以及 `certbot/EXPIRING` 标记文件（剩余不足 48 小时时生成）。
需要邮件或群机器人通知，请提供发信方式后再接。

### 证书存放与部署

- ACME 状态（账户、archive、续期配置）：`./certbot/`（宿主持久化，容器重建不丢）
- **对外服务的证书**：`./certs/`，由脚本用 `cp -L` 解引用复制成**实体文件**
  （certbot 的 `live/` 是符号链接，直接挂载会在容器内悬空）
- 私钥权限 600，且 `certs/`、`certbot/`、`acme-webroot/` 均已在 `.gitignore` 中

### 首次签发与切换（已完成，供重建时参考）

```bash
# 1) 引导：仅 ACME 的 HTTP 配置（80 端口只提供挑战路径，其余 503）
sed -i 's|^NGINX_CONF=.*|NGINX_CONF=nginx-acme.conf|' deploy/.env
docker compose --env-file deploy/.env -f docker-compose.demo.yml \
  -f deploy/docker-compose.tls.yml up -d nginx

# 2) staging 演练 → 正式签发（staging 必须先通过，避免消耗生产配额）
./deploy/certbot.sh issue-staging
./deploy/certbot.sh issue

# 3) 切到 HTTPS 配置（80 端口保留挑战路径 + 301 跳转，443 提供受信任 HTTPS）
sed -i 's|^NGINX_CONF=.*|NGINX_CONF=nginx-demo-tls.conf|' deploy/.env
docker compose --env-file deploy/.env -f docker-compose.demo.yml \
  -f deploy/docker-compose.tls.yml up -d nginx
```

> **不要**手写 `renew_before_expiry` 到续期配置文件末尾：`webroot_path` 是逗号结尾的列表，
> 追加的行会被解析成第二个 webroot，续期会以 `No such file or directory: '2 days/.well-known'` 失败。
> 脚本已改为插入到 `[renewalparams]` 标题正下方。

### 安全组

| 端口 | 用途 | 状态 |
|---|---|---|
| 22 | SSH | 建议收紧到你的出口 IP |
| 80 | ACME `http-01`，续期**长期需要**；仅提供挑战路径与 301 跳转 | 已放行 |
| 443 | HTTPS 服务 | 需放行 |
| 5432/9000/3310/8000 | 数据库、对象存储、杀毒、API | **禁止放行** |



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
