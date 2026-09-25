#!/usr/bin/env bash
# ============================================================
#  知识管理工作台 (KB Workbench) · 一键离线安装
#
#  适用平台（同一个包通吃，脚本自动识别）：
#    · Linux   x86_64 / arm64
#    · macOS   Intel / Apple Silicon
#    · Windows 见同目录 install.bat（走 PowerShell）
#
#  前置要求：目标机已安装 Docker（含 compose v2）。
#            本包不含 Docker 本体，只含应用镜像与运行文件。
#
#  用法：
#    bash install.sh                       # 装到 ~/kb-workbench 并启动
#    bash install.sh --dir /opt/kb-workbench
#    bash install.sh --port 8082 --backend-port 8001
#    bash install.sh --dry-run             # 只体检、不改动
# ============================================================
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------
# 输出
# ------------------------------------------------------------
if [ -t 1 ]; then
  C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'
  C_C=$'\033[36m'; C_B=$'\033[1m'; C_N=$'\033[0m'
else
  C_R=""; C_G=""; C_Y=""; C_C=""; C_B=""; C_N=""
fi
step() { printf "\n${C_C}${C_B}▸ %s${C_N}\n" "$*"; }
ok()   { printf "  ${C_G}✔${C_N} %s\n" "$*"; }
warn() { printf "  ${C_Y}!${C_N} %s\n" "$*"; }
note() { printf "    %s\n" "$*"; }
die()  { printf "\n${C_R}✘ %s${C_N}\n\n" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
知识管理工作台 · 一键离线安装

用法: bash install.sh [选项]

选项:
  -d, --dir <路径>        安装目录（默认: $HOME/kb-workbench）
  -p, --port <端口>       前端访问端口（默认: 8082）
  -b, --backend-port <端口>  后端 API 端口（默认: 8001）
      --password <口令>   初始管理员口令（默认: 自动随机生成）
      --instance <名称>   实例后缀：同一台机器上跑第二套互不干扰的实例时用
                          （容器名与 compose 项目名会带上该后缀）
      --data-dir <路径>   数据根目录：data / files / backups 都放这里。
                          只在**全新安装**时生效；已有安装改位置请用
                          bash scripts/move-data.sh <新路径>
      --skip-load         跳过镜像导入（镜像已在本地时用）
      --no-start          只装好文件与镜像，不启动容器
      --force             安装目录非空时也继续
      --dry-run           只检测环境并选包，不做任何改动
  -h, --help              显示本帮助

说明:
  脚本会自动识别当前操作系统与 CPU 架构，从 images/ 目录挑选
  对应的镜像包。同一个离线包可直接用于 Linux/macOS 的 x86_64
  与 arm64 平台。

  关于「装在哪」:
    安装目录本身只有几百 KB（编排文件 + 运维脚本），几乎不占空间。
    会长大的是数据目录 —— 元数据库、文件原文、备份快照。
    生产环境因此建议把两者拆开，装在小盘、数据放大盘:

      bash install.sh --dir /opt/kb-workbench --data-dir /data/kb-workbench

    已经装好但想换数据位置（例如默认的 ~/kb-workbench 所在分区太小）:

      bash scripts/move-data.sh /data/kb-workbench

    搬迁脚本会停服 → 搬数据 → 改 .env → 起服务 → 体检，
    并在动手前备份 .env，任何一步失败自动回滚。
EOF
}

# ------------------------------------------------------------
# 默认参数
# ------------------------------------------------------------
OPT_DIR="$HOME/kb-workbench"
OPT_PORT="8082"
OPT_BACKEND_PORT="8001"
OPT_PASSWORD=""
OPT_DATA_DIR=""
OPT_INSTANCE=""
OPT_SKIP_LOAD=0
OPT_NO_START=0
OPT_FORCE=0
OPT_DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    -d|--dir)          OPT_DIR="${2:-}"; shift 2 ;;
    -p|--port)         OPT_PORT="${2:-}"; shift 2 ;;
    -b|--backend-port) OPT_BACKEND_PORT="${2:-}"; shift 2 ;;
    --password)        OPT_PASSWORD="${2:-}"; shift 2 ;;
    --instance)        OPT_INSTANCE="${2:-}"; shift 2 ;;
    --data-dir)        OPT_DATA_DIR="${2:-}"; shift 2 ;;
    --skip-load)       OPT_SKIP_LOAD=1; shift ;;
    --no-start)        OPT_NO_START=1; shift ;;
    --force)           OPT_FORCE=1; shift ;;
    --dry-run)         OPT_DRY_RUN=1; shift ;;
    -h|--help)         usage; exit 0 ;;
    *)                 die "未知参数: $1（用 --help 看用法）" ;;
  esac
