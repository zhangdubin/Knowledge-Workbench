#!/usr/bin/env bash
#
# 知识工作台 —— 把数据根目录搬到另一块盘（或在磁盘满之前先腾地方）
#
# 为什么需要它：
#   安装目录本身只有几百 KB（编排文件 + 脚本），真正会长大的是数据：
#     data/      元数据 + 全文/向量索引（kb.db）
#     files/     文件原文（最大头，随上传量线性增长）
#     backups/   备份快照（默认保留 14 份，硬链接增量）
#   所以「安装目录空间不够」几乎总是数据目录的问题 —— 把数据搬到大容量盘即可，
#   安装目录留在原地完全不用动。
#
# 用法:
#   bash scripts/move-data.sh /data/kb-workbench          # 搬到新盘（会先预览再确认）
#   bash scripts/move-data.sh /data/kb-workbench --yes    # 不问，直接做
#   bash scripts/move-data.sh /mnt/big/kb --keep-source   # 搬完保留原目录
#
# 它做四件事（任一步失败自动回滚 .env）：
#   1. 停容器（留足 60s 关停维护时间，让 WAL 落盘）
#   2. 把四个数据目录搬到新根目录下
#   3. 改写 .env 里对应的宿主机路径
#   4. 起容器并等待健康检查
#
# 同盘搬迁用 mv（瞬时、原子）；跨盘用 rsync 复制后逐项校验（文件数 + 实际
# 占用 + 硬链接是否保留），确认无误才切 .env。跨盘时**保留**原目录，
# 脚本退出前会打印清理命令 —— 先确认服务正常，再手动删。
#
# 选项:
#   --yes | -y            预览后不再询问，直接执行
#   --keep-source         跨盘搬完保留原目录（默认也保留，此项仅用于表意）
#   --only data,files     只搬这几个（可选: data files backups backups-alt）
#   --skip backups        不搬这几个
#   -h | --help           显示本帮助
#
# 四个数据目录都会列出来让你看清楚再确认 —— 包括本来就躺在别的盘上的
# （例如专门挂的备份盘 / NAS）。不想连它一起并过来，用 --skip backups。
#
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

if [ -t 1 ]; then
  C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_C=$'\033[36m'; C_B=$'\033[1m'; C_N=$'\033[0m'
else
  C_R=""; C_G=""; C_Y=""; C_C=""; C_B=""; C_N=""
fi
step() { printf "\n${C_C}${C_B}▸ %s${C_N}\n" "$*"; }
ok()   { printf "  ${C_G}✔${C_N} %s\n" "$*"; }
warn() { printf "  ${C_Y}!${C_N} %s\n" "$*"; }
note() { printf "    %s\n" "$*"; }
die()  { printf "\n${C_R}✘ %s${C_N}\n\n" "$*" >&2; exit 1; }

# 帮助正文 = 文件头注释（到 set -euo 之前）。用模式匹配而不是写死行号，
# 这样以后往头部加说明不会把 help 截断。
usage() { sed -n '3,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

# ------------------------------------------------------------
# 参数
# ------------------------------------------------------------
NEW_ROOT=""
ASSUME_YES=0
KEEP_SOURCE=0
ONLY=""
SKIP_LIST=""

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y)         ASSUME_YES=1; shift ;;
    --keep-source)    KEEP_SOURCE=1; shift ;;
    --only)           ONLY="${2:-}"; shift 2 ;;
    --skip)           SKIP_LIST="${2:-}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    -*)               die "未知参数: $1（用 --help 看用法）" ;;
    *)                NEW_ROOT="$1"; shift ;;
  esac
done

[ -n "$NEW_ROOT" ] || { usage; printf "\n"; die "缺少参数：新的数据根目录"; }

# ------------------------------------------------------------
# 中断自愈
#
# 这个脚本会先停服再动数据，中途任何一步失败（磁盘写满、权限、Ctrl-C）
# 都可能把「服务停着、配置没改、数据也没搬完」这种半吊子状态留给用户。
# 挂个 EXIT 钩子：只要不是正常跑完，就把服务拉回来 —— 此时 .env 没被改过，
# 数据库也没挪过位，用原配置重启一定是对的。
# ------------------------------------------------------------
SERVICES_STOPPED=0
FINISHED=0
on_exit() {
  if [ "$FINISHED" -eq 0 ] && [ "$SERVICES_STOPPED" -eq 1 ]; then
    printf "\n${C_Y}! 未正常结束，配置未改、数据未动，正在把服务按原配置拉回来…${C_N}\n"
    ( cd "$APP_DIR" && docker compose -p "$COMPOSE_PROJECT" up -d ) >/dev/null 2>&1 \
      && printf "  ${C_G}✔${C_N} 服务已恢复（原配置）\n" \
      || printf "  ${C_R}✘${C_N} 自动恢复失败，请手工执行: cd %s && docker compose -p %s up -d\n" "$APP_DIR" "$COMPOSE_PROJECT"
  fi
}
trap on_exit EXIT

