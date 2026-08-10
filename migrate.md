# BDC 英语词汇学习系统 — 远程部署手册

> **日期**: 2026-08-05
> **目标服务器**: Oracle Linux 9 (ARM64) @ `129.146.153.133`
> **源码仓库**: `https://github.com/gaojon/bdc`

---

## 目录

1. [环境信息](#1-环境信息)
2. [初始环境准备](#2-初始环境准备)
3. [应用部署](#3-应用部署)
4. [运维管理](#4-运维管理)
5. [更新部署](#5-更新部署)

---

## 1. 环境信息

| 项目 | 值 |
|------|-----|
| 服务器 IP | `129.146.153.133` |
| SSH 密钥 | `/home/jon/cli/cli_bdc.key` |
| SSH 用户 | `opc` |
| 应用路径 | `/home/opc/bdc/` |
| 数据库文件 | `/home/opc/bdc/db.sqlite3` |
| 配置文件 | `/home/opc/bdc/config/app_config.json` |
| 对外访问 | `https://bdc8.cc.cd`（HTTP 自动跳转 HTTPS） |
| 反向代理 | nginx（80/443，TLS 终止；证书 Let's Encrypt 自动续期） |
| WSGI 服务器 | Gunicorn（2 workers，监听 `127.0.0.1:8000`，仅内网） |
| 启动脚本 | `/home/opc/bdc/start.sh`（含环境变量，gitignored） |
| 进程管理 | PID 文件 `/home/opc/bdc/gunicorn.pid` |

### 管理员凭据

| 字段 | 值 |
|------|-----|
| 用户名 | `admin` |
| 密码 | `admin123456` |

---

## 2. 初始环境准备

### 2.1 SSH 连接

```bash
cd /home/jon/cli
ssh -i ./cli_bdc.key opc@129.146.153.133
```

### 2.2 安装系统依赖

```bash
# Git
sudo dnf install -y git

# Python 3.12 + pip
sudo dnf install -y python3.12 python3.12-pip python3.12-devel
```

### 2.3 克隆代码仓库

```bash
cd /home/opc
git clone https://github.com/gaojon/bdc.git
```

### 2.3.1 ⚠️ 上传配置文件（必须）

`config/app_config.json` 包含 API Key，已加入 `.gitignore`，不会被 git 克隆。
需要从本地手动上传：

```bash
# 在本地机器执行（替换为实际路径）
scp -i /home/jon/cli/cli_bdc.key \
    /home/jon/bdc/config/app_config.json \
    opc@129.146.153.133:/home/opc/bdc/config/app_config.json
```

> 如果跳过此步骤，应用将报 `FileNotFoundError: app_config.json` 错误。

### 2.4 安装 Python 依赖

```bash
cd /home/opc/bdc
python3.12 -m pip install -r requirements.txt
```

### 2.5 数据库初始化

```bash
# 数据库迁移
python3.12 manage.py migrate

# 收集静态文件（CSS / JS）
python3.12 manage.py collectstatic --noinput

# 创建管理员账户
python3.12 manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_superuser('admin', password='admin123456')
"

# 预置兴趣类别（13 个）
python3.12 manage.py seed_interests
```

### 2.6 配置 nginx / HTTPS / 防火墙

> 对外架构：`nginx`（root 监听 80/443，TLS 终止）→ 反代 → `gunicorn`（`127.0.0.1:8000`，仅内网）。

```bash
# 1) 安装 nginx 与 certbot（EPEL 走 Oracle 自带仓库）
sudo dnf install -y nginx
sudo dnf config-manager --set-enabled ol9_developer_EPEL
sudo dnf install -y certbot python3-certbot-nginx

# 2) SELinux：允许 nginx 反代到内网后端端口（否则 502 Permission denied）
sudo setsebool -P httpd_can_network_connect 1

# 3) OS 防火墙：开放 80 / 443
sudo firewall-cmd --add-port=80/tcp --permanent
sudo firewall-cmd --add-port=443/tcp --permanent
sudo firewall-cmd --reload
```

> ⚠️ **OCI 控制台（VCN 安全列表）还需放行公网 443 入站**：Networking → Virtual cloud networks → 子网 → Security Lists → 默认安全列表 → Add Ingress Rules（TCP，目标端口 `443`，源 `0.0.0.0/0`）。OS 防火墙之外这层不放开，公网无法访问 HTTPS。

### 2.7 首次签发证书

```bash
# 写好 nginx vhost（/etc/nginx/conf.d/bdc8.cc.cd.conf，80 反代 127.0.0.1:8000）
# 文件若从 /tmp 移入，需刷新 SELinux 上下文：sudo restorecon /etc/nginx/conf.d/bdc8.cc.cd.conf
sudo systemctl enable --now nginx

# 签发证书（HTTP-01 走 80），自动配置 443 + HTTP→HTTPS 跳转
sudo certbot --nginx -d bdc8.cc.cd --register-unsafely-without-email --redirect
sudo systemctl enable --now certbot-renew.timer   # 自动续期
```

---

## 3. 应用部署

### 3.1 启动服务（Gunicorn 守护进程）

> 通过 `start.sh` 启动。该脚本为 **gitignored** 文件，内含 `DJANGO_SECRET_KEY`，不提交版本库；内容为 export 环境变量后启动 gunicorn：

```bash
cd /home/opc/bdc
cat > start.sh <<'SH'
#!/bin/bash
set -e
cd /home/opc/bdc
export DJANGO_DEBUG=false
export DJANGO_SECRET_KEY="<由 python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())' 生成>"
export DJANGO_ALLOWED_HOSTS="bdc8.cc.cd,localhost,127.0.0.1,129.146.153.133"
export DJANGO_BEHIND_PROXY=1
exec python3.12 -m gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --daemon \
    --access-logfile /home/opc/bdc/access.log --error-logfile /home/opc/bdc/error.log \
    --pid /home/opc/bdc/gunicorn.pid
SH
chmod +x start.sh
./start.sh
```

### 3.2 验证服务状态

```bash
# 检查进程
cat /home/opc/bdc/gunicorn.pid
ps aux | grep gunicorn
systemctl status nginx --no-pager | grep Active

# 外部访问测试（公网 HTTPS）
curl -s -o /dev/null -w "HTTP %{http_code}" https://bdc8.cc.cd/account/login/
# 预期: HTTP 200
```

### 3.3 访问地址

| 页面 | URL |
|------|-----|
| 学习主页 | `https://bdc8.cc.cd/` |
| 词库管理 | `https://bdc8.cc.cd/bank/` |
| 学习统计 | `https://bdc8.cc.cd/stats/` |
| 系统面板 | `https://bdc8.cc.cd/admin/dashboard/` |
| API 配置 | `https://bdc8.cc.cd/admin/api-config/` |
| 用户管理 | `https://bdc8.cc.cd/admin/users/` |
| Django Admin | `https://bdc8.cc.cd/admin/` |

---

## 4. 运维管理

### 4.1 停止服务

```bash
kill $(cat /home/opc/bdc/gunicorn.pid)
```

> nginx 保持运行，无需动它。

### 4.2 重启服务

```bash
kill $(cat /home/opc/bdc/gunicorn.pid)
sleep 2
cd /home/opc/bdc
./start.sh
```

### 4.3 HTTPS 证书运维

```bash
# 手动续期（通常由 certbot-renew.timer 每日自动执行）
sudo certbot renew --deploy-hook "systemctl reload nginx"

# 查看证书状态
sudo certbot certificates

# 查看续期定时器
systemctl status certbot-renew.timer
```

### 4.4 查看日志

```bash
# 访问日志
tail -f /home/opc/bdc/access.log

# 错误日志
tail -f /home/opc/bdc/error.log

# nginx 日志
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

### 4.5 数据库备份

```bash
cp /home/opc/bdc/db.sqlite3 /home/opc/bdc/backups/db_$(date +%Y%m%d_%H%M%S).sqlite3
```

也可通过 Admin → Dashboard → Download Backup 在线下载。

### 4.6 数据库恢复

```bash
cp /home/opc/bdc/backups/db_YYYYMMDD_HHMMSS.sqlite3 /home/opc/bdc/db.sqlite3
# 然后重启服务
```

### 4.7 修改 DeepSeek API 配置

两种方式：

**方式 A — 在线编辑（推荐）**：
访问 `https://bdc8.cc.cd/admin/api-config/`，在表单中修改并保存。保存后自动清除配置缓存。

**方式 B — 直接编辑文件**：
```bash
vim /home/opc/bdc/config/app_config.json
# 修改 deepseek 区块，然后重启服务
```

---

## 5. 更新部署

### 5.1 拉取最新代码并重启

```bash
cd /home/opc/bdc

# 必须先丢弃：该文件每次 gunicorn 启动都会被 learning/apps.py 重写
git checkout -- version.json

# 停止服务（nginx 保持运行，无需动）
kill $(cat gunicorn.pid) 2>/dev/null

# 拉取最新代码
git pull origin master

# 安装可能新增的依赖
python3.12 -m pip install -r requirements.txt

# 执行数据库迁移
python3.12 manage.py migrate

# 收集静态文件
python3.12 manage.py collectstatic --noinput

# 重新启动服务（start.sh 内含环境变量，gitignored，不会因 pull 丢失）
./start.sh

# 验证（走 nginx → HTTPS）
curl -s -o /dev/null -w "HTTP %{http_code}" https://bdc8.cc.cd/account/login/ --resolve bdc8.cc.cd:443:127.0.0.1
# 预期: HTTP 200
```

### 5.2 一键更新脚本

将以下内容保存为 `/home/opc/bdc/update.sh`：

```bash
#!/bin/bash
set -e

cd /home/opc/bdc

echo ">>> Discarding version.json..."
git checkout -- version.json

echo ">>> Stopping gunicorn..."
kill $(cat gunicorn.pid) 2>/dev/null || true
sleep 2

echo ">>> Pulling latest code..."
git pull origin master

echo ">>> Installing dependencies..."
python3.12 -m pip install -r requirements.txt --quiet

echo ">>> Running migrations..."
python3.12 manage.py migrate

echo ">>> Starting gunicorn via start.sh..."
./start.sh

sleep 1
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://bdc8.cc.cd/account/login/ --resolve bdc8.cc.cd:443:127.0.0.1)
if [ "$HTTP_CODE" = "200" ]; then
    echo ">>> Deploy successful! (HTTP $HTTP_CODE)"
else
    echo ">>> WARNING: Health check returned HTTP $HTTP_CODE"
fi
```

运行：

```bash
chmod +x /home/opc/bdc/update.sh
./update.sh
```

---

## 附录 A: 依赖清单

```
Django>=5.1,<6.0       # Web 框架
openai>=1.0,<2.0        # DeepSeek API 调用（兼容 OpenAI SDK）
gunicorn>=22.0          # WSGI 生产服务器
```

## 附录 B: 配置项说明（config/app_config.json）

| 配置路径 | 默认值 | 说明 |
|----------|--------|------|
| `deepseek.api_key` | `sk-xxx` | DeepSeek API 密钥 |
| `deepseek.base_url` | `https://api.deepseek.com` | API 端点 |
| `deepseek.model` | `deepseek-chat` | 模型名称 |
| `deepseek.timeout_seconds` | `120` | 请求超时（秒） |
| `article.target_word_count` | `500` | 目标文章词数 |
| `article.min_hit_words` | `25` | 最少命中词数 |
| `article.max_hit_words` | `50` | 最多命中词数 |
| `article.max_word_pool_size` | `500` | 单词池上限 |
| `limits.daily_generation_limit` | `3` | 每日生成上限 |
| `limits.article_history_retention` | `24` | 文章历史保留数 |
| `spaced_repetition.intervals` | `[1,3,7,21,60]` | SM-2 间隔（天） |
