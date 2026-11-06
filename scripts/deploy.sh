#!/usr/bin/env bash
# FridgePilot 服务器一键部署：git pull → 构建前端 → 发布到 nginx/www → 重启容器
# 跳过 git：SKIP_GIT_PULL=1 bash scripts/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 工作目录: $ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: 缺少 .env（请先从 .env.example 复制并填写密钥，不要用 git 覆盖它）"
  exit 1
fi

if [[ "${SKIP_GIT_PULL:-0}" == "1" ]]; then
  echo "==> 跳过 git pull（SKIP_GIT_PULL=1）"
else
  echo "==> git pull"
  export GIT_TERMINAL_PROMPT=0
  # 国内访问 GitHub 可能很慢/卡住，120s 超时
  if ! timeout 120 git fetch --prune origin; then
    echo "WARN: git fetch 失败或超时，继续用当前代码部署"
  else
    git pull --ff-only origin main || echo "WARN: git pull 失败，继续用当前代码部署"
  fi
fi

echo "==> 构建前端并发布到 nginx/www"
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: 未安装 Node/npm。宝塔可安装 Node 版本管理器，或本机构建后把 dist 同步到 nginx/www"
  exit 1
fi

(
  cd fridgepilotweb
  npm ci
  npm run build
)

mkdir -p nginx/www nginx/ssl data
# 保留目录，清空旧静态资源（保留隐藏的 .gitkeep）
find nginx/www -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +
cp -r fridgepilotweb/dist/. nginx/www/

echo "==> docker compose up"
# build.network: host 时，新版 buildx 需要显式授权
docker compose build --allow=network.host
docker compose up -d
docker compose ps

echo "==> 健康检查"
curl -fsS "http://127.0.0.1:8080/api/v1/health" || true
echo
echo "部署完成"
