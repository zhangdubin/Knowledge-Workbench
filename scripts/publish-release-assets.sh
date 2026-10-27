#!/usr/bin/env bash
# ============================================================
# 把离线包里的产物挂到 GitHub Release 上
#
# 为什么必须有这一步：
#   「一键升级」的后端逻辑是从 Release 上**下载镜像包**来更新的。
#   而 GitHub 自动生成的只有源码包（Source code）—— 那不是镜像，
#   离线部署的机器下载下来也没法 docker load。
#   Release 上一个资产都没挂，就等于「升级功能写好了但没弹药」。
#
# 会上传的资产：
#   kb-workbench-images-arm64.tar.gz     ← 后端自动升级下载的就是这个
#   kb-workbench-images-amd64.tar.gz
#   kb-workbench-offline-v<版本>.tar.gz   ← 完整离线包，给人手动升级
#   kb-workbench-backend-tools-arm64.tar.gz（可选）← 带 git/docker/compose 的后端镜像
#   kb-workbench-backend-tools-amd64.tar.gz（可选）
#
# 用法：
#   ./scripts/publish-release-assets.sh                 # 用 CHANGELOG 里的最新版本
#   ./scripts/publish-release-assets.sh 0.5.0           # 指定版本
#   ./scripts/publish-release-assets.sh --dry-run       # 只看要传什么，不真传
#   ./scripts/publish-release-assets.sh --repo owner/name
#   ./scripts/publish-release-assets.sh --pkg-dir dist-offline/kb-workbench-offline-v0.5.0-20261027
#
# token 从 macOS 钥匙串取：
#   security find-generic-password -s "GitHub - https://api.github.com" -a "zhangdubin" -w
# ⚠️ token 绝不打印、也不进命令行参数（ps 能看到别人的 argv）。
#   下面把它写进一个 600 权限的临时 curl 配置文件，用 --config 传。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

REPO=""
VERSION=""
TAG=""
PKG_DIR=""
DRY_RUN=0
ARCHES="${ARCHES:-arm64 amd64}"
KEYCHAIN_SERVICE="GitHub - https://api.github.com"
KEYCHAIN_ACCOUNT="zhangdubin"

if [ -t 1 ]; then
  C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'
  C_C=$'\033[36m'; C_B=$'\033[1m'; C_N=$'\033[0m'
else
  C_R=""; C_G=""; C_Y=""; C_C=""; C_B=""; C_N=""
fi
step() { printf "\n${C_C}${C_B}▸ %s${C_N}\n" "$*"; }
ok()   { printf "  ${C_G}✔${C_N} %s\n" "$*"; }
warn() { printf "  ${C_Y}!${C_N} %s\n" "$*"; }
die()  { printf "\n${C_R}✘ %s${C_N}\n\n" "$*" >&2; exit 1; }

usage() {
  sed -n '2,32p' "$0"
  exit 0
}

# ------------------------------------------------------------
# 参数
# ------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --repo)    REPO="${2:-}"; shift 2 ;;
    --tag)     TAG="${2:-}"; shift 2 ;;
    --pkg-dir) PKG_DIR="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -*) die "未知参数：$1" ;;
    *)
      if [ -z "$VERSION" ]; then VERSION="$1"; else die "多余参数：$1"; fi
      shift
      ;;
  esac
done

command -v curl >/dev/null 2>&1 || die "需要 curl"
command -v python3 >/dev/null 2>&1 || die "需要 python3（用来解析 GitHub 返回的 JSON）"

