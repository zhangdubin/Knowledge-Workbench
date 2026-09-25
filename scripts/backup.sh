#!/usr/bin/env bash
#
# 知识工作台 —— 完整快照备份（库 + 文件原文）
#
#   ./scripts/backup.sh                  # 备份一次，保留最近 14 份
#   ./scripts/backup.sh --keep 30        # 保留 30 份
#   ./scripts/backup.sh --dir /mnt/nas/kb-backups   # 这一次备份到别处
#   ./scripts/backup.sh --set-dir /mnt/kb-backup    # 把默认备份目录改成容器内路径
#
# 备份内容（一份快照 = 一个目录）：
#   snap-<时间>/kb.db      元数据 + 全文索引 + 向量索引（VACUUM INTO 一致性副本）
#   snap-<时间>/files/     文件原文目录（增量：与上一份快照硬链接共享未变动的文件）
#   snap-<时间>/meta.json  校验结果、文件数、体积
#
# 为什么不是 cp 库文件：
#   库跑在 WAL 模式下，最新写入可能还只在 kb.db-wal 里。单拷 kb.db 会得到
#   一份「退回上一次检查点」的旧库；写入正在进行时还可能拷到撕裂的页。
#   这里用 SQLite 官方的 VACUUM INTO，走读事务快照拿一致性副本，顺带剔掉空闲页。
#
# 为什么必须一起备份 files 目录：
#   v0.3 起文件原文不再存在库里。只备份 kb.db 会得到一份「元数据完整、
#   内容全丢」的备份 —— 恢复后每个文件都点不开，而且要到那时候才会发现。
#
# 放到别的盘：
#   长期切换请用 `--set-dir`（或界面「系统设置 → 备份目录」，效果相同、立即生效）——
#   直接落到目标盘，才能保留硬链接增量。
#   `--dir` 是「先备再搬」，每次都要把快照搬一遍，只适合临时拷走一份。
#
set -euo pipefail

cd "$(dirname "$0")/.."

# 脚本需要知道 compose 里 volume 的宿主机路径，才能把后端返回的容器内路径
# 映射回宿主机路径。这里只读 .env 里的两个备份相关变量，避免 source 整个
# .env 把 KB_CORS_ORIGINS=[] 这种带特殊字符的值污染到环境。
read_env() {
  local key="$1" default="$2"
  local val
  val="$(grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "${val:-$default}"
}
KB_BACKUP_DIR="${KB_BACKUP_DIR:-$(read_env KB_BACKUP_DIR ./backups)}"
KB_BACKUP_ALT_HOST_DIR="${KB_BACKUP_ALT_HOST_DIR:-$(read_env KB_BACKUP_ALT_HOST_DIR ./backups-alt)}"

CONTAINER="${KB_BACKEND_CONTAINER:-$(read_env KB_BACKEND_CONTAINER kb-backend)}"
# compose 项目名同理：带实例后缀时，光靠目录名找不准实例
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(read_env COMPOSE_PROJECT_NAME kb-workbench)}"
export COMPOSE_PROJECT_NAME
KEEP=""
DEST="${KB_BACKUP_HOST_DIR:-}"
SET_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP="$2"; shift 2 ;;
    --dir)  DEST="$2"; shift 2 ;;
    # 注意这是**容器内**路径（不是宿主机路径）：设置项由后端读取，
    # 后端跑在容器里，只认得容器内的目录。
    --set-dir) SET_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "找不到运行中的后端容器「${CONTAINER}」。" >&2
  echo "备份不依赖服务运行，但脚本走容器内执行以保证与生产完全一致的环境，" >&2
  echo "请先 docker compose up -d" >&2
  exit 1
fi

# --set-dir：只改默认备份目录，不做备份。
# 它写的是与界面「系统设置 → 备份目录」同一份配置（data/bootstrap.json），
# 改完立即生效 —— 不再需要「改 .env 再重启容器」。
if [ -n "$SET_DIR" ]; then
  RESULT="$(docker exec -i "$CONTAINER" python - "$SET_DIR" <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
from app.services import settings_store as ss

out = asyncio.run(ss.set_many({"backup_dir": sys.argv[1]}, who="backup.sh"))
print(json.dumps(out, ensure_ascii=False))
PY
)"
  case "$RESULT" in
    *'"ok": true'*)
      echo "✓ 默认备份目录已设为 ${SET_DIR}（立即生效，界面「系统设置 → 备份目录」可见）"
      echo "  目标目录里已有的快照不会自动搬过去，需要的话手动 cp 一份。"
      exit 0
      ;;
    *)
      echo "✗ 设置失败：$RESULT" >&2
      echo "  常见原因：写成了宿主机路径（这里要的是容器内路径，如 /mnt/kb-backup），" >&2
      echo "            或该路径不在持久挂载点上（写进去容器一重建就没了）。" >&2
      exit 1
      ;;
  esac
fi

