"""一键升级执行器 —— 把「检查到新版」变成「真的升上去」

背景：`services/update.py` 只负责**查**（GitHub 上有没有新 Release）。
这一模块负责**做**（把本机切到新版本并重建服务）。

为什么拆成两个文件：`update.py` 是老代码、已经被设置页依赖，
往里塞「起后台进程、重建容器」这类逻辑会把它搅浑；而且两者生命周期不同 ——
查是一次性的请求，做是一个跨分钟的后台作业。

**两种部署形态，两条自动升级路径**

| 形态 | 判据 | 步骤 |
| --- | --- | --- |
| 源码部署 `git` | 部署目录里有 `.git` | fetch → checkout → build → restart |
| 离线包部署 `offline` | 部署目录里有编排文件但**没有** `.git` | fetch-release → download → load → restart |

为什么必须分开：离线包安装的机器上**没有 git、没有源码**，
编排文件里只有 `image:`（预构建镜像）。对它跑 `git fetch` 只会得到
"git: command not found" —— 而这恰恰是用户最需要正确指引的时刻。
离线包的正路是：从 Release 下载镜像包 → `docker load` 导入 →
把架构标签提升成 `:latest`（编排文件引用的就是 `:latest`）→ `docker compose up -d`。

**执行流程与它的坑**

源码部署：

    1. git fetch origin --tags --force      快
    2. git checkout <tag>                   快
    3. docker compose build                 慢（但这段时间后端容器还活着）
    4. docker compose up -d --remove-orphans 快（会重建后端容器）

离线包部署：

    1. 查 GitHub Release，找镜像资产        快
    2. 下载镜像包到临时目录                  慢（几百 MB）
    3. docker load -i + docker tag → :latest 中
    4. docker compose up -d                 快（会重建后端容器）

第 4 步是整套流程里唯一「会把自己杀掉」的一步：正在跑的这个后端进程
就是 `kb-backend` 容器里的进程，`docker compose up -d` 重建容器时它会被
停掉。因此：

  - 前三步的日志必须**在第 4 步之前**就落到两个地方：内存缓冲（给还在
    活着的后端提供实时日志）+ 状态文件（给重启后的新容器提供历史日志）。
  - 第 4 步一执行，立刻把状态置为 `restarting` 并写盘。写不进去也无所谓
    —— 状态文件早就写好了。新容器起来后从状态文件读到 `restarting`，
    浏览器就知道「刚才那一步把服务重启了，不是升级失败」。
  - 前端要能扛住「第 4 步之后接口连不上」这件事：轮询失败不是错误，
    而是「正在重启服务，请稍候」。

**可行性判定**（任一不满足就退回「手动模式」，并说清缺什么）

  - 源码部署：项目目录里有 .git + 容器内能执行 git + 能执行 docker
    （/var/run/docker.sock 存在 + docker 可执行）+ 编排文件里有 build: 段
  - 离线包部署：能找到安装目录 + 容器内能执行 docker / compose +
    docker.sock 存在 + 目标版本的 Release 里挂着镜像资产
    （离线包的编排文件全是 image:，**没有** build: 段才对 —— 那才是它的常态）

**安全**

  - 需要 system_config 功能位（superuser 自动放行），见 routers/system.py
  - 源码部署时工作区不干净直接拒绝，并列出脏文件：升级会 checkout 覆盖
    工作区，本地改动会被冲掉，而且冲掉之后用户根本不知道少了什么
  - 同一时刻只允许一个升级作业：重复调用返回当前作业，而不是再起一个
    （两个作业抢同一个目录，第二个 checkout 会把第一个的构建产物搞乱）
  - 全程写审计日志
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from . import audit as audit_svc
from . import settings_store as ss
from . import update as upd

log = logging.getLogger("kb.upgrade")

# Docker 守护进程的套接字。容器里要靠它才能反向操作宿主机的容器
DOCKER_SOCK = "/var/run/docker.sock"
# 编排文件的候选名（按优先级）。compose v2 起推荐 compose.yaml，
# 但绝大多数存量项目还是 docker-compose.yml —— 两个都得认。
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
# 升级作业状态文件。放在数据目录里，因为数据目录是**持久化**的：
# 容器被第 4 步重启后，内存里的东西全没了，只有这个文件能把
# 「刚才升到哪一步了」留下来。
STATE_FILE = Path(settings.data_dir) / "upgrade-state.json"

# 作业状态
ST_PENDING = "pending"
ST_RUNNING = "running"
ST_RESTARTING = "restarting"   # 第 4 步已启动：服务即将中断
ST_SUCCEEDED = "succeeded"
ST_FAILED = "failed"

# 部署模式（与前端 utils/update.js 的 DEPLOY_MODE 对应）
MODE_GIT = "git"                # 源码部署：有 .git，能自己拉代码重建
MODE_OFFLINE = "offline"        # 离线包部署：靠新离线包 / Release 镜像资产升级

# 目标版本号的白名单。目标会直接进 `git checkout <tag>`，
# 哪怕不用 shell 也得防住「--upload-pack=...」这类被当成选项的输入。
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# 架构别名：docker 守护进程报的是 Go 的架构名（x86_64 / aarch64），
# 而镜像包与镜像标签用的是 docker 官方名（amd64 / arm64）。
# 认错了就会去下另一个架构的包 —— 那是最难查的一类故障：
# 拉下来才发现架构不对，白等几百 MB。
_ARCH_ALIASES = {
    "x86_64": "amd64", "amd64": "amd64", "x64": "amd64",
    "aarch64": "arm64", "arm64": "arm64", "armv8l": "arm64",
}

# 源码部署的步骤。顺序即执行顺序，note 里写清每一步「快还是慢」
# 「会不会断连接」—— 用户看着日志滚动时需要知道该等多久，而不是以为卡死了。
GIT_STAGE_DEFS = [
    {"key": "fetch", "title": "拉取远端 tag",
     "command": "git fetch origin --tags --force",
     "note": "快：从 GitHub 拉下所有版本标签"},
    {"key": "checkout", "title": "切换到目标版本",
     "command": "git checkout <tag>",
     "note": "快：工作区切到目标 tag（本地改动会消失，所以先查工作区是否干净）"},
    {"key": "build", "title": "重建镜像",
     "command": "docker compose build",
     "note": "慢：这一步期间后端容器还活着，日志能持续输出"},
    {"key": "restart", "title": "重启服务",
     "command": "docker compose up -d --remove-orphans",
     "note": "快：会重建后端容器，接口随即中断 —— 浏览器会自动等待"},
]

# 离线包部署的步骤
OFFLINE_STAGE_DEFS = [
    {"key": "fetch-release", "title": "查询 Release 镜像资产",
     "command": "GET /repos/<owner>/<repo>/releases/tags/<tag>",
     "note": "快：在 GitHub 上找这一版的镜像包"},
    {"key": "download", "title": "下载镜像包",
     "command": "下载 kb-workbench-images-<arch>.tar.gz 到临时目录",
     "note": "慢：几百 MB，走配置的出站代理"},
    {"key": "load", "title": "导入镜像并提升标签",
     "command": "docker load -i <包> && docker tag kb-workbench-backend:<arch> kb-workbench-backend:latest",
     "note": "中：编排文件引用的是 :latest，必须把架构标签提升成 latest"},
    {"key": "restart", "title": "重启服务",
     "command": "docker compose up -d",
     "note": "快：会用上新镜像重建容器，接口随即中断 —— 浏览器会自动等待"},
]

# 内存里的日志最多留这么多行。docker compose build 的输出可以上千行，
# 全留着会把接口响应撑大，而用户真正关心的通常只是最后几十行。
LOG_MAX_LINES = 3000
# 状态文件的落盘间隔（秒）。build 阶段日志刷得很快，
# 每行都落盘会把磁盘 IO 打满，而用户 1.5 秒才轮询一次，没必要更细。
FLUSH_INTERVAL = 0.4


# ==================== 小工具 ====================

def _git_cmd(pdir: Path, *args: str) -> list[str]:
    """拼一条 git 命令

    带 `-c safe.directory=<项目目录>`：容器里是 root，宿主项目目录是宿主
    用户拥有的，git 2.35.2 起会直接拒绝操作「归属可疑」的仓库
    （fatal: detected dubious ownership in repository）。加上这行才跑得动。
    """
    return ["git", "-c", f"safe.directory={pdir}", *args]


async def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 30) -> tuple[int, str]:
    """跑一条命令并收回全部输出（stdout+stderr 合并）。

    只用于「问一句」的场景（探测工具是否存在、读 git status），
    需要流式输出的升级步骤不走这里。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except (OSError, ValueError) as e:
        return 127, str(e)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "命令超时"
    return proc.returncode or 0, (out or b"").decode("utf-8", errors="replace")


def _env_dir() -> tuple[str, str]:
    """环境变量里配的部署目录（容器内路径）

    源码部署用 KB_PROJECT_DIR，离线包安装用 KB_INSTALL_DIR —— 两个都认，
    免得用户为了换个名字去改镜像。
    """
    for key in ("KB_INSTALL_DIR", "KB_PROJECT_DIR", "KB_UPGRADE_PROJECT_DIR", "PROJECT_DIR"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v, key
    return "", ""


def _find_root() -> tuple[Path | None, bool, str]:
    """定位部署根目录（里面放着编排文件的那个目录）

    返回 (目录, 有没有 .git, 来源说明)。
    找不到时目录为 None —— 调用方要把它当成「不可行」处理，
    而不是随便挑一个目录去 checkout / compose up。
    """
    env, env_key = _env_dir()
    if env:
        p = Path(env).expanduser()
        if not p.is_dir():
            return None, False, f"环境变量 {env_key} 指向的目录不存在"
        return p, (p / ".git").exists(), f"环境变量 {env_key}"

    # 自动探测：常见挂载点 + 从当前目录向上找。
    # 先找带 .git 的（源码部署），再找不带 .git 的（离线包安装）。
    candidates: list[Path] = [
        Path("/app/install"), Path("/app/project"), Path("/install"), Path("/project"),
        Path("/workspace"), Path("/host/install"), Path("/host/project"), Path("/mnt/install"),
    ]
    try:
        here = Path.cwd().resolve()
        candidates.append(here)
        candidates.extend(here.parents)
    except OSError:
        pass

    git_hit: Path | None = None
    offline_hit: Path | None = None
    for c in candidates:
        try:
            if not c.is_dir():
                continue
            if not any((c / f).exists() for f in COMPOSE_FILES):
                continue
            if (c / ".git").exists():
                if git_hit is None:
                    git_hit = c
            elif offline_hit is None:
                offline_hit = c
        except OSError:
            continue
    if git_hit is not None:
        return git_hit, True, "自动探测"
    if offline_hit is not None:
        return offline_hit, False, "自动探测"
    return None, False, "未找到"


def _compose_file(pdir: Path) -> Path | None:
    """项目目录里的编排文件"""
    for f in COMPOSE_FILES:
        p = pdir / f
        if p.is_file():
            return p
    return None


def _has_build_section(text: str) -> bool:
    """编排文件里有没有 build: 段

    离线包安装的编排文件全是 image:（用预构建镜像，没有源码可构建），
    没有 build: 段就没法「拉新代码 → 重建镜像」—— 那类安装只能换镜像包。

    优先用 YAML 解析（注释、缩进都认）；解析不了再退回逐行扫，
    因为线上编排文件偶尔带 compose 特有的语法，YAML 解析器可能不认。
    """
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        services = data.get("services") if isinstance(data, dict) else None
        if isinstance(services, dict):
            # 用 "build" in v 而不是 v.get("build")：build: 后面为空
            # （用默认上下文）也是合法写法，不该判成「没有 build 段」
            return any(isinstance(v, dict) and "build" in v for v in services.values())
    except Exception:
        pass
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("build:") or s.startswith("build "):
            return True
    return False


# ==================== 版本核对 ====================

# 版本号归一：GitHub 的 tag 写 "v0.6.9"，代码里写 "0.6.9"。
# 比版本时必须先归一 —— 否则 "0.6.9" != "v0.6.9"，
# 明明升上去了却被判成「没生效」，比不判还糟。
_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)")


def _norm_version(raw: str) -> str:
    """把版本号归一成「数字.数字.数字」（去掉 v 前缀与空白）"""
    s = str(raw or "").strip()
    m = _VERSION_RE.match(s)
    return m.group(1) if m else s.lstrip("vV")


def _same_version(a: str, b: str) -> bool:
    """两个版本号是不是同一个

    拿不到版本号时一律判「不同」—— 「不知道」不能当成「一样」，
    否则界面会为一个根本没核对过的状态报成功。
    """
    na, nb = _norm_version(a), _norm_version(b)
    return bool(na) and bool(nb) and na == nb


