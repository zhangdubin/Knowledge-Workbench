#!/usr/bin/env bash
# ============================================================
# 知识工作台 · 一键开启「自动升级」
#
# 在**宿主机**上跑（用户的服务器），做三件事：
#   1. 给编排文件的后端服务幂等地加三样东西：
#        - /var/run/docker.sock 挂进容器（后端要靠它驱动 docker）
#        - 安装目录挂进容器（后端要靠它找到项目目录、跑 compose）
#        - KB_PROJECT_DIR / KB_INSTALL_DIR 环境变量（告诉后端目录在哪）
#   2. 检查后端镜像里有没有 git / docker CLI / docker compose
#   3. 打印验证命令
#
# 为什么要有这个脚本：
#   「一键升级」要能跑起来，宿主机上得改编排文件。这三样东西缺一样都不行，
#   而让用户手改 YAML —— 缩进错了、挂漏了、变量名写错了 —— 十有八九会半途放弃，
#   最后变成「功能有，但没人用得上」。所以把它变成一条命令。
#
# 用法：
#   bash scripts/enable-one-click-upgrade.sh                 # 当前目录就是安装目录
#   bash scripts/enable-one-click-upgrade.sh --dir /opt/kb   # 指定安装目录
#   bash scripts/enable-one-click-upgrade.sh --dry-run       # 只看要做什么
#   bash scripts/enable-one-click-upgrade.sh --instance test # 隔离实例（别撞在跑的栈上）
#
# 幂等：重复跑不会重复加、不会报错、不会产生第二份备份噪音。
#
# 为什么这个脚本是**单文件**（不依赖 scripts/lib 下的其它文件）：
#   用户的服务器上往往只有这一个文件（scp 过去就能跑），
#   少一个依赖就少一次「脚本跑不起来」的机会。
#
# 两个 bash 3.2（macOS 自带）的坑，本脚本已经绕开，改的时候别踩回去：
#   1. 变量名后面紧跟中文标点时，必须写成 ${VAR}：
#      bash 会把全角括号当成变量名的一部分，于是报
#      "BACKEND_CONTAINER）: unbound variable"。
#   2. 空数组展开要写成 ${arr[@]+"${arr[@]}"}，否则 set -u 下会报 unbound variable。
# ============================================================
set -euo pipefail

INSTALL_DIR=""
COMPOSE_FILE=""
BACKEND_CONTAINER=""
DATA_DIR=""
INSTANCE=""
DRY_RUN=0

if [ -t 1 ]; then
  C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'
  C_C=$'\033[36m'; C_B=$'\033[1m'; C_N=$'\033[0m'
else
  C_R=""; C_G=""; C_Y=""; C_C=""; C_B=""; C_N=""
fi
step() { printf "\n${C_C}${C_B}▸ %s${C_N}\n" "$*"; }
ok()   { printf "  ${C_G}✔${C_N} %s\n" "$*"; }
warn() { printf "  ${C_Y}!${C_N} %s\n" "$*"; }
die()  { printf "\n${C_R}✘ %s${C_N}\n\n" "$*" >&2; exit 1; }
note() { printf "    %s\n" "$*"; }

usage() { sed -n '2,36p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    -d|--dir)           INSTALL_DIR="${2:-}"; shift 2 ;;
    -f|--compose-file)  COMPOSE_FILE="${2:-}"; shift 2 ;;
    -c|--container)     BACKEND_CONTAINER="${2:-}"; shift 2 ;;
    --data-dir)         DATA_DIR="${2:-}"; shift 2 ;;
    --instance)         INSTANCE="${2:-}"; shift 2 ;;
    --dry-run)          DRY_RUN=1; shift ;;
    -*) die "未知参数：$1" ;;
    *)  die "多余参数：$1" ;;
  esac
done

# ------------------------------------------------------------
# 0. 定位安装目录 / 编排文件 / 数据目录
# ------------------------------------------------------------
step "定位安装目录"
[ -n "$INSTALL_DIR" ] || INSTALL_DIR="$(pwd)"
INSTALL_DIR="$(cd "$INSTALL_DIR" 2>/dev/null && pwd)" || die "安装目录不存在：$INSTALL_DIR"
ok "安装目录: $INSTALL_DIR"

if [ -z "$COMPOSE_FILE" ]; then
  for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
    if [ -f "$INSTALL_DIR/$f" ]; then COMPOSE_FILE="$INSTALL_DIR/$f"; break; fi
  done
