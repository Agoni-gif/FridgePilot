# FridgePilot

面向个人用户的冰箱食材与菜谱助手：自然语言输入食材与约束 → Tavily 联网检索真实菜谱 → DeepSeek 整理为带来源的烹饪指南。

## 项目结构

| 目录 | 说明 |
|---|---|
| `fridgepilotweb` | Vue 3 前端 |
| `fridgepilotserver` | FastAPI 后端 |

## 技术栈

- 前端：Vue 3 + TypeScript + Vite（`fridgepilotweb`）
- 后端：FastAPI + Pydantic + SQLAlchemy（`fridgepilotserver`）
- 数据库：本地开发 MySQL，线上 / Docker 使用 SQLite
- LLM：DeepSeek（OpenAI 兼容）
- 搜索：Tavily

## 快速开始（本地开发）

### 1. 配置环境变量

```bash
cp .env.example .env
```

在 `.env` 中填入 `LLM_API_KEY`、`TAVILY_API_KEY`，以及本地 MySQL 的 `DATABASE_URL`：

```env
DATABASE_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/fridgepilot?charset=utf8mb4
```

首次启动时后端会自动 `CREATE DATABASE IF NOT EXISTS fridgepilot`（需账号有建库权限）。**不要把 `.env` 提交到 Git。**

### 2. 启动后端（fridgepilotserver）

```bash
cd fridgepilotserver
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：`GET http://127.0.0.1:8000/api/v1/health`

日志默认输出到终端，同时写入 `fridgepilotserver/logs/fridgepilotserver.log`（可用 `.env` 的 `LOG_LEVEL` / `LOG_FILE` 调整）。用户输入仅记录脱敏预览，不会打印 API Key。

### 数据库策略

| 环境 | 数据库 | 配置方式 |
|---|---|---|
| 本地开发 | MySQL | `.env` 中的 `DATABASE_URL` |
| 线上 / Docker Compose | SQLite | `docker-compose.yml` 强制覆盖为 `sqlite:///./data/fridgepilot.db` |

### 3. 启动前端（fridgepilotweb）

```bash
cd fridgepilotweb
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 已将 `/api` 代理到后端。

### 4. 运行测试

```bash
cd fridgepilotserver
pytest
```

## Docker Compose（生产）

目录约定：

```text
nginx/
  conf.d/     # 站点配置（fridgepilot.conf）
  ssl/        # 证书（可选）
  www/        # 前端静态文件（由 fridgepilotweb/dist 发布过来）
data/         # 后端 SQLite 等
```

| 挂载 | 说明 |
|---|---|
| `./nginx/www` → `/usr/share/nginx/html` | 前端静态资源 |
| `./nginx/conf.d` → `/etc/nginx/conf.d` | Nginx 配置 |
| `./nginx/ssl` → `/etc/nginx/ssl` | HTTPS 证书 |
| `./data` → `/app/data` | SQLite 持久化 |

```bash
# 本机构建并发布到 nginx/www
cd fridgepilotweb
npm ci && npm run build
# Windows PowerShell:
Copy-Item -Recurse -Force dist\* ..\nginx\www\
# Linux/macOS:
# rm -rf ../nginx/www/* && cp -r dist/* ../nginx/www/

# 服务器上
mkdir -p data
docker compose up -d --build
```

访问 `http://127.0.0.1:8080`。域名生产环境：`frid.weiverse.xyz`（见下方）。以后只改前端：覆盖 `nginx/www` 后执行 `docker compose restart nginx`。

### 域名 frid.weiverse.xyz（宝塔反代）

1. DNS：给 `frid.weiverse.xyz` 加 **A 记录** → 服务器公网 IP  
2. 容器照常监听 `8080`  
3. 宝塔 → 网站 → 添加站点 `frid.weiverse.xyz` → 反向代理到 `http://127.0.0.1:8080`  
4. 站点 SSL → Let’s Encrypt，开启强制 HTTPS  

### 自动部署（少用手改服务器）

仓库里有 `scripts/deploy.sh`：在服务器项目目录执行即可 `git pull`、构建前端、重启 Docker。**.env 不会被 git 覆盖，请留在服务器本地。**

**方式 A：宝塔计划任务（简单）**

1. 服务器先 `git clone` 好仓库，装好 Docker、Node（宝塔「Node 版本管理器」）  
2. 宝塔 → 计划任务 → Shell 脚本，例如每天或每小时：

```bash
cd /www/wwwroot/FridgePal && bash scripts/deploy.sh >> /tmp/fridgepilot-deploy.log 2>&1
```

改完代码：本机 `git push`，等任务跑，或 SSH 手动执行一次 `bash scripts/deploy.sh`。

**方式 B：GitHub Actions（push 即部署）**

1. 把 `scripts/deploy.sh` 与 `.github/workflows/deploy.yml` 推到 GitHub  
2. 仓库 Settings → Secrets 增加：`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY`、`DEPLOY_PATH`  
3. 之后 `git push origin main` 会自动 SSH 执行部署  

## API（MVP）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 存活检查 |
| POST | `/api/v1/chat` | 解析食材 → 搜索 → 结构化菜谱 |

请求示例：

```json
{
  "message": "我有鸡蛋、番茄和葱，想做简单晚饭",
  "session_id": null,
  "preferences": {
    "max_time_minutes": 20,
    "servings": 2,
    "dietary_restrictions": ["不吃辣"]
  }
}
```

## 安全提示

- 所有密钥仅由后端读取，前端产物中不应出现 API Key。
- 若密钥曾泄露到聊天记录或截图，请尽快在服务商控制台轮换。
