#!/usr/bin/env bash
# 知识工作台 · 一键升级（依托 GitHub Releases / git tag）
#
# 用法：
#   ./scripts/upgrade.sh              # 升到最新的 git tag（即最新 Release）
#   ./scripts/upgrade.sh v0.3.5       # 升到指定版本
#   ./scripts/upgrade.sh --list       # 只列出可用版本，不动手
#
# 前置条件：
#   1. 本目录是 git 仓库且已配置 remote origin（GitHub）
#   2. 宿主机能访问 GitHub；被墙时 export KB_UPDATE_PROXY=http://10.10.10.252:1086
#
# 安全设计：
#   - 工作区有未提交改动时拒绝执行（防止升级把本地改动冲掉）
#   - .env 不受版本库管理，升级前照样备份一份
#   - 升级后做健康检查；失败自动回滚到升级前的 commit 并重建
set -euo pipefail

cd "$(dirname "$0")/.."

# ---- 可选代理：KB_UPDATE_PROXY > http_proxy > 常用内网代理，都不设置就直连 ----
if [[ -n "${KB_UPDATE_PROXY:-}" ]]; then
  export http_proxy="$KB_UPDATE_PROXY" https_proxy="$KB_UPDATE_PROXY"
fi

API_PORT="${KB_BACKEND_PORT:-8001}"
HEALTH_URL="http://localhost:${API_PORT}/api/health"

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "ℹ️  $*"; }

[[ -d .git ]] || die "当前目录不是 git 仓库，请先 git init 并配置 GitHub remote"
git remote get-url origin >/dev/null 2>&1 || die "没有配置 origin remote，无法从 GitHub 拉取"

# ---- 工作区必须干净 ----
if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  die "工作区有未提交的改动。升级会切换版本，请先提交或 stash"
fi

# ---- 拉取远程 tag ----
info "从 GitHub 拉取最新 tag（走代理：${https_proxy:-直连}）…"
git fetch origin --tags --force 2>/dev/null || git fetch --tags --force

# ---- 选目标版本：取语义化版本最大的 tag ----
latest_tag() {
  git tag --list 'v[0-9]*' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1
}

if [[ "${1:-}" == "--list" ]]; then
  echo "可用版本（旧 → 新）："
  git tag --list 'v[0-9]*' | sort -t. -k1,1n -k2,2n -k3,3n
  exit 0
fi

TARGET="${1:-$(latest_tag)}"
[[ -n "$TARGET" ]] || die "仓库里没有任何 v 开头的版本 tag"
git rev-parse -q --verify "refs/tags/${TARGET}" >/dev/null \
  || die "版本 ${TARGET} 不存在（用 --list 查看可用版本）"

CURRENT_TAG="$(git describe --tags --exact-match 2>/dev/null || echo "未打标签")"
OLD_HEAD="$(git rev-parse HEAD)"
info "当前：${CURRENT_TAG}（${OLD_HEAD:0:7}）  目标：${TARGET}"
if [[ "$CURRENT_TAG" == "$TARGET" ]]; then
  echo "✅ 已经是 ${TARGET}，无需升级"
  exit 0
fi

# ---- 备份 .env（虽不入库，compose 行为可能随版本变化）----
if [[ -f .env ]]; then
  cp .env ".env.bak-upgrade-$(date +%Y%m%d%H%M%S)"
  info "已备份 .env"
fi

# ---- 切换版本 ----
git checkout "$TARGET" 2>&1 | tail -1

# ---- 重建 + 重启 ----
info "重建镜像（前端构建较慢，请稍候）…"
docker compose build --pull=false
docker compose up -d

# ---- 健康检查：后端版本号必须等于目标 tag ----
tag_ver="${TARGET#v}"
info "健康检查（期望版本 ${tag_ver}）…"
ok=""
for i in $(seq 1 30); do
  if body="$(curl -s -m 3 "$HEALTH_URL" 2>/dev/null)"; then
    got="$(printf '%s' "$body" | grep -o '"version"[: ]*"[^"]*"' | head -1 | grep -o '[0-9][^"]*')"
    if [[ "$got" == "$tag_ver" ]]; then ok=1; break; fi
  fi
  sleep 2
done

if [[ -n "$ok" ]]; then
  echo "✅ 升级完成：${CURRENT_TAG} → ${TARGET}"
  echo "   打开 ${HEALTH_URL} 可确认；浏览器请硬刷新（Cmd+Shift+R）加载新前端"
  exit 0
fi

# ---- 失败回滚 ----
echo "⚠️  健康检查未通过，回滚到 ${OLD_HEAD:0:7} …"
git checkout "$OLD_HEAD" 2>&1 | tail -1
docker compose build --pull=false
docker compose up -d
die "已回滚。请把失败现象（docker compose logs backend）反馈到 GitHub Issues"