done

# 展开 ~ 与相对路径
case "$OPT_DIR" in
  "~")     OPT_DIR="$HOME" ;;
  "~/"*)   OPT_DIR="$HOME/${OPT_DIR#\~/}" ;;
esac

if [ -n "$OPT_DATA_DIR" ]; then
  case "$OPT_DATA_DIR" in
    "~")   OPT_DATA_DIR="$HOME" ;;
    "~/"*) OPT_DATA_DIR="$HOME/${OPT_DATA_DIR#\~/}" ;;
  esac
fi

# ------------------------------------------------------------
# 1. 环境体检
# ------------------------------------------------------------
step "环境检测"

OS="$(uname -s)"
case "$OS" in
  Linux)  OS_NAME="Linux" ;;
  Darwin) OS_NAME="macOS" ;;
  *)      die "不支持的系统: ${OS}（Windows 请用 install.bat）" ;;
esac

RAW_ARCH="$(uname -m)"
case "$RAW_ARCH" in
  x86_64|amd64)   ARCH="amd64" ;;
  arm64|aarch64)  ARCH="arm64" ;;
  armv7l|armv7)   ARCH="armv7" ;;
  *)              die "无法识别的 CPU 架构: $RAW_ARCH" ;;
esac

ok "系统: $OS_NAME ($RAW_ARCH → $ARCH)"

# Docker
if ! command -v docker >/dev/null 2>&1; then
  printf "\n"
  die "没有找到 docker 命令。
   本机需要先安装 Docker 才能运行本系统（离线包只含应用镜像，不含 Docker 本体）：
     · Linux : curl -fsSL https://get.docker.com | sh
     · macOS : 安装 Docker Desktop  https://www.docker.com/products/docker-desktop/
   装好后重新执行本脚本。"
fi

if ! docker info >/dev/null 2>&1; then
  die "Docker 已安装，但守护进程没有运行。
     · Linux : sudo systemctl start docker
     · macOS : 启动 Docker Desktop，等鲸鱼图标变绿后重试"
fi
DOCKER_VER="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
ok "Docker: $DOCKER_VER"

if ! docker compose version >/dev/null 2>&1; then
  die "缺少 docker compose v2。
     · 单独安装插件: https://docs.docker.com/compose/install/linux/
     · Docker Desktop 自带，检查是否被停用"
fi
ok "Compose: $(docker compose version --short 2>/dev/null || echo 'v2')"

# ------------------------------------------------------------
# 2. 挑选镜像包
# ------------------------------------------------------------
step "选择镜像包"

IMG_DIR="$PKG_ROOT/images"
[ -d "$IMG_DIR" ] || die "包结构不完整：缺少 images/ 目录（离线包可能没有完整解压）"

ARCHIVE="$IMG_DIR/kb-workbench-images-$ARCH.tar.gz"
if [ ! -f "$ARCHIVE" ]; then
  printf "\n"
  warn "本机是 $ARCH 架构，但包里没有对应的镜像文件。"
  printf "    包内现有:\n"
  for f in "$IMG_DIR"/kb-workbench-images-*.tar.gz; do
    [ -f "$f" ] && printf "      · %s\n" "$(basename "$f")"
  done
  die "请使用包含 $ARCH 架构的离线包，或在联网机器上重新打包：
     PLATFORMS=linux/$ARCH ./scripts/build-offline-images.sh"
fi

ARCHIVE_SIZE="$(du -h "$ARCHIVE" | cut -f1)"
ok "镜像包: $(basename "$ARCHIVE")  ($ARCHIVE_SIZE)"

# ------------------------------------------------------------
# 3. 安装目录
# ------------------------------------------------------------
step "准备安装目录"

TARGET="$OPT_DIR"
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

IS_UPGRADE=0
if [ -f "$TARGET/.env" ]; then
  IS_UPGRADE=1
  ok "检测到已有安装 → 按「升级」处理（保留 .env 与全部数据）"