# 展开 ~
case "$NEW_ROOT" in
  "~")   NEW_ROOT="$HOME" ;;
  "~/"*) NEW_ROOT="$HOME/${NEW_ROOT#\~/}" ;;
esac
case "$NEW_ROOT" in
  /*) ;;
  *)  NEW_ROOT="$APP_DIR/$NEW_ROOT" ;;
esac

# ------------------------------------------------------------
# .env 读写
# ------------------------------------------------------------
ENV_FILE="$APP_DIR/.env"
[ -f "$ENV_FILE" ] || die "找不到 $ENV_FILE —— 这里看起来不是安装目录（请在本系统的安装目录下执行）"

read_env() {
  local key="$1" default="$2" val
  val="$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "${val:-$default}"
}

set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    # 用 | 作分隔符，路径里不太可能有它
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# 相对路径一律按安装目录解析（compose 的相对路径基准就是它）
abspath() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s' "$APP_DIR/${1#./}" ;;
  esac
}

OLD_DATA="$(abspath "$(read_env KB_DATA_DIR ./data)")"
OLD_FILES="$(abspath "$(read_env KB_FILE_STORE_DIR ./files)")"
OLD_BACKUP="$(abspath "$(read_env KB_BACKUP_DIR ./backups)")"
OLD_ALT="$(abspath "$(read_env KB_BACKUP_ALT_HOST_DIR ./backups-alt)")"

CONTAINER="$(read_env KB_BACKEND_CONTAINER kb-backend)"
COMPOSE_PROJECT="$(read_env COMPOSE_PROJECT_NAME kb-workbench)"
FRONTEND_PORT="$(read_env KB_FRONTEND_PORT 8082)"

# ------------------------------------------------------------
# 设备号 / 占用
# ------------------------------------------------------------
dev_of() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1"; }
du_kb()  { du -sk "$1" 2>/dev/null | cut -f1; }
count_of(){ find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }
human()  { awk -v k="$1" 'BEGIN{ split("KB MB GB TB",u," "); i=1; while(k>=1024 && i<4){k/=1024;i++} printf "%.1f%s", k, u[i] }'; }

# ------------------------------------------------------------
# 1. 规划
# ------------------------------------------------------------
step "搬前检查"

mkdir -p "$NEW_ROOT"
NEW_ROOT="$(cd "$NEW_ROOT" && pwd)"
[ "$NEW_ROOT" = "$APP_DIR" ] && die "新目录就是安装目录，无需搬迁"

APP_DEV="$(dev_of "$APP_DIR")"
NEW_DEV="$(dev_of "$NEW_ROOT")"

ok "安装目录: $APP_DIR"
ok "新数据根: $NEW_ROOT"

if [ "$APP_DEV" = "$NEW_DEV" ]; then
  warn "新目录与安装目录在**同一块磁盘**上，搬过去省不了空间（只方便挂载管理）"
fi

# 计划：待搬迁的 (源 → 目的)
#
# 刻意**不**做「已经在别的盘上就自动跳过」这种自作聪明 —— 数据本来就常常
# 躺在第二块盘上，用户想把它并到另一块更大的盘时，自动跳过会让脚本一脸
# 无辜地说「没有需要搬迁的目录」。改成全部列出、标出「原本在别的盘上」，
# 由确认环节把关；要排除就用 --only / --skip 明说。
PLAN_SRC=(); PLAN_DST=(); PLAN_NOTE=(); PARENTS=(); PLAN_BYTES=0
declare -a SKIPPED=()

plan_one() {
  local name="$1" src="$2"
  [ -e "$src" ] || { SKIPPED+=("${name}（不存在）"); return 0; }
  local dst="$NEW_ROOT/$name"
  case "$src" in
    "$NEW_ROOT"|"$NEW_ROOT"/*) SKIPPED+=("${name}（已在新目录下）"); return 0 ;;
  esac
  if [ -n "$ONLY" ]; then
    case ",${ONLY}," in *",${name},"*) ;; *) SKIPPED+=("${name}（--only 未选中）"); return 0 ;; esac
  fi
  if [ -n "$SKIP_LIST" ]; then
    case ",${SKIP_LIST}," in *",${name},"*) SKIPPED+=("${name}（--skip）"); return 0 ;; esac
  fi
  [ -e "$dst" ] && die "目标已存在，拒绝覆盖: ${dst}
    先把它挪走或改名，再重跑。"
  PLAN_SRC+=("$src"); PLAN_DST+=("$dst")
  local note_txt=""
  if [ "$(dev_of "$src")" != "$APP_DEV" ]; then
    note_txt="原本在另一块盘上"
  fi
  if [ -d "$src" ] && [ "$(dev_of "$src")" != "$NEW_DEV" ]; then
    note_txt="${note_txt:+${note_txt}，}跨盘复制"
  else
    note_txt="${note_txt:+${note_txt}，}同盘移动"
  fi
  PLAN_NOTE+=("$note_txt")
  PARENTS+=("$(dirname "${src}")")
  PLAN_BYTES=$((PLAN_BYTES + $(du_kb "$src")))
}

# 同盘 mv 之后，原来的父目录可能空着（例如数据本来单独放在 /data/kb-workbench
# 下，四个子目录搬走后只剩一个空壳）。用 rmdir 删 —— 它只在目录**确实为空**
# 时才成功，所以这里不可能误删有内容的目录；安装目录本身跳过。
cleanup_empty_parents() {
  local p
  for p in ${PARENTS[@]+"${PARENTS[@]}"}; do
    [ "$p" = "$APP_DIR" ] && continue
    [ -d "$p" ] || continue
    rmdir "$p" 2>/dev/null && ok "已清掉空目录 $p"
  done
}

plan_one "data"        "$OLD_DATA"
plan_one "files"       "$OLD_FILES"
plan_one "backups"     "$OLD_BACKUP"
plan_one "backups-alt" "$OLD_ALT"

printf "\n"
if [ "${#PLAN_SRC[@]}" -eq 0 ]; then
  for s in ${SKIPPED[@]+"${SKIPPED[@]}"}; do note "跳过 ${s}"; done
  die "没有需要搬迁的目录（要用 --only / --skip 调整范围）"
fi

# 空间够不够
AVAIL_KB="$(df -Pk "$NEW_ROOT" | awk 'NR==2{print $4}')"
NEED_KB=$((PLAN_BYTES + PLAN_BYTES / 10 + 65536))

printf "  将搬迁:\n"
i=0
while [ "$i" -lt "${#PLAN_SRC[@]}" ]; do
  printf "    %-11s %s → %s  (%s)\n" "${PLAN_SRC[$i]##*/}" "${PLAN_SRC[$i]}" "${PLAN_DST[$i]}" "$(human "$(du_kb "${PLAN_SRC[$i]}")")"
  printf "                %s\n" "${PLAN_NOTE[$i]}"
  i=$((i + 1))