echo "▶ 正在做完整快照（库用 VACUUM INTO，文件目录用增量硬链接）..."

# --keep 通过命令行参数（而不是环境变量）下发：
# 容器里已经有 compose 下发的 BACKUP_KEEP，若继续用环境变量覆盖，
# 「运行期设置 vs 命令行」谁赢就取决于执行顺序；走 argv 最直白。
# 不传 = 用运行期设置里的保留份数（界面可改的那个值）。
# 必须带 -i：脚本正文是通过 stdin 送进去的，没 -i 容器内拿不到内容
RESULT="$(docker exec -i "$CONTAINER" python - "${KEEP:-0}" <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
from app.services import maintenance as m

arg = sys.argv[1] if len(sys.argv) > 1 else "0"
keep = int(arg) if arg.isdigit() and int(arg) > 0 else None
print(json.dumps(asyncio.run(m.make_backup(keep=keep)), ensure_ascii=False))
PY
)"

get() { printf '%s' "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))"; }

# 后端返回的是容器内绝对路径（如 /mnt/kb-backup/kb-backups/snap-...），
# 但脚本在宿主机跑，需要映射回宿主机路径才能 ls / mv / 轮转。
# 映射规则与 docker-compose.yml 里的 volume 一致。
host_path_for() {
  local cpath="$1"
  case "$cpath" in
    /app/backups) echo "${KB_BACKUP_DIR:-./backups}" ;;
    /app/backups/*) echo "${KB_BACKUP_DIR:-./backups}${cpath#/app/backups}" ;;
    /mnt/kb-backup) echo "${KB_BACKUP_ALT_HOST_DIR:-./backups-alt}" ;;
    /mnt/kb-backup/*) echo "${KB_BACKUP_ALT_HOST_DIR:-./backups-alt}${cpath#/mnt/kb-backup}" ;;
    *) echo "$cpath" ;;
  esac
}

OK="$(get ok)"
if [ "$OK" != "True" ]; then
  echo "✗ 备份失败：$RESULT" >&2
  exit 1
fi

CPATH="$(get path)"
NAME="$(get name)"
BYTES="$(get bytes)"
DB_BYTES="$(get db_bytes)"
FILES="$(get files_count)"
LINKED="$(get files_linked)"
COPIED="$(get files_copied)"

# 转成宿主机路径，用于 ls / mv / 提示
to_host() { host_path_for "$1"; }
SRC="$(to_host "$CPATH")"

hr() { awk -v b="$1" 'BEGIN{ if (b>=1073741824) printf "%.2f GB", b/1073741824; else printf "%.1f MB", b/1048576 }'; }

echo "✓ 快照完成：$NAME"
echo "  容器内路径 $CPATH"
echo "  宿主机路径 $SRC"
echo "  库文件    $(hr "$DB_BYTES")（quick_check = ok）"
# 变量一律用 ${} 包起来：后面紧跟全角标点，bash 会把多字节字符的字节
# 当成标识符的一部分，`$LINKED，` 会被解析成名为「LINKED<半个字>」的变量
echo "  文件原文  ${FILES} 个 / $(hr "$((BYTES - DB_BYTES))")（复用 ${LINKED}，新拷贝 ${COPIED}）"
echo "  快照总体积 $(hr "$BYTES")"

# ---- 搬到别处（可选）----
if [ -n "$DEST" ]; then
  mkdir -p "$DEST"
  if [ -e "$DEST/$NAME" ]; then rm -rf "$DEST/$NAME"; fi
  mv "$SRC" "$DEST/$NAME"
  SRC="$DEST/$NAME"
  echo "  已迁移至：$SRC"
  echo "  提示：想让后续备份直接落在这里（保留硬链接增量），用"
  echo "        ./scripts/backup.sh --set-dir <容器内路径>"
  echo "        或在界面「系统设置 → 备份目录」里点选 —— 两种方式效果相同，都立即生效。"
fi

# 后端已按运行期设置的 backup_keep 做过一次轮转；这里在宿主机侧再补一次，
# 以处理「--dir 迁走」或后端意外未跑完的场景（幂等）。
ROT_DIR="$(dirname "$SRC")"
LIMIT="${KEEP:-14}"
if [ -d "$ROT_DIR" ]; then
  COUNT=$(find "$ROT_DIR" -maxdepth 1 -type d -name 'snap-*' | wc -l | tr -d ' ')
  if [ "$COUNT" -gt "$LIMIT" ]; then
    find "$ROT_DIR" -maxdepth 1 -type d -name 'snap-*' | sort | head -n "$((COUNT - LIMIT))" | while read -r old; do
      rm -rf "$old"
      echo "  轮转删除旧快照：$(basename "$old")"
    done
  fi
fi

echo
echo "恢复到指定快照： ./scripts/restore.sh $SRC"
echo "⚠ 备份要真的可用，必须满足两条：① 定期跑通一次恢复演练；② 备份落在另一块物理盘上。"
