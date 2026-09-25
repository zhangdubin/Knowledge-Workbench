#!/usr/bin/env bash
# ============================================================
# 组装「一键离线安装包」
#
# 用法：
#   ./scripts/make-offline-package.sh
#   PLATFORMS="arm64" ./scripts/make-offline-package.sh
#   ./scripts/make-offline-package.sh --no-desktop     # 只产出到 dist-offline/
#
# 前置：先跑 ./scripts/build-offline-images.sh 准备好双架构镜像。
#
# 产出：
#   dist-offline/kb-workbench-offline-v<版本>-<日期>/     目录
#   ~/Desktop/kb-workbench-offline-v<版本>-<日期>.tar.gz  压缩包
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

PLATFORMS="${PLATFORMS:-arm64 amd64}"
OUT_DIR="${OUT_DIR:-$ROOT/dist-offline}"
TO_DESKTOP=1
[ "${1:-}" = "--no-desktop" ] && TO_DESKTOP=0

VERSION="$(sed -n 's/.*app_version: str = "\([^"]*\)".*/\1/p' backend/app/config.py | head -1)"
[ -n "$VERSION" ] || VERSION="0.0.0"
DATE="$(date +%Y%m%d)"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %z')"
NAME="kb-workbench-offline-v${VERSION}-${DATE}"
PKG="$OUT_DIR/$NAME"

say() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }

# ------------------------------------------------------------
# 0. 前置检查
# ------------------------------------------------------------
say "检查镜像（${PLATFORMS}）"
for tag in $PLATFORMS; do
  for svc in backend frontend; do
    if ! docker image inspect "kb-workbench-$svc:$tag" >/dev/null 2>&1; then
      printf "\033[31m✘ 缺少镜像 kb-workbench-%s:%s\033[0m\n" "$svc" "$tag"
      echo "  先执行: ./scripts/build-offline-images.sh"
      exit 1
    fi
  done
  printf "  ✔ %s\n" "$tag"
done

# ------------------------------------------------------------
# 1. 目录骨架
# ------------------------------------------------------------
say "创建目录结构"
rm -rf "$PKG"
mkdir -p "$PKG/app" "$PKG/images" "$PKG/scripts/lib" "$PKG/source"

# ------------------------------------------------------------
# 2. 安装脚本
# ------------------------------------------------------------
say "放入安装脚本"
cp packaging/install.sh packaging/install.command packaging/安装说明.txt "$PKG/"
chmod +x "$PKG/install.sh" "$PKG/install.command"
# 版本史随包走：升级的人不用回源码仓库就能看到「这版改了什么」
[ -f CHANGELOG.md ] && cp CHANGELOG.md "$PKG/CHANGELOG.md"

# install.ps1 必须以 UTF-8 BOM 保存，否则 PowerShell 5.1 会按 ANSI 解析，
# 中文全部乱码。
printf '\xEF\xBB\xBF' > "$PKG/install.ps1"
cat packaging/install.ps1 >> "$PKG/install.ps1"
cp packaging/install.bat "$PKG/"
printf "  ✔ install.sh / install.command / install.ps1 / install.bat\n"

# ------------------------------------------------------------
# 3. 运行编排
# ------------------------------------------------------------
say "放入运行编排"
cp packaging/app/docker-compose.yml "$PKG/app/docker-compose.yml"
cp .env.example "$PKG/app/.env.example"
printf "  ✔ docker-compose.yml / .env.example\n"

# ------------------------------------------------------------
# 4. 运维脚本
# ------------------------------------------------------------
say "放入运维脚本"
RUNTIME_SCRIPTS="backup.sh restore.sh healthcheck.sh reset-admin-password.sh migrate-blobs.sh move-data.sh"
for f in $RUNTIME_SCRIPTS; do
  if [ -f "scripts/$f" ]; then
    cp "scripts/$f" "$PKG/scripts/$f"
  else
    printf "  ! scripts/%s 不存在，跳过\n" "$f"
  fi
done
cp scripts/lib/* "$PKG/scripts/lib/" 2>/dev/null || true
chmod +x "$PKG"/scripts/*.sh 2>/dev/null || true
printf "  ✔ %s\n" "$(ls "$PKG/scripts" | tr '\n' ' ')"

# ------------------------------------------------------------
# 5. 源码快照
# ------------------------------------------------------------
say "打包源码快照（供自行重建镜像用）"
(
  COPYFILE_DISABLE=1 tar -czf "$PKG/source/kb-workbench-src.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    --exclude='dist' \
    --exclude='.venv' \
    --exclude='data' \
    --exclude='files' \
    --exclude='backups' \
    --exclude='backups-alt' \
    --exclude='dist-offline' \
    --exclude='.git' \
    --exclude='.DS_Store' \
    backend frontend docker-compose.yml start.sh .env.example README.md CHANGELOG.md scripts packaging 2>/dev/null
) || true
if [ -f "$PKG/source/kb-workbench-src.tar.gz" ]; then
  printf "  ✔ source/kb-workbench-src.tar.gz (%s)\n" "$(du -h "$PKG/source/kb-workbench-src.tar.gz" | cut -f1)"
else
  printf "  ! 源码快照生成失败，包仍可用（只是不能自行重建镜像）\n"
fi

# ------------------------------------------------------------
# 6. 导出镜像
# ------------------------------------------------------------
for tag in $PLATFORMS; do
  say "导出 $tag 镜像（需要一两分钟）"
  OUT="$PKG/images/kb-workbench-images-$tag.tar.gz"
  docker save \
      "kb-workbench-backend:$tag" \
      "kb-workbench-frontend:$tag" \
    | gzip > "$OUT"
  printf "  ✔ images/kb-workbench-images-%s.tar.gz (%s)\n" "$tag" "$(du -h "$OUT" | cut -f1)"
done

# ------------------------------------------------------------
# 7. manifest.json + 校验值
# ------------------------------------------------------------
say "生成清单与校验值"
python3 - "$PKG" "$NAME" "$VERSION" "$STAMP" "$PLATFORMS" <<'PY'
import hashlib, json, os, sys

pkg, name, version, stamp, platforms = sys.argv[1:6]

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

entries = []
for root, _dirs, files in os.walk(pkg):
    for fn in sorted(files):
        full = os.path.join(root, fn)
        rel = os.path.relpath(full, pkg)
        entries.append({
            'path': rel.replace(os.sep, '/'),
            'size': os.path.getsize(full),
            'sha256': sha256(full),
        })
entries.sort(key=lambda e: e['path'])

def human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f} {unit}' if unit != 'B' else f'{n} B'
        n /= 1024

images = [e for e in entries if e['path'].startswith('images/')]

manifest = {
    'name': name,
    'app': 'kb-workbench',
    'version': version,
    'built_at': stamp,
    'built_on': sys.platform,
    'architectures': platforms.split(),
    'install_entry': {
        'linux_macos': 'install.sh  (或 double-click install.command)',
        'windows': 'install.bat  (内部调用 install.ps1)',
    },
    'requires': {
        'docker': '>= 20.10（含 compose v2）',
        'note': '本包不含 Docker 本体，目标机需预装',
    },
    'default_ports': {'frontend': 8082, 'backend': 8001},
    'images': [
        {'file': i['path'], 'size': i['size'], 'size_human': human(i['size']), 'sha256': i['sha256']}
        for i in images
    ],
    'total_files': len(entries),
    'total_size': sum(e['size'] for e in entries),
    'files': entries,
}

with open(os.path.join(pkg, 'manifest.json'), 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

with open(os.path.join(pkg, 'images', 'SHA256SUMS'), 'w', encoding='utf-8') as f:
    for i in images:
        f.write(f"{i['sha256']}  {os.path.basename(i['path'])}\n")

print(f"  ✔ manifest.json（{len(entries)} 个文件）")
print(f"  ✔ images/SHA256SUMS")
PY

if command -v shasum >/dev/null 2>&1; then
  # 用 -exec 而不是管道 + xargs：macOS 自带的 BSD sort 不支持 -z，
  # 那种写法在这里会直接失败。
  ( cd "$PKG" && find . -type f ! -name 'checksums.txt' -exec shasum -a 256 {} \; > checksums.txt ) || true
  printf "  ✔ checksums.txt\n"
fi

# ------------------------------------------------------------
# 8. 汇总
# ------------------------------------------------------------
PKG_SIZE="$(du -sh "$PKG" | cut -f1)"
say "完成"
printf "  目录: %s  (%s)\n" "$PKG" "$PKG_SIZE"

if [ "$TO_DESKTOP" -eq 1 ]; then
  DESKTOP="$HOME/Desktop"
  if [ -d "$DESKTOP" ]; then
    say "压缩并复制到桌面"
    ARCHIVE="$DESKTOP/$NAME.tar.gz"
    ( cd "$OUT_DIR" && COPYFILE_DISABLE=1 tar --no-xattrs -czf "$ARCHIVE" "$NAME" ) 2>/dev/null \
      || ( cd "$OUT_DIR" && COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" "$NAME" )
    printf "  ✔ %s (%s)\n" "$ARCHIVE" "$(du -h "$ARCHIVE" | cut -f1)"
    shasum -a 256 "$ARCHIVE" | awk '{print "  sha256: "$1}'
  else
    printf "  ! 桌面目录不存在，跳过复制\n"
  fi
fi
