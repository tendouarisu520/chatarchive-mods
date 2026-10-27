# ChatArchive 模组分享站

独立的模组分享网站，基于 Django、SQLite、原生 JavaScript 与 Nginx。

## 功能

- 邮箱验证码注册、登录及密码重设；同一邮箱不能重复注册。
- 素材区支持 ZIP / 7Z / RAR / CAPK（KPAC v1）；预设区支持常见文本格式。
- 单文件最大 50,000,000 字节，每个账号每天最多成功上传 5 次；两区均可附一张最大 2 MB 的 PNG / JPG / WebP 例图。
- 投稿与修订经过管理员审核后公开；站主管理管理员权限，管理员可审核、下架和封禁。
- 喜爱与差评互斥，可取消或切换；按下载或喜爱统计日榜、周榜、月榜和总榜。
- 私有文件按当前权限鉴权；15 分钟下载授权链接兼容手机独立下载器与断点续传。
- Cloudflare Turnstile、SMTP 发信、移动端派生封面与条件缓存。

## 本地运行

需要 Python 3.12；前端测试还需要 Node.js。以下命令在仓库根目录执行：

```sh
python -m venv .venv
# Linux/macOS
.venv/bin/python -m pip install -r modshare/requirements.txt
.venv/bin/python modshare/manage.py migrate
.venv/bin/python modshare/manage.py runserver 127.0.0.1:3310
```

Windows 使用 `.venv/Scripts/python.exe` 替换 `.venv/bin/python`。

访问 http://127.0.0.1:3310/ 。默认数据写入 `.runtime/modshare/data/`，默认邮件后端为内存后端，仅用于开发，不会真实投递验证码；可在 Django shell 中检查 `django.core.mail.outbox`。本地开发密钥仅用于本机，公网部署必须配置独立随机密钥。

通过 `MOD_CONFIG_FILE` 指向仓库之外的私有 JSON，字段见 [配置示例](modshare/deploy/config.example.json)。开发时如不使用 SMTP，应省略 `smtp`；如不使用 Turnstile，将其 `enabled` 设为 `false`。真实 SMTP、Turnstile 和服务器凭据不应加入版本控制。

首次创建站主管理员：

```sh
.venv/bin/python modshare/manage.py bootstrap_owner --email owner@example.com --credentials .runtime/owner-credentials.json
```

替换为自己的邮箱；凭据文件必须保存在受保护目录，登录后修改密码。系统只允许一个站主账号；其他管理员通过站主任命。

## 测试

```sh
.venv/bin/python modshare/manage.py check
.venv/bin/python modshare/manage.py test community.tests
.venv/bin/python modshare/manage.py makemigrations --check --dry-run
node --check modshare/static/modshare/app.js
node scripts/test_modshare_boot.cjs
node scripts/test_modshare_turnstile.cjs
```

## 部署与安全

参见 [部署说明](modshare/README.md)。仓库提供通用 Nginx / systemd / 安装和备份脚本，不包含实际服务器配置、密钥、数据库、账号、日志、备份或用户投稿。

公开源码不包含用户作品的授权；用户上传的模组、素材和预设不随本仓库分发。本仓库暂未指定开源许可证。