def _version_mismatch_message(running: str, target: str) -> str:
    """版本没对上时给用户看的一句话

    要回答三件事：现在跑的是哪一版、目标是哪一版、接下来查什么。
    只说「升级失败」等于把排查的活儿全推给用户。

    具体是「**哪一层**」没换成功（源码 / 镜像 / 容器 / 缓存），
    由 verify_running_version() 判定 —— 那儿能看见镜像与容器，
    这里看不见，所以这里给的是兜底的话 + 一个明确的下一步入口。
    """
    return (f"服务已重启，但运行的仍是 v{_norm_version(running)}"
            f"（目标 v{_norm_version(target)}）—— 升级没有真正生效。"
            "请点「重新核验」看是哪一层没换成功，并照着它给出的命令处理；"
            "也可以先执行 docker compose logs backend "
            "与 docker image inspect 确认镜像标签是否换成功。")


def _declared_version(config_text: str) -> str:
    """从 backend/app/config.py 的源码里读出它声明的 app_version

    不 import 那个文件（会拉起整套 pydantic 配置，还依赖运行目录），
    只按行找 `app_version: str = "0.6.9"` 这一行 ——
    读源码足够回答「这个 tag 里写的是哪个版本」。
    """
    m = re.search(r"""app_version\s*:\s*str\s*=\s*["']([^"']+)["']""", config_text)
    return m.group(1).strip() if m else ""


# ==================== 编排文件里的镜像引用 ====================

def _split_ref(ref: str) -> tuple[str, str]:
    """镜像引用 → (仓库名, 标签)

    "kb-workbench-backend:latest" → ("kb-workbench-backend", "latest")
    "kb-workbench-backend"        → ("kb-workbench-backend", "latest")
    """
    r = str(ref or "").strip()
    if "@" in r:                      # 形如 repo@sha256:... —— 摘要引用，用不上
        r = r.split("@", 1)[0]
    tail = r.rsplit("/", 1)[-1]
    if ":" in tail:
        repo, tag = r.rsplit(":", 1)
        return repo, tag
    return r, "latest"


def _resolve_image_ref(raw: str) -> str:
    """把编排文件里的 image 值解析成实际的镜像引用

    支持 compose 的变量写法（`${VAR:-默认值}`）。
    解析不出来就返回空串 —— 调用方会退回「按项目名拼」的兜底。
    """
    v = str(raw or "").strip().strip('"\'')
    if not v:
        return ""
    if "${" not in v:
        return v
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}", v)
    if m:
        var, default = m.group(1), m.group(2)
        env_val = (os.environ.get(var) or "").strip()
        if env_val:
            return env_val
        return (default or "").strip()
    # 混合写法（如 ${A}-${B}）不好还原，认不出来就当没有
    return ""


def _compose_project_name(text: str, fallback: str) -> str:
    """compose 的项目名（编排文件里的 name: 键，没有就用目录名）

    为什么重要：编排文件里不写 image: 时，compose 构建出来的镜像名是
    `<项目名>-<服务名>:latest`。项目名取错，标签就打错地方，
    compose up 起来的还是旧镜像 —— 而日志里看不出任何异常。
    """
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            n = str(data.get("name") or "").strip()
            if n:
                return n
    except Exception:
        pass
    # 兜底：逐行找顶格的 name:
    for line in text.splitlines():
        m = re.match(r"^name\s*:\s*(\S+)", line)
        if m:
            return m.group(1).strip().strip('"\'')
    return fallback


def _scan_compose_container_names(text: str) -> dict[str, str]:
    """逐行扫出 services 段里各服务写死的 container_name

    为什么需要它：自愈时要用 `docker compose up -d --force-recreate`
    换掉后端容器。但如果那个容器**不是 compose 建的**
    （用户手工 docker run 起的、或者项目名改过），
    compose 会因为「容器名已被占用」而失败 ——
    于是自愈看起来「开始了」，其实什么都没换。
    知道容器名之后，可以在失败时把它删掉再试一次。
    """
    out: dict[str, str] = {}
    in_services = False
    svc_indent: int | None = None
    current = ""
    for raw in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_services = stripped.rstrip(":") == "services"
            svc_indent = None
            current = ""
            continue
        if not in_services:
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$", stripped)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if svc_indent is None:
            svc_indent = indent
        if indent <= svc_indent:
            current = key
            out.setdefault(current, "")
            continue
        if current and key == "container_name" and val:
            out[current] = val.strip().strip('"\'')
    return out


def _scan_compose_images(text: str) -> dict[str, str]:
    """逐行扫出 services 段里各服务的 image 值（YAML 解析不可用时的兜底）

    手法与 `_has_build_section()` 一致：能用 YAML 就用 YAML，
    解析不了再退回逐行扫 —— 线上编排文件偶尔带 compose 特有的语法，
    YAML 解析器可能不认。
    """
    out: dict[str, str] = {}
    in_services = False
    svc_indent: int | None = None
    current = ""
    for raw in text.splitlines():
        # 只把「前面是空白的 #」当注释，避免误伤值里的 #
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_services = stripped.rstrip(":") == "services"
            svc_indent = None
            current = ""
            continue
        if not in_services:
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$", stripped)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if svc_indent is None:
            svc_indent = indent
        if indent <= svc_indent:
            current = key                      # 服务名
            out.setdefault(current, "")
            continue
        if current and key == "image":
            out[current] = val
    return out


def _compose_service_images(text: str, project: str) -> dict[str, str]:
    """编排文件里每个服务期望的镜像引用

    有 image: 就用它；没有就按 compose 自己的命名规则拼
    `<项目名>-<服务名>:latest`（这正是 compose build 出来的名字）。

    为什么必须知道这个：离线升级导入的是**架构标签**的镜像
    （kb-workbench-backend:amd64），而 compose 引用的是 :latest。
    不把新镜像打到 compose 真正引用的那个名字上，
    compose up 起来的还是旧镜像 —— 界面显示「升级完成」，实际没变。
    """
    services: dict[str, str] = {}
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        raw_services = data.get("services") if isinstance(data, dict) else None
        if isinstance(raw_services, dict):
            for name, svc in raw_services.items():
                ref = ""
                if isinstance(svc, dict):
                    ref = _resolve_image_ref(svc.get("image") or "")
                # 服务定义为空（`backend:` 底下什么都没有）也照样给个名字 ——
                # 编排文件写得再差，也不能因此漏掉给某个服务准备镜像。
                services[str(name)] = ref or f"{project}-{name}:latest"
            return services
    except Exception:
        pass
    # YAML 解析不了时的兜底
    scanned = _scan_compose_images(text)
    for name, raw_img in scanned.items():
        ref = _resolve_image_ref(raw_img) if raw_img else ""
        services[name] = ref or f"{project}-{name}:latest"
    return services


async def _detect_compose_cmd() -> tuple[list[str], str]:
    """找出可用的 compose 命令

    优先 `docker compose`（v2 插件形态），退化到 `docker-compose`（v1）。
    docker 存在不等于 compose 存在 —— compose 是**插件**，默认镜像里没有，
    所以必须实跑一次 `compose version` 才算数（只看文件在不在会误判）。
    """
    docker = shutil.which("docker")
    if docker:
        rc, _ = await _run([docker, "compose", "version"], timeout=15)
        if rc == 0:
            return [docker, "compose"], "docker compose"
    legacy = shutil.which("docker-compose")
    if legacy:
        rc, _ = await _run([legacy, "version"], timeout=15)
        if rc == 0:
            return [legacy], "docker-compose"
    return [], ""


def _norm_arch(raw: str) -> str:
    """docker 官方架构名（amd64 / arm64）"""
    v = (raw or "").strip().lower()
    return _ARCH_ALIASES.get(v, v)


async def _host_arch(docker: str | None) -> tuple[str, str]:
    """**宿主机**的架构（docker 守护进程所在那台机器的）

    为什么不能看容器自己的架构：容器可能被模拟执行（Apple Silicon 上跑
    x86 镜像就是 qemu 模拟），这时容器里 uname 报的是 x86_64，
    而宿主机其实是 arm64 —— 照着容器架构去下包，下回来的镜像宿主机跑不了。
    守护进程自己报的架构才是宿主机的。

    返回 (docker 官方架构名, 原始值)。
    """
    if docker:
        rc, out = await _run([docker, "info", "--format", "{{.Architecture}}"], timeout=25)
        raw = out.strip().splitlines()[0].strip() if out.strip() else ""
        if rc == 0 and raw:
            return _norm_arch(raw), raw
    return "", ""


# ==================== 服务端权威核验 ====================
#
# 为什么要有这一节：
# 以前「跑的是不是新版本」是**前端**拿 /api/health 的 version 跟目标比字符串。
# 两个问题：
#   1. 两端各写一份比较逻辑（v 前缀、字段个数），迟早有一处漏；
#   2. 前端看不见镜像、看不见容器，比对失败只能给一句
#      「升级没有真正生效，请检查 docker compose logs backend」——
#      把排查的活儿全推给用户。
#
# 现在由后端自己回答：它读得到自己容器的镜像 ID、读得到镜像里声明的版本、
# 读得到部署目录里源码声明的版本，于是能说清「**哪一层**没换成功」，
# 并给出对应的命令 —— 前端不再自己比两个字符串。

# 核验结论里的「层」。分层不是为了好看：
# 不同的层要不同的处置办法 —— 一句「升级没生效」只能让用户自己猜。
LAYER_OK = "ok"                   # 全部对得上
LAYER_SOURCE = "source"           # 源码没换：tag 里的代码就不是目标版本
LAYER_IMAGE = "image"             # 镜像没换：镜像里声明的版本不对
LAYER_CONTAINER = "container"     # 容器没重建：镜像是对的，容器还在跑旧的
LAYER_CACHE = "cache"             # 缓存没刷新：拿到的是旧响应

# 核验结果的缓存时间（秒）。核验要起一个临时容器读镜像里的 config.py，
# 前端在「等待服务恢复」期间每 2 秒问一次 —— 不缓存的话就是每 2 秒起一个容器。
VERIFY_CACHE_TTL = 10.0
_verify_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _parse_loaded_images(out: str) -> list[str]:
    """从 `docker load` 的输出里认出导入了哪些镜像

    docker load 的输出措辞各版本不同：
      老版本：Loaded image: kb-workbench-backend:arm64
      新版本（镜像没有标签名时）：Loaded image ID: sha256:xxxx

    只认第一种的话，第二种情况下认出来的列表是空的 ——
    于是新镜像**根本没被打上标签**，compose up 起来的还是旧镜像，
    而升级流程一路绿灯，最后报「升级完成，刷新后版本没变」。
    这正是这次要修的那个现象，所以两种措辞都要认。
    """
    return re.findall(r"Loaded image(?:\s+ID)?:\s*(\S+)", out or "")


def _versioned_ref(ref: str, version: str) -> str:
    """给镜像引用套一个版本化标签

    kb-workbench-backend:latest → kb-workbench-backend:1.0.0

    为什么要有版本化标签：编排文件里写死的是 :latest，
    而 :latest 是个**会被下一次构建覆盖的移动靶** ——
    出问题之后没人说得清「现在跑的到底是哪一版」。
    再打一个版本化标签，核验时就有了一个不会动的锚点：
    「1.0.0 这个标签指向的镜像，声明的版本是不是 1.0.0」。
    """
    repo, _tag = _split_ref(ref)
    v = _norm_version(version)
    return f"{repo}:{v}" if v else ""


async def _image_id(docker: str, ref: str) -> str:
    """某个镜像引用当前指向的镜像 ID（取不到就返回空串）

    「指向哪个镜像」和「镜像里声明的版本」是两件事：
    前者是一次 inspect 的事，后者要起个容器读文件 ——
    所以判层的时候先用便宜的那一个，只有需要时再花贵的那个。
    """
    if not ref or not docker:
        return ""
    rc, out = await _run([docker, "image", "inspect", "-f", "{{.Id}}", ref], timeout=30)
    return out.strip() if rc == 0 else ""


async def _self_image_info(docker: str) -> dict[str, Any]:
    """当前进程所在容器的镜像信息

    image_id 是「这个容器实际在跑的镜像」的 ID，
    image_ref 是容器启动时用的镜像名（通常是 :latest）。
    两者分开记，因为它们**可以不一致** ——
    那正是「容器没重建」的确切证据：
    标签已经指向新镜像了，容器却还在跑旧镜像。
    """
    info = await _self_container_info(docker)
    if not info:
        return {}
    cfg = info.get("Config") or {}
    return {
        "container_id": str(info.get("Id") or ""),
        "image_id": str(info.get("Image") or ""),
        "image_ref": str(cfg.get("Image") or ""),
    }