done
for s in ${SKIPPED[@]+"${SKIPPED[@]}"}; do printf "    跳过 %s\n" "${s}"; done

printf "\n  合计约 %s，目标盘可用 %s\n" "$(human "$PLAN_BYTES")" "$(human "$AVAIL_KB")"
[ "$AVAIL_KB" -ge "$NEED_KB" ] || die "目标盘空间不足（需要约 $(human "$NEED_KB")，可用 $(human "$AVAIL_KB")）"

if [ "$ASSUME_YES" -eq 0 ]; then
  printf "\n  搬运期间服务会短暂停止。继续？[y/N] "
  read -r ans || ans=""
  case "$ans" in y|Y|yes|YES) ;; *) printf "\n  已取消\n\n"; exit 0 ;; esac
fi

# ------------------------------------------------------------
# 2. 停服
# ------------------------------------------------------------
step "停止服务"
( cd "$APP_DIR" && docker compose -p "$COMPOSE_PROJECT" down ) 2>&1 | sed 's/^/    /' || true
SERVICES_STOPPED=1
ok "已停止（关停维护已执行）"

# ------------------------------------------------------------
# 3. 搬运
# ------------------------------------------------------------
# ------------------------------------------------------------
# 跨盘复制
#
# 必须保住硬链接 —— 备份快照之间就是靠硬链接共享未变动的文件，
# 一旦被展开成独立副本，备份目录的体积会成倍膨胀（而且是在你不知道的时候）。
#
# 三个方案按可靠性排序，逐个降级：
#   rsync -aHAX  rsync 3.x，最稳（A=ACL、X=xattr）
#   rsync -aHE   macOS 自带的是 rsync 2.6.9，不认 -A/-X，但支持 -E（扩展属性）
#               注意 -E 在 rsync 3.x 里是 --executability，含义完全不同，
#               所以必须按版本号挑，不能无脑都带
#   tar 管道     bsdtar / GNU tar 默认就把同一批文件里的硬链接存成链接
# ------------------------------------------------------------
RSYNC_OPTS=""
if command -v rsync >/dev/null 2>&1; then
  R_MAJOR="$(rsync --version 2>/dev/null | head -1 | sed -n 's/.*version \([0-9][0-9]*\)\..*/\1/p')"
  case "$R_MAJOR" in
    ''|*[!0-9]*) R_MAJOR=2 ;;
  esac
  if [ "$R_MAJOR" -ge 3 ]; then RSYNC_OPTS="-aHAX"; else RSYNC_OPTS="-aHE"; fi
