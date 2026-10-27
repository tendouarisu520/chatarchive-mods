# ChatArchive 模组分享站

独立的 Django 模组分享站，使用邮箱验证码注册机制，提供素材/预设投稿、管理员审核、账户封禁、超级管理员任免和每次鉴权的私有下载。账号、数据、Cookie、配置与部署均独立。

素材区支持 ZIP、7Z、RAR 和 ChatArchive CAPK（KPAC v1）文件；CAPK 校验包结构但不解包或执行，审核通过后原样下载。预设区仍使用文本格式。

限制：单文件 50,000,000 字节；每账户每天 5 次成功上传（两区合计，北京时间零点重置），替换文件计一次。私有文件初始总容量 20,000,000,000 字节。素材支持 ZIP/7Z/RAR；预设支持 TXT/JSON/JSONL/YAML/YML/TOML/INI/CFG/XML/MD/CSV。服务器不解压或执行上传内容。

## 本机开发

在仓库根目录使用 Python 3.12，Windows PowerShell 示例：

```powershell
python -m venv .runtime/modshare/venv
.runtime/modshare/venv/Scripts/python.exe -m pip install -r modshare/requirements.txt
.runtime/modshare/venv/Scripts/python.exe modshare/manage.py migrate
.runtime/modshare/venv/Scripts/python.exe modshare/manage.py runserver 127.0.0.1:3310
```

打开 `http://127.0.0.1:3310/`。默认数据在 `.runtime/modshare/data/`，默认邮箱为仅开发使用的内存后端。真实 SMTP 使用 `MOD_CONFIG_FILE` 指向独立私有 JSON，字段见 `deploy/config.example.json`。凭据不得写进源码或示例。

```powershell
.runtime/modshare/venv/Scripts/python.exe modshare/manage.py test community.tests -v 2
.runtime/modshare/venv/Scripts/python.exe modshare/manage.py check
node --check modshare/static/modshare/app.js
```

## 独立部署目录

下列路径是安装脚本的通用约定。为自己的部署准备独立域名、TLS 证书、SMTP 与 Turnstile 配置。生产密钥和配置存放在仓库之外。

| 路径 | 用途 / 权限 |
| --- | --- |
| `/opt/modshare/app/` | root 所有的只读源码 |
| `/opt/modshare/venv/` | root 所有的独立 Python 环境；服务用户可读/执行、不可写 |
| `/opt/modshare/data/modshare.db` | 独立 SQLite 数据库 |
| `/opt/modshare/data/files/` | 私有 `.blob` 文件 |
| `/opt/modshare/data/tmp/` | 私有临时上传 |
| `/opt/modshare/data/static/` | collectstatic 输出 |
| `/opt/modshare/secrets/config.json` | root:modshare 0640，父目录 0750 |
| `/opt/modshare/secrets/runtime.env` | 独立运行参数，空 URL 前缀，MOD_X_ACCEL=1 |
| `/opt/modshare/backups/` | root:root 0700；含账号、文件与 SMTP 秘密 |

服务名 `modshare.service`，系统用户和组均为 `modshare`。Gunicorn 2 个 worker、每个 2 线程，SQLite 使用 WAL 和 IMMEDIATE 事务。systemd 仅允许写数据目录，内存上限 768MB、CPU 150%。Nginx 请求上限 51m 给 multipart 留余量，文件字节数由应用限制为 50,000,000。

## 安装或更新

Ubuntu 需要 `python3`、`python3-venv`、`rsync`、`acl` 和 systemd。操作员可用 `apt-get install python3-venv rsync acl` 安装缺失依赖。代码包包含 `manage.py`、锁定的 `requirements.txt` 与 `deploy/`，暂存于独立目录，例如 `/opt/modshare-stage`；不要打包运行数据、配置秘密或虚拟环境。