def _backend_ref(refs: dict[str, str]) -> str:
    """从编排文件解析出的镜像引用里挑出「后端服务」那个

    服务名可能不叫 backend（用户改过），镜像名里带 backend 的更可靠；
    都认不出来就退回约定名 —— 与 install.sh 的做法保持一致。
    """
    for name, ref in refs.items():
        if name == "backend" and ref:
            return ref
    for ref in refs.values():
        if ref and "backend" in ref:
            return ref
    for ref in refs.values():
        if ref:
            return ref
    return "kb-workbench-backend:latest"


def _verdict(running: str, target: str, image_declared: str = "",
             image_id_running: str = "", image_id_tag: str = "",
             source_declared: str = "") -> tuple[str, str]:
    """判定「差在哪一层」

    返回 (layer, reason)。这是纯函数：把各种已知的现场摆进去，
    它负责给出唯一的结论 —— 于是可以用脚本把每种情形都走一遍。

    判定顺序有讲究：从「最具体」往「最笼统」排。
    反过来会把「镜像是对的、只是容器没重建」误判成「镜像没换」，
    而这两者的处置命令完全不同（一个要 build，一个只要 up -d --force-recreate）。
    """
    want = _norm_version(target)
    got = _norm_version(running)
    if not want:
        return LAYER_IMAGE, "没有目标版本，无法核验升级是否生效"
    if not got:
        return LAYER_IMAGE, "拿不到当前运行的版本号，无法核验升级是否生效"
    if got == want:
        return LAYER_OK, f"当前运行版本 v{got}，与目标一致"
    # 镜像里就是目标版本 → 镜像换对了，是容器没跟上
    if image_declared and _norm_version(image_declared) == want:
        return (LAYER_CONTAINER,
                f"镜像里已经是 v{want}，但正在运行的容器还是 v{got} —— "
                "容器没有重建（或重建完又被换回了旧镜像）")
    # 标签指向的镜像与容器在跑的不是同一个 → 容器没跟上新镜像
    if image_id_tag and image_id_running and image_id_tag != image_id_running:
        return (LAYER_CONTAINER,
                f"镜像标签已经指向另一个镜像（{image_id_tag[:19]}），"
                f"但正在运行的容器跑的是（{image_id_running[:19]}）—— "
                "容器没有重建")
    # 部署目录里的源码就不是目标版本 → 源码没换
    if source_declared and _norm_version(source_declared) != want:
        return (LAYER_SOURCE,
                f"部署目录里的源码声明的是 v{_norm_version(source_declared)}，"
                f"不是 v{want} —— 源码没有切到目标版本")
    return (LAYER_IMAGE,
            f"镜像里声明的版本是 v{_norm_version(image_declared) or got}，"
            f"不是 v{want} —— 镜像没有换成目标版本")


def _fix_commands(layer: str, root: str, target: str, ref: str) -> list[str]:
    """每一层对应的处置命令（可以直接复制到宿主机上执行）

    为什么要给到命令这一级：只说「升级没生效」，用户能做的事只有重试；
    而重试在「容器没重建」这一层是**必然无效**的
    —— compose up -d 看到镜像 ID 没变就不会重建容器。
    """
    tag = target or "<目标版本>"
    cd = f"cd {root} && " if root else ""
    if layer == LAYER_SOURCE:
        return [
            f"{cd}git fetch origin --tags --force && git checkout {tag}",
            f"{cd}docker compose build",
            f"{cd}docker compose up -d --force-recreate --remove-orphans",
        ]
    if layer == LAYER_IMAGE:
        return [
            f"{cd}docker compose build",
            f"{cd}docker compose up -d --force-recreate --remove-orphans",
        ]
    if layer == LAYER_CONTAINER:
        return [
            f"{cd}docker compose up -d --force-recreate --remove-orphans",
        ]
    if layer == LAYER_CACHE:
        return [
            "curl -s -H 'Cache-Control: no-cache' "
            "http://127.0.0.1:8001/api/health",
        ]
    if ref:
        return [f"docker image inspect {ref}"]
    return []


async def _compose_refs(root: Path | None) -> tuple[dict[str, str], str]:
    """编排文件里各服务引用的镜像（顺带把项目名一起带出来）"""
    if root is None:
        return {}, ""
    cf = _compose_file(root)
    if cf is None:
        return {}, ""
    try:
        text = cf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    project = _compose_project_name(text, root.name)
    return _compose_service_images(text, project), project


async def verify_running_version(target: str = "", refresh: bool = False) -> dict[str, Any]:
    """服务端权威核验：现在跑的是不是目标版本

    返回结构固定，前端按字段渲染，不要去解析文案：

      ok                       —— 跑的就是目标版本
      running                  —— 当前运行进程声明的版本
      target / target_version  —— 目标版本（原始值 / 归一后的）
      image_ref                —— 编排文件里后端服务引用的镜像
      image_id                 —— 当前容器正在跑的镜像 ID
      image_id_tag             —— 那个标签当前指向的镜像 ID
      image_declared_version   —— 镜像里 backend/app/config.py 声明的版本
      source_declared_version  —— 部署目录里源码声明的版本
      layer                    —— 差在哪一层（ok/source/image/container/cache）
      reason                   —— 人话解释
      fix                      —— 下一步该做什么
      commands                 —— 可以直接复制执行的命令

    查不到镜像信息时（镜像里没装 docker CLI、没有 docker.sock）
    照样返回结论，只是 layer 退化成「image」并说明「查不了」——
    「查不了」不能被说成「一样」，但也不该让接口整个失败。
    """
    want = _norm_version(target)
    running = str(settings.app_version or "")
    cache_key = f"{want}|{_norm_version(running)}"
    if not refresh:
        hit = _verify_cache.get(cache_key)
        if hit and (time.monotonic() - hit[0]) < VERIFY_CACHE_TTL:
            return dict(hit[1])

    root, _has_git, _src = _find_root()
    refs, _project = await _compose_refs(root)
    ref = _backend_ref(refs)

    docker = shutil.which("docker") or ""
    self_info = await _self_image_info(docker) if docker else {}
    image_id_running = str(self_info.get("image_id") or "")
    container_id = str(self_info.get("container_id") or "")
    image_ref_in_use = str(self_info.get("image_ref") or "")

    image_id_tag = await _image_id(docker, ref) if docker else ""

    # 镜像里声明的版本：起一个临时容器读 config.py。
    # 读不到就返回空串 —— 「查不了」不等于「版本不对」。
    image_declared = ""
    if docker:
        image_declared = await _image_declared_version(docker, ref)

    # 部署目录里源码声明的版本：判「源码没换」这一层用。
    source_declared = ""
    if root is not None:
        try:
            source_declared = _declared_version(
                (root / "backend" / "app" / "config.py").read_text(
                    encoding="utf-8", errors="replace"))
        except OSError:
            source_declared = ""

    layer, reason = _verdict(running, target, image_declared,
                              image_id_running, image_id_tag, source_declared)
    if not docker and layer != LAYER_OK:
        reason += "（本机后端镜像里没有 docker 命令，无法进一步区分是哪一层）"

    commands = _fix_commands(layer, str(root or ""), target, ref)
    if layer == LAYER_OK:
        # 已经对了就别再给命令 —— 给一堆命令只会让人以为还有事要办
        commands = []
        fix = "升级已经生效，无需处理"
    else:
        fix = "；".join(commands) if commands else "请到服务器上查看升级日志"
    out: dict[str, Any] = {
        "ok": layer == LAYER_OK,
        "running": running,
        "target": target,
        "target_version": want,
        "image_ref": ref,
        "image_ref_in_use": image_ref_in_use,
        "image_id": image_id_running,
        "image_id_tag": image_id_tag,
        "container_id": container_id,
        "image_declared_version": image_declared,
        "source_declared_version": source_declared,
        "docker_available": bool(docker),
        "layer": layer,
        "reason": reason,
        "fix": fix,
        "commands": commands,
        "repairable": layer in (LAYER_SOURCE, LAYER_IMAGE, LAYER_CONTAINER),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _verify_cache[cache_key] = (time.monotonic(), dict(out))
    return out


# ==================== GitHub Release 资产 ====================

async def _release_assets(tag: str) -> tuple[list[dict[str, Any]], str]:
    """目标版本在 GitHub Release 上的资产列表

    复用 `services/update.py` 里已有的仓库配置、代理与 HTTP 客户端参数 ——
    同一份仓库、同一份代理，不另起一套，免得两边行为不一致
    （比如用户在界面上改了代理，这边却还在直连）。

    返回 (资产列表, 错误说明)。错误时列表为空。
    """
    cfg = upd.effective_config()
    repo_raw = (cfg.get("update_repo") or "").strip()
    if not repo_raw:
        return [], "未配置升级仓库：到「系统设置 → 升级与更新」填入 owner/name 并保存。"
    repo, err = ss.normalize_repo(repo_raw)
    if err:
        return [], f"升级仓库配置不合法：{err}"

    proxy = (cfg.get("update_proxy") or "").strip()
    # 直接用 update.py 的客户端参数（超时、UA、代理），不重写
    kwargs = upd._client_kwargs(proxy)
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        async with httpx.AsyncClient(**kwargs) as cli:
            r = await cli.get(url)
    except httpx.ProxyError:
        return [], f"连不上配置的代理 {proxy} —— 核对「系统设置 → 升级与更新」里的代理地址。"
    except httpx.ConnectError:
        return [], "连不上 api.github.com：容器没有出网（DNS 或防火墙拦截）。"
    except httpx.TimeoutException:
        return [], "访问 GitHub 超时：容器到 api.github.com 的链路不通。"
    except httpx.HTTPError:
        return [], "访问 GitHub 失败：网络请求没成功。"
    except Exception:
        return [], "访问 GitHub 失败：请求过程中出现意外错误。"

    if r.status_code == 404:
        return [], f"GitHub 上找不到 {tag} 这个 Release（仓库 {repo}）。"
    if r.status_code in (401, 403):
        return [], f"GitHub 拒绝了这次访问（{r.status_code}）：可能是未认证限额用完了，或仓库是私有的。"
    if r.status_code >= 400:
        return [], f"GitHub 返回了 {r.status_code}。"

    try:
        data = r.json()
    except Exception:
        return [], "GitHub 返回的内容不是预期的 JSON。"

    assets: list[dict[str, Any]] = []
    for a in (data.get("assets") or []):
        if not isinstance(a, dict):
            continue
        assets.append({
            "name": str(a.get("name") or ""),
            "size": int(a.get("size") or 0),
            "url": str(a.get("browser_download_url") or ""),
        })
    return assets, ""


def _pick_asset(assets: list[dict[str, Any]], arch: str) -> dict[str, Any] | None:
    """从 Release 资产里挑出本机架构的镜像包

    架构已知时**只认架构对得上的那个**：架构不对的包就算只有一个也不给 ——
    下错了要等几百 MB 才发现，跑起来还是 "exec format error"，
    比现在就报一句「这个版本没有 arm64 的包」糟糕得多。
    架构拿不到时（没有 docker CLI / socket）才退而求其次：
    只有一个候选就认它。
    """
    if not assets:
        return None
    cands = [a for a in assets
             if str(a.get("name") or "").startswith("kb-workbench-images-")
             and str(a.get("name") or "").endswith((".tar.gz", ".tgz"))]
    if arch:
        exact = f"kb-workbench-images-{arch}.tar.gz"
        for a in cands:
            if a.get("name") == exact:
                return a
        # 命名带额外后缀的变体（如 kb-workbench-images-linux-amd64.tar.gz）
        for a in cands:
            name = str(a.get("name") or "")
            if f"-{arch}" in name or f"_{arch}" in name:
                return a
        return None
    if len(cands) == 1:
        return cands[0]
    return None


# ==================== 升级作业 ====================

class UpgradeJob:
    """一个升级作业的状态

    状态机：

        pending → running →(前三步)→ restarting →(第 4 步，容器被重建)
                                 → succeeded / failed

    `restarting` 是个关键状态：它表示「服务正在重启，不是出错了」。
    前端看到它就应该转入「等待服务恢复」模式，而不是弹错误。
    """

    def __init__(self, job_id: str, target: str, current: str, root: str,
                 compose_cmd: str, who: str, mode: str, stage_defs: list[dict[str, Any]]):
        self.job_id = job_id
        self.target = target
        self.current = current
        self.root = root
        self.compose_cmd = compose_cmd
        self.who = who
        self.mode = mode
        self.status = ST_PENDING
        self.stage = ""
        self.error = ""
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.updated_at = self.started_at
        self.finished_at = ""
        self.log_lines: list[str] = []
        self.log_chars = 0
        self.log_truncated = False
        self.steps = [
            {"key": d["key"], "title": d["title"], "command": d["command"],
             "note": d["note"], "status": "pending"}
            for d in stage_defs
        ]
        self._last_flush = 0.0

    # ---- 日志 ----
    def log(self, text: str) -> None:
        if not text:
            return
        self.log_lines.append(text)
        self.log_chars += len(text) + 1
        # 只留尾部：build 输出动辄上千行，中间那些基本没人看
        while len(self.log_lines) > LOG_MAX_LINES:
            self.log_lines.pop(0)
            self.log_truncated = True

    def set_step(self, key: str, status: str) -> None:
        for s in self.steps:
            if s["key"] == key:
                s["status"] = status
                break

    def is_active(self) -> bool:
        """作业是否还在跑（决定能不能再起一个）"""
        return self.status in (ST_PENDING, ST_RUNNING, ST_RESTARTING)

    def snapshot(self) -> dict[str, Any]:
        """给前端的快照（不含内部字段）"""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "stage_title": next((s["title"] for s in self.steps if s["key"] == self.stage), ""),
            "target": self.target,
            "current": self.current,
            "mode": self.mode,
            "root": self.root,
            "compose_cmd": self.compose_cmd,
            "steps": [dict(s) for s in self.steps],
            "log": "\n".join(self.log_lines),
            "log_lines": len(self.log_lines),
            "log_truncated": self.log_truncated,
            "error": self.error,
            "who": self.who,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


# 全局只允许一个作业在跑
_current_job: UpgradeJob | None = None
# plan 结果的短缓存：可行性判定要跑好几次 git/docker 探测，
# 前端「检查更新」与「打开一键升级弹窗」往往会连着来，缓存一下省得重复探测。
_plan_cache: dict[str, Any] = {}
_PLAN_CACHE_TTL = 15.0


async def _flush_state(job: UpgradeJob, force: bool = False) -> None:
    """把作业状态写到状态文件

    为什么必须落盘：第 4 步会把后端容器重建掉，进程一死内存就没了。
    新容器里的后端只能靠这个文件还原「升级进行到哪一步、日志是什么」。
    """
    now = time.monotonic()
    if not force and (now - job._last_flush) < FLUSH_INTERVAL:
        return
    job._last_flush = now
    job.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = job.snapshot()

    def _write() -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, STATE_FILE)   # 原子替换：读到一半的半截 JSON 比没有更糟
        except OSError as e:
            log.warning("升级状态写盘失败：%s", e)

    # 放到线程里执行：build 阶段日志刷得频繁，同步写会卡住事件循环
    await asyncio.to_thread(_write)


