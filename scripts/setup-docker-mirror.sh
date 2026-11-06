#!/usr/bin/env bash
# 配置 Docker 国内镜像加速 + DNS（腾讯云推荐）
set -euo pipefail

mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ],
  "dns": ["223.5.5.5", "119.29.29.29", "8.8.8.8"]
}
EOF

systemctl daemon-reload
systemctl restart docker
echo "Docker 镜像加速已配置："
docker info 2>/dev/null | grep -A5 'Registry Mirrors' || true
