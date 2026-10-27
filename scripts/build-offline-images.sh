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
#   ./scripts/build-offline-images.sh --tools-only     # 只构建「带工具」的后端镜像
#
# 「带工具」变体（tools-only）：
#   kb-workbench-backend:tools-<arch>
#   = 同一个 Dockerfile，但构建参数 INSTALL_UPGRADE_TOOLS=1，
#     里面多装了 git / docker CLI / docker compose v2 插件。
#   用途：给「一键升级」用。默认镜像不带这些工具（不给所有用户白涨 90MB），
#   想要一键升级的机器才换这个镜像。
#   只构建 backend —— 前端镜像跟升级工具无关，没必要重建。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

PLATFORMS="${PLATFORMS:-linux/arm64,linux/amd64}"
BUILDER="${BUILDER:-multiarch}"
TOOLS_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --tools-only) TOOLS_ONLY=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数：${arg}（用 --help 看用法）" >&2
      exit 1
      ;;
  esac
done

# docker buildx 的 builder 选 default 时走本机原生构建（无 QEMU，最快）
# 注意 macOS 自带 bash 3.2：set -u 下空数组 "${BUILDER_ARG[@]}" 会报
# unbound variable，必须用 ${arr[@]+...} 守卫
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
if [ "$TOOLS_ONLY" = "1" ]; then
  echo "   变体: 仅「带工具」的后端镜像（INSTALL_UPGRADE_TOOLS=1）"
fi
echo ""

if [ "$TOOLS_ONLY" = "1" ]; then
  for platform in $(echo "$PLATFORMS" | tr ',' ' '); do
    tag="$(arch_tag "$platform")"
    echo "────────  backend+tools  ($platform)  →  kb-workbench-backend:tools-$tag  ────────"
    # --build-arg 只在这一个构建里生效，不影响普通镜像
    docker buildx build ${BUILDER_ARG[@]+"${BUILDER_ARG[@]}"} \
      --platform "$platform" \
      --build-arg INSTALL_UPGRADE_TOOLS=1 \
      -t "kb-workbench-backend:tools-$tag" \
      --load \
      "./backend"
    echo ""
  done
  echo "✅ 带工具的后端镜像构建完成"
  echo "   用法：docker tag kb-workbench-backend:tools-<arch> kb-workbench-backend:latest"
  echo "   （或者在编排文件里把后端的 image: 直接写成 kb-workbench-backend:tools-<arch>）"
  docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' \
    | grep '^kb-workbench-backend:tools-' || true
  exit 0
fi

for platform in $(echo "$PLATFORMS" | tr ',' ' '); do
  tag="$(arch_tag "$platform")"
  for svc in backend frontend; do
    echo "────────  $svc  ($platform)  →  kb-workbench-$svc:$tag  ────────"
    docker buildx build ${BUILDER_ARG[@]+"${BUILDER_ARG[@]}"} \
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
