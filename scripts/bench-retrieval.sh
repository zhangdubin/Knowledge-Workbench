#!/usr/bin/env bash
# 检索基准的外壳：把「被测代码」钉死，再跑 scripts/bench-retrieval.py
#
# 为什么需要这个外壳：
#   仓库是多人并行改的。测「优化前 vs 优化后」时，如果两边跑的是
#   不同版本的周边代码（别人刚加的字段、刚改的路由…），数字就不可比，
#   甚至会因为「某条 SQL 报错被吞掉」而显得变快了 —— 那不是优化，是假象。
#
# 所以这里造两个**只差我那几个文件**的环境：
#   base    = git HEAD 的代码（原样）
#   current = git HEAD 的代码 + 我改过的文件（其余一律用 HEAD 的）
#
# 用法：
#   scripts/bench-retrieval.sh base    --iterations 20
#   scripts/bench-retrieval.sh current --iterations 20
#   scripts/bench-retrieval.sh current --iterations 20 --json /tmp/after.json
#
# 环境变量：
#   KB_BENCH_IMAGE  镜像名（默认 kb-workbench-backend:latest）
#   KB_BENCH_KEEP=1 保留临时环境（排查时用）
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-current}"
shift || true
IMAGE="${KB_BENCH_IMAGE:-kb-workbench-backend:latest}"
KEEP="${KB_BENCH_KEEP:-0}"

if [ "$MODE" != "base" ] && [ "$MODE" != "current" ]; then
  echo "用法：$0 {base|current} [bench 参数...]" >&2
  exit 2
fi

# 我负责的文件：基准的「current」环境只叠加这些，
# 保证前后两次测的是同一套周边代码。
MY_FILES="
backend/app/services/document.py
backend/app/services/docindex.py
backend/app/services/embedding.py
backend/app/services/knowledge.py
backend/app/routers/search.py
backend/app/routers/knowledge.py
backend/app/config.py
backend/app/database.py
"

ENV_DIR="$(mktemp -d -t kb-bench-env-XXXXXX)"
cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "环境保留在 $ENV_DIR"
  else
    rm -rf "$ENV_DIR"
  fi
}
trap cleanup EXIT

# 1) HEAD 的代码
mkdir -p "$ENV_DIR/app"
git -C "$REPO" archive HEAD backend | tar -x -C "$ENV_DIR"
if [ ! -d "$ENV_DIR/backend/app" ]; then
  echo "取 HEAD 代码失败" >&2
  exit 1
fi

# 2) 叠加我改过的文件
if [ "$MODE" = "current" ]; then
  for f in $MY_FILES; do
    if [ -f "$REPO/$f" ]; then
      cp "$REPO/$f" "$ENV_DIR/$f"
    fi
  done
fi

echo "== 基准环境：${MODE}（${ENV_DIR}）=="

# 3) 在容器里跑（依赖齐全，还能访问外网测 embedding/大模型延迟）
docker run --rm \
  -v "$ENV_DIR/backend/app:/app/app:ro" \
  -v "$REPO/scripts:/scripts:ro" \
  -v "$REPO/data:/app/data:ro" \
  --entrypoint python "$IMAGE" \
  /scripts/bench-retrieval.py \
    --db /app/data/kb.db \
    --backend /app \
    "$@"