先在受保护路径准备 JSON 配置：随机至少 32 字符的 secret_key、allowed_hosts、空 script_name、secure 和 smtp（host、port、username、password、from、ssl）。SSH 预览只能使用 `secure: false` 和 `allowed_hosts: ["127.0.0.1", "localhost"]`，且两个服务都绑定 loopback。SMTP 使用 SSL；发件地址需已获服务商验证。已有配置未传第二参数时会保留。

安装可能超过一分钟，使用后台任务和受保护日志：

```bash
install -d -m 0700 /opt/modshare-install-logs
log="/opt/modshare-install-logs/install-$(date -u +%Y%m%dT%H%M%SZ).log"
nohup bash /opt/modshare-stage/deploy/install.sh /opt/modshare-stage /root/modshare-config.json >"$log" 2>&1 &
pid=$!
printf 'PID=%s\nLOG=%s\nOUTPUT=/opt/modshare\n' "$pid" "$log"
```

短窗口检查 `ps -p "$pid" -o pid,etime,time,rss,args`、`stat "$log"`、`tail -n 30 "$log"`。日志长时间不更新时检查 pip 网络重试、子进程与磁盘。仍在运行的任务须明确报告其进度。失败后新服务保持停止以便诊断，使用升级前备份及对应代码包恢复。

安装脚本仅备份、安装、迁移和启动独立的新站服务，并设置私有文件 ACL。它不会编辑 `/etc/nginx` 或任何既有网站配置。Nginx 预览模板和未来 TLS 模板均保留于 `/opt/modshare/app/deploy/`，由操作员审核后单独启用。

安装时 `umask 077` 保护秘密；pip 完成后仅对 root-owned venv 执行 `chmod -R a+rX,go-w`，并以 modshare 用户实际运行 Python 导入 Django/Gunicorn、检查环境不可写。该权限调整不涉及 data 或 secrets。已有以 0700 创建的 venv 也会修复。Linux 最小权限回归可运行 `bash /opt/modshare/app/deploy/test-venv-permissions.sh`；该测试只操作临时目录，不改真实数据。

### SSH 隧道预览（仅供开发）

正式环境已启用secure=true，请访问正式HTTPS网址；以下secure=false预览流程不能用于公网。

操作员确认 `deploy/nginx-preview.conf` 只监听 `127.0.0.1:3311` 后，将其链接为新的 `/etc/nginx/conf.d/chatarchive-preview.conf`（该路径如已存在先核查，不能覆盖未知配置）。执行 `nginx -t`，通过后优雅 reload。现有网站 vhost 和证书无需修改。

在本机开启专用 SSH 隧道，再访问 `http://127.0.0.1:3311/`：

```powershell
ssh -N -L 127.0.0.1:3311:127.0.0.1:3311 root@YOUR_SERVER_IP
```

隧道连接保持期间浏览器可访问预览；结束预览时关闭这条专用隧道。不要把预览端口改为公网监听，也不要把 secure=false 配置用于公开网站。预览 Nginx 提供静态文件，代理鉴权请求到 Gunicorn；私有文件仍使用 X-Accel internal 下载，直接访问 `/_modshare_private/` 应为 404。

### 文件 ACL 与 owner

默认 Nginx worker 用户 `www-data`；不同用户需在安装时设置 `NGINX_USER` 或运行 `NGINX_USER=实际用户 bash /opt/modshare/app/deploy/install-file-access.sh`。ACL 只允许其穿越 data 并读取 files/static，不能读取数据库或配置。最终文件在 files 直接建立并 chmod 0640，以启用继承的 Nginx ACL，临时文件保持私有。

```bash
runuser -u www-data -- test ! -r /opt/modshare/data/modshare.db
runuser -u www-data -- test ! -r /opt/modshare/secrets/config.json
getfacl /opt/modshare/data /opt/modshare/data/files
systemctl is-active modshare.service
ss -ltnp | grep -E '127\.0\.0\.1:(3310|3311)'
curl -I http://127.0.0.1:3311/
curl -I http://127.0.0.1:3311/_modshare_private/example.blob
```