# ------------------------------------------------------------
# 版本 / 仓库
# ------------------------------------------------------------
detect_version() {
  # CHANGELOG 顶部第一个 "## x.y.z" —— 发版流程规定「改 app_version → 加一节 CHANGELOG」，
  # 所以 CHANGELOG 的第一条就是当前要发的版本
  local v
  v="$(sed -n 's/^## \([0-9][0-9.]*\).*/\1/p' CHANGELOG.md 2>/dev/null | head -1)"
  [ -n "$v" ] && { printf '%s' "$v"; return 0; }
  # 兜底：直接读代码里的版本号
  v="$(sed -n 's/.*app_version: str = "\([^"]*\)".*/\1/p' backend/app/config.py 2>/dev/null | head -1)"
  [ -n "$v" ] && { printf '%s' "$v"; return 0; }
  return 1
}

detect_repo() {
  local url
  url="$(git remote get-url origin 2>/dev/null || true)"
  if [ -n "$url" ]; then
    # 两种常见写法都要认：
    #   https://github.com/owner/repo.git
    #   git@github.com:owner/repo.git
    # 注意 bash 3.2 里 ${url/:/\//} 这种「替换里带斜杠」的写法会把反斜杠
    # 一起留下（结果是 github.com\//owner/repo），所以这里用 case 分流 +
    # 前缀截断，不玩字符串替换。
    case "$url" in
      *://*)
        url="${url#*://}"   # github.com/owner/repo.git
        url="${url#*/}"      # owner/repo.git
        ;;
      *:*)
        url="${url#*:*}"     # owner/repo.git
        ;;
    esac
    url="${url%.git}"
    url="${url#/}"
    url="${url%/}"
    case "$url" in
      */*) printf '%s' "$url"; return 0 ;;
    esac
  fi
  printf '%s' "zhangdubin/Knowledge-Workbench"
}

[ -n "$VERSION" ] || VERSION="$(detect_version)" || die "无法确定版本号（CHANGELOG.md 与 config.py 里都没找到）"
[ -n "$TAG" ] || TAG="v${VERSION}"
[ -n "$REPO" ] || REPO="$(detect_repo)"

step "发布目标"
ok "仓库:   $REPO"
ok "版本:   $VERSION"
ok "Tag:    $TAG"
[ "$DRY_RUN" = "1" ] && warn "演练模式（--dry-run）：不会真的上传"

# ------------------------------------------------------------
# 找离线包目录
# ------------------------------------------------------------
if [ -z "$PKG_DIR" ]; then
  # 取版本号匹配、且最新修改的那个目录
  PKG_DIR="$(ls -dt dist-offline/kb-workbench-offline-v${VERSION}-* 2>/dev/null | head -1 || true)"
  if [ -z "$PKG_DIR" ]; then
    PKG_DIR="$(ls -dt dist-offline/kb-workbench-offline-* 2>/dev/null | head -1 || true)"
  fi
fi
[ -n "$PKG_DIR" ] && [ -d "$PKG_DIR" ] || die "找不到离线包目录（先跑 ./scripts/make-offline-package.sh，或用 --pkg-dir 指定）"
ok "离线包: $PKG_DIR"

# ------------------------------------------------------------
# 收集要上传的文件
# ------------------------------------------------------------
ASSETS=()          # 待上传文件路径
NAMES=()           # 上传后的资产名（默认与文件名相同）

add_asset() {      # add_asset <文件路径> [资产名]
  local f="$1" n="${2:-}"
  [ -f "$f" ] || return 0
  [ -n "$n" ] || n="$(basename "$f")"
  ASSETS+=("$f")
  NAMES+=("$n")
}

step "收集资产"
for arch in $ARCHES; do
  add_asset "$PKG_DIR/images/kb-workbench-images-${arch}.tar.gz"
done

# 完整离线包（给人手动升级用的那个 tar.gz）
FULL_PKG=""
for cand in \
  "dist-offline/kb-workbench-offline-v${VERSION}.tar.gz" \
  "$HOME/Desktop/kb-workbench-offline-v${VERSION}.tar.gz" \
  "$(ls -t "$HOME"/Desktop/kb-workbench-offline-v${VERSION}-*.tar.gz 2>/dev/null | head -1 || true)" \
  "$(ls -t dist-offline/kb-workbench-offline-v${VERSION}-*.tar.gz 2>/dev/null | head -1 || true)"
do
  [ -n "$cand" ] && [ -f "$cand" ] && { FULL_PKG="$cand"; break; }
done
if [ -z "$FULL_PKG" ]; then
  # 没有压缩包就现打一个：Release 上必须有一份完整包，
  # 「手动升级」的路径依赖它（离线机器没法 clone 仓库）
  FULL_PKG="dist-offline/kb-workbench-offline-v${VERSION}.tar.gz"
  warn "没找到完整离线包压缩包，正在现打一个（可能要点时间）…"
  ( cd dist-offline && COPYFILE_DISABLE=1 tar --no-xattrs -czf "../$FULL_PKG" "$(basename "$PKG_DIR")" ) \
    || ( cd dist-offline && COPYFILE_DISABLE=1 tar -czf "../$FULL_PKG" "$(basename "$PKG_DIR")" )
fi
add_asset "$FULL_PKG" "kb-workbench-offline-v${VERSION}.tar.gz"

# 带工具的后端镜像（可选）：本地有才传。
# 离线机器想用「一键升级」就得换这个镜像 —— 后端自己没带 git/docker。
for arch in $ARCHES; do
  if docker image inspect "kb-workbench-backend:tools-${arch}" >/dev/null 2>&1; then
    TOOLS_OUT="dist-offline/kb-workbench-backend-tools-${arch}.tar.gz"
    if [ ! -f "$TOOLS_OUT" ]; then
      step "导出带工具的后端镜像 ${arch}"
      docker save "kb-workbench-backend:tools-${arch}" | gzip > "$TOOLS_OUT"
    fi
    add_asset "$TOOLS_OUT"
  fi
done

[ "${#ASSETS[@]}" -gt 0 ] || die "一个资产都没找到，检查一下离线包目录"
ok "待上传 ${#ASSETS[@]} 个资产"
for i in "${!ASSETS[@]}"; do
  printf "    %-44s %s\n" "${NAMES[$i]}" "$(du -h "${ASSETS[$i]}" | cut -f1)"
done

if [ "$DRY_RUN" = "1" ]; then
  step "演练结束"
  ok "以上文件会被上传到 $REPO 的 $TAG 资产里"
  exit 0
fi

# ------------------------------------------------------------
# token
# ------------------------------------------------------------
get_token() {
  # 环境变量优先：CI / 没有钥匙串的机器上用这个
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    printf '%s' "$GITHUB_TOKEN"
    return 0
  fi
  if command -v security >/dev/null 2>&1; then
    local t=""
    if t="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null)"; then
      [ -n "$t" ] && { printf '%s' "$t"; return 0; }
    fi
  fi
  return 1
}

TOKEN="$(get_token)" || die "拿不到 GitHub token：请在钥匙串里存好「${KEYCHAIN_SERVICE} / ${KEYCHAIN_ACCOUNT}」，或设置 GITHUB_TOKEN 环境变量"
[ -n "$TOKEN" ] || die "GitHub token 是空的"

# token 写进临时 curl 配置（600 权限），命令行里只出现配置文件的路径。
# 原因：`ps aux` 能看到别人的完整命令行，token 走 argv 等于公开。
CURL_CFG="$(mktemp -t kb-gh-curl.XXXXXX)"
chmod 600 "$CURL_CFG"
trap 'rm -f "$CURL_CFG"' EXIT
{
  printf 'header = "Authorization: Bearer %s"\n' "$TOKEN"
  printf 'header = "Accept: application/vnd.github+json"\n'
  printf 'header = "User-Agent: kb-workbench-release-publisher"\n'
  printf 'silent\n'
  printf 'show-error\n'
  printf 'fail-with-body\n'
} > "$CURL_CFG"
unset TOKEN

gh() { curl --config "$CURL_CFG" "$@"; }

# ------------------------------------------------------------
# 找到 Release
# ------------------------------------------------------------
step "定位 Release"
REL_JSON="$(gh "https://api.github.com/repos/$REPO/releases/tags/$TAG")" \
  || die "拿不到 $TAG 的 Release 信息（tag 不存在？token 没权限？）"
RID="$(printf '%s' "$REL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
[ -n "$RID" ] || die "GitHub 上找不到 $REPO 的 $TAG Release —— 先去网页上把这个 Release 建出来"
ok "Release id: $RID"

# ------------------------------------------------------------
# 上传
# ------------------------------------------------------------
step "上传资产"
UPLOADED=()
for i in "${!ASSETS[@]}"; do
  f="${ASSETS[$i]}"; n="${NAMES[$i]}"

  # GitHub 不允许同名资产，所以先删旧的。
  # 为什么要删而不是跳过：同名旧资产多半是上一次传的半截文件
  # （或者内容已经变了），留着只会让人下载到过期的东西。
  old_id="$(gh "https://api.github.com/repos/$REPO/releases/$RID/assets" | python3 -c "
import json,sys
try:
    items = json.load(sys.stdin)
except Exception:
    items = []
print(next((str(a.get('id')) for a in items if a.get('name') == '''$n'''), ''))
")"
  if [ -n "$old_id" ]; then
    gh -X DELETE "https://api.github.com/repos/$REPO/releases/assets/$old_id" >/dev/null 2>&1 \
      || warn "删不掉同名资产 ${n}（继续尝试上传，失败会给出提示）"
    ok "已删除同名旧资产：$n"
  fi

  URL="https://uploads.github.com/repos/$REPO/releases/$RID/assets?name=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$n")"
  resp="$(gh -X POST -H 'Content-Type: application/octet-stream' --data-binary "@$f" "$URL")" \
    || die "上传 $n 失败"
  ok "已上传 ${n}（$(du -h "$f" | cut -f1)）"
  UPLOADED+=("$n")
done

# ------------------------------------------------------------
# 汇总
# ------------------------------------------------------------
step "完成"
for n in "${UPLOADED[@]}"; do
  printf "  ${C_G}✔${C_N} https://github.com/%s/releases/download/%s/%s\n" "$REPO" "$TAG" "$n"
done
echo ""
echo "  离线机器上可以用这些地址下载镜像包（配合 install.sh 导入）："
echo "    curl -LO https://github.com/$REPO/releases/download/$TAG/kb-workbench-images-arm64.tar.gz"
echo ""
