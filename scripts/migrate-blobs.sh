#!/usr/bin/env bash
#
# 知识工作台 —— 把库里剩余的 BLOB 原文外迁到文件目录
#
#   ./scripts/migrate-blobs.sh            # 循环跑到全部迁完
#   ./scripts/migrate-blobs.sh --batch 20 # 每次搬 20 个（默认 50）
#   ./scripts/migrate-blobs.sh --once     # 只跑一批，看看结果
#
# 为什么要在服务运行时迁：
#   迁移是「读 BLOB → 写文件 → 同事务清空该列」，走的是正常连接，
#   读写可以并行；不需要停服。分批提交让单次事务很短，中断后重跑即可续上。
#
# 迁完之后**必须**再做一次「整体重整（VACUUM）」才能真正缩小库文件：
#   清空 BLOB 只把页标记为空闲，空间仍在库里挂着，要等 VACUUM 重写库文件
#   才会归还给操作系统。
#
set -euo pipefail

cd "$(dirname "$0")/.."

CONTAINER="${KB_BACKEND_CONTAINER:-kb-backend}"
BATCH=50
ONCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --batch) BATCH="$2"; shift 2 ;;
    --once)  ONCE=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "后端容器「${CONTAINER}」未运行，请先 docker compose up -d" >&2
  exit 1
fi

echo "▶ 开始外迁（每批 $BATCH 个）..."
ROUND=0
TOTAL=0
while true; do
  ROUND=$((ROUND + 1))
  OUT="$(docker exec -i -e "BATCH=$BATCH" "$CONTAINER" python - <<'PY'
import asyncio, json, os, sys
sys.path.insert(0, "/app")
from app.services import maintenance as m
batch = int(os.environ.get("BATCH") or 50)
out = asyncio.run(m.run_op("externalize_blobs", batch=batch))
print(json.dumps({k: out.get(k) for k in
                  ("ok","result","moved","moved_bytes","remaining","errors")},
                 ensure_ascii=False))
PY
)"
  echo "  第 $ROUND 批：$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result"))')"

  MOVED="$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("moved") or 0)')"
  REMAIN="$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("remaining"))')"
  TOTAL=$((TOTAL + MOVED))

  if [ "$ONCE" = "1" ]; then break; fi
  # remaining < 0 表示查询失败；移动到 0 个且没有剩余才算结束
  if [ "${REMAIN:-0}" -le 0 ] 2>/dev/null; then break; fi
  if [ "$MOVED" = "0" ]; then
    echo "  本批没有可迁移的记录（可能都是空原文），停止循环"
    break
  fi
done

echo "✓ 本轮共外迁 $TOTAL 个文件，剩余 $REMAIN"

if [ "${REMAIN:-1}" -le 0 ] 2>/dev/null && [ "$TOTAL" -gt 0 ]; then
  echo
  echo "▶ 库内原文已清空，正在执行整体重整以真正回收空间..."
  echo "  （VACUUM 期间需要独占锁，会短暂阻塞所有请求；大库可能耗时数分钟）"
  docker exec -i "$CONTAINER" python - <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
from app.services import maintenance as m
print(json.dumps(asyncio.run(m.run_op("vacuum")), ensure_ascii=False))
PY
  echo
  echo "▶ 一致性普查："
  docker exec -i "$CONTAINER" python - <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
from app.services import maintenance as m
print(json.dumps(asyncio.run(m.run_op("verify_files")), ensure_ascii=False))
PY
fi

echo
echo "下一步建议：./scripts/backup.sh 做一份新快照（此时库文件已明显变小）"
