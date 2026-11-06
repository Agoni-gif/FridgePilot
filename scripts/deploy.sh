#!/usr/bin/env bash
# FridgePilot 服务器一键部署：git pull → 构建前端 → 发布到 nginx/www → 重启容器
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 工作目录: $ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: 缺少 .env（请先从 .env.example 复制并填写密钥，不要用 git 覆盖它）"
  exit 1
fi

echo "==> git pull"
git fetch origin
git pull --ff-only origin main

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
docker compose up -d --build
docker compose ps

echo "==> 健康检查"
curl -fsS "http://127.0.0.1:8080/api/v1/health" || true
echo
echo "部署完成"