def _save_state_file(data: dict[str, Any]) -> None:
    """原子替换状态文件（同步版）

    给「进程重启后要修正状态」这种低频路径用 ——
    _flush_state 是给正在跑的作业用的，走线程池。
    这里一个进程重启后的兜底修正，同步写一次无妨。
    """
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log.warning("升级状态写盘失败：%s", e)


def _read_state_file() -> dict[str, Any] | None:
    """读状态文件（重启后的后端靠它还原上一次升级的现场）"""
    try:
        if not STATE_FILE.is_file():
            return None
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as e:
        log.warning("升级状态文件读取失败：%s", e)
        return None


def _append_log(text: str, line: str) -> str:
    """往作业日志尾部追加一行"""
    if not line:
        return text or ""
    return f"{text}\n{line}" if text else line


def _audit_restored_verdict(job_data: dict[str, Any], action: str,
                            detail: dict[str, Any]) -> None:
    """给「重启之后才结算出来的升级结果」补一条审计

    为什么要有：正常升级路径里，成功/失败的审计是 `_run_job` 写的，
    而第 4 步会把那个进程杀掉 —— 于是走完一次升级，审计日志里
    反而什么都没有。这里补上，升级这件事才是有据可查的。

    get_job 是同步函数，不能 await 审计写入，所以用 create_task 挂到
    当前事件循环上。审计写失败绝不能把接口带崩 —— 整段都兜住。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return                      # 没有事件循环（测试环境）就跳过

    async def _safe_log() -> None:
        # 审计写失败（表不存在、字段对不上……）绝不能变成
        # 一个没人认领的 task 异常，把日志刷满。
        try:
            await audit_svc.log_event(
                str(job_data.get("who") or ""), action,
                resource="system_upgrade", method="POST",
                path="/api/system/update/apply",
                status=200 if action == "upgrade_succeeded" else 500,
                detail=detail,
            )
        except Exception:
            pass

    try:
        loop.create_task(_safe_log())
    except Exception:
        pass


def _settle_restarting_job(data: dict[str, Any]) -> dict[str, Any]:
    """把「重启中」的历史作业结算成「成功」或「失败」

    为什么必须核对版本：状态文件里的 restarting 是**上一个进程**写的，
    它没能看到新容器起来。现在能应答的这个进程只说明「服务回来了」——
    至于回来的是不是新版本，要看它自己的版本号。

    以前这里无条件判成功，于是「升级没生效」会被说成「升级完成」，
    用户刷新页面看到还是旧版本，却找不到任何报错 ——
    这正是这次要修的那个现象。

    结算结果要**写回状态文件**：不然下一次轮询又读到 restarting，
    同一段话会被追加进日志很多遍，日志框里全是重复。
    """
    running = str(settings.app_version or "")
    target = str(data.get("target") or "")
    if not target:
        # 没有目标版本可比对（比如作业没记下目标）：
        # 判成功不算错，但必须把「没核对过」讲清楚，不能假装核对过。
        out = {**data, "status": ST_SUCCEEDED,
               "note": "服务已重启完成（未记录目标版本，未核对版本号）"}
        _save_state_file(out)
        return out
    if _same_version(running, target):
        out = {**data, "status": ST_SUCCEEDED,
               "note": f"已确认运行版本 v{_norm_version(running)}"}
        _save_state_file(out)
        _audit_restored_verdict(out, "upgrade_succeeded", {
            "target": target, "running": running,
            "note": "重启后核对运行版本一致",
        })
        return out
    msg = _version_mismatch_message(running, target)
    out = {**data, "status": ST_FAILED, "error": msg,
           "note": "服务已重启，但版本没有变"}
    # 同一段话也要进日志：弹窗里的日志框是用户排障时唯一能看到的东西，
    # 只写进 error 字段的话，日志框里仍然是满屏「成功」的记录。
    out["log"] = _append_log(str(out.get("log") or ""), msg)
    try:
        out["log_lines"] = int(out.get("log_lines") or 0) + 1
    except (TypeError, ValueError):
        out["log_lines"] = 1
    _save_state_file(out)
    _audit_restored_verdict(out, "upgrade_failed", {
        "target": target, "running": running, "error": msg[:500],
        "note": "重启后核对运行版本不一致 —— 升级没有真正生效",
    })
    return out


def get_job(job_id: str = "") -> dict[str, Any]:
    """取当前作业状态

    内存里没有（说明容器刚重启过）就从状态文件恢复 —— 这正是
    「重启后前端还能看到刚才的日志」的实现方式。
    """
    job = _current_job
    if job is not None and (not job_id or job.job_id == job_id):
        return {"ok": True, "job": job.snapshot(), "restored": False}
    data = _read_state_file()
    if data and (not job_id or data.get("job_id") == job_id):
        # 状态停在「重启中」，而我们现在还能应答 —— 说明新容器已经起来了。
        # 但「服务回来了」不等于「升级生效了」：要拿这个进程自己的版本号
        # 跟作业的目标版本比一比，对不上就必须如实报失败。
        if data.get("status") == ST_RESTARTING:
            data = _settle_restarting_job(data)
        # 状态停在「运行中」，但内存里没有活着的作业 ——
        # 写这个状态的进程已经不在了（容器重启过、进程被杀了、宿主机断电）。
        # 谎称还在跑只会让前端转圈转到天荒地老，
        # 用户既看不到结果也没法重新发起（并发锁还占着）。
        # 这里如实说「中断了」，并把并发锁放开。
        elif data.get("status") in (ST_PENDING, ST_RUNNING):
            data = {**data, "status": ST_FAILED,
                    "error": "升级进程在完成前中断了（后端容器被重启过）。"
                             "请重新发起一次升级。"}
            _save_state_file(data)
        return {"ok": True, "job": data, "restored": True}
    if job is not None:
        return {"ok": True, "job": job.snapshot(), "restored": False}
    return {"ok": True, "job": None, "restored": False}


async def get_job_async(job_id: str = "") -> dict[str, Any]:
    """作业状态 + 实时日志（异步版：失败时顺带做一次服务端权威核验）

    为什么要有异步版：失败时要说清「**哪一层**没换成功」，
    而那要读镜像、读容器 —— 都是异步的 docker 调用。
    同步的 get_job() 保留着（老脚本与老调用方还在用）：
    状态与日志完全一致，只是拿不到分层结论。
    """
    res = get_job(job_id)
    job = res.get("job")
    if isinstance(job, dict) and job.get("status") == ST_FAILED and job.get("target"):
        verdict = await verify_running_version(str(job.get("target") or ""))
        res = {**res, "job": {**job, "verify": verdict}}
    return res


# ==================== 可行性判定 ====================

def _blocker(code: str, title: str, detail: str, fix: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail, "fix": fix}


def _warning(code: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail}


async def _dirty_files(pdir: Path) -> list[str]:
    """工作区里没提交的改动（升级会覆盖它们，所以必须先问清楚）"""
    rc, out = await _run(_git_cmd(pdir, "status", "--porcelain"), cwd=pdir, timeout=30)
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


async def _local_tags(pdir: Path) -> list[str]:
    """本地已有的 tag（判断目标版本是不是已经拉下来过）"""
    rc, out = await _run(_git_cmd(pdir, "tag", "--list"), cwd=pdir, timeout=30)
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _enable_commands(mode: str) -> list[str]:
    """「在宿主机上执行这几行就能开启自动升级」

    注意里面用的是 `<安装目录>` 占位符而不是容器内路径：
    这些命令是给**宿主机**上的用户执行的，容器内的路径（如 /app/install）
    在宿主机上根本不存在，直接给路径等于给一条跑不通的命令。
    """
    cmds = ["bash scripts/enable-one-click-upgrade.sh --dir <安装目录>"]
    if mode == MODE_GIT:
        # 源码部署还要把 git / docker 工具装进后端镜像。
        # Dockerfile 现在把「带工具」做成了独立的 stage（--target tools），
        # 编排文件里的 build.target 由这个环境变量控制。
        cmds.append("KB_BUILD_TARGET=tools docker compose build backend")
    cmds.append("cd <安装目录> && docker compose up -d backend")
    return cmds


def _manual_commands(mode: str, target: str) -> list[str]:
    """手动升级的命令（在宿主机上执行）"""
    if mode == MODE_OFFLINE:
        return [
            "# 离线包部署：下载新版离线安装包并解压，然后执行",
            "bash install.sh -d <安装目录>",
        ]
    return [
        "# 在**宿主机**的项目目录里执行（不是容器内）",
        "cd <项目目录>",
        "git fetch origin --tags --force",
        f"git checkout {target}" if target else "git checkout <目标版本>",
        "docker compose build",
        "docker compose up -d --remove-orphans",
    ]


def _human_size(n: int) -> str:
    """字节数 → 人看的体积（小文件也别说成 0MB）"""
    n = int(n or 0)
    if n >= 1048576:
        return f"{n // 1048576}MB"
    if n >= 1024:
        return f"{n // 1024}KB"
    return f"{n}B"


def _empty_plan(current: str, error: str, mode: str = MODE_OFFLINE,
                root: Path | None = None, source: str = "未找到") -> dict[str, Any]:
    """连目标版本都定不出来时的计划（前端据此显示错误）

    即便目标定不出来，部署形态也要报上去：前端要靠 mode 决定
    「给 git 命令」还是「给离线包指引」。
    """
    return {
        "ok": False, "error": error,
        "mode": mode, "feasible": False, "auto_upgrade_supported": root is not None,
        "current": current, "current_display": f"v{current}",
        "target": "", "has_update": False,
        "project_dir": str(root) if root else "",
        "install_dir": str(root) if root else "",
        "project_dir_source": source,
        "compose_file": "", "compose_cmd": "", "compose_cmd_args": [], "arch": "",
        "blockers": [], "warnings": [], "dirty_files": [],
        "steps": [], "manual_commands": [], "enable_commands": [],
        "release_assets": [], "notes": [],
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


async def build_plan(target: str = "", force: bool = False) -> dict[str, Any]:
    """可行性判定 + 步骤清单 + 手动命令

    返回里有两个容易混的字段，界面上要分开渲染：

      auto_upgrade_supported —— **这种部署形态**有没有自动升级的路可走。
        源码部署有（git fetch/checkout/build），离线包部署现在也有了
        （下载镜像包 → docker load → compose up）。
        它为 False 只剩一种情况：连部署形态都判不出来（既没有源码目录，
        也没有带编排文件的安装目录）。
      feasible —— **这台机器此刻**能不能升：工具齐不齐、目录找不找得到、
        目标版本的镜像资产在不在。缺什么都在 blockers 里逐条说明。

    `mode` 告诉前端这套部署是「源码部署」还是「离线包部署」：
    有 .git → git 模式；只有编排文件 → offline 模式。
    """
    now = time.monotonic()
    if not force and _plan_cache.get("target") == target:
        if now - _plan_cache.get("ts", 0) < _PLAN_CACHE_TTL:
            return dict(_plan_cache["result"])

    current = settings.app_version
    target = (target or "").strip()
    update_error = ""

    # ---- 部署形态（先判形态，再定目标）----
    # 顺序有讲究：形态跟目标版本无关，而前端要的恰恰是「即使查不到目标，
    # 也要告诉我这套部署是源码还是离线包」—— 两种形态的升级指引完全不同。
    root, has_git, dir_source = _find_root()
    mode = MODE_GIT if has_git else MODE_OFFLINE

    if not target:
        # 没指定目标版本时，去问一次更新检查（服务端有 10 分钟缓存）
        info = await upd.check_update()
        target = (info.get("latest") or "").strip()
        update_error = info.get("error") or ""
        if not info.get("ok") and not target:
            return _empty_plan(current, update_error or "无法确定目标版本",
                               mode=mode, root=root, source=dir_source)
    else:
        # 目标必须长得像版本号：它会直接进 `git checkout <tag>`
        if not _TAG_RE.match(target):
            return _empty_plan(current, f"目标版本「{target}」格式不合法",
                               mode=mode, root=root, source=dir_source)

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    dirty: list[str] = []
    notes: list[str] = []
    release_assets: list[dict[str, Any]] = []

    # 目标版本是否真的比当前版本新。用与更新检查同一套比较逻辑，
    # 免得界面上「已是最新」和「有新版本」两处说法打架。
    has_update = bool(target) and upd.is_newer(target, current)

    compose_file = _compose_file(root) if root else None
    compose_path = str(compose_file) if compose_file else ""

    has_build = False
    if compose_file:
        try:
            has_build = _has_build_section(compose_file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            has_build = False

    # ---- 工具探测（两种模式都需要）----
    git_bin = shutil.which("git")
    docker_bin = shutil.which("docker")
    compose_cmd, compose_label = await _detect_compose_cmd()
    has_socket = Path(DOCKER_SOCK).exists()
    arch, _arch_raw = await _host_arch(docker_bin)

    if root is None:
        if mode == MODE_GIT:
            blockers.append(_blocker(
                "project_dir_missing",
                "找不到项目目录",
                f"容器里找不到带 .git 与编排文件的项目目录（{dir_source}）。"
                "一键升级需要操作宿主机的项目目录。",
                "在编排文件里把项目目录挂进后端容器并设置环境变量 "
                "KB_PROJECT_DIR（例：- .:/app/project 与 - KB_PROJECT_DIR=/app/project）。",
            ))
        else:
            # 「找不到…（未找到）」是废话。找不到的时候，
            # 有价值的是「都找过哪些地方」—— 用户照着挂一次就明白了。
            tried = ""
            if dir_source == "未找到":
                tried = ("已经找过 /app/install、/app/project、/install、/project、"
                         "/workspace 这些常见挂载点，以及当前目录向上的每一层，"
                         "都没有带编排文件的目录。")
            else:
                tried = f"（{dir_source}）。"
            blockers.append(_blocker(
                "install_dir_missing",
                "找不到安装目录",
                f"容器里找不到带编排文件的安装目录。{tried}"
                "离线包升级要在安装目录里执行 docker compose up -d，"
                "容器里看不到安装目录就没法继续。",
                "在编排文件的后端服务里加两行："
                "- <安装目录>:/app/install 与 - KB_INSTALL_DIR=/app/install；"
                "或者在宿主机上执行 bash scripts/enable-one-click-upgrade.sh --dir <安装目录>。",
            ))

    if not docker_bin:
        blockers.append(_blocker(
            "no_docker_cli",
            "后端镜像里没装 docker 命令",
            "后端容器里没有 docker CLI，无法导入镜像、无法重建容器、无法重启服务。",
            "需要换用带工具的后端镜像（构建时用 --target tools，"
            "它会一并装上 docker CLI 与 compose 插件）。"
            "在宿主机上执行：bash scripts/enable-one-click-upgrade.sh --dir <安装目录>",
        ))
    if not has_socket:
        blockers.append(_blocker(
            "no_docker_socket",
            "容器里没有 docker socket",
            f"{DOCKER_SOCK} 不存在：后端容器没有接管宿主机的 docker 守护进程，"
            "跑不了 compose / docker load 命令。",
            "在编排文件的后端服务里加一行 - /var/run/docker.sock:/var/run/docker.sock，"
            "然后执行 docker compose up -d backend 生效。",
        ))
    if not compose_cmd:
        blockers.append(_blocker(
            "no_compose_cmd",
            "没有可用的 compose 命令",
            "docker compose 是插件形态，默认镜像里没有；docker-compose（v1）也没装。"
            "没有它就没法统一地 build / up 这套编排。",
            "需要换用带工具的后端镜像（构建时用 --target tools，"
            "它会一并装上 compose 插件），或改用手动升级。",
        ))

    # ---- 模式相关的检查 ----
    if mode == MODE_GIT:
        if not git_bin:
            blockers.append(_blocker(
                "no_git",
                "容器里没有 git",
                "后端镜像里没有 git 命令，无法拉取 tag、无法切换版本。",
                "构建后端镜像时用 tools 变体重建（KB_BUILD_TARGET=tools docker compose build backend），"
                "或改用离线包升级。",
            ))
        if compose_file and not has_build:
            blockers.append(_blocker(
                "no_build_section",
                "编排文件里没有 build: 段",
                f"{compose_file.name} 里的服务只有 image:，没有 build: —— "
                "意味着这套部署用的是预构建镜像，拉了新代码也重建不出镜像。",
                "改用离线包升级：下载新版离线安装包 → 解压 → bash install.sh -d <安装目录>。",
            ))
        if root and git_bin:
            rc, out = await _run(_git_cmd(root, "remote", "get-url", "origin"), cwd=root, timeout=20)
            if rc != 0:
                blockers.append(_blocker(
                    "no_origin",
                    "没有配置 origin remote",
                    "git 仓库里没有 origin，fetch 不到远端的 tag。",
                    "在项目目录里执行 git remote add origin <仓库地址>。",
                ))
        if root and git_bin and (root / ".git").exists():
            dirty = await _dirty_files(root)
            if dirty:
                blockers.append(_blocker(
                    "dirty_tree",
                    "工作区有未提交的改动",
                    "升级会 checkout 到目标 tag，把这些改动覆盖掉，而且覆盖之后"
                    "没法从版本库里找回来。",
                    "先提交（git commit -am '...'）或 stash 这些改动，再执行升级。",
                ))
            if target:
                tags = await _local_tags(root)
                if target not in tags:
                    warnings.append(_warning(
                        "tag_not_local",
                        "本地还没有目标版本的 tag",
                        "升级第一步会先 fetch 远端 tag，拉下来再切换，不影响升级。",
                    ))
        notes.append("第 4 步会重建后端容器，接口会短暂中断几秒到几十秒，浏览器会自动等待。")
    else:
        # 离线包部署：不需要 git，也不需要 build: 段（它本来就是 image:）
        if target:
            assets, asset_error = await _release_assets(target)
            release_assets = assets
            if asset_error:
                blockers.append(_blocker(
                    "release_lookup_failed",
                    "查不到目标版本的 Release",
                    asset_error,
                    "确认「系统设置 → 升级与更新」里的升级仓库与代理配置；"
                    "也可以手动下载离线包升级。",
                ))
            else:
                picked = _pick_asset(assets, arch)
                if picked is None:
                    names = "、".join(a.get("name") or "" for a in assets) or "（一个都没有）"
                    if not arch:
                        # 架构都探测不到，说「没有本机架构的镜像资产」是误导 ——
                        # 资产可能一个不少（arm64 / amd64 都有），
                        # 只是分不清该下哪一个。
                        # 这两种情况的解法完全不同，不能混成一条。
                        blockers.append(_blocker(
                            "unknown_arch",
                            "没能确定本机架构",
                            "容器里没有 docker 命令，探测不到宿主机的架构，"
                            "因此没法确认该下载哪个架构的镜像包"
                            f"（当前 Release 的资产：{names}）。",
                            "换成带 docker 命令的后端镜像后就能自动判断；"
                            "或者手动下载对应架构的镜像包升级。",
                        ))
                    else:
                        blockers.append(_blocker(
                            "no_release_asset",
                            "目标版本没有本机架构的镜像包",
                            f"{target} 这个 Release 里没有 {arch} 的镜像资产"
                            f"（当前 Release 的资产：{names}）。"
                            "离线包部署的自动升级靠下载镜像包完成，没有它就升不了。",
                            "让发版的人把 kb-workbench-images-<arch>.tar.gz 挂到这个 Release 上；"
                            "或者手动下载完整离线包升级。",
                        ))
                else:
                    notes.append(f"将下载 {picked.get('name')}（约 "
                                 f"{_human_size(picked.get('size'))}）并导入本机。")
        notes.append("最后一步会重建容器，接口会短暂中断几秒到几十秒，浏览器会自动等待。")

    # ---- 步骤清单 ----
    stage_defs = GIT_STAGE_DEFS if mode == MODE_GIT else OFFLINE_STAGE_DEFS
    steps = [dict(d) for d in stage_defs]
    for s in steps:
        if s["key"] == "checkout" and target:
            s["command"] = f"git checkout {target}"
        if s["key"] == "load" and arch:
            s["command"] = (f"docker load -i <包> && docker tag "
                            f"kb-workbench-backend:{arch} kb-workbench-backend:latest")

    feasible = not blockers
    # 形态层面支不支持自动升级：两种形态都有路可走；
    # 只有「连形态都判不出来」时才算不支持。
    auto_upgrade_supported = root is not None

    result = {
        "ok": True,
        "mode": mode,
        "feasible": feasible,
        "auto_upgrade_supported": auto_upgrade_supported,
        "current": current,
        "current_display": f"v{current}",
        "target": target,
        "has_update": has_update,
        "project_dir": str(root) if root else "",
        "install_dir": str(root) if root else "",
        "project_dir_source": dir_source,
        "compose_file": compose_path,
        "compose_cmd": compose_label,
        "compose_cmd_args": list(compose_cmd),
        "arch": arch,
        "blockers": blockers,
        "warnings": warnings,
        "dirty_files": dirty,
        "steps": steps,
        "manual_commands": _manual_commands(mode, target),
        "enable_commands": _enable_commands(mode),
        "release_assets": release_assets,
        "notes": notes,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _plan_cache["target"] = target
    _plan_cache["ts"] = now
    _plan_cache["result"] = dict(result)
    return result


# ==================== 执行 ====================

async def _drain(proc: asyncio.subprocess.Process, job: UpgradeJob,
                 sink: list[str] | None = None) -> None:
    """把子进程的输出逐行写进日志缓冲

    用 read(块) + 自己拆行，而不是 readline()：docker 的输出里存在
    没有换行结尾的超长行，readline() 遇到超过缓冲上限的行会直接抛异常。
    """
    buf = ""
    stream = proc.stdout
    if stream is None:
        return
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.rstrip("\r")
            job.log(line)
            if sink is not None:
                sink.append(line)
    if buf:
        line = buf.rstrip("\r")
        job.log(line)
        if sink is not None:
            sink.append(line)


async def _stage(job: UpgradeJob, key: str, cmd: list[str], cwd: Path,
                 timeout: float) -> str:
    """执行一个步骤，把输出流式写进日志。返回收集到的输出文本。"""
    job.stage = key
    job.set_step(key, "running")
    job.log(f"$ {' '.join(cmd)}")
    await _flush_state(job, force=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except (OSError, ValueError) as e:
        job.set_step(key, "failed")
        raise RuntimeError(f"无法执行 {cmd[0]}：{e}") from e

    sink: list[str] = []
    drain = asyncio.create_task(_drain(proc, job, sink))
    try:
        await asyncio.wait_for(drain, timeout=timeout)
    except asyncio.TimeoutError:
        drain.cancel()
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        job.set_step(key, "failed")
        raise RuntimeError(f"步骤「{key}」超时（{int(timeout)} 秒）") from None
    rc = await proc.wait()
    if rc != 0:
        job.set_step(key, "failed")
        raise RuntimeError(f"命令退出码 {rc}：{' '.join(cmd)}")
    job.set_step(key, "done")
    await _flush_state(job, force=True)
    return "\n".join(sink)


async def _download_asset(url: str, dest: Path, proxy: str, job: UpgradeJob) -> None:
    """把 Release 资产下载到本地文件

    走 update.py 里同一套代理配置 —— 用户在界面上配的代理对「检查更新」
    和「下载镜像包」必须是同一个，否则会出现「检查能连上、下载连不上」。

    带**断点续传的重试**。为什么必须有：
    镜像包 90MB 上下，服务器到 GitHub 的链路常常是抖的 ——
    下载中途断一次，之前就整包作废，用户只能从头再来。
    这里用 HTTP Range 从断处接着下，最多试 4 次；
    服务器不支持 Range（返回 200 而不是 206）就老实从头下。
    """
    kwargs = upd._client_kwargs(proxy)
    kwargs["timeout"] = httpx.Timeout(60.0, read=600.0, write=60.0, pool=60.0)
    # GitHub 的资产地址会 302 跳到对象存储，不跟重定向就只会拿到一个 302
    kwargs["follow_redirects"] = True

    total = 0
    for attempt in range(1, 5):
        done = dest.stat().st_size if dest.exists() else 0
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            async with httpx.AsyncClient(**kwargs) as cli:
                async with cli.stream("GET", url, headers=headers) as r:
                    if r.status_code >= 400:
                        raise RuntimeError(f"下载失败：HTTP {r.status_code}")
                    # 206 = 断点续传成功，200 = 服务器从头给（那就重头写）
                    if done and r.status_code != 206:
                        job.log("  服务器不支持断点续传，从头开始下载")
                        done = 0
                    cr = r.headers.get("content-range")
                    if cr and "/" in cr:
                        total = int(cr.rsplit("/", 1)[1])
                    else:
                        total = int(r.headers.get("content-length") or 0)
                    last_mark = done
                    mode = "ab" if done else "wb"
                    with dest.open(mode) as f:
                        async for chunk in r.aiter_bytes(256 * 1024):
                            f.write(chunk)
                            done += len(chunk)
                            # 每 10% 打一行进度，别刷屏
                            if total and done - last_mark >= max(1, total // 10):
                                last_mark = done
                                job.log(f"  下载中 {done * 100 // total}%"
                                        f"（{_human_size(done)} / {_human_size(total)}）")
            if total and done < total:
                raise RuntimeError(f"下载不完整：{done}/{total} 字节")
            job.log(f"  下载完成：{_human_size(done)}")
            return
        except Exception as e:
            if attempt >= 4:
                raise
            job.log(f"  第 {attempt} 次下载中断（{e}），"
                    f"已下载 {_human_size(done)}，3 秒后续传")
            await asyncio.sleep(3)


async def _self_container_info(docker: str) -> dict[str, Any]:
    """看自己这个容器的信息（镜像 ID、挂载关系）

    为什么要看自己的挂载：第 4 步的 compose up 是在**宿主机**上执行的，
    而我们只知道自己眼里的路径（比如 /app/install）。宿主机的真实路径
    得从挂载关系里反查出来 —— 传给 compose 的路径必须是宿主机的视角。
    """
    cid = os.environ.get("HOSTNAME", "").strip()
    if not cid:
        return {}
    rc, out = await _run([docker, "inspect", cid], timeout=30)
    if rc != 0 or not out.strip():
        return {}
    try:
        data = json.loads(out)
        return data[0] if isinstance(data, list) and data else {}
    except (ValueError, IndexError, TypeError):
        return {}


async def _run_in_helper_container(root: Path, script: str,
                                    log_path: str = ".upgrade-restart.log") -> tuple[bool, str]:
    """在宿主机上起一个**独立容器**执行一段 shell 脚本

    为什么必须独立：本容器就是 compose up 要重建的那个。
    容器一停，容器里的所有进程（包括 compose 客户端）一起被杀 ——
    compose 刚把新容器创建出来、还没 start，客户端就被腰斩了。
    实测现象：旧容器 Exited(0)、新容器卡在 Created（从没启动过），
    服务就此起不来，状态永远停在「重启中」。

    独立容器跑在宿主机上，不在本容器的进程树里，本容器被停掉也影响不到它，
    它照样能把 compose up 跑完。

    用的镜像是**当前正在跑的这个容器的镜像 ID**（不是 :latest 标签）：
    此刻 :latest 已经指向新镜像了，而新镜像未必带 docker/compose；
    老镜像一定带（能执行升级就说明它带）。

    返回 (是否起得来, 容器名)。起不来时调用方要自己兜底。
    """
    docker = shutil.which("docker") or "docker"
    info = await _self_container_info(docker)
    image_id = str(info.get("Image") or "")
    if not image_id:
        return False, ""

    cpath = str(root)                      # 容器眼里的安装目录
    hpath = ""                             # 宿主机上的安装目录
    for m in (info.get("Mounts") or []):
        if m.get("Destination") == cpath:
            hpath = str(m.get("Source") or "")
            break
    if not hpath:
        return False, ""

    name = f"kb-upgrade-restart-{uuid.uuid4().hex[:6]}"
    full = (f"sleep 2; cd {shlex.quote(cpath)} && ({script}) "
            f"> {shlex.quote(cpath)}/{log_path} 2>&1")
    cmd = [docker, "run", "-d", "--rm", "--name", name,
           "-v", "/var/run/docker.sock:/var/run/docker.sock",
           "-v", f"{hpath}:{cpath}",
           "-w", cpath,
           image_id,
           "sh", "-c", full]
    rc, out = await _run(cmd, timeout=120)
    if rc != 0:
        return False, ""
    return True, name


async def _start_restart_helper(job: UpgradeJob, plan: dict[str, Any],
                                root: Path, compose: list[str],
                                extra: list[str] | None = None) -> bool:
    """起一个**独立容器**去跑 compose up。

    为什么不能在本容器里直接跑 compose up：
    第 4 步要重建的后端容器，就是发起这条命令的这个容器。容器一停，
    容器里的所有进程（包括 compose 客户端）一起被杀 ——
    compose 刚把新容器创建出来、还没 start，客户端就被腰斩了。
    实测现象：旧容器 Exited(0)、新容器卡在 Created（从没启动过），
    服务就此起不来，状态永远停在「重启中」。

    独立容器跑在宿主机上，不在本容器的进程树里，本容器被停掉也影响不到它，
    它照样能把 compose up 跑完。

    用的镜像是**当前正在跑的这个容器的镜像 ID**（不是 :latest 标签）：
    此刻 :latest 已经指向新镜像了，而新镜像未必带 docker/compose；
    老镜像一定带（能执行升级就说明它带）。

    `extra` 是追加给 compose up 的参数（离线升级传 --no-build）：
    绝不能让 compose 拿本地源码重新构建 —— 那会把刚导入的新镜像盖掉。

    返回 False 表示起不来（调用方退回「在本容器里跑」的旧办法）。
    """
    inner = " ".join([*compose, "up", "-d", "--remove-orphans", *(extra or [])])
    ok, name = await _run_in_helper_container(root, inner)
    if not ok:
        job.log("  临时容器起不来（多半是镜像里没有 docker 命令或没有 docker.sock）")
        return False
    job.log(f"起一个临时容器执行重启（{name}）—— "
            f"它独立于本容器，本容器被停掉也不影响它把 compose 跑完")
    job.log(f"  临时容器已启动，日志见 {root}/.upgrade-restart.log")
    return True


async def _find_image_with_version(docker: str, candidates: list[str],
                                    want: str) -> str:
    """在候选镜像里找出「声明的版本 == 目标版本」的那一个

    为什么要找而不是直接用「最新的那个」：latest 指向哪个镜像是**上次构建**的事，
    它可能比目标版本新，也可能比目标版本旧。
    自愈时必须确认拿到的那个镜像里装的确实是目标版本，
    否则就是「换了个容器，还是不对」。
    """
    want = _norm_version(want)
    for ref in candidates:
        if not ref:
            continue
        if not await _image_id(docker, ref):
            continue
        declared = await _image_declared_version(docker, ref)
        if declared and _norm_version(declared) == want:
            return ref
    return ""


async def repair_running_version(target: str, who: str = "") -> dict[str, Any]:
    """自愈：核验不通过时，强制换镜像并重建容器

    为什么要自愈：用户点完「一键升级」之后，唯一能做的事就只剩「重启一下试试」。
    而「docker compose up -d」在**镜像 ID 没变**时**不会重建容器** ——
    于是「再点一次升级」也修不好（跑的还是同一个镜像）。
    「--force-recreate」才是那个能真正换掉容器的开关。

    自愈分三步，按需要执行：
      1. 找一个声明了目标版本的镜像（版本化标签 / latest / 当前容器在跑的那个）；
      2. 把它打到编排文件真正引用的那个标签上（顺便打一个版本化标签）；
      3. 「docker compose up -d --force-recreate」重建容器。

    找不到「声明了目标版本的镜像」时（说明源码本身就不对），
    退回到「切 tag + 重新构建」—— 那是源码没换那一层的处置办法。

    为什么要用独立容器执行：本容器就是第 3 步要重建的那个，
    容器一停，里面的进程一起被杀（详见 _run_in_helper_container）。
    所以本函数**先返回、稍后再动手**（独立容器里先 sleep 2 秒），
    保证前端能收到「已开始自愈」的答复。
    """
    verdict = await verify_running_version(target, refresh=True)
    if verdict.get("ok"):
        return {**verdict, "repair_started": False,
                "note": "核验已通过，无需自愈"}

    want = _norm_version(target)
    docker = shutil.which("docker") or ""
    compose, _label = await _detect_compose_cmd()
    root, has_git, _src = _find_root()
    layer = str(verdict.get("layer") or LAYER_IMAGE)

    commands = list(verdict.get("commands") or [])
    base: dict[str, Any] = {
        **verdict,
        "repair_started": False,
        "commands": commands,
        "note": "",
    }
    if not docker or not compose or root is None:
        base["note"] = ("无法自动自愈："
                        + ("后端镜像里没有 docker 命令；" if not docker else "")
                        + ("找不到 compose 命令；" if not compose else "")
                        + ("找不到部署目录。" if root is None else "")
                        + "请在宿主机上按下面的命令手工处理。")
        return base

    refs, _project = await _compose_refs(root)
    ref = _backend_ref(refs)
    repo, _tag = _split_ref(ref)
    versioned = _versioned_ref(ref, want)

    # 找一个「里面确实是目标版本」的镜像
    running_image_id = str(verdict.get("image_id") or "")
    source_ref = await _find_image_with_version(
        docker, [versioned, ref, running_image_id], want)

    steps: list[str] = []
    if source_ref and source_ref != ref:
        steps.append(f"docker tag {source_ref} {ref}")
    if source_ref and versioned and versioned != ref:
        steps.append(f"docker tag {source_ref} {versioned}")

    need_build = False
    if not source_ref:
        # 找不到目标版本的镜像 → 源码多半也不对，得重新构建
        need_build = True
        if has_git and shutil.which("git"):
            steps.append(f"git -c safe.directory={root} fetch origin --tags --force")
            steps.append(f"git -c safe.directory={root} checkout {target}")
        else:
            base["note"] = ("找不到声明了目标版本的镜像，而本机又没有 git "
                            "（源码部署的机器）—— 无法自动重建。"
                            "请到宿主机上下载新版离线包重新安装，或执行下面的命令。")
            return base

    if need_build:
        steps.append(" ".join([*compose, "build"]))

    up_cmd = " ".join([*compose, "up", "-d", "--force-recreate", "--remove-orphans"])

    # compose up 有时会因为「容器名已被占用」失败：
    # 那个占名的容器**不是 compose 建的**（用户手工 docker run 起的、
    # 或者项目名改过），compose 认不出它、也不肯接管它。
    # 这时候先把占名的容器删掉再试一次 —— 它本来就要被重建掉。
    compose_text = ""
    cf = _compose_file(root)
    if cf is not None:
        try:
            compose_text = cf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            compose_text = ""
    names = [v for v in _scan_compose_container_names(compose_text).values() if v]
    if names:
        rm = "; ".join([f"docker rm -f {n} || true" for n in names])
        steps.append(f"{up_cmd} || {{ {rm}; {up_cmd}; }}")
    else:
        steps.append(up_cmd)
    script = "set -e; " + "; ".join([s for s in steps if s])

    ok, name = await _run_in_helper_container(root, script, ".upgrade-repair.log")
    if not ok:
        base["note"] = ("起不了用于自愈的临时容器"
                        "（多半是后端镜像里没有 docker 命令或没有挂 docker.sock）"
                        "—— 请在宿主机上按下面的命令手工处理。")
        return base

    base["repair_started"] = True
    base["helper_container"] = name
    base["note"] = (f"已开始强制换镜像并重建容器（临时容器 {name}）—— "
                    "服务会短暂中断（约 10–30 秒），"
                    "恢复后请再核验一次。")
    base["repair_log"] = f"{root}/.upgrade-repair.log"
    try:
        await audit_svc.log_event(
            who or "", "upgrade_repair_started", resource="system_upgrade",
            method="POST", path="/api/system/update/verify",
            detail={"target": target, "layer": layer, "helper": name})
    except Exception:
        pass
    return base


async def _run_offline_job(job: UpgradeJob, plan: dict[str, Any]) -> None:
    """离线包部署的升级流程

    1. 查 Release 找镜像资产
    2. 下载到临时目录
    3. docker load 导入 + 把架构标签提升成 :latest（编排文件引用的是 :latest）
    4. 在安装目录里 docker compose up -d（会用上新镜像重建容器）
    """
    root = Path(plan.get("install_dir") or plan.get("project_dir") or "")
    target = job.target
    docker = shutil.which("docker") or "docker"
    compose = list(plan.get("compose_cmd_args") or [])
    if not compose:
        compose, _ = await _detect_compose_cmd()
    if not compose:
        raise RuntimeError("找不到 compose 命令")

    # ---- 1. 查 Release ----
    job.stage = "fetch-release"
    job.set_step("fetch-release", "running")
    job.log("查询 GitHub Release …")
    await _flush_state(job, force=True)
    assets, err = await _release_assets(target)
    if err:
        job.set_step("fetch-release", "failed")
        raise RuntimeError(err)
    arch = plan.get("arch") or ""
    asset = _pick_asset(assets, arch)
    if asset is None:
        job.set_step("fetch-release", "failed")
        names = "、".join(a.get("name") or "" for a in assets) or "（一个都没有）"
        raise RuntimeError(f"{target} 这个 Release 里没有本机架构（{arch or '未知'}）的镜像包"
                           f"；当前资产：{names}")
    job.log(f"  找到镜像包：{asset['name']}（{_human_size(asset.get('size'))}）")
    job.set_step("fetch-release", "done")
    await _flush_state(job, force=True)

    # ---- 2. 下载 ----
    tmpdir = Path(tempfile.mkdtemp(prefix="kb-upgrade-"))
    tar_path = tmpdir / str(asset.get("name") or "images.tar.gz")
    try:
        job.stage = "download"
        job.set_step("download", "running")
        job.log(f"下载 {asset.get('url')}")
        await _flush_state(job, force=True)
        cfg = upd.effective_config()
        await _download_asset(str(asset.get("url") or ""), tar_path,
                              (cfg.get("update_proxy") or "").strip(), job)
        job.set_step("download", "done")
        await _flush_state(job, force=True)

        # ---- 3. 导入 + 提升标签 ----
        #
        # 回滚：改标签前先记住旧标签指向哪个镜像。
        # 为什么需要：`:latest` 一旦被指到新镜像，旧镜像就成了没有标签的悬空镜像，
        # 用户想退回去就没有抓手了 —— 而「新镜像起不来」正是这套流程最该防的事故。
        # 所以这里先记下旧 ID，出错时把标签指回去。
        old_ids: dict[str, str] = {}

        # 编排文件里各服务真正引用的镜像 —— 标签必须打到这些名字上。
        #
        # 为什么非知道不可：镜像包里装的是**架构标签**的镜像
        # （kb-workbench-backend:amd64），而 compose 引用的是 :latest
        # （或者用户自己写的名字）。不把新镜像打到 compose 真正引用的
        # 那个名字上，compose up 起来的还是旧容器 ——
        # 而日志里看不出任何异常，用户只会看到「升级完成，刷新后还是旧版」。
        compose_file = _compose_file(root)
        compose_text = ""
        if compose_file is not None:
            try:
                compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                job.log(f"⚠️ 读不到编排文件 {compose_file}（{e}），"
                        f"只能按约定的镜像名打标签")
        expected_refs: dict[str, str] = {}
        if compose_text:
            project = _compose_project_name(compose_text, root.name)
            expected_refs = _compose_service_images(compose_text, project)
        if not expected_refs:
            # 读不到编排文件：只能按约定的名字打标签（与 install.sh 一致）
            expected_refs = {
                "backend": "kb-workbench-backend:latest",
                "frontend": "kb-workbench-frontend:latest",
            }
        job.log("编排文件里各服务引用的镜像："
                + "；".join(f"{svc} → {ref}" for svc, ref in sorted(expected_refs.items())))

        # 要打标签的目标引用：编排文件引用的那些 + 约定的两个名字。
        # 约定的那两个也要打 —— 别的工具（比如 install.sh、用户的 docker 命令）
        # 可能还在用它们，而它们指向旧镜像会让人误判。
        target_refs: list[str] = []
        for ref in (list(expected_refs.values())
                    + ["kb-workbench-backend:latest", "kb-workbench-frontend:latest"]):
            if ref and ref not in target_refs:
                target_refs.append(ref)

        # 记下升级前每个标签指向的镜像（回滚与事后核对都要用）
        for ref in target_refs:
            repo_name, tag = _split_ref(ref)
            img_id = await _image_id(docker, ref)
            if img_id:
                old_ids[ref] = img_id

        async def _rollback_tags() -> None:
            if not old_ids:
                return
            job.log("出错，正在把镜像标签回退到升级前的版本……")
            for ref, img_id in old_ids.items():
                rc, _ = await _run([docker, "tag", img_id, ref], timeout=120)
                if rc == 0:
                    job.log(f"已回退 {ref} → {img_id[:19]}")
                else:
                    job.log(f"回退 {ref} 失败，需要手工处理："
                            f"docker tag {img_id} {ref}")

        try:
            out = await _stage(job, "load", [docker, "load", "-i", str(tar_path)],
                                root, timeout=1800)
            # 认导入的镜像（两种输出措辞都要认，见 _parse_loaded_images）
            loaded = _parse_loaded_images(out)
            job.log(f"docker load 报告导入 {len(loaded)} 个镜像"
                    + (f"：{'、'.join(loaded[:6])}" if loaded else "（没认出来标签名）"))

            # 新镜像在哪个标签下：镜像包里通常是架构标签（:amd64 / :arm64），
            # 而 compose 引用的是 :latest —— 这一步就是把两者对上。
            source_by_repo: dict[str, str] = {}
            for ref in loaded:
                if not ref.startswith("kb-workbench-"):
                    continue
                repo_name, _t = _split_ref(ref)
                source_by_repo.setdefault(repo_name, ref)
            # 架构标签优先（它是镜像包的正式产物）
            for ref in loaded:
                repo_name, t = _split_ref(ref)
                if t in ("amd64", "arm64"):
                    source_by_repo[repo_name] = ref

            want = _norm_version(target)

            async def _pick_source(repo_name: str, want_version: str = "") -> str:
                """为某个仓库挑出「该用的那个镜像」

                优先级：
                  1. 镜像里声明的版本 == 目标版本的那个 —— **版本才是身份**，
                     标签名只是包装（镜像包里是架构标签，发布时残留的可能是旧版）
                  2. docker load 输出里认出来的那个
                  3. 约定的架构标签（跟 install.sh 的做法保持一致）
                """
                cands: list[str] = []
                if want_version:
                    cands.append(f"{repo_name}:{_norm_version(want_version)}")
                if repo_name in source_by_repo:
                    cands.append(source_by_repo[repo_name])
                if arch:
                    cands.append(f"{repo_name}:{arch}")
                for cand in cands:
                    if not cand:
                        continue
                    if not await _image_id(docker, cand):
                        continue
                    if want_version:
                        declared = await _image_declared_version(docker, cand)
                        if not declared or _norm_version(declared) != _norm_version(want_version):
                            job.log(f"  {cand} 里声明的版本是 "
                                    f"{declared or '（读不到）'}，"
                                    f"不是 {_norm_version(want_version)}，跳过")
                            continue
                    return cand
                return ""

            tagged = False
            backend_ref = _backend_ref(expected_refs)
            for ref in target_refs:
                repo_name, _tag = _split_ref(ref)
                is_backend = ref == backend_ref
                # 后端镜像必须**按版本认人**：源镜像再新，标签没换上去，
                # compose 起来的还是旧的 —— 而那正是「版本没变」的成因。
                src = await _pick_source(repo_name, want if is_backend else "")
                if not src:
                    job.log(f"⚠️ 镜像包里没有可用的 {repo_name}"
                            f"（或它的版本不是 {_norm_version(target)}）—— "
                            f"{ref} 仍指向升级前的镜像，相关服务可能还是旧版")
                    continue
                if src == ref:
                    job.log(f"镜像包里的 {ref} 就是编排文件引用的镜像，无需改标签")
                    tagged = True
                else:
                    job.log(f"$ docker tag {src} {ref}")
                    await _stage(job, "load", [docker, "tag", src, ref],
                                 root, timeout=120)
                    tagged = True
                if is_backend:
                    # 版本化标签：给镜像一个不会随下一次构建漂移的锚点。
                    # 核验时靠它判断「镜像到底换没换」，人工排查时也一眼能认。
                    versioned = _versioned_ref(ref, want)
                    if versioned and versioned != ref:
                        job.log(f"$ docker tag {src} {versioned}")
                        await _stage(job, "load", [docker, "tag", src, versioned],
                                     root, timeout=120)
            if not tagged:
                job.log("⚠️ 没有找到可用的新镜像标签，"
                        "这次升级很可能不会生效 —— 请检查镜像包内容")

            # 核对标签确实换掉了。
            #
            # 为什么必须查：之前 compose 里两个服务都只有 build: 没有 image:，
            # `docker compose up -d` 会**按本地源码重建** ——
            # 明明导入了新镜像、前端却还是旧代码，
            # 用户看到的就是「显示升级完成，刷新后还是旧版本」。
            #
            # 现在 compose 写死了 image:，up -d 用的就是导入的镜像。
            # 这里再核对一遍，是为了让「升级成功」这句话真的可信 ——
            # 万一某个镜像没换上，日志里要写清楚，而不是闷声报成功。
            #
            # 注意：这里**只告警不判失败** ——
            # 标签没变可能是有意的（比如用户就是要留在旧版），
            # 但把它悄悄咽下去，就是「谎报成功」，那才是真正要修的毛病。
            for ref in target_refs:
                repo_name, tag = _split_ref(ref)
                new_id = await _image_id(docker, ref)
                old_id = old_ids.get(ref, "")
                if new_id and old_id and new_id == old_id:
                    job.log(f"⚠️ {ref} 仍是升级前的镜像（{new_id[:19]}）"
                            f" —— 这个服务可能还是旧版")

            # ---- 镜像里的版本对不对得上目标版本？----
            #
            # 为什么必须在重启之前查：
            # 镜像包是构建产物，可能比代码旧（发布时拿了本机上残留的旧镜像）。
            # 这种包 load 进来是「成功」的，compose 也能把服务拉起来 ——
            # 但起来跑的是旧版本。用户看到的现象就是：
            #   「服务已恢复，但版本号没变」
            # 而且是在服务被中断重启之后才发现的。
            #
            # 在这里查是唯一能把损失降到零的时机：
            # 还没重启、用户的服务一直在线，发现不对就直接回退标签并报错。
            #
            # 这条检查是 0.7.1 的教训：发布流程里镜像没跟代码对账，
            # 结果升级包带着旧版本发出去，升级「成功」但版本没变。
            await _verify_loaded_image_version(job, docker, target, backend_ref)
        except Exception:
            await _rollback_tags()
            raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---- 4. 重启（会把自己杀掉）----
    job.status = ST_RESTARTING
    job.stage = "restart"
    job.set_step("restart", "running")
    job.log("正在重建容器，服务会短暂中断（约 10–30 秒）……")
    await _flush_state(job, force=True)
    # --no-build：绝不能让 compose 拿本地源码重新构建一遍 ——
    # 离线升级已经把新镜像导入并打好标签了，
    # compose 再 build 一次，起来的就还是旧代码（这就是那个老 bug）。
    # 编排文件里没有 image: 时 compose build 出来的名字是
    # `<项目名>-<服务名>:latest`，正是上面打好的那个标签，所以 --no-build 也安全。
    if not await _start_restart_helper(job, plan, root, compose, extra=["--no-build"]):
        # 起不了临时容器只能退回在本容器里跑（多半会失败，但总得试）
        job.log("  临时容器起不来，退回在本容器里执行 compose up")
async def _image_declared_version(docker: str, image_ref: str) -> str:
    """读出镜像里 backend/app/config.py 声明的版本号

    ⚠️ 参数顺序：镜像名必须放在**命令参数之前**。
    写成「docker run --rm --entrypoint grep -h "app_version: str" <镜像> <路径>」
    的话，docker 会把 -h 当成**自己的**选项（打印帮助后以 1 退出）——
    结果永远是「读不到」，而读不到又被当成「查不了 ≠ 版本不对」，
    于是所有镜像版本核对都被静默跳过了：
    装着旧版本的镜像照样被拉起来，升级报「成功」，版本却没变。
    这正是这次要修的那个现象，所以这里必须写成
    「docker run --rm --entrypoint grep <镜像> -h ... <路径>」。

    读不到就返回空字符串 —— 读不到不等于版本不对，
    那是「查不了」，由调用方决定要不要当成失败。
    """
    rc, out = await _run([docker, "run", "--rm", "--entrypoint", "grep",
                           image_ref, "-h", "app_version: str",
                           "/app/app/config.py"], timeout=180)
    if rc != 0:
        # 镜像里没有 grep（有些精简镜像没装）→ 退回到 cat，正则照样能解析
        rc, out = await _run([docker, "run", "--rm", "--entrypoint", "cat",
                              image_ref, "/app/app/config.py"], timeout=180)
        if rc != 0:
            return ""
        m = re.search(r"""app_version\s*:\s*str\s*=\s*["']([^"']+)["']""", out)
        return m.group(1).strip() if m else ""
    m = re.search(r"""app_version:\s*str\s*=\s*["']([^"']+)["']""", out)
    return m.group(1).strip() if m else ""
    return m.group(1).strip() if m else ""


async def _verify_loaded_image_version(job: UpgradeJob, docker: str, target: str,
                                       backend_ref: str) -> None:
    """核对「编排文件真正引用的那个镜像」里声明的版本与目标版本一致

    为什么核对的是**标签**而不是镜像包里那个源镜像：
    compose up 用的是标签指向的镜像 —— 源镜像再新，
    标签没换上去，起来的还是旧的。
    以前这里核对的是「docker load 输出里认出来的那个镜像」，
    而那个认不出来的时候（输出措辞变了）就**整个核对被跳过** ——
    于是新镜像没换上也没人知道，一路绿灯到「升级完成，版本没变」。
    所以改成核对标签：标签是 compose 真正用的东西，认不出来的概率小得多。

    不一致就**直接失败**（并由调用方回退标签）：
    用一个装着旧版本的镜像去「升级」，服务是能起来的，
    但版本号不会变 —— 用户付了升级的代价却什么都没拿到。
    宁可现在报错（服务还没重启，一直在线），也不要重启完再宣布失败。

    查不到版本时不判失败：镜像结构不一样、镜像里没有这个文件，
    都属于「查不了」，不该被说成「升级失败」。
    """
    want = _norm_version(target)
    if not want:
        return
    got = await _image_declared_version(docker, backend_ref)
    if not got:
        job.log(f"读不出 {backend_ref} 里声明的版本，跳过这次核对"
                f"（查不了 ≠ 版本不对）")
        return
    got = _norm_version(got)
    job.log(f"镜像 {backend_ref} 里声明的版本是 {got}，目标版本是 {want}")
    if got != want:
        raise RuntimeError(
            f"镜像 {backend_ref} 里装的是 {got}，不是 {want} —— "
            f"这个镜像包（或标签）不能用。"
            f"多半是发布时打包进了本机残留的旧镜像，"
            f"或者导入后标签没有换成功。"
            f"请重新下载该版本的镜像包，或在宿主机上执行："
            f"bash scripts/build-offline-images.sh --tools-only && "
            f"bash scripts/make-offline-package.sh"
        )
async def _check_checked_out_version(job: UpgradeJob, root: Path, target: str) -> None:
    """核对 checkout 出来的代码里声明的版本与目标 tag 一致

    不一致就**直接失败**：这个 tag 里根本没有用户要的那一版，
    继续 build + up 只会得到「一切正常，但版本没变」——
    也就是这次要修的那个现象。宁可现在报错，也不要报成功。

    读不到文件时不报错（只是跳过核对）：编排目录结构可能不一样，
    那是部署形态的差异，不该被说成「升级失败」。
    """
    cfg_path = root / "backend" / "app" / "config.py"
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        job.log(f"⚠️ 读不到 {cfg_path}（{e}），跳过版本核对")
        return
    declared = _declared_version(text)
    if not declared:
        job.log(f"⚠️ {cfg_path.name} 里找不到 app_version 声明，跳过版本核对")
        return
    if not _same_version(declared, target):
        msg = (f"目标 tag {target} 里的 backend/app/config.py 声明的版本是 "
               f"{declared}，不是 {_norm_version(target)} —— "
               "这个 tag 里没有你要的版本，升级不会生效。"
               "请确认目标 tag 是否正确。")
        job.set_step("checkout", "failed")
        job.log(f"❌ {msg}")
        raise RuntimeError(msg)
    job.log(f"✓ 目标 tag {target} 里声明的版本是 {declared}，与目标一致")


async def _verify_built_image_version(job: UpgradeJob, root: Path,
                                       target: str) -> None:
    """核对刚构建出来的镜像里声明的版本 == 目标版本

    不一致就**直接失败**（在重启之前）：服务还一直在线，
    用户没有付出任何代价；重启完再宣布失败，代价已经付过了。

    查不到版本时不判失败（镜像结构不一样、没装 grep 等）——
    那是「查不了」，不是「版本不对」。
    """
    docker = shutil.which("docker") or "docker"
    refs, _project = await _compose_refs(root)
    ref = _backend_ref(refs)
    got = await _image_declared_version(docker, ref)
    want = _norm_version(target)
    if not got:
        job.log(f"⚠️ 读不出 {ref} 里声明的版本，跳过这次核对"
                f"（查不了 ≠ 版本不对）")
        return
    job.log(f"构建产物 {ref} 里声明的版本是 {_norm_version(got)}，"
            f"目标版本是 {want}")
    if _norm_version(got) != want:
        msg = (f"构建出来的镜像 {ref} 里装的是 {_norm_version(got)}，"
               f"不是 {want} —— 构建用的不是刚 checkout 的那份源码，"
               f"升级不会生效。请检查编排文件里 build.context 指向的目录。")
        job.set_step("build", "failed")
        job.log(f"❌ {msg}")
        raise RuntimeError(msg)

    # 版本化标签：给镜像一个不会随下一次构建漂移的锚点。
    # 核验时靠它判断「镜像到底换没换」，人工排查时也一眼能认。
    versioned = _versioned_ref(ref, want)
    if versioned and versioned != ref:
        job.log(f"$ docker tag {ref} {versioned}")
        rc, _ = await _run([docker, "tag", ref, versioned], timeout=120)
        if rc != 0:
            job.log(f"⚠️ 打版本化标签 {versioned} 失败（不影响升级本身）")


async def _run_git_job(job: UpgradeJob, plan: dict[str, Any]) -> None:
    """源码部署的升级流程

    1. git fetch origin --tags --force
    2. git checkout <tag>
    3. docker compose build（慢，但这段时间后端容器还活着）
    4. docker compose up -d --remove-orphans（会重建后端容器）
    """
    root = Path(plan["project_dir"])
    compose = list(plan.get("compose_cmd_args") or [])
    if not compose:
        compose, _ = await _detect_compose_cmd()
    if not compose:
        raise RuntimeError("找不到 compose 命令")

    await _stage(job, "fetch", _git_cmd(root, "fetch", "origin", "--tags", "--force"),
                 root, timeout=600)
    await _stage(job, "checkout", _git_cmd(root, "checkout", job.target), root, timeout=300)

    # ---- 核对 checkout 出来的代码里声明的版本 ----
    #
    # 为什么必须查：tag 里的版本号与代码里的 app_version 是两回事 ——
    # 打 tag 时忘了改 app_version（或者 tag 打在了一个错的提交上），
    # 升级流程会一路「成功」地跑完：fetch ✓ checkout ✓ build ✓ up ✓，
    # 而跑起来的还是旧版本。用户看到的正是「显示升级完成，刷新后还是 0.6.8」。
    #
    # 与 scripts/upgrade.sh 的做法一致：那边是在重启后拿 /api/health 的
    # 版本号对账，这边是在 build 之前先看一眼源码里写的是什么 ——
    # 更早发现，少白等一次构建。
    await _check_checked_out_version(job, root, job.target)

    await _stage(job, "build", [*compose, "build"], root, timeout=3600)

    # ---- 核对**构建产物**里声明的版本 ----
    #
    # 为什么源码核对还不够：源码对了，不代表**构建出来的镜像**是对的。
    # 构建上下文可能不是刚 checkout 的那份源码（编排文件在别的目录、
    # context 指向别处），于是 build 出来的还是旧镜像 ——
    # 而 build 这一步会「成功」退出，日志里看不出任何异常。
    # 这是「显示升级完成，刷新后版本没变」最隐蔽的一种成因，
    # 所以必须在重启之前把构建产物也核对一遍。
    await _verify_built_image_version(job, root, job.target)

    # ---- 第 4 步：会把自己杀掉 ----
    # 先把状态置成 restarting 并落盘，再执行命令：命令一执行，
    # 这个进程随时可能消失，日志写不进去也无所谓。
    job.status = ST_RESTARTING
    job.stage = "restart"
    job.set_step("restart", "running")
    job.log("正在重建容器，服务会短暂中断（约 10–30 秒）……")
    await _flush_state(job, force=True)
    if not await _start_restart_helper(job, plan, root, compose):
        job.log("  临时容器起不来，退回在本容器里执行 compose up")
        await _stage(job, "restart", [*compose, "up", "-d", "--remove-orphans"],
                     root, timeout=900)


async def _run_job(job: UpgradeJob, plan: dict[str, Any], who: str) -> None:
    """作业主流程（后台任务）"""
    try:
        job.status = ST_RUNNING
        await _flush_state(job, force=True)

        if job.mode == MODE_OFFLINE:
            await _run_offline_job(job, plan)
        else:
            await _run_git_job(job, plan)

        # 能走到这里，说明这个容器没被纳入同一个 compose 项目（没被杀）。
        # 属于少见情况，但也不能把状态留在 restarting 不放。
        job.status = ST_SUCCEEDED
        job.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.log("✅ 升级完成。")
        await _flush_state(job, force=True)
    except Exception as e:      # 任何一步失败都要落到 failed，并把原因写进日志
        job.status = ST_FAILED
        job.error = str(e)
        job.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        job.log(f"❌ 升级失败：{e}")
        log.warning("升级作业失败：%s", e)
        await _flush_state(job, force=True)
        try:
            await audit_svc.log_event(
                who, "upgrade_failed", resource="system_upgrade", method="POST",
                path="/api/system/update/apply",
                status=500,
                detail={"target": job.target, "error": str(e)[:500],
                        "stage": job.stage, "mode": job.mode,
                        "root": job.root},
            )
        except Exception:
            pass
        return

    try:
        await audit_svc.log_event(
            who, "upgrade_succeeded", resource="system_upgrade", method="POST",
            path="/api/system/update/apply",
            detail={"target": job.target, "mode": job.mode, "root": job.root},
        )
    except Exception:
        pass


async def start_upgrade(target: str = "", who: str = "") -> dict[str, Any]:
    """启动一个升级作业

    同一时刻只允许一个：已经在跑就直接返回那一个（而不是再起一个）。
    两个作业抢同一个目录时，第二个 checkout 会把第一个正在构建的代码换掉，
    产物就是错乱的。
    """
    global _current_job

    job = _current_job
    if job is not None and job.is_active():
        return {"ok": True, "already_running": True, "job": job.snapshot()}

    plan = await build_plan(target, force=True)
    if not plan.get("ok"):
        return {"ok": False, "error": plan.get("error") or "无法生成升级计划",
                "plan": plan}
    if not plan.get("feasible"):
        reasons = "；".join(b.get("title", "") for b in plan.get("blockers") or [])
        return {"ok": False,
                "error": f"当前环境不支持一键升级（{reasons or '条件不满足'}）",
                "plan": plan}
    if not plan.get("target"):
        return {"ok": False, "error": "没有可升级的目标版本", "plan": plan}

    mode = plan.get("mode") or MODE_GIT
    stage_defs = GIT_STAGE_DEFS if mode == MODE_GIT else OFFLINE_STAGE_DEFS
    new_job = UpgradeJob(
        job_id=uuid.uuid4().hex[:12],
        target=plan["target"],
        current=plan["current"],
        root=plan.get("install_dir") or plan.get("project_dir") or "",
        compose_cmd=plan.get("compose_cmd") or "",
        who=who,
        mode=mode,
        stage_defs=stage_defs,
    )
    # 立刻置成 running：这样第二个并发调用会看到「已有作业在跑」，
    # 而不是趁任务还没被调度起来又起一个
    new_job.status = ST_RUNNING
    _current_job = new_job
    await _flush_state(new_job, force=True)

    try:
        await audit_svc.log_event(
            who, "upgrade_started", resource="system_upgrade", method="POST",
            path="/api/system/update/apply",
            detail={"target": new_job.target, "mode": mode,
                    "root": new_job.root, "job_id": new_job.job_id},
        )
    except Exception:
        pass

    asyncio.create_task(_run_job(new_job, plan, who))
    return {"ok": True, "already_running": False, "job": new_job.snapshot()}