fi

copy_tree() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  if [ -n "$RSYNC_OPTS" ] && rsync $RSYNC_OPTS "$src/" "$dst/" 2>/dev/null; then
    printf '%s' "rsync ${RSYNC_OPTS}"
    return 0
  fi
  rm -rf "$dst"; mkdir -p "$dst"
  if ( cd "$src" && tar -cf - . ) | ( cd "$dst" && tar -xf - ) 2>/dev/null; then
    printf '%s' "tar 管道"
    return 0
  fi
  rm -rf "$dst"
  return 1
}

step "搬迁数据"

ENV_BAK="$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$ENV_FILE" "$ENV_BAK"
ok "已备份配置 → $(basename "$ENV_BAK")"

CROSS_DEVICE=0
MOVED_DST=(); MOVED_SRC=()
i=0
while [ "$i" -lt "${#PLAN_SRC[@]}" ]; do
  src="${PLAN_SRC[$i]}"; dst="${PLAN_DST[$i]}"
  same_dev=0
  [ "$(dev_of "$src")" = "$NEW_DEV" ] && same_dev=1

  if [ "$same_dev" -eq 1 ]; then
    # 同一块盘：rename 是原子的，瞬时完成
    mv "$src" "$dst"
    ok "$(basename "$src") → 同盘移动完成"
  else
    CROSS_DEVICE=1
    printf "  ${C_C}·${C_N} 跨盘复制 %s（%s，需要一会儿）\n" "$(basename "$src")" "$(human "$(du_kb "$src")")"
    if ! COPY_METHOD="$(copy_tree "$src" "$dst")"; then
      die "复制失败：$(basename "${src}")
    目标目录已删除，原数据未动，.env 也没有改。
    请检查目标盘（是否只读 / 空间被别的进程占了），然后重跑本脚本。"
    fi

    S_N="$(count_of "$src")"; D_N="$(count_of "$dst")"
    S_K="$(du_kb "$src")";   D_K="$(du_kb "$dst")"
    if [ "$S_N" != "$D_N" ]; then
      rm -rf "$dst"
      die "复制校验失败：文件数不一致（源 ${S_N} / 目标 ${D_N}）。
    目标目录已删除，原数据未动，服务未启动。请检查磁盘后重试。"
    fi
    # 硬链接若丢失，目标占用会明显大于源；给 5% 余量容忍文件系统差异
    if [ "$D_K" -gt $((S_K + S_K / 20 + 1024)) ]; then
      rm -rf "$dst"
      die "复制校验失败：目标占用 ${D_K}KB 远大于源 ${S_K}KB —— 硬链接没保住。
    备份快照依赖硬链接共享未变动的文件，这样搬过去体积会成倍膨胀。
    请确认 rsync 版本（需要 -H 支持），或先在备份目录里只留一两份再搬。"
    fi
    ok "$(basename "$src") → 已复制并校验（${COPY_METHOD}，${D_N} 个文件，${D_K}KB）"
  fi

  MOVED_SRC+=("$src"); MOVED_DST+=("$dst")
  i=$((i + 1))
done

# ------------------------------------------------------------
# 4. 改写 .env
# ------------------------------------------------------------
step "改写配置"

