"""一键升级执行器 —— 把「检查到新版」变成「真的升上去」

背景：`services/update.py` 只负责**查**（GitHub 上有没有新 Release）。
这一模块负责**做**（把本机切到新版本并重建服务）。

为什么拆成两个文件：`update.py` 是老代码、已经被设置页依赖，
往里塞「起后台进程、重建容器」这类逻辑会把它搅浑；而且两者生命周期不同 ——
查是一次性的请求，做是一个跨分钟的后台作业。

**执行流程与它的坑**

    1. git fetch origin --tags --force      快
    2. git checkout <tag>                   快
    3. docker compose build                 慢（但这段时间后端容器还活着）
    4. docker compose up -d --remove-orphans 快（会重建后端容器）

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

  - 项目目录里有 .git —— 离线包安装没有版本库，本来就该走离线包升级
  - 容器内能执行 git
  - 容器内能执行 docker（/var/run/docker.sock 存在 + docker 可执行）
  - 编排文件里有 build: 段 —— 离线包的编排文件全是 image:，没有它就重建不了

**安全**

  - 需要 system_config 功能位（superuser 自动放行），见 routers/system.py
  - 工作区不干净直接拒绝，并列出脏文件：升级会 checkout 覆盖工作区，
    本地改动会被冲掉，而且冲掉之后用户根本不知道少了什么
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
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from . import audit as audit_svc
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
MODE_GIT = "git"                # 源码部署：有 .git + 编排文件带 build:
MODE_OFFLINE = "offline"        # 离线包部署：只能靠新离线包替换镜像

# 目标版本号的白名单。目标会直接进 `git checkout <tag>`，
# 哪怕不用 shell 也得防住「--upload-pack=...」这类被当成选项的输入。
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# 步骤定义。顺序即执行顺序，note 里写清每一步「快还是慢」「会不会断连接」——
# 用户看着日志滚动时需要知道该等多久，而不是以为卡死了。
STAGE_DEFS = [
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


def _env_project_dir() -> str:
    """环境变量里配的项目目录（容器内路径）

    为什么用环境变量而不是自动猜：项目目录在宿主上的位置千差万别，
    猜出来的路径可能指向另一个项目的仓库，猜错比不猜更糟。
    """
    for key in ("KB_PROJECT_DIR", "KB_UPGRADE_PROJECT_DIR", "PROJECT_DIR"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


def _find_project_dir() -> tuple[Path | None, str]:
    """定位项目目录（宿主项目目录在容器里的挂载点）

    返回 (目录, 来源说明)。找不到时目录为 None —— 调用方要把它当成
    「不可行」处理，而不是随便挑一个目录去 checkout。
    """
    env = _env_project_dir()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p, "环境变量 KB_PROJECT_DIR"
        return None, "环境变量 KB_PROJECT_DIR 指向的目录不存在"

    # 自动探测：常见挂载点 + 从当前目录向上找（.git 与编排文件都在才算）
    candidates: list[Path] = [
        Path("/app/project"), Path("/project"), Path("/workspace"),
        Path("/host/project"), Path("/mnt/project"), Path("/srv/kb-workbench"),
    ]
    try:
        here = Path.cwd().resolve()
        candidates.append(here)
        candidates.extend(here.parents)
    except OSError:
        pass
    for c in candidates:
        try:
            if not c.is_dir():
                continue
            if (c / ".git").exists() and any((c / f).exists() for f in COMPOSE_FILES):
                return c, "自动探测"
        except OSError:
            continue
    return None, "未找到"


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
    没有 build: 段就没法「拉新代码 → 重建镜像」—— 这类安装只能换离线包。

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


# ==================== 升级作业 ====================

class UpgradeJob:
    """一个升级作业的状态

    状态机：

        pending → running →(前三步)→ restarting →(第 4 步，容器被重建)
                                 → succeeded / failed

    `restarting` 是个关键状态：它表示「服务正在重启，不是出错了」。
    前端看到它就应该转入「等待服务恢复」模式，而不是弹错误。
    """

    def __init__(self, job_id: str, target: str, current: str, project_dir: str,
                 compose_cmd: str, who: str):
        self.job_id = job_id
        self.target = target
        self.current = current
        self.project_dir = project_dir
        self.compose_cmd = compose_cmd
        self.who = who
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
            for d in STAGE_DEFS
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
            "project_dir": self.project_dir,
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
        return {"ok": True, "job": data, "restored": True}
    if job is not None:
        return {"ok": True, "job": job.snapshot(), "restored": False}
    return {"ok": True, "job": None, "restored": False}


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


async def build_plan(target: str = "", force: bool = False) -> dict[str, Any]:
    """可行性判定 + 步骤清单 + 手动命令

    返回的 `mode` 告诉前端这套部署是「源码部署」还是「离线包部署」：
    有 .git + 编排文件带 build: → git 模式（可以自己拉代码重建）；
    否则 → offline 模式（只能靠新离线包替换镜像，引导文案完全不同）。
    """
    now = time.monotonic()
    if not force and _plan_cache.get("target") == target:
        if now - _plan_cache.get("ts", 0) < _PLAN_CACHE_TTL:
            return dict(_plan_cache["result"])

    current = settings.app_version
    target = (target or "").strip()
    update_error = ""
    has_update = False

    if not target:
        # 没指定目标版本时，去问一次更新检查（服务端有 10 分钟缓存）
        info = await upd.check_update()
        target = (info.get("latest") or "").strip()
        update_error = info.get("error") or ""
        if not info.get("ok") and not target:
            return {
                "ok": False, "error": update_error or "无法确定目标版本",
                "mode": MODE_OFFLINE, "feasible": False,
                "current": current, "current_display": f"v{current}",
                "target": "", "has_update": False,
                "blockers": [], "warnings": [], "dirty_files": [],
                "steps": [], "manual_commands": [], "notes": [],
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
    else:
        # 目标必须长得像版本号：它会直接进 `git checkout <tag>`
        if not _TAG_RE.match(target):
            return {
                "ok": False, "error": f"目标版本「{target}」格式不合法",
                "mode": MODE_OFFLINE, "feasible": False,
                "current": current, "current_display": f"v{current}",
                "target": "", "has_update": False,
                "blockers": [], "warnings": [], "dirty_files": [],
                "steps": [], "manual_commands": [], "notes": [],
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    dirty: list[str] = []
    notes: list[str] = []

    # 目标版本是否真的比当前版本新。用与更新检查同一套比较逻辑，
    # 免得界面上「已是最新」和「有新版本」两处说法打架。
    has_update = bool(target) and upd.is_newer(target, current)

    pdir, dir_source = _find_project_dir()
    compose_file = _compose_file(pdir) if pdir else None
    compose_path = str(compose_file) if compose_file else ""

    # --- 编排文件里有没有 build: 段 ---
    has_build = False
    if compose_file:
        try:
            has_build = _has_build_section(compose_file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            has_build = False

    # --- 部署模式 ---
    # 有 .git + 有 build: → 源码部署；否则 → 离线包部署。
    # 这个判断同时决定「一键升级能不能做」和「该给用户哪种升级指引」。
    is_git_deploy = bool(pdir and (pdir / ".git").exists() and has_build)
    mode = MODE_GIT if is_git_deploy else MODE_OFFLINE

    # --- 1. 项目目录 ---
    if pdir is None:
        blockers.append(_blocker(
            "project_dir_missing",
            "找不到项目目录",
            f"容器里找不到带 .git 与编排文件的项目目录（{dir_source}）。"
            "一键升级需要操作宿主机的项目目录。",
            "在编排文件里把项目目录挂进后端容器并设置环境变量 "
            "KB_PROJECT_DIR（例：- .:/app/project 与 - KB_PROJECT_DIR=/app/project）。",
        ))
    elif not (pdir / ".git").exists():
        blockers.append(_blocker(
            "no_git_dir",
            "项目目录里没有 .git",
            f"{pdir} 不是 git 仓库。离线包安装本来就没有版本库，"
            "这类安装只能靠新离线包替换镜像。",
            "改用离线包升级：下载新版离线安装包 → 解压 → bash install.sh -d <安装目录>。",
        ))

    # --- 2. git 可执行 ---
    git_bin = shutil.which("git")
    if not git_bin:
        blockers.append(_blocker(
            "no_git",
            "容器里没有 git",
            "后端镜像里没有 git 命令，无法拉取 tag、无法切换版本。",
            "构建后端镜像时把 INSTALL_UPGRADE_TOOLS 改成 1 重建镜像"
            "（docker-compose.yml 里已写好用法），或改用离线包升级。",
        ))

    # --- 3. docker 可执行 + socket ---
    docker_bin = shutil.which("docker")
    if not docker_bin:
        blockers.append(_blocker(
            "no_docker_cli",
            "容器里没有 docker 命令",
            "后端镜像里没有 docker CLI，无法重建镜像、无法重启容器。",
            "构建后端镜像时把 INSTALL_UPGRADE_TOOLS 改成 1 重建镜像"
            "（docker-compose.yml 里已写好用法），或改用离线包升级。",
        ))
    if not Path(DOCKER_SOCK).exists():
        blockers.append(_blocker(
            "no_docker_socket",
            "容器里没有 docker socket",
            f"{DOCKER_SOCK} 不存在：后端容器没有接管宿主机的 docker 守护进程，"
            "跑不了 compose 命令。",
            "在编排文件里给后端服务加上 "
            "- /var/run/docker.sock:/var/run/docker.sock（等于把宿主机 root 权限"
            "交给容器，请只在可信环境开启）。",
        ))

    # --- 4. 编排文件有 build: 段 ---
    if compose_file and not has_build:
        blockers.append(_blocker(
            "no_build_section",
            "编排文件里没有 build: 段",
            f"{compose_file.name} 里的服务只有 image:，没有 build: —— "
            "意味着这套部署用的是预构建镜像，拉了新代码也重建不出镜像。",
            "改用离线包升级：下载新版离线安装包 → 解压 → bash install.sh -d <安装目录>。",
        ))

    # --- 5. compose 命令 ---
    # compose 是**插件**，装了 docker CLI 不等于有 compose。
    # 这里实跑一次 version 来确认，跑不通就是硬性缺失（自动升级做不了）。
    compose_cmd, compose_label = await _detect_compose_cmd()
    if not compose_cmd:
        blockers.append(_blocker(
            "no_compose_cmd",
            "没有可用的 compose 命令",
            "docker compose 是插件形态，默认镜像里没有；docker-compose（v1）也没装。"
            "没有它就没法统一地 build / up 这套编排。",
            "构建后端镜像时把 INSTALL_UPGRADE_TOOLS 改成 1 重建镜像"
            "（该构建参数会一并装上 compose 插件），或改用离线包升级。",
        ))

    # --- 6. origin remote ---
    if pdir and git_bin:
        rc, out = await _run(_git_cmd(pdir, "remote", "get-url", "origin"), cwd=pdir, timeout=20)
        if rc != 0:
            blockers.append(_blocker(
                "no_origin",
                "没有配置 origin remote",
                "git 仓库里没有 origin，fetch 不到远端的 tag。",
                "在项目目录里执行 git remote add origin <仓库地址>。",
            ))

    # --- 7. 工作区是否干净 ---
    if pdir and git_bin and (pdir / ".git").exists():
        dirty = await _dirty_files(pdir)
        if dirty:
            blockers.append(_blocker(
                "dirty_tree",
                "工作区有未提交的改动",
                "升级会 checkout 到目标 tag，把这些改动覆盖掉，而且覆盖之后"
                "没法从版本库里找回来。",
                "先提交（git commit -am '...'）或 stash 这些改动，再执行升级。",
            ))

    # --- 警告项 ---
    if pdir and git_bin and target:
        tags = await _local_tags(pdir)
        if target not in tags:
            warnings.append(_warning(
                "tag_not_local",
                "本地还没有目标版本的 tag",
                "升级第一步会先 fetch 远端 tag，拉下来再切换，不影响升级。",
            ))
    if mode == MODE_GIT:
        notes.append("第 4 步会重建后端容器，接口会短暂中断几秒到几十秒，浏览器会自动等待。")

    # --- 手动命令（宿主机执行）---
    manual = [
        "# 在**宿主机**的项目目录里执行（不是容器内）",
        "cd <项目目录>",
        "git fetch origin --tags --force",
        f"git checkout {target}" if target else "git checkout <目标版本>",
        "docker compose build",
        "docker compose up -d --remove-orphans",
    ]
    if mode == MODE_OFFLINE:
        manual = [
            "# 离线包部署：下载新版离线安装包并解压，然后执行",
            "bash install.sh -d <安装目录>",
        ]

    steps = [dict(d) for d in STAGE_DEFS]
    for s in steps:
        if s["key"] in ("checkout",) and target:
            s["command"] = f"git checkout {target}"

    feasible = not blockers and bool(compose_cmd)

    result = {
        "ok": True,
        "mode": mode,
        "feasible": feasible,
        "current": current,
        "current_display": f"v{current}",
        "target": target,
        "has_update": has_update,
        "project_dir": str(pdir) if pdir else "",
        "project_dir_source": dir_source,
        "compose_file": compose_path,
        "compose_cmd": compose_label,
        # 真正执行时用的命令（含绝对路径）。展示用 compose_cmd（"docker compose"），
        # 执行用这个 —— 拆成两个字段是为了界面上能显示人话。
        "compose_cmd_args": list(compose_cmd),
        "blockers": blockers,
        "warnings": warnings,
        "dirty_files": dirty,
        "steps": steps,
        "manual_commands": manual,
        "notes": notes,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _plan_cache["target"] = target
    _plan_cache["ts"] = now
    _plan_cache["result"] = dict(result)
    return result


# ==================== 执行 ====================

async def _drain(proc: asyncio.subprocess.Process, job: UpgradeJob) -> None:
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
            job.log(line.rstrip("\r"))
    if buf:
        job.log(buf.rstrip("\r"))


async def _stage(job: UpgradeJob, key: str, cmd: list[str], cwd: Path, timeout: float) -> None:
    """执行一个步骤，把输出流式写进日志"""
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

    drain = asyncio.create_task(_drain(proc, job))
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


async def _run_job(job: UpgradeJob, plan: dict[str, Any], who: str) -> None:
    """作业主流程（后台任务）"""
    pdir = Path(plan["project_dir"])
    # compose_cmd_args 是探测出来的真实命令（含绝对路径）；
    # compose_cmd 只是给人看的名字（"docker compose"）
    compose = list(plan.get("compose_cmd_args") or [])
    if not compose:
        compose, _ = await _detect_compose_cmd()
    if not compose:
        job.status = ST_FAILED
        job.error = "找不到 compose 命令"
        await _flush_state(job, force=True)
        return

    try:
        job.status = ST_RUNNING
        await _flush_state(job, force=True)

        await _stage(job, "fetch", _git_cmd(pdir, "fetch", "origin", "--tags", "--force"),
                     pdir, timeout=600)
        await _stage(job, "checkout", _git_cmd(pdir, "checkout", job.target),
                     pdir, timeout=300)
        await _stage(job, "build", [*compose, "build"], pdir, timeout=3600)

        # ---- 第 4 步：会把自己杀掉 ----
        # 先把状态置成 restarting 并落盘，再执行命令：命令一执行，
        # 这个进程随时可能消失，日志写不进去也无所谓。
        job.status = ST_RESTARTING
        job.stage = "restart"
        job.set_step("restart", "running")
        job.log("正在重建容器，服务会短暂中断（约 10–30 秒）……")
        await _flush_state(job, force=True)

        await _stage(job, "restart", [*compose, "up", "-d", "--remove-orphans"],
                     pdir, timeout=600)

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
                        "stage": job.stage, "project_dir": job.project_dir},
            )
        except Exception:
            pass
        return

    try:
        await audit_svc.log_event(
            who, "upgrade_succeeded", resource="system_upgrade", method="POST",
            path="/api/system/update/apply",
            detail={"target": job.target, "project_dir": job.project_dir},
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

    new_job = UpgradeJob(
        job_id=uuid.uuid4().hex[:12],
        target=plan["target"],
        current=plan["current"],
        project_dir=plan["project_dir"],
        compose_cmd=plan.get("compose_cmd") or "",
        who=who,
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
            detail={"target": new_job.target, "project_dir": new_job.project_dir,
                    "job_id": new_job.job_id},
        )
    except Exception:
        pass

    asyncio.create_task(_run_job(new_job, plan, who))
    return {"ok": True, "already_running": False, "job": new_job.snapshot()}
