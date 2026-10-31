#!/usr/bin/env bash
# ============================================================
# 端到端验证：备份导出/导入还原 + 升级后的版本核对
#
# 为什么用「一次性容器」而不是线上那套：
#   线上那套连着用户真实的 data/ 与 files/，
#   验证过程里的一次还原就会把用户的数据换成快照里的内容 ——
#   这种事不能拿用户的数据做实验。
#
# 这里起一个独立的后端容器：
#   - 独立的数据/文件/备份目录（都在临时目录里，验完删掉）
#   - KB_AUTH_ENABLED=false（本地验证不必先登录）
#   - 端口 18001（不碰线上的 8001）
#
# 覆盖两件事：
#   1) 备份能导出成文件、能从文件导入回来、导入后能还原
#   2) 升级后如果跑的还是旧版本，接口必须如实报失败（而不是谎报成功）
#
# 用法：
#   ./scripts/verify-backup-upgrade-e2e.sh            # 用本地镜像 kb-workbench-backend:latest
#   ./scripts/verify-backup-upgrade-e2e.sh <镜像>     # 指定镜像
# ============================================================
set -uo pipefail

cd "$(dirname "$0")/.."

IMAGE="${1:-kb-workbench-backend:latest}"
PORT="${KB_E2E_PORT:-18001}"
NAME="kb-e2e-backend"
TMP="$(mktemp -d /tmp/kb-e2e-XXXXXX)"
BASE="http://127.0.0.1:${PORT}/api"

PASS=0
FAIL=0

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
step() { printf '\n\033[36m▸\033[0m %s\n' "$*"; }

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

# ---- 起容器 ----
step "起一次性后端容器（镜像 ${IMAGE}）"
mkdir -p "$TMP/data" "$TMP/files" "$TMP/backups"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "${PORT}:8000" \
  -e KB_AUTH_ENABLED=false \
  -e DATA_DIR=/app/data \
  -e KB_FILE_STORE=fs \
  -e KB_FILE_STORE_DIR=/app/files \
  -e KB_BACKUP_DIR=/app/backups \
  -e DATABASE_URL="sqlite+aiosqlite:///./data/kb.db" \
  -v "$TMP/data:/app/data" \
  -v "$TMP/files:/app/files" \
  -v "$TMP/backups:/app/backups" \
  "$IMAGE" >/dev/null || { echo "容器起不来"; exit 1; }

printf '  等待服务就绪'
for i in $(seq 1 60); do
  if curl -fsS -m 2 "$BASE/health" >/dev/null 2>&1; then break; fi
  printf '.'; sleep 1
done
echo
HEALTH="$(curl -fsS -m 5 "$BASE/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
  echo "  服务没起来："; docker logs --tail 30 "$NAME"; exit 1
fi
VER="$(printf '%s' "$HEALTH" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))')"
ok "服务已就绪，版本 v${VER}"

# ==================== 1. 备份导出 ====================
step "备份：做一份快照并导出成文件"
BK="$(curl -fsS -m 120 -X POST "$BASE/system/storage/backup")"
SNAP="$(printf '%s' "$BK" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("name",""))')"
[ -n "$SNAP" ] && ok "已生成快照 $SNAP" || { bad "没拿到快照名：$BK"; }

LIST="$(curl -fsS -m 30 "$BASE/system/storage/backups")"
printf '%s' "$LIST" | grep -q "$SNAP" && ok "备份列表里有 $SNAP" || bad "备份列表里找不到 $SNAP"

EXPORT="$TMP/${SNAP}.tar.gz"
HTTP_CODE="$(curl -sS -m 300 -o "$EXPORT" -w '%{http_code}' \
  "$BASE/system/storage/backups/${SNAP}/export")"
if [ "$HTTP_CODE" = "200" ] && [ -s "$EXPORT" ]; then
  ok "导出成功（$(wc -c < "$EXPORT" | tr -d ' ') 字节）"
  tar tzf "$EXPORT" >/dev/null 2>&1 && ok "导出的是合法 tar.gz" || bad "导出的文件解不开"
else
  bad "导出失败（HTTP ${HTTP_CODE}）"
fi

# ---- 危险文件名必须被拒 ----
step "备份：越界文件名必须被拒"
CODE="$(curl -sS -m 20 -o /dev/null -w '%{http_code}' \
  "$BASE/system/storage/backups/..%2f..%2fetc%2fpasswd/export")"
