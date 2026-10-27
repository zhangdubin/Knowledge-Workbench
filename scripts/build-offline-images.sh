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
#   ./scripts/build-offline-images.sh --tools-with-git # 同上，但额外装 git（源码部署才需要）
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
WITH_GIT=0

for arg in "$@"; do
  case "$arg" in
    --tools-only) TOOLS_ONLY=1 ;;
    --tools-with-git) TOOLS_ONLY=1; WITH_GIT=1 ;;
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

# 预置「带工具镜像」需要的两个静态二进制。
#
# 为什么要在宿主机上先下好，而不是让构建沙箱自己下：
#   实测同样这两个文件，宿主机 curl 能跑 13MB/s，buildkit 沙箱里只有 5KB/s
#   —— 差的是沙箱的网络策略，不是源。60MB 的包在沙箱里要下好几个小时，
#   而且断了就得从头来（urlretrieve 不支持续传）。
#   curl 的 --continue-at + --retry 断点续传，稳得多。
#
# 下好了放进 backend/.docker-cache/，Dockerfile 会优先用本地副本。
fetch_upgrade_tools() {
  local cache_dir="backend/.docker-cache"
  local docker_cli_ver="${DOCKER_CLI_VERSION:-27.3.1}"
  local compose_ver="${DOCKER_COMPOSE_VERSION:-2.29.7}"
  mkdir -p "$cache_dir"
  for platform in $(echo "$PLATFORMS" | tr ',' ' '); do
    local tag darch
    tag="$(arch_tag "$platform")"
    case "$tag" in
      amd64) darch=x86_64 ;;
      arm64) darch=aarch64 ;;
      *) echo "  ! 跳过不支持的架构：$platform" >&2; continue ;;
    esac
    local cli_tgz="$cache_dir/docker-cli-$tag.tgz"
    local compose_bin="$cache_dir/docker-compose-$tag"
    if [ ! -s "$cli_tgz" ]; then
      echo "  下载 docker CLI（${tag}）…"
      curl -fsSL --retry 8 --retry-all-errors --retry-delay 3 -C - \
        -o "$cli_tgz" \
        "https://download.docker.com/linux/static/stable/$darch/docker-$docker_cli_ver.tgz" \
        || { echo "  ! docker CLI 下载失败：$tag" >&2; return 1; }
    else
      echo "  docker CLI（${tag}）已就绪，跳过下载"
    fi
    if [ ! -s "$compose_bin" ]; then
      echo "  下载 compose 插件（${tag}）…"
      curl -fsSL --retry 8 --retry-all-errors --retry-delay 3 -C - \
        -o "$compose_bin" \
        "https://github.com/docker/compose/releases/download/v$compose_ver/docker-compose-linux-$darch" \
        || { echo "  ! compose 插件下载失败：$tag" >&2; return 1; }
      chmod 0755 "$compose_bin"
    else
      echo "  compose 插件（${tag}）已就绪，跳过下载"
    fi
  done
}

if [ "$TOOLS_ONLY" = "1" ]; then
  fetch_upgrade_tools
  for platform in $(echo "$PLATFORMS" | tr ',' ' '); do
    tag="$(arch_tag "$platform")"
    echo "────────  backend+tools  ($platform)  →  kb-workbench-backend:tools-$tag  ────────"
    # --build-arg 只在这一个构建里生效，不影响普通镜像
    # INSTALL_GIT 只给「源码部署」那套自动升级路径要（它走 git fetch/checkout）。
    # 离线包部署走的是「下载镜像包 → docker load → compose up」，用不到 git，
    # 所以默认不装 —— 装 git 要连带拉 perl 全家桶，慢且容易因为源抖动失败。
    # 预置的二进制靠 Dockerfile 里的 bind mount 挂进来
    # （build secret 有 500KiB 上限，装不下这两个二进制；COPY 又会进镜像层）。
    docker buildx build ${BUILDER_ARG[@]+"${BUILDER_ARG[@]}"} \
      --build-context "dockercache=./backend/.docker-cache" \
      --platform "$platform" \
      --build-arg INSTALL_UPGRADE_TOOLS=1 \
      --build-arg INSTALL_GIT="$WITH_GIT" \
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
      --build-context "dockercache=./backend/.docker-cache" \
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