fi
[ -n "$COMPOSE_FILE" ] || die "在 $INSTALL_DIR 里找不到编排文件（docker-compose.yml / compose.yaml）"
[ -f "$COMPOSE_FILE" ] || die "编排文件不存在：$COMPOSE_FILE"
ok "编排文件: $COMPOSE_FILE"

# 数据目录：从 .env 里读（跟编排文件里的 ${KB_DATA_DIR:-./data} 对齐）
if [ -z "$DATA_DIR" ]; then
  if [ -f "$INSTALL_DIR/.env" ]; then
    DATA_DIR="$(sed -n 's/^[[:space:]]*KB_DATA_DIR[[:space:]]*=[[:space:]]*//p' "$INSTALL_DIR/.env" \
      | tail -1 | sed -e "s/[\"']//g" -e 's/[[:space:]]*$//' -e 's/\r$//')"
  fi
  [ -n "$DATA_DIR" ] || DATA_DIR="./data"
fi
case "$DATA_DIR" in
  /*) DATA_ABS="$DATA_DIR" ;;
  *)  DATA_ABS="$INSTALL_DIR/${DATA_DIR#./}" ;;
esac
ok "数据目录: $DATA_ABS"
if [ ! -d "$DATA_ABS" ]; then
  warn "数据目录还不存在（正常：第一次启动时才会建）"
fi

command -v docker >/dev/null 2>&1 || die "宿主机上没有 docker 命令 —— 这个脚本是给装好 Docker 的机器用的"

# ------------------------------------------------------------
# 1. 找后端容器
# ------------------------------------------------------------
step "定位后端容器"
if [ -z "$BACKEND_CONTAINER" ]; then
  if [ -n "$INSTANCE" ]; then
    # 与 install.sh --instance 同一套命名（kb-<实例>-backend）
    BACKEND_CONTAINER="kb-${INSTANCE}-backend"
  else
    BACKEND_CONTAINER="kb-backend"
  fi
fi
if docker ps --format '{{.Names}}' | grep -qx "$BACKEND_CONTAINER"; then
  ok "后端容器: $BACKEND_CONTAINER"
elif [ -n "$INSTANCE" ]; then
  die "找不到容器 ${BACKEND_CONTAINER}（--instance ${INSTANCE} 对应的容器没在跑）"
else
  # 没指定实例时给个提示，但继续往下走：编排文件照样能改
  warn "容器 ${BACKEND_CONTAINER} 当前没在跑（不影响改编排文件，但没法检查容器里的工具）"
fi

# ------------------------------------------------------------
# 2. 改编排文件（幂等）
# ------------------------------------------------------------
step "检查后端服务需要的挂载与环境变量"

# 编排文件的编辑用一段内嵌 Python 做：
#   - 纯文本处理，不依赖 PyYAML（目标机器上不一定装了）
#   - 只动 backend 服务里的 volumes / environment 两个列表
#   - 已存在的条目不重复加
#   - 用引号包住的 heredoc（<<'PY'）保证 python 代码原样传进去，
#     里面的 $ 不会被 shell 展开
if ! command -v python3 >/dev/null 2>&1; then
  die "需要 python3 来安全地改编排文件（没有它我不敢瞎改 YAML）。可以手动加下面这些，效果一样：
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - ${INSTALL_DIR}:/app/install
  environment:
    - KB_PROJECT_DIR=/app/install
    - KB_INSTALL_DIR=/app/install"
fi

if [ "$DRY_RUN" = "1" ]; then EDIT_MODE="plan"; else EDIT_MODE="apply"; fi

EDIT_OUT="$(python3 - "$COMPOSE_FILE" "$INSTALL_DIR" "$EDIT_MODE" <<'PYEOF'
import sys

compose_file, install_dir, mode = sys.argv[1], sys.argv[2], sys.argv[3]

# 要加的东西：
#   socket —— 后端要靠它驱动宿主机的 docker（拉镜像、build、up）
#   安装目录 —— 后端要靠它找到项目目录并在那个目录里跑 compose
VOLUME_ITEMS = [
    "/var/run/docker.sock:/var/run/docker.sock",
    install_dir + ":/app/install",
]
ENV_ITEMS = [
    "KB_INSTALL_DIR=/app/install",
    "KB_PROJECT_DIR=/app/install",
]


def ind(line):
    return len(line) - len(line.lstrip())


def key_of(line):
    """取行首的键名：'volumes:  # 注释' → 'volumes'；列表项 → 空串"""
    s = line.strip()
    if s.startswith("-"):
        return ""
    return s.split(":")[0].strip()


with open(compose_file, encoding="utf-8") as f:
    lines = f.read().split("\n")

# ---- 找 services: 段 ----
svc_idx = -1
svc_ind = 0
for i, line in enumerate(lines):
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    if key_of(line) == "services":
        svc_idx, svc_ind = i, ind(line)
        break
if svc_idx < 0:
    print("ERR: 编排文件里没有 services: 段")
    sys.exit(2)

# services 下面第一层的缩进（服务名所在的缩进）
child_ind = svc_ind + 2
for j in range(svc_idx + 1, len(lines)):
    s = lines[j].strip()
    if not s or s.startswith("#"):
        continue
    if ind(lines[j]) > svc_ind:
        child_ind = ind(lines[j])
        break

# ---- 找 backend 服务 ----
b_idx = -1
b_ind = 0
for j in range(svc_idx + 1, len(lines)):
    s = lines[j].strip()
    if not s or s.startswith("#"):
        continue
    if ind(lines[j]) < child_ind:
        break
    if ind(lines[j]) == child_ind and key_of(lines[j]) == "backend":
        b_idx, b_ind = j, ind(lines[j])
        break
if b_idx < 0:
    print("ERR: 编排文件里没有 backend 服务")
    sys.exit(2)

# backend 服务体到下一个同级键为止
b_end = len(lines)
for j in range(b_idx + 1, len(lines)):
    s = lines[j].strip()
    if not s or s.startswith("#"):
        continue
    if ind(lines[j]) <= b_ind:
        b_end = j
        break


def find_key(name):
    """在 backend 服务里找某个键，返回 (行号, 缩进)；找不到返回 None"""
    for j in range(b_idx + 1, b_end):
        s = lines[j].strip()
        if not s or s.startswith("#"):
            continue
        if ind(lines[j]) <= b_ind:
            break
        if key_of(lines[j]) == name:
            return j, ind(lines[j])
    return None


def list_items(key_idx, key_ind):
    """键下面的列表项（跳过注释与空行）"""
    out = []
    for j in range(key_idx + 1, b_end):
        s = lines[j].strip()
        if not s:
            continue
        if ind(lines[j]) <= key_ind:
            break
        if s.startswith("#"):
            continue
        out.append((j, s))
    return out


def plan_key(name, wanted):
    """算出 name 这个列表要补哪些条目（不改文件）

    返回 (插入位置, 要插入的行, [(列表名, 条目)])；
    键不存在时返回 None —— 那种情况要在服务体末尾新建一个键。
    """
    found = find_key(name)
    if found is None:
        return None
    k_idx, k_ind = found
    items = list_items(k_idx, k_ind)
    have = set()
    for _j, s in items:
        if s.startswith("-"):
            have.add(s[1:].strip())
    missing = [w for w in wanted if w not in have]
    if not missing:
        return (k_idx + 1, [], [])
    # 新条目的缩进：跟已有列表项一致；没有列表项就用 key 缩进 + 2
    item_ind = ind(lines[items[0][0]]) if items else k_ind + 2
    new_lines = [" " * item_ind + "- " + w for w in missing]
    return (k_idx + 1, new_lines, [(name, w) for w in missing])


# ---- 先把两个键都算出来，再统一写入 ----
#
# 为什么不在算的时候直接插：插一行会让后面所有行号往后挪，
# 第二个键（environment）的行号就全错了 —— 那种错不会报错，
# 只会「加到了别的地方」，比直接失败难查得多。
# 所以改成：先算计划，再**从后往前**插入，前面的插入不影响后面的行号。
todo = []
plan = []

for name, wanted in (("volumes", VOLUME_ITEMS), ("environment", ENV_ITEMS)):
    got = plan_key(name, wanted)
    if got is None:
        # 服务里没有这个键：在服务体末尾新建一个
        key_ind = b_ind + 2
        item_ind = key_ind + 2
        new_lines = [" " * key_ind + name + ":"]
        new_lines += [" " * item_ind + "- " + w for w in wanted]
        todo.append((b_end, new_lines, [(name, w) for w in wanted]))
        continue
    pos, new_lines, added = got
    if not new_lines:
        continue
    todo.append((pos, new_lines, added))

todo.sort(key=lambda t: -t[0])          # 行号大的先插
for pos, new_lines, added in todo:
    for off, nl in enumerate(new_lines):
        lines.insert(pos + off, nl)
    plan.extend(added)

if not plan:
    print("NOCHANGE")
    sys.exit(0)

for name, w in plan:
    print("ADD\t%s\t%s" % (name, w))

if mode == "plan":
    sys.exit(0)

# 写回（保留原来的换行风格与结尾）
out = "\n".join(lines)
with open(compose_file, "w", encoding="utf-8") as f:
    f.write(out)
PYEOF
)" || true

if printf '%s' "$EDIT_OUT" | grep -q '^ERR'; then
  die "改编排文件失败：$(printf '%s' "$EDIT_OUT" | grep '^ERR' | head -1)"
fi

if [ -z "$EDIT_OUT" ] || printf '%s' "$EDIT_OUT" | grep -q '^NOCHANGE'; then
  ok "编排文件已经齐了（不用改）"
else
  if [ "$DRY_RUN" = "1" ]; then
    warn "演练模式：以下改动**没有**写入（真跑时会写）"
  else
    BAK="$COMPOSE_FILE.bak-$(date +%Y%m%d%H%M%S)"
    cp "$COMPOSE_FILE" "$BAK"
    ok "已备份编排文件：$BAK"
  fi
  printf '%s\n' "$EDIT_OUT" | while IFS="$(printf '\t')" read -r _k _name _val; do
    [ "$_k" = "ADD" ] || continue
    ok "backend.${_name} += ${_val}"
  done
fi

# 改完立刻验一遍 YAML —— 手改编排文件最容易出的错就是缩进，
# 而缩进错了 docker compose 会直接报一堆看不懂的错
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if [ "$DRY_RUN" = "1" ]; then
    note "（演练模式：跳过编排文件校验）"
  elif docker compose -f "$COMPOSE_FILE" config --quiet 2>/dev/null; then
    ok "编排文件语法校验通过"
  else
    warn "编排文件校验没通过（docker compose config 报错）："
    docker compose -f "$COMPOSE_FILE" config --quiet 2>&1 | head -5 | sed 's/^/    /'
    note "已经备份过了，可以用备份文件还原：ls -t ${COMPOSE_FILE}.bak-* | head -1"
  fi
fi

# ------------------------------------------------------------
# 3. 后端镜像里有没有工具
# ------------------------------------------------------------
step "检查后端镜像里的升级工具"
HAS_DOCKER=0
HAS_COMPOSE=0

if docker ps --format '{{.Names}}' | grep -qx "$BACKEND_CONTAINER"; then
  if docker exec "$BACKEND_CONTAINER" sh -c 'command -v docker' >/dev/null 2>&1; then
    HAS_DOCKER=1
  fi
  if docker exec "$BACKEND_CONTAINER" sh -c 'docker compose version' >/dev/null 2>&1; then
    HAS_COMPOSE=1
  fi
  ok "已在运行中的容器里检查过（${BACKEND_CONTAINER}）"
else
  # 容器没跑：退而求其次，检查镜像本身
  # 镜像名要从编排文件里抠出来（backend 服务的 image: 行）。
  # 用 sed 而不是 tr 去掉引号：tr 的参数里同时要放单双引号，shell 引号嵌套太容易写错。
  IMAGE_NAME="$(sed -n '/^[[:space:]]*backend:/,/^[[:space:]]*[a-zA-Z]/p' "$COMPOSE_FILE" \
    | sed -n 's/^[[:space:]]*image:[[:space:]]*//p' | head -1 \
    | sed -e "s/[\"']//g" -e 's/\r$//')"
  if [ -n "$IMAGE_NAME" ] && docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c 'command -v docker' >/dev/null 2>&1; then
      HAS_DOCKER=1
    fi
    if docker run --rm --entrypoint sh "$IMAGE_NAME" -c 'docker compose version' >/dev/null 2>&1; then
      HAS_COMPOSE=1
    fi
    ok "已在镜像 ${IMAGE_NAME} 里检查过"
  else
    warn "容器没在跑、本地也没有这个镜像，跳过工具检查"
  fi
