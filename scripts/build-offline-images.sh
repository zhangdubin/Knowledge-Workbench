#!/bin/bash
# ============================================================
# 构建「离线安装包」所需的双架构镜像
#
# 产出（打完架构标签，供 docker save 使用）：
#   kb-workbench-backend:arm64   kb-workbench-frontend:arm64
#   kb-workbench-backend:amd64   kb-workbench-frontend:amd64
#
# 为什么按架构分开打标签：
#   docker load 不会校验架构，两个架构的镜像若都叫 :latest，
#   后加载的会把先加载的覆盖掉，启动时报 exec format error。
#   所以包内保存「架构标签」，由安装脚本 load 之后再打 :latest。
#
# 用法：
#   ./scripts/build-offline-images.sh                 # 双架构
#   PLATFORMS=linux/amd64 ./scripts/build-offline-images.sh
#   BUILDER=default \
#     PLATFORMS=linux/arm64 ./scripts/build-offline-images.sh   # 本机原生，最快
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

PLATFORMS="${PLATFORMS:-linux/arm64,linux/amd64}"
BUILDER="${BUILDER:-multiarch}"

# docker buildx 的 builder 选 default 时走本机原生构建（无 QEMU，最快）
BUILDER_ARG=()
if [ "$BUILDER" != "default" ]; then
  BUILDER_ARG=(--builder "$BUILDER")
fi

arch_tag() {
  case "$1" in
    linux/amd64)  echo amd64 ;;
    linux/arm64)  echo arm64 ;;
    linux/arm/v7) echo armv7 ;;
    *)            echo "$1" | tr '/' '-' ;;
  esac
}

echo "▶️  构建离线镜像"
echo "   平台: $PLATFORMS"
echo "   构建器: $BUILDER"
echo ""

for platform in $(echo "$PLATFORMS" | tr ',' ' '); do
  tag="$(arch_tag "$platform")"
  for svc in backend frontend; do
    echo "────────  $svc  ($platform)  →  kb-workbench-$svc:$tag  ────────"
    docker buildx build "${BUILDER_ARG[@]}" \
      --platform "$platform" \
      -t "kb-workbench-$svc:$tag" \
      --load \
      "./$svc"
    echo ""
  done
done

echo "✅ 全部完成"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' \
  | grep '^kb-workbench-' || true
