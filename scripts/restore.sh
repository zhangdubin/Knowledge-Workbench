#!/usr/bin/env bash
#
# 知识工作台 —— 从快照恢复（库 + 文件原文）
#
#   ./scripts/restore.sh                       # 交互式列出快照并选择
#   ./scripts/restore.sh backups/snap-20260924-220600
#   ./scripts/restore.sh backups/snap-20260924-220600 --db-only
#   ./scripts/restore.sh backups/snap-20260924-220600 --files-only
#
# v0.3 起一份备份是一个目录（kb.db + files/），所以恢复必须**两样一起换**：
#   只换库  → 记录指向的文件不在盘上，每个附件都打不开
#   只换文件 → 盘上文件与库里记录对不上，出现无主文件与死档
#
# 恢复是破坏性操作，所以脚本会：
#   1. 先校验目标快照的库真的能打开（打不开的一律拒绝，避免拿坏备份覆盖好数据）
#   2. 把当前线上状态另存为一份快照（库 + 文件），随时可以退回去
#   3. 停后端 → 换库（连同 -wal/-shm 一起清掉）+ 换文件目录 → 起后端 → 深度自检
#
set -euo pipefail

cd "$(dirname "$0")/.."

# ---------- 读取 .env 里的实例配置 ----------
# 容器名与 compose 项目名可能带实例后缀。脚本不在 compose 的变量注入环境里，
# 所以自己读一次 .env，否则 docker compose stop/start 会作用到错的实例上。
env_val() {
  local key="$1" default="$2" v
  v="$(grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- \
        | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "${v:-$default}"
}

CONTAINER="${KB_BACKEND_CONTAINER:-$(env_val KB_BACKEND_CONTAINER kb-backend)}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(env_val COMPOSE_PROJECT_NAME kb-workbench)}"
export COMPOSE_PROJECT_NAME
DATA_DIR="data"
LIVE="$DATA_DIR/kb.db"
FILE_DIR="files"

BACKUP=""
MODE="all"

while [ $# -gt 0 ]; do
  case "$1" in
    --db-only)    MODE="db"; shift ;;
    --files-only) MODE="files"; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) BACKUP="$1"; shift ;;
  esac
done

# ---- 选择备份 ----
if [ -z "$BACKUP" ]; then
  mapfile -t LIST < <(ls -1dt backups/snap-* 2>/dev/null || true)
  # 兼容 v0.2 的单文件备份（那种备份不含 files 目录）
  mapfile -t LEGACY < <(ls -1t backups/kb-*.db 2>/dev/null || true)
  ALL=("${LIST[@]}" "${LEGACY[@]}")
  if [ "${#ALL[@]}" -eq 0 ]; then
    echo "backups/ 下没有可用备份。先跑 ./scripts/backup.sh" >&2
    exit 1
  fi
  echo "可用备份（新 → 旧）："
  i=1
  for f in "${ALL[@]}"; do
    if [ -d "$f" ]; then
      SZ="$(du -sh "$f" 2>/dev/null | awk '{print $1}')"
      TAG="快照"
    else
      SZ="$(ls -lh "$f" | awk '{print $5}')"
      TAG="旧格式(无文件)"
    fi
    printf "  %2d) %-30s %8s  %-12s %s\n" "$i" "$(basename "$f")" "$SZ" "$TAG" \
      "$(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '')"
    i=$((i + 1))
  done
  read -r -p "选择序号（默认 1）：" PICK
  PICK="${PICK:-1}"
  BACKUP="${ALL[$((PICK - 1))]}"
fi

if [ ! -e "$BACKUP" ]; then
  echo "备份不存在：$BACKUP" >&2
  exit 1
fi

# ---- 归一化：找出库文件与文件目录 ----
if [ -d "$BACKUP" ]; then
  SNAP_DB="$BACKUP/kb.db"
  SNAP_FILES="$BACKUP/files"
else
  SNAP_DB="$BACKUP"
  SNAP_FILES=""
fi

if [ "$MODE" != "files" ] && [ ! -f "$SNAP_DB" ]; then
  echo "快照里找不到 kb.db：$BACKUP" >&2
  exit 1
fi
if [ "$MODE" = "files" ] && { [ -z "$SNAP_FILES" ] || [ ! -d "$SNAP_FILES" ]; }; then
  echo "这份备份没有 files 目录（v0.2 的旧格式只备份了库），无法只恢复文件" >&2
  exit 1
fi

# ---- 1. 校验备份的库 ----
if [ "$MODE" != "files" ]; then
  echo "▶ 校验备份：$(basename "$BACKUP")"
  CHECK="$(python3 - "$SNAP_DB" <<'PY'