fi

# ------------------------------------------------------------
# 4. 结论 + 下一步
# ------------------------------------------------------------
step "结论"
if [ "$HAS_DOCKER" = "1" ] && [ "$HAS_COMPOSE" = "1" ]; then
  ok "后端镜像里 docker CLI 与 compose 插件都在 —— 重启后端即可开启一键升级"
  note "重启：cd ${INSTALL_DIR} && docker compose up -d --force-recreate backend"
else
  [ "$HAS_DOCKER" = "0" ] && warn "后端镜像里没有 docker CLI"
  [ "$HAS_COMPOSE" = "0" ] && warn "后端镜像里没有 docker compose 插件（它是插件形态，装 docker CLI 不会自动带上）"
  echo ""

  # ---- 本地已经有带工具的镜像？那就顺手换上，别让用户自己抄命令 ----
  #
  # 为什么自动做：让用户自己去敲那四行 docker 命令，
  # 十有八九会在某一行上敲错（尤其是 tag 的名字），
  # 然后卡在「我明明装了 docker 命令，怎么还是说没有」。
  # 能在本机直接做完的事，就别写成说明书。
  HOST_ARCH="$(docker info --format '{{.Architecture}}' 2>/dev/null | head -1)"
  case "$HOST_ARCH" in
    arm64|aarch64) TOOLS_TAG="arm64" ;;
    amd64|x86_64)  TOOLS_TAG="amd64" ;;
    *)             TOOLS_TAG="" ;;
  esac
  if [ -n "$TOOLS_TAG" ] && docker image inspect "kb-workbench-backend:tools-${TOOLS_TAG}" >/dev/null 2>&1; then
    step "本地已有带工具的后端镜像，直接换上"
    docker tag "kb-workbench-backend:tools-${TOOLS_TAG}" "kb-workbench-backend:latest"
    ok "标签已指向 kb-workbench-backend:tools-${TOOLS_TAG}"
    if ( cd "$INSTALL_DIR" && docker compose up -d --force-recreate backend ) >/dev/null 2>&1; then
      ok "后端容器已重建（等它健康）"
      sleep 3
      if docker exec "$BACKEND_CONTAINER" sh -c 'command -v docker && docker compose version' >/dev/null 2>&1; then
        HAS_DOCKER=1
        HAS_COMPOSE=1
        ok "工具已就位：docker CLI 与 compose 插件都在"
      else
        warn "重建后仍然没检测到工具，请手动看一眼：docker logs ${BACKEND_CONTAINER}"
      fi
    else
      warn "重建后端失败，编排文件没动过，可自己再试："
      note "cd ${INSTALL_DIR} && docker compose up -d --force-recreate backend"
    fi
  fi

  if [ "$HAS_DOCKER" = "1" ] && [ "$HAS_COMPOSE" = "1" ]; then
    ok "工具齐了 —— 现在可以点一键升级"
  else
  echo "  两条路，选一条："
  echo ""
  echo "  (a) 下载带工具的后端镜像（离线机器走这条）"
  echo "      # 架构按机器选（uname -m：aarch64→arm64，x86_64→amd64）"
  echo "      curl -LO https://github.com/zhangdubin/Knowledge-Workbench/releases/download/<版本>/kb-workbench-backend-tools-<arch>.tar.gz"
  echo "      docker load -i kb-workbench-backend-tools-<arch>.tar.gz"
  echo "      docker tag kb-workbench-backend:tools-<arch> kb-workbench-backend:latest"
  echo "      cd ${INSTALL_DIR} && docker compose up -d --force-recreate backend"
  echo ""
  echo "  (b) 用源码重建（能拿到源码时）"
  echo "      cd ${INSTALL_DIR}"
  echo "      docker build --target tools --build-arg INSTALL_UPGRADE_TOOLS=1 \\"
  echo "        --build-arg INSTALL_GIT=1 -t kb-workbench-backend:latest backend/"
  echo "      docker compose up -d --force-recreate backend"
  echo ""
  note "重建完记得再跑一次本脚本，它会重新检查工具并告诉你结果。"
  fi
fi

echo ""
step "验证"
echo "  docker exec ${BACKEND_CONTAINER} kb-upgrade-selftest"
echo ""
echo "  这一条会逐项检查：git / docker / docker.sock / compose / 部署目录。"
echo "  全部 [OK] 就能在「系统设置 → 升级与更新」里点一键升级了。"
echo ""

if [ "$DRY_RUN" = "1" ]; then
  warn "这是演练模式：编排文件没有被改动（上面的备份也没有生成）"
fi