else
  if [ -n "$(ls -A "$TARGET" 2>/dev/null | grep -v '^\.DS_Store$' || true)" ] && [ "$OPT_FORCE" -eq 0 ]; then
    die "$TARGET 不是空目录，且里面没有本系统的配置文件。
    确认要装到这里请加 --force，或换个目录: --dir /path/to/kb-workbench"
  fi
  ok "全新安装 → $TARGET"
fi

# ------------------------------------------------------------
# 数据位置
#
#  安装目录和「数据根目录」是两件事：
#    安装目录 = compose 文件 + 运维脚本，几百 KB，几乎不占空间
#    数据根   = data/（库）+ files/（文件原文）+ backups/（快照），会长大
#  生产环境把小盘给安装目录、大盘给数据根，是最省事的扩容方式。
# ------------------------------------------------------------

# 读已有 .env 里的一个键（只取值，不 source 整个文件 —— 避免把
# KB_CORS_ORIGINS=[] 这类带特殊字符的值污染到当前环境）
env_get() {
  local key="$1" val
  val="$(grep "^${key}=" "$TARGET/.env" 2>/dev/null | head -1 | cut -d= -f2- | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "$val"
}

# 把 .env 里的路径解析成绝对路径：相对路径的基准是安装目录（compose 的规则）
env_path() {
  local v="$1" dflt="$2"
  [ -n "$v" ] || v="$dflt"
  case "$v" in
    /*) printf '%s' "$v" ;;
    *)  printf '%s/%s' "$TARGET" "${v#./}" ;;
  esac
}

if [ "$IS_UPGRADE" -eq 1 ]; then
  # 升级：**以 .env 里已有的路径为准**。它才是真正生效的 —— 数据可能早就
  # 被搬到别的盘了，这里再打印一句「数据目录: $TARGET/data」会是假信息。
  SHOW_DATA="$(env_path   "$(env_get KB_DATA_DIR)"              ./data)"
  SHOW_FILES="$(env_path  "$(env_get KB_FILE_STORE_DIR)"         ./files)"
  SHOW_BACKUP="$(env_path "$(env_get KB_BACKUP_DIR)"             ./backups)"
  SHOW_ALT="$(env_path    "$(env_get KB_BACKUP_ALT_HOST_DIR)"    ./backups-alt)"
  DATA_ROOT="$SHOW_DATA"
  ok "数据目录: $SHOW_DATA"
  note "文件原文 ${SHOW_FILES} · 备份 ${SHOW_BACKUP}"

  # 升级模式不会重新生成 .env，所以 --data-dir 改不动已有安装。
  # 与其静默忽略（用户会以为改了、其实没改），不如明确说清怎么改。
  if [ -n "$OPT_DATA_DIR" ]; then
    WANT="$(cd "$OPT_DATA_DIR" 2>/dev/null && pwd || printf '%s' "$OPT_DATA_DIR")"
    if [ "$WANT" != "$DATA_ROOT" ]; then
      printf "\n"
      warn "升级模式不修改数据目录：.env 里已有路径优先级更高，写了也不会生效"
      note "当前: $DATA_ROOT"
      note "想要: $WANT"
      note "搬迁请用: bash $TARGET/scripts/move-data.sh $WANT"
      note "（停服 → 搬数据 → 改 .env → 起服务 → 体检，失败自动回滚）"
      printf "\n"
    fi
  fi
else
  if [ -n "$OPT_DATA_DIR" ]; then
    DATA_ROOT="$OPT_DATA_DIR"
    mkdir -p "$DATA_ROOT"
    DATA_ROOT="$(cd "$DATA_ROOT" && pwd)"
  else
    DATA_ROOT="$TARGET"
  fi
  SHOW_DATA="$DATA_ROOT/data"
  SHOW_FILES="$DATA_ROOT/files"
  SHOW_BACKUP="$DATA_ROOT/backups"
  SHOW_ALT="$DATA_ROOT/backups-alt"
  ok "数据目录: $SHOW_DATA"
  note "文件原文 ${SHOW_FILES} · 备份 ${SHOW_BACKUP}"
fi

if [ "$OPT_DRY_RUN" -eq 1 ]; then
  printf "\n${C_G}${C_B}✔ 体检通过（--dry-run，未做任何改动）${C_N}\n\n"
  printf "  将要执行: 解包 app/ → %s，导入 %s 镜像，启动服务\n\n" "$TARGET" "$ARCH"
  exit 0
fi

# ------------------------------------------------------------
# 4. 释放运行文件
# ------------------------------------------------------------
step "释放运行文件"

if [ ! -d "$PKG_ROOT/app" ]; then
  die "包结构不完整：缺少 app/ 目录"
fi

# 运行文件（compose / 脚本 / 说明）。.env 与数据目录由下面单独处理，
# 不会被这一步覆盖。
cp -R "$PKG_ROOT/app/." "$TARGET/"

if [ -d "$PKG_ROOT/scripts" ]; then
  mkdir -p "$TARGET/scripts"
  cp -R "$PKG_ROOT/scripts/." "$TARGET/scripts/"
  chmod +x "$TARGET"/scripts/*.sh 2>/dev/null || true
fi

chmod +x "$TARGET"/*.sh 2>/dev/null || true
ok "运行文件已就位"

# 数据骨架（用上面解析出的真实路径，升级时也只在缺失处补目录，绝不覆盖内容）
mkdir -p "$SHOW_DATA" "$SHOW_FILES" "$SHOW_BACKUP" "$SHOW_ALT"
ok "数据目录已就绪"

# ------------------------------------------------------------
# 5. 生成 .env（仅全新安装）
# ------------------------------------------------------------
step "配置"

gen_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 2>/dev/null | tr -dc 'A-Za-z0-9' | cut -c1-20
  else
    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom 2>/dev/null | head -c 20 || true
  fi
}

# 实例后缀：默认空 = 单机一套（容器名 kb-backend / kb-frontend）。
# 指定后容器名与 compose 项目名都带后缀，可与已有实例并存互不干扰。
#
# 升级时必须沿用 .env 里记着的实例标识：否则 compose 会拿当前这次的默认值
# 去操作，`-p kb-workbench` 和原来的 `-p kb-workbench-qa` 是两个不同的项目，
# 轻则认不出原有容器、重则因容器名冲突起不来。
if [ "$IS_UPGRADE" -eq 1 ] && [ -z "$OPT_INSTANCE" ]; then
  COMPOSE_PROJECT="$(env_get COMPOSE_PROJECT_NAME)"
  C_BACKEND="$(env_get KB_BACKEND_CONTAINER)"
  C_FRONTEND="$(env_get KB_FRONTEND_CONTAINER)"
  [ -n "$COMPOSE_PROJECT" ] || COMPOSE_PROJECT="kb-workbench"
  [ -n "$C_BACKEND" ] || C_BACKEND="kb-backend"
  [ -n "$C_FRONTEND" ] || C_FRONTEND="kb-frontend"
  ok "沿用原实例标识: ${COMPOSE_PROJECT}（容器 ${C_BACKEND} / ${C_FRONTEND}）"
elif [ -n "$OPT_INSTANCE" ]; then
  COMPOSE_PROJECT="kb-workbench-$OPT_INSTANCE"
  C_BACKEND="kb-$OPT_INSTANCE-backend"
  C_FRONTEND="kb-$OPT_INSTANCE-frontend"
  ok "实例标识: ${OPT_INSTANCE}（容器 $C_BACKEND / ${C_FRONTEND}）"
  if [ "$IS_UPGRADE" -eq 1 ]; then
    OLD_PROJ="$(env_get COMPOSE_PROJECT_NAME)"
    if [ -n "$OLD_PROJ" ] && [ "$OLD_PROJ" != "$COMPOSE_PROJECT" ]; then
      printf "\n"
      warn "这个目录原来用的是 ${OLD_PROJ}，而这次指定了 --instance ${OPT_INSTANCE}"
      note "容器会按新标识创建，原容器不会被接管 —— 确认这是你要的；"
      note "只是想升级的话，去掉 --instance 即可沿用原标识。"
      printf "\n"
    fi
  fi
else
  COMPOSE_PROJECT="kb-workbench"
  C_BACKEND="kb-backend"
  C_FRONTEND="kb-frontend"
fi

ENV_FILE="$TARGET/.env"
ADMIN_PASSWORD=""

if [ "$IS_UPGRADE" -eq 1 ]; then
  ok ".env 已存在，保持不变"
elif [ -n "$OPT_PASSWORD" ]; then
  ADMIN_PASSWORD="$OPT_PASSWORD"
else
  ADMIN_PASSWORD="$(gen_password)"
fi

if [ ! -f "$ENV_FILE" ]; then
  if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="kb$(date +%s)Admin"
    warn "随机口令生成失败，已使用兜底口令"
  fi

  umask 077
  cat > "$ENV_FILE" <<ENVEOF
# ============================================================
# kb-workbench 运行配置（安装脚本自动生成）
# 完整的可调项与说明见同目录 .env.example
# ============================================================

# 初始管理员口令：只在「库里一个用户都没有」时生效，登录后强制改密。
# 忘记口令用: bash scripts/reset-admin-password.sh
KB_ADMIN_PASSWORD=$ADMIN_PASSWORD

# ---- 端口 ----
KB_FRONTEND_PORT=$OPT_PORT
KB_BACKEND_PORT=$OPT_BACKEND_PORT

# ---- 容器名与项目名（同机并存多套实例时靠它们隔离）----
COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT
KB_BACKEND_CONTAINER=$C_BACKEND
KB_FRONTEND_CONTAINER=$C_FRONTEND

# ---- 存储 ----
# 下面四项都是**宿主机路径**，compose 用它们做 bind mount。
# 安装目录只放编排文件（几百 KB），数据全在这四个目录里 —— 空间不够时
# 搬它们就够了，不用动安装目录：bash scripts/move-data.sh /data/kb-workbench
KB_FILE_STORE=fs
KB_DATA_DIR=$DATA_ROOT/data
KB_FILE_STORE_DIR=$DATA_ROOT/files
KB_BACKUP_DIR=$DATA_ROOT/backups
# 第二块盘的挂载位：挂上别的盘后可在「系统设置 → 备份目录」里一键切换
KB_BACKUP_ALT_HOST_DIR=$DATA_ROOT/backups-alt
BACKUP_SEPARATE_MOUNTS=/mnt/kb-backup
KB_BACKUP_KEEP=14

# ---- 容量 ----
UPLOAD_MAX_MB=1024
LARGE_FILE_WARN_MB=200

# ---- SQLite 调优 ----
SQLITE_CACHE_MB=64
SQLITE_MMAP_MB=256

# ---- 安全 ----
KB_AUTH_ENABLED=true
KB_SESSION_DAYS=14
# 套了 HTTPS 反代后改成 true，否则浏览器不保存登录 Cookie
KB_COOKIE_SECURE=false
KB_MAINTENANCE_ENABLED=true
LOG_LEVEL=INFO
ENVEOF
  umask 022
  chmod 600 "$ENV_FILE"
  ok ".env 已生成（管理员口令：${ADMIN_PASSWORD}）"
fi

# ------------------------------------------------------------
# 6. 导入镜像
# ------------------------------------------------------------
if [ "$OPT_SKIP_LOAD" -eq 1 ]; then
  step "跳过镜像导入（--skip-load）"
else
  step "导入镜像（${ARCH}，约 ${ARCHIVE_SIZE}，需要一两分钟）"
  # docker load 能直接读 gzip 压缩的 tar
  docker load -i "$ARCHIVE" | sed 's/^/    /'
  ok "镜像已导入"
fi

# 关键一步：把「架构标签」提升为 compose 使用的 :latest。
# 为什么不一上来就存成 latest —— 同一个机器上若先后导入过两个
# 架构的包，latest 会被后导入的覆盖，启动时报 exec format error。
# 在这里按当前架构重新打标签，这才是唯一正确的那个。
docker tag "kb-workbench-backend:$ARCH"  "kb-workbench-backend:latest"
docker tag "kb-workbench-frontend:$ARCH" "kb-workbench-frontend:latest"
ok "镜像标签已指向本机架构（${ARCH}）"

# ------------------------------------------------------------
# 7. 启动
# ------------------------------------------------------------
if [ "$OPT_NO_START" -eq 1 ]; then
  step "跳过启动（--no-start）"
else
  step "启动服务"

  # 启动前先单独校验一次配置：把「编排文件不合法」和「容器起不来」分开报。
  # 否则用户拿到的往往是一句 Go 结构体校验错误（例如老版本 Compose 遇到新写法
  # 报的 "env_file.0 must be a string"），只知道失败了、不知道要改什么。
  CFG_ERR="$(mktemp -t kb-compose-cfg.XXXXXX)"
  if ! ( cd "$TARGET" && docker compose -p "$COMPOSE_PROJECT" config --quiet ) 2>"$CFG_ERR"; then
    printf "\n${C_R}✘ compose 配置校验未通过${C_N}\n\n"
    sed 's/^/    /' "$CFG_ERR"
    printf "\n    当前 Compose 版本: %s\n" "$(docker compose version --short 2>/dev/null || echo '未知')"
    printf "    多半是 Compose 版本过老，不认识编排文件里的新写法。\n"
    printf "    升级方式: https://docs.docker.com/compose/install/linux/\n\n"
    rm -f "$CFG_ERR"
    exit 1
  fi
  rm -f "$CFG_ERR"

  if ! ( cd "$TARGET" && docker compose -p "$COMPOSE_PROJECT" up -d ) 2>&1 | sed 's/^/    /'; then
    printf "\n${C_R}✘ 启动失败${C_N}\n"
    printf "    看详细日志: cd %s && docker compose -p %s logs\n\n" "$TARGET" "$COMPOSE_PROJECT"
    exit 1
  fi
  ok "容器已拉起"
fi

# ------------------------------------------------------------
# 8. 等待就绪
# ------------------------------------------------------------
http_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 "$1" >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -q -T 3 -O /dev/null "$1" >/dev/null 2>&1
  else
    return 2
  fi
}

if [ "$OPT_NO_START" -eq 0 ]; then
  step "等待服务就绪"
  READY=0
  i=0
  while [ "$i" -lt 60 ]; do
    if http_ok "http://127.0.0.1:$OPT_PORT/healthz"; then
      READY=1
      break
    fi
    i=$((i + 1))
    printf "\r    等待中… %ds" "$((i * 2))"
    sleep 2
  done
  printf "\r                    \r"

  if [ "$READY" -eq 1 ]; then
    ok "服务已就绪"
  else
    warn "等待超时（服务可能还在初始化，或端口被占用）"
    note "看日志: cd $TARGET && docker compose logs -f"
  fi
fi

# ------------------------------------------------------------
# 9. 交付信息
# ------------------------------------------------------------
if [ "$IS_UPGRADE" -eq 0 ] && [ -n "$ADMIN_PASSWORD" ]; then
  umask 077
  cat > "$TARGET/初始口令.txt" <<PWEOF
知识管理工作台 · 初始登录信息
====================================

  地址: http://localhost:$OPT_PORT
  账号: admin
  口令: $ADMIN_PASSWORD

首次登录会被要求修改口令。
改完之后请删除本文件：rm "$TARGET/初始口令.txt"
PWEOF
  chmod 600 "$TARGET/初始口令.txt"
fi

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -n "$HOST_IP" ] || HOST_IP="<本机IP>"

printf "\n${C_G}${C_B}"
printf "╭──────────────────────────────────────────────╮\n"
printf "│  ✔  知识管理工作台 安装完成                  │\n"
printf "╰──────────────────────────────────────────────╯${C_N}\n\n"

printf "  前端访问   ${C_B}http://localhost:%s${C_N}\n" "$OPT_PORT"
printf "  局域网访问 http://%s:%s\n" "$HOST_IP" "$OPT_PORT"
printf "  后端 API   http://localhost:%s/api/docs\n" "$OPT_BACKEND_PORT"
printf "  安装目录   %s\n" "$TARGET"
printf "  数据目录   %s\n" "$SHOW_DATA"
note "（安装目录只放编排文件，数据都在上面这个目录里；
    空间不够时用 scripts/move-data.sh 把数据搬到大容量盘）"
if [ "$IS_UPGRADE" -eq 0 ] && [ -n "$ADMIN_PASSWORD" ]; then
  printf "  登录账号   admin / ${C_B}%s${C_N}\n" "$ADMIN_PASSWORD"
  printf "             （也记在 %s/初始口令.txt）\n" "$TARGET"
else
  printf "  登录账号   admin（沿用原有口令）\n"
fi

if [ "$OPT_INSTANCE" = "" ]; then
  COMPOSE_HINT="docker compose"
else
  COMPOSE_HINT="docker compose -p $COMPOSE_PROJECT"
fi

printf "\n  常用操作:\n"
printf "    启动/停止   cd %s && %s up -d / down\n" "$TARGET" "$COMPOSE_HINT"
printf "    看日志      cd %s && %s logs -f\n" "$TARGET" "$COMPOSE_HINT"
printf "    健康体检    bash %s/scripts/healthcheck.sh\n" "$TARGET"
printf "    立即备份    bash %s/scripts/backup.sh\n" "$TARGET"
printf "    重置口令    bash %s/scripts/reset-admin-password.sh\n" "$TARGET"
printf "    数据备份建议指向另一块物理盘（系统设置 → 备份目录）\n\n"
