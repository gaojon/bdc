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
| 监听端口 | `8000` |
| WSGI 服务器 | Gunicorn（2 workers） |
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

### 2.4 安装 Python 依赖

```bash
cd /home/opc/bdc
python3.12 -m pip install -r requirements.txt
```

### 2.5 数据库初始化

```bash
# 数据库迁移
python3.12 manage.py migrate

# 创建管理员账户
python3.12 manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_superuser('admin', password='admin123456')
"

# 预置兴趣类别（13 个）
python3.12 manage.py seed_interests
```

### 2.6 配置防火墙

```bash
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --reload
```

---

## 3. 应用部署

### 3.1 启动服务（Gunicorn 守护进程）

```bash
cd /home/opc/bdc
python3.12 -m gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --daemon \
    --access-logfile /home/opc/bdc/access.log \
    --error-logfile /home/opc/bdc/error.log \
    --pid /home/opc/bdc/gunicorn.pid
```

### 3.2 验证服务状态

```bash
# 检查进程
cat /home/opc/bdc/gunicorn.pid
ps aux | grep gunicorn

# 外部访问测试
curl -s -o /dev/null -w "HTTP %{http_code}" http://129.146.153.133:8000/account/login/
# 预期: HTTP 200
```

### 3.3 访问地址

| 页面 | URL |
|------|-----|
| 学习主页 | `http://129.146.153.133:8000/` |
| 词库管理 | `http://129.146.153.133:8000/bank/` |
| 学习统计 | `http://129.146.153.133:8000/stats/` |
| 系统面板 | `http://129.146.153.133:8000/admin/dashboard/` |
| API 配置 | `http://129.146.153.133:8000/admin/api-config/` |
| 用户管理 | `http://129.146.153.133:8000/admin/users/` |
| Django Admin | `http://129.146.153.133:8000/admin/` |

---

## 4. 运维管理

### 4.1 停止服务

```bash
kill $(cat /home/opc/bdc/gunicorn.pid)
```

### 4.2 重启服务

```bash
kill $(cat /home/opc/bdc/gunicorn.pid)
sleep 2
cd /home/opc/bdc
python3.12 -m gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 --workers 2 --daemon \
    --access-logfile /home/opc/bdc/access.log \
    --error-logfile /home/opc/bdc/error.log \
    --pid /home/opc/bdc/gunicorn.pid
```

### 4.3 查看日志

```bash
# 访问日志
tail -f /home/opc/bdc/access.log

# 错误日志
tail -f /home/opc/bdc/error.log
```

### 4.4 数据库备份

```bash
cp /home/opc/bdc/db.sqlite3 /home/opc/bdc/backups/db_$(date +%Y%m%d_%H%M%S).sqlite3
```

也可通过 Admin → Dashboard → Download Backup 在线下载。

### 4.5 数据库恢复

```bash
cp /home/opc/bdc/backups/db_YYYYMMDD_HHMMSS.sqlite3 /home/opc/bdc/db.sqlite3
# 然后重启服务
```

### 4.6 修改 DeepSeek API 配置

两种方式：

**方式 A — 在线编辑（推荐）**：
访问 `http://129.146.153.133:8000/admin/api-config/`，在表单中修改并保存。保存后自动清除配置缓存。

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

# 停止服务
kill $(cat gunicorn.pid) 2>/dev/null

# 拉取最新代码
git pull origin master

# 安装可能新增的依赖
python3.12 -m pip install -r requirements.txt

# 执行数据库迁移
python3.12 manage.py migrate

# 重新启动服务
python3.12 -m gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 --workers 2 --daemon \
    --access-logfile /home/opc/bdc/access.log \
    --error-logfile /home/opc/bdc/error.log \
    --pid /home/opc/bdc/gunicorn.pid

# 验证
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:8000/account/login/
```

### 5.2 一键更新脚本

将以下内容保存为 `/home/opc/bdc/update.sh`：

```bash
#!/bin/bash
set -e

cd /home/opc/bdc

echo ">>> Stopping gunicorn..."
kill $(cat gunicorn.pid) 2>/dev/null || true
sleep 2

echo ">>> Pulling latest code..."
git pull origin master

echo ">>> Installing dependencies..."
python3.12 -m pip install -r requirements.txt --quiet

echo ">>> Running migrations..."
python3.12 manage.py migrate

echo ">>> Starting gunicorn..."
python3.12 -m gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 --workers 2 --daemon \
    --access-logfile /home/opc/bdc/access.log \
    --error-logfile /home/opc/bdc/error.log \
    --pid /home/opc/bdc/gunicorn.pid

sleep 1
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/account/login/)
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