首次 owner 使用独立管理命令，应用账户将随机凭据写入受保护临时文件，root 移至站主专用路径。不要打印凭据或将密码放进命令参数/日志：

```bash
cd /opt/modshare/app
export MOD_CONFIG_FILE=/opt/modshare/secrets/config.json
export MOD_DATA_DIR=/opt/modshare/data MOD_SCRIPT_NAME= MOD_DEBUG=0
runuser -u modshare -- /opt/modshare/venv/bin/python manage.py bootstrap_owner --email OWNER_EMAIL --credentials /opt/modshare/data/tmp/owner-credentials.txt >/dev/null
install -m 0600 -o root -g root /opt/modshare/data/tmp/owner-credentials.txt /opt/modshare/secrets/owner-credentials.txt
rm -- /opt/modshare/data/tmp/owner-credentials.txt
```

站主安全取走凭据并登录后修改密码；普通管理员用独立邮箱账户，由 owner 任命。

## 验收和运维

验收包含真实 SMTP 注册、上传、owner 审核、另一用户下载，以及封禁已有会话后拒绝新下载、Range 请求和越权 private URL。同时检查同主机既有网站健康接口和服务正常。

```bash
systemctl status modshare.service --no-pager
journalctl -u modshare.service -n 80 --no-pager
du -sh /opt/modshare/data/files /opt/modshare/backups
df -h /opt/modshare
```

20GB 限额不预留备份、临时区和系统空间。备份前核对空间；不要手工删除投稿记录引用的文件。禁止日志记录验证码、SMTP 密码、请求正文或 owner 密码。

## 备份与恢复

`deploy/backup.sh` 仅暂停 `modshare.service`，使用 SQLite online backup 复制数据库，再复制私有文件与秘密配置，生成 SHA-256/字节数 manifest 并校验完整性，退出时恢复原先运行的新站服务。备份期间新站短暂不可用；文件接近 20GB 时可能较久，使用后台任务：

```bash
log="/opt/modshare-install-logs/backup-$(date -u +%Y%m%dT%H%M%SZ).log"
nohup bash /opt/modshare/app/deploy/backup.sh /opt/modshare/backups >"$log" 2>&1 &
printf 'PID=%s\nLOG=%s\nOUTPUT=/opt/modshare/backups\n' "$!" "$log"
```

完成后日志应包含 `Verified snapshot`，并确认服务恢复 active。快照包含 SMTP 秘密，保持 root-only 并加密复制到异地。源码包另行保留；静态文件可 collectstatic，未完成上传不备份。保留策略由站主决定，脚本不自动删除历史快照。

恢复先取对应版本代码包并验证快照。以下只针对固定新站目录；`SNAPSHOT` 替换为已验证快照绝对路径。移动前确认目标确为 `/opt/modshare/data` 且不是符号链接：

```bash
SNAPSHOT=/opt/modshare/backups/具体快照目录
python3 /opt/modshare/app/deploy/backup_snapshot.py --verify "$SNAPSHOT"
systemctl stop modshare.service
mv -- /opt/modshare/data "/opt/modshare/data-before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0750 -o modshare -g modshare /opt/modshare/data
cp -- "$SNAPSHOT/modshare.db" /opt/modshare/data/modshare.db
cp -a -- "$SNAPSHOT/files" /opt/modshare/data/files
chown -R modshare:modshare /opt/modshare/data
chmod 0600 /opt/modshare/data/modshare.db
find /opt/modshare/data/files -type f -exec chmod 0640 {} +
find /opt/modshare/data/files -type d -exec chmod 0750 {} +
install -d -m 0750 -o modshare -g modshare /opt/modshare/data/tmp /opt/modshare/data/static
install -m 0640 -o root -g modshare "$SNAPSHOT/config.json" /opt/modshare/secrets/config.json
if [ -f "$SNAPSHOT/runtime.env" ]; then install -m 0640 -o root -g modshare "$SNAPSHOT/runtime.env" /opt/modshare/secrets/runtime.env; fi
```

