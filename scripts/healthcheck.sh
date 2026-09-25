#!/usr/bin/env bash
#
# 知识工作台 —— 上线/巡检自检
#
#   ./scripts/healthcheck.sh
#
# 检查「服务能跑」之外的六件事，任何一项不过都算没准备好上生产：
#   1. 容器状态与健康检查
#   2. 后端存活 + 数据库自检（quick_check / 向量扩展）
#   3. 文件原文目录可写、磁盘余量充足
#   4. 备份目录可写、是否与数据分盘、最近一份备份是否太旧
#   5. 关键接口是否登录保护（未登录应返回 401，而不是 200）
#   6. 默认口令是否已改
#
# 退出码：0 = 全部通过；1 = 有警告；2 = 有严重问题
#
set -uo pipefail

cd "$(dirname "$0")/.."

# ---------- 读取 .env 里的实例配置 ----------
# 脚本不在 compose 的变量注入环境里，所以自己读一次 .env。
# 不读的话，同机多实例时项目名会退化成目录名，把跑得好好的容器判成「未启动」。
env_val() {
  local key="$1" default="$2" v
  v="$(grep "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- \
        | sed "s/^[\"']//;s/[\"']$//" || true)"
  printf '%s' "${v:-$default}"
}
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(env_val COMPOSE_PROJECT_NAME kb-workbench)}"
export COMPOSE_PROJECT_NAME

API="${KB_API:-http://127.0.0.1:$(env_val KB_BACKEND_PORT 8001)}"
WARN=0
FAIL=0

ok()   { printf "  ✓ %s\n" "$1"; }
warn() { printf "  ! %s\n" "$1"; WARN=$((WARN + 1)); }
bad()  { printf "  ✗ %s\n" "$1"; FAIL=$((FAIL + 1)); }

hr() { awk -v b="$1" 'BEGIN{ if (b>=1073741824) printf "%.2f GB", b/1073741824; else printf "%.1f MB", b/1048576 }'; }

echo "═══ 1. 容器状态 ═══"
if ! command -v docker >/dev/null 2>&1; then
  bad "找不到 docker 命令"
else
  # 变量一律写 ${}：后面紧跟全角标点时，bash 会把多字节字符的字节
  # 当成标识符的一部分，`$svc：` 会被解析成名为「svc<半个字>」的变量，
  # 在 set -u 下直接报 unbound variable
  for svc in backend frontend; do
    LINE="$(docker compose ps "$svc" --format '{{.State}} {{.Status}}' 2>/dev/null | head -1)"
    case "$LINE" in
      running*healthy*) ok "${svc}：${LINE}" ;;
      running*)         warn "${svc}：${LINE}（健康检查未通过或未定义）" ;;
      "")               bad "${svc}：未启动（docker compose up -d）" ;;
      *)                bad "${svc}：${LINE}" ;;
    esac
  done
fi

echo "═══ 2. 后端与数据库 ═══"
BODY="$(curl -fsS --max-time 5 "$API/api/health" 2>/dev/null || true)"
if [ -z "$BODY" ]; then
  bad "无法访问 $API/api/health"
else
  ok "接口可达"
  python3 - "$BODY" <<'PY'
import json, sys
h = json.loads(sys.argv[1])
db = h.get("db") or {}
qc = str(db.get("quick_check") or "unknown")
# unknown 不算失败：服务刚起来、后台首次探测还没跑完时会短暂处于这个状态。
# 真正的失败是 quick_check 返回了非 ok 的具体结果。
if qc.lower() == "ok":
    print("  ✓ 数据库快速自检：ok")
elif qc == "unknown":
    print("  ! 数据库自检结果尚未就绪（后台探测还没跑完，稍后重试）")
else:
    print(f"  ✗ 数据库快速自检异常：{qc}")
if db.get("stale"):
    print("  ! 数据库自检结果已过期 —— 后台定时维护可能已停摆（查 KB_MAINTENANCE_ENABLED 与日志）")
elif db.get("age_seconds") is not None:
    print(f"  ✓ 自检结果新鲜度：{db['age_seconds']} 秒前")
print(("  ✓ " if db.get("vec_available") else "  ! ") + "向量扩展 sqlite-vec：" +
      ("可用" if db.get("vec_available") else "不可用（语义检索会失效）"))
print(f"  · 版本 {h.get('version')}，鉴权 {'开启' if h.get('auth_enabled') else '关闭'}")
PY
  # 上面那段只负责打印，结论必须在这里落到退出码上 ——
  # 打印一个 ✗ 却不影响结论，是最容易骗过自己的一种「检查」
  DBSTATE="$(printf '%s' "$BODY" | python3 -c 'import json,sys; d=(json.load(sys.stdin).get("db") or {}); print("ok" if d.get("ok") else "bad")' 2>/dev/null || echo bad)"
  if [ "$DBSTATE" = "bad" ]; then
    bad "数据库自检未通过（详见上方输出）"
  fi
fi

echo "═══ 3. 文件原文目录 ═══"
DEEP="$(curl -fsS --max-time 30 "$API/api/health/deep" 2>/dev/null || true)"
if [ -z "$DEEP" ]; then
  warn "深度自检接口不可达（可能未登录或后端异常）"