import sqlite3, sys
p = sys.argv[1]
try:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    qc = c.execute("pragma quick_check").fetchone()[0]
    counts = {t: c.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("document", "entity_record", "document_chunk")}
    try:
        # 有多少条记录指向外置文件 —— 这个数与 files 目录的实际文件数
        # 对不上就说明快照不完整，恢复后会有一批附件打不开
        counts["fs_docs"] = c.execute(
            "select count(*) from document where storage='fs'").fetchone()[0]
    except sqlite3.Error:
        counts["fs_docs"] = 0
    print(f"{qc}|{counts}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
PY
)"

  case "$CHECK" in
    ok\|*) echo "  ✓ 校验通过：${CHECK#ok|}" ;;
    *) echo "✗ 备份不可用，已中止：$CHECK" >&2; exit 1 ;;
  esac

  # 完整性交叉核对：快照里有文件记录，却没有 files 目录 → 立刻拦下
  FS_DOCS="$(printf '%s' "${CHECK#ok|}" | python3 -c 'import ast,sys; print(ast.literal_eval(sys.stdin.read()).get("fs_docs",0))')"
  if [ "${FS_DOCS:-0}" -gt 0 ] && { [ -z "$SNAP_FILES" ] || [ ! -d "$SNAP_FILES" ]; }; then
    echo "✗ 快照中有 $FS_DOCS 个文件的原文外置在 files 目录，但这份备份没有 files 目录。" >&2
    echo "  恢复它会导致这些文件全部打不开。若要强行只恢复库，请加 --db-only。" >&2
    exit 1
  fi
fi

# ---- 2. 先把当前状态存成一份快照（退路） ----
echo "▶ 为当前线上状态留取退路..."
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  RESULT="$(docker exec -i "$CONTAINER" python - <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
from app.services import maintenance as m
print(json.dumps(asyncio.run(m.make_backup()), ensure_ascii=False))
PY
)" || true
  PRE="$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("name",""))' 2>/dev/null || true)"
  if [ -n "$PRE" ]; then
    echo "  退路快照：backups/${PRE}（库 + 文件，可用 restore.sh 退回）"
  else
    echo "  警告：退路快照创建失败，继续恢复将无法回退" >&2
    read -r -p "  仍要继续？(yes/no) " ANS
    [ "$ANS" = "yes" ] || { echo "已取消"; exit 1; }
  fi
else
  echo "  后端未在运行，跳过（退路只能靠已有的旧备份）"
fi

# ---- 3. 停服 → 换数据 ----
echo "▶ 停止后端（释放数据库锁）..."
docker compose stop backend >/dev/null

if [ "$MODE" != "files" ]; then
  echo "▶ 写入恢复的库文件..."
  cp "$SNAP_DB" "$LIVE"
  # WAL 与 shm 属于旧库的状态，留着会让新库读到旧内容，必须一起清掉
  rm -f "$LIVE-wal" "$LIVE-shm"
fi

if [ "$MODE" != "db" ] && [ -d "$SNAP_FILES" ]; then
  echo "▶ 同步文件原文目录..."
  mkdir -p "$FILE_DIR"
  if command -v rsync >/dev/null 2>&1; then
    # --delete 是必须的：快照里删掉的文件在线上也必须消失，
    # 否则会留下一批「库里没有、盘上还有」的无主文件
    rsync -a --delete "$SNAP_FILES/" "$FILE_DIR/"
  else
    rm -rf "$FILE_DIR"
    cp -R "$SNAP_FILES" "$FILE_DIR"
  fi
  echo "  已同步 $(find "$FILE_DIR" -type f | wc -l | tr -d ' ') 个文件"
fi

echo "▶ 启动后端..."
docker compose start backend >/dev/null

# ---- 4. 等健康并深度自检 ----
printf "  等待服务就绪"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  printf "."
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
  echo "✗ 后端未能就绪。查看日志：docker compose logs backend --tail 50" >&2
  echo "  若要回退：用上面那份退路快照再跑一次本脚本" >&2
  exit 1
fi

echo
echo "▶ 深度自检（库 + 文件目录一致性）..."
curl -fsS http://127.0.0.1:8001/api/health/deep | python3 -m json.tool 2>/dev/null || true

echo
echo "✓ 恢复完成。请核对："
echo "    - 文件数量与最近上传记录（打开几个附件确认能预览/下载）"
echo "    - 登录账号（备份里的口令与账号是备份时刻的状态）"
echo "    - 若仍有异常，用上面那份退路快照重跑本脚本即可退回"