用对应源码包再执行 install.sh，完成迁移、静态收集、ACL 和启动。不要将旧 `modshare.db-wal`/`modshare.db-shm` 搭配快照数据库恢复。恢复到旧版本前先还原相应源码，不能假设新版代码兼容旧库。验收后再处理保留的失败状态目录。

## 正式域名与 HTTPS

注册独立域名并配置 DNS/证书后，才启用 `deploy/nginx-vhost.conf`。模板中的 `__MODSHARE_DOMAIN__` 必须全部替换为真实新域名，证书路径必须实际存在；仓库文件是部署模板。

操作员建立新的独立 vhost 和证书，配置文件 allowed_hosts 改为实际新域名、secure 改 true、script_name 保持空字符串，runtime.env 保持 `MOD_SCRIPT_NAME=` 和 `MOD_X_ACCEL=1`。先验证 `nginx -t`，再 reload Nginx 并重启 modshare.service。检查 HTTPS 跳转、安全 Cookie、CSRF、静态文件、邮件注册与私有下载。正式 vhost 使用 `/static/` 和 internal `/_modshare_private/`，应用位于域名根路径。

切换时若保留 SSH 预览，secure=true 会使 HTTP 预览自动跳转 HTTPS；可在独立 TLS 域名验收通过后移除该预览配置。任何域名/协议切换都要重新核对 Cookie 和登录行为。
# 社区榜单与素材例图

素材及预设投稿均可附一张 2MB 以内的 PNG/JPG/WebP 静态例图，审核后用于列表与详情。例图与资源同次上传仅扣一次每日次数。

`/rankings/` 提供下载/喜爱的日、周、月、总榜及分类筛选。北京时间自然周期；登录用户公开版本完整下载每日去重，喜爱可取消。下架作品不参与，被封禁用户的互动不计。下载开始统计，不追溯旧下载日志。

管理员直接在详情页管理作品与待审修订。验证脚本失败可重试加载；不降低服务端验证要求，客户端错误码和脱敏日志用于排查。

喜爱和差评为互斥评价，可取消、切换。列表与详情显示数量、好评率与五档综合标签（95/70/40/20% 分界）；无评价显示暂无评价，少于10条注明评价较少。取消评价和被封禁用户不计入比例。首次差评后改为喜爱才建立首次喜爱时间，已有喜爱日期由迁移保留。

移动列表使用640边WebP派生封面，详情保留原图；派生缓存位于data/tmp/preview-cards，可重建、约128MB。每次读取依然检查访问权限，不改原Blob或用户上传额度。触摸/小屏停用持续装饰动画及模糊，文本资源通过独立vhost压缩。

访问优化：公开列表/榜单与账号状态并行加载，账号请求8秒超时不会阻塞公开列表。已发布例图采用private/no-cache及ETag条件请求，每次先检查封禁、发布和修订权限；待审例图仍no-store。派生缓存丢失或被并发清理时回退原图并改用原图ETag。

网页下载按钮先以登录会话和CSRF调用 `POST /api/downloads/<revision>/ticket/`（JSON `review`布尔值），获得15分钟、绑定单作品/用户密码鉴权hash/用途的签名链接，供无网页Cookie的原生下载器使用。每次下载仍检查用户存在、封禁、作品状态、当前审阅权限；密码变更立即失效。凭证允许Range重复请求，登出不会立即撤回已签发的15分钟链接；需要新链接时回作品页点击下载。原Cookie下载仍兼容，无凭证且无会话继续401。禁止将凭证当作永久公开文件URL。

生产部署建议启用 HTTP/2，转发应用的条件缓存策略；`nginx-log-privacy.conf`在http上下文定义去查询参数的访问日志格式，只有此站vhost使用。私有文件internal location显式no-referrer、no-store。原有error日志可能包含异常请求URL，应保持受限访问；短时凭证不得复制到公开日志或文档。模板文件与真实vhost分别保存，部署前验证Nginx版本语法。