case "$CODE" in
  400|403|404) ok "越界文件名被拒（HTTP ${CODE}）" ;;
  *) bad "越界文件名竟然通过了（HTTP ${CODE}）" ;;
esac

# ==================== 2. 本地导入 ====================
step "备份：把导出的文件再导入回来"
IMP="$(curl -fsS -m 300 -X POST "$BASE/system/storage/import" \
  -F "file=@${EXPORT};filename=${SNAP}.tar.gz")"
echo "  导入返回：$(printf '%s' "$IMP" | head -c 300)"
IMP_NAME="$(printf '%s' "$IMP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("name") or (d.get("entry") or {}).get("name",""))')"
[ -n "$IMP_NAME" ] && ok "导入成功，新快照名 $IMP_NAME" || bad "导入没返回快照名"

LIST2="$(curl -fsS -m 30 "$BASE/system/storage/backups")"
printf '%s' "$LIST2" | grep -q "$IMP_NAME" && ok "导入的快照出现在备份列表里" || bad "导入的快照没进列表"

# ---- 坏包必须被拒 ----
step "备份：坏包必须被拒"
BADPKG="$TMP/bad.tar.gz"
mkdir -p "$TMP/evil"
echo "not a db" > "$TMP/evil/kb.db"
tar czf "$BADPKG" -C "$TMP/evil" kb.db
CODE="$(curl -sS -m 60 -o /dev/null -w '%{http_code}' -X POST "$BASE/system/storage/import" \
  -F "file=@${BADPKG};filename=bad.tar.gz")"
case "$CODE" in
  400|422) ok "损坏的库文件被拒（HTTP ${CODE}）" ;;
  *) bad "损坏的库文件竟然通过了（HTTP ${CODE}）" ;;
esac

# ==================== 3. 用导入的快照还原 ====================
step "备份：用导入的快照还原"
if [ -n "$IMP_NAME" ]; then
  REST="$(curl -fsS -m 300 -X POST "$BASE/system/storage/restore" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"${IMP_NAME}\",\"confirm\":\"${IMP_NAME}\"}")"
  echo "  还原返回：$(printf '%s' "$REST" | head -c 300)"
  printf '%s' "$REST" | grep -q '"ok":true' && ok "还原成功" || bad "还原失败"
else
  bad "没有导入成功的快照，跳过还原"
fi

# ==================== 4. 升级后的版本核对 ====================
step "升级：版本没变时必须如实报失败"
STATE="$TMP/data/upgrade-state.json"
# 4a. 目标版本与运行版本不一致 → 必须判失败
cat > "$STATE" <<EOF
{"job_id":"e2e-mismatch","status":"restarting","stage":"restart",
 "target":"v9.9.9","current":"${VER}","log":"假想的升级日志\n"}
EOF
sleep 0.3
JOB="$(curl -fsS -m 20 "$BASE/system/update/job")"
echo "  作业状态：$(printf '%s' "$JOB" | head -c 400)"
printf '%s' "$JOB" | grep -q '"status":"failed"' && ok "版本不一致时判为失败" || bad "版本不一致却没判失败"
printf '%s' "$JOB" | grep -q '9\.9\.9' && ok "失败原因里写明了目标版本" || bad "失败原因里没有目标版本"
printf '%s' "$JOB" | grep -q "${VER}" && ok "失败原因里写明了当前运行版本" || bad "失败原因里没有当前版本"

# 4b. 目标版本与运行版本一致 → 必须判成功
cat > "$STATE" <<EOF
{"job_id":"e2e-match","status":"restarting","stage":"restart",
 "target":"v${VER}","current":"${VER}","log":"假想的升级日志\n"}
EOF
sleep 0.3
JOB2="$(curl -fsS -m 20 "$BASE/system/update/job")"
echo "  作业状态：$(printf '%s' "$JOB2" | head -c 400)"
printf '%s' "$JOB2" | grep -q '"status":"succeeded"' && ok "版本一致时判为成功" || bad "版本一致却没判成功"

printf '\n============================================================\n'
printf '通过 %s 项，失败 %s 项\n' "$PASS" "$FAIL"
[ "$FAIL" = "0" ] || exit 1