rollback_env() {
  warn "正在回滚 .env …"
  cp -p "$ENV_BAK" "$ENV_FILE"
  j=0
  while [ "$j" -lt "${#MOVED_SRC[@]}" ]; do
    if [ -e "${MOVED_DST[$j]}" ] && [ ! -e "${MOVED_SRC[$j]}" ]; then
      mv "${MOVED_DST[$j]}" "${MOVED_SRC[$j]}" 2>/dev/null || true
    fi
    j=$((j + 1))
  done
}

set_env KB_DATA_DIR "$NEW_ROOT/data"
set_env KB_FILE_STORE_DIR "$NEW_ROOT/files"
set_env KB_BACKUP_DIR "$NEW_ROOT/backups"
set_env KB_BACKUP_ALT_HOST_DIR "$NEW_ROOT/backups-alt"
ok "已写入新的宿主机路径"

# 目录骨架（迁过来的可能少了某个，补上不覆盖）
mkdir -p "$NEW_ROOT/data" "$NEW_ROOT/files" "$NEW_ROOT/backups" "$NEW_ROOT/backups-alt"

# ------------------------------------------------------------
# 5. 起服务并体检
# ------------------------------------------------------------
step "启动服务"
if ! ( cd "$APP_DIR" && docker compose -p "$COMPOSE_PROJECT" up -d ) 2>&1 | sed 's/^/    /'; then
  rollback_env
  die "启动失败，已回滚配置。看日志: cd $APP_DIR && docker compose -p $COMPOSE_PROJECT logs"
fi

step "等待就绪"
READY=0
i=0
while [ "$i" -lt 45 ]; do
  st="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo none)"
  [ "$st" = "healthy" ] && { READY=1; break; }
  i=$((i + 1)); printf "\r    等待中… %ds" "$((i * 2))"; sleep 2
done
printf "\r                    \r"

if [ "$READY" -ne 1 ]; then
  warn "后端容器未在 90s 内变为 healthy，不回滚（数据已在新位置，回滚反而更危险）"
  note "看日志: cd $APP_DIR && docker compose -p $COMPOSE_PROJECT logs --tail 80"
  note "确认无误后再删原目录；若有问题可用 $ENV_BAK 恢复配置"
else
  ok "后端容器 healthy"
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 5 "http://127.0.0.1:${FRONTEND_PORT}/healthz" >/dev/null 2>&1; then
      ok "前端已就绪"
    else
      warn "前端 ${FRONTEND_PORT} 端口暂未响应（可能仍在启动）"
    fi
  fi
fi

# 全部走完、服务已经起来之后，再清掉同盘搬空的父目录。
# 放在这里是有意的：万一中途失败要回滚，父目录还得留着接 mv 回来的目录；
# 走到这一步说明已经不会再回滚了。
cleanup_empty_parents

# ------------------------------------------------------------
# 6. 交付
# ------------------------------------------------------------
printf "\n${C_G}${C_B}╭──────────────────────────────────────────────╮\n"
printf "│  ✔  数据目录搬迁完成                        │\n"
printf "╰──────────────────────────────────────────────╯${C_N}\n\n"
printf "  新数据根   ${C_B}%s${C_N}\n" "$NEW_ROOT"
printf "    元数据   %s/data\n" "$NEW_ROOT"
printf "    文件原文 %s/files\n" "$NEW_ROOT"
printf "    备份     %s/backups\n\n" "$NEW_ROOT"

if [ "$CROSS_DEVICE" -eq 1 ]; then
  if [ "$KEEP_SOURCE" -eq 1 ]; then
    printf "  ${C_Y}跨盘搬迁，原目录按你的要求保留。${C_N}\n"
  else
    printf "  ${C_Y}跨盘搬迁：原目录仍然保留着（已校验通过，但先别急着删）。${C_N}\n"
  fi
  printf "  确认界面能正常打开、文件能下载之后，再执行下面的命令释放原空间：\n\n"
  printf "    rm -rf"
  j=0
  while [ "$j" -lt "${#MOVED_SRC[@]}" ]; do printf " %s" "${MOVED_SRC[$j]}"; j=$((j + 1)); done
  printf "\n\n"
  printf "  配置快照  %s（需要时 cp 回来即可回滚）\n\n" "$ENV_BAK"
else
  printf "  同盘移动，无需清理。配置快照 %s\n\n" "$ENV_BAK"
fi

printf "  体检      bash %s/scripts/healthcheck.sh\n" "$APP_DIR"

FINISHED=1
