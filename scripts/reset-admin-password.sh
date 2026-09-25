#!/usr/bin/env bash
#
# 重置管理员口令（服务端运维脚本）
#
#   ./scripts/reset-admin-password.sh                 # 交互式输入，推荐
#   ./scripts/reset-admin-password.sh 'NewPass@2026'  # 直接给（会留在 shell 历史里，慎用）
#
# 只改口令、并作废该账号已发出的会话，不碰任何业务数据。
# 口令经 stdin 送进容器，不出现在 docker 命令行参数里。
#
set -euo pipefail

cd "$(dirname "$0")/.."

# 容器名可能带实例后缀（写在 .env 里）。脚本不在 compose 的变量注入环境里，
# 所以自己读一次 .env，否则找不到容器。
env_val() {
  local key="$1" default="$2" v
  v="$(grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- \
        | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "${v:-$default}"
}

CONTAINER="${KB_BACKEND_CONTAINER:-$(env_val KB_BACKEND_CONTAINER kb-backend)}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "找不到运行中的后端容器「${CONTAINER}」，请先 docker compose up -d" >&2
  exit 1
fi

NEW="${1:-}"
if [ -z "$NEW" ]; then
  read -r -s -p "请输入 admin 的新口令（至少 8 位）：" NEW; echo
  read -r -s -p "再输入一次确认：" AGAIN; echo
  if [ "$NEW" != "$AGAIN" ]; then
    echo "两次输入不一致，已取消" >&2
    exit 1
  fi
fi

if [ "${#NEW}" -lt 8 ]; then
  echo "口令至少 8 位，已取消" >&2
  exit 1
fi

TMP_PY="$(mktemp -t kb-reset-pw.XXXXXX)"
trap 'rm -f "$TMP_PY"' EXIT

cat > "$TMP_PY" <<'PY'
import asyncio
import sys

# 脚本是以文件路径执行的（stdin 要留给口令），sys.path[0] 会是 /tmp，
# 显式把镜像里的应用根目录加进来，否则 import app 会失败。
sys.path.insert(0, "/app")

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import User, UserSession
from app.services.auth import hash_password

new_password = sys.stdin.read()


async def main() -> int:
    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.username == "admin")
        )).scalar_one_or_none()
        if user is None:
            print("ERROR: 库里没有 admin 账号", file=sys.stderr)
            return 2

        user.password_hash = hash_password(new_password)
        # 手工重置的口令视为已确认，不再强制改密
        user.must_change_password = False
        user.is_active = True
        # 换口令必须作废既有会话，否则重置前登录的设备照样能用
        result = await db.execute(
            delete(UserSession).where(UserSession.user_id == user.id)
        )
        await db.commit()
        print(f"OK: admin 口令已重置（id={user.id}），作废会话 {result.rowcount or 0} 个")
    return 0


sys.exit(asyncio.run(main()))
PY

docker cp "$TMP_PY" "$CONTAINER:/tmp/kb_reset_pw.py" >/dev/null
trap 'rm -f "$TMP_PY"; docker exec "$CONTAINER" rm -f /tmp/kb_reset_pw.py >/dev/null 2>&1 || true' EXIT

printf '%s' "$NEW" | docker exec -i "$CONTAINER" python /tmp/kb_reset_pw.py