else
  python3 - "$DEEP" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
fs = d.get("file_store") or {}
disk = fs.get("disk") or {}
def mb(b): 
    return f"{b/1073741824:.2f} GB" if b >= 1073741824 else f"{b/1048576:.1f} MB"
print(f"  · 存储模式：{fs.get('mode')}，目录 {fs.get('root')}")
print(f"  · 已存 {fs.get('files', 0)} 个文件 / {mb(fs.get('bytes', 0))}")
if disk.get("total"):
    free = disk.get("free", 0)
    flag = "✗" if free < 5 * 1024**3 else ("!" if free < 20 * 1024**3 else "✓")
    print(f"  {flag} 磁盘剩余 {mb(free)}（已用 {disk.get('pct_used')}%）")
b = d.get("backup") or {}
print(("  ✓ " if b.get("writable") else "  ✗ ") + f"备份目录可写：{b.get('dir')}")
PY
fi

echo "═══ 4. 备份新鲜度 ═══"
LATEST="$(ls -1dt backups/snap-* 2>/dev/null | head -1 || true)"
if [ -z "$LATEST" ]; then
  warn "没有任何快照备份。上生产前至少跑一次 ./scripts/backup.sh"
else
  AGE_H=$(( ( $(date +%s) - $(date -r "$LATEST" +%s) ) / 3600 ))
  if [ "$AGE_H" -le 48 ]; then ok "最近一份备份：$(basename "$LATEST")（$AGE_H 小时前）"
  else warn "最近一份备份已是 $AGE_H 小时前（$(basename "$LATEST")）—— 定时备份可能没在跑"; fi
  if [ -f "$LATEST/kb.db" ] && [ -d "$LATEST/files" ]; then
    ok "备份内容完整（kb.db + files/）"
  else
    warn "备份缺少 kb.db 或 files/，可能不完整"
  fi
fi
# 备份目录是不是真的和数据分了盘。
# 这里读的是**生效配置**（界面「系统设置 → 备份目录」改的就是它），
# 而不是宿主机的 KB_BACKUP_DIR —— 否则在界面上改过之后，这项检查会看错对象。
BDIR_INFO="$(docker compose exec -T backend python - <<'PY' 2>/dev/null || true
import json, sys
sys.path.insert(0, "/app")
from app.services import settings_store as ss

value, source = ss.effective("backup_dir")
info = ss.probe_dir(str(value))
info["blocked"] = ss._blocked_reason(str(value))
info["source"] = source
print(json.dumps(info, ensure_ascii=False))
PY
)"
if [ -n "$BDIR_INFO" ]; then
  printf '%s' "$BDIR_INFO" | python3 -c '
import json, sys
info = json.load(sys.stdin)
path = info.get("path", "")
if not info.get("ok"):
    print("  ✗ 备份目录不可用 %s：%s" % (path, info.get("error")))
elif info.get("blocked"):
    print("  ✗ 备份目录 %s：%s" % (path, info["blocked"]))
elif info.get("same_device_as_data"):
    print("  ! 备份目录 %s 与数据目录在同一块盘上：只防误删、防不了磁盘故障。" % path)
    print("    可在界面「系统设置 → 备份目录」切到已挂载的独立盘，立即生效、无需重启")
else:
    why = "按部署声明" if info.get("separate_declared") else "自动检测"
    print("  ✓ 备份目录 %s 与数据目录不同盘（%s）" % (path, why))
'
fi

echo "═══ 5. 接口鉴权 ═══"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/api/documents" 2>/dev/null || echo 000)"
if [ "$CODE" = "401" ]; then ok "未登录访问 /api/documents 返回 401"
elif [ "$CODE" = "000" ]; then bad "接口无响应"
elif [ "$CODE" = "200" ]; then bad "未登录就能读到数据 —— 鉴权可能被关闭（KB_AUTH_ENABLED=false）"
else warn "未登录访问返回 ${CODE}（预期 401）"; fi

echo "═══ 6. 默认口令 ═══"
ST="$(curl -fsS --max-time 5 "$API/api/auth/status" 2>/dev/null || true)"
if [ -n "$ST" ]; then
  INIT="$(printf '%s' "$ST" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("initial_password"))' 2>/dev/null || echo '?')"
  if [ "$INIT" = "True" ]; then
    bad "管理员仍是初始口令 —— 请立刻登录改密，或跑 scripts/reset-admin-password.sh"
  else
    ok "管理员口令已修改"
  fi
fi

echo
if [ "$FAIL" -gt 0 ]; then
  echo "结论：$FAIL 项严重问题、$WARN 项警告 —— 不建议上生产，请先处理。"
  exit 2
elif [ "$WARN" -gt 0 ]; then
  echo "结论：$WARN 项警告，无严重问题 —— 可以上生产，但建议逐条确认。"
  exit 1
else
  echo "结论：全部通过，可以上生产。"
  echo "提醒：上线后请定期跑一次恢复演练（restore.sh），并确认备份落在另一块物理盘。"
  exit 0
fi
