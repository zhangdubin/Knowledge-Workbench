"""运行期可改配置 —— 存在数据目录下的 bootstrap.json，改完立即生效，不用重启容器

为什么需要这一层（而不是继续只用 .env）：

1. `.env` 是**启动时**读的。改一次备份目录要重启整个服务，而这类配置
   是「改一次、用很久」的运维参数，重启窗口完全没必要。
2. 容器里 compose 已经把 `KB_BACKUP_DIR` 硬设成 `/app/backups`，
   于是配置文件里怎么写都不生效 —— 这正是「文档里写着、实际没用」的
   一类静默失效，和之前 `KB_` 前缀那个坑同源。
3. 界面要能解释「为什么我改的值没生效」，所以每一项都带**来源**标注：
   `file`（界面改的）/ `env`（环境变量）/ `default`（代码默认）。

**为什么存在文件里、而不是数据库里** —— 这一点是刻意的：

  备份目录必须能在**数据库被删掉之后**还被读到。如果把它存进 kb.db，
  就会出现循环依赖：灾难恢复时你要先知道「备份在哪」，而这条信息
   正好躺在那份你正准备恢复的库里。同理，初始管理员口令要在库为空时
   生效，它也不能存在库里。

  所以引导级配置落在 `data/bootstrap.json`（`data/` 本身由 compose 挂载
  持久化，且会在快照备份里跟着走），文件权限 0600。

优先级：**bootstrap.json > 环境变量 > 代码默认值**。文件放最高是有意的 ——
界面上的操作必须能被信任，否则运维会陷入「点了保存但没变化」的困惑。

安全边界：
  - 只有白名单里的 key 能写（EDITABLE），前端传什么 key 都注不进来；
  - 写入前逐项校验（类型、范围、路径探针实测）；
  - 初始口令**只存哈希**，从不落明文；界面也不回显。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger("kb.settings")

# 引导级配置的落盘位置（数据目录里，与 kb.db 同级）
BOOTSTRAP_FILE = Path(settings.data_dir) / "bootstrap.json"
# 口令字段在文件里存的是哈希，键名与可编辑项区分开，避免误读
HASH_KEY = "admin_password_hash"

GROUP_STORAGE = "存储与备份"
GROUP_SECURITY = "安全"

# 默认弱口令：库里没人时用它建 admin。这个值在生产是不能接受的，
# 所以界面上要显式提示「仍是默认口令」而不是静默放过。
WEAK_DEFAULTS = {"admin12345", "admin", "12345678", "password"}

EDITABLE: dict[str, dict] = {
    "backup_dir": {
        "kind": "path",
        "label": "备份目录",
        "group": GROUP_STORAGE,
        "help": (
            "备份快照（库文件 + 文件原文目录）的落盘位置，必须写容器内的绝对路径。"
            "与数据放在同一个目录里只能防误删、防不了磁盘故障 —— 生产应指向另一块"
            "物理盘或网络存储。要让宿主机上的盘出现在下面的候选里，需要先在 "
            "docker-compose.yml 里把它挂进容器。"
        ),
    },
    "backup_keep": {
        "kind": "int",
        "min": 1,
        "max": 365,
        "label": "备份保留份数",
        "group": GROUP_STORAGE,
        "help": (
            "备份按时间轮转，只保留最近的 N 份。快照之间用硬链接共享未变动的文件，"
            "所以份数调大不会成倍占用空间（只有新增/修改过的文件才复制一份）。"
        ),
    },
    "admin_password": {
        "kind": "secret",
        "min_len": 8,
        "label": "初始管理员口令",
        "group": GROUP_SECURITY,
        "help": (
            "只在**一个用户都没有的空库上首次启动**时生效，用来创建 admin 账号"
            "（登录后仍强制改密）。库里已有账号时它不会被读取 —— 改口令请走"
            "「用户管理 → 重置密码」，那里改的才是真正生效的口令。"
            "这里存的是哈希（不落明文），好处是删库重建、或把配置迁到新机器时"
            "口令设置能跟着 data/ 目录一起走。"
        ),
    },
}

# 可编辑项 key → 文件里的存储 key。只有初始口令需要这层间接：
# 界面上的「口令」是明文，落盘的是哈希，两者不能同名混用。
STORAGE_KEY = {"admin_password": HASH_KEY}

# 进程内缓存：备份目录这类读取点在维护/备份路径上被频繁调用，
# 每次都去读文件不值得。写入后立即刷新，保证读到的永远是最新值。
_cache: dict[str, str] = {}
_loaded = False


def _skey(key: str) -> str:
    return STORAGE_KEY.get(key, key)


def _stored(key: str) -> str | None:
    """文件里存的原始值（初始口令这里是哈希，不是明文）"""
    return _cache.get(_skey(key))


def _env_value(key: str) -> str:
    """取环境变量的值

    `_promote_kb_env()` 启动时已把 `KB_BACKUP_DIR` 映射成 `BACKUP_DIR`，
    两种写法都要认（直接读 os.environ 是因为这一层要能区分
    「值来自环境变量」和「值来自代码默认」）。
    """
    upper = key.upper()
    return os.environ.get(upper) or os.environ.get(f"KB_{upper}") or ""


def _coerce(key: str, raw: Any) -> Any:
    spec = EDITABLE.get(key) or {}
    if raw is None:
        return None
    if spec.get("kind") == "int":
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return spec.get("default", 0)
    return str(raw)


def effective(key: str) -> tuple[Any, str]:
    """返回 (值, 来源)。来源用于界面标注，不是装饰 —— 排查「改了没生效」全靠它"""
    if _skey(key) in _cache:
        if key == "admin_password":
            # 文件里只有哈希，明文不可得；界面据此显示「已自定义」而不是回显
            return "", "file"
        return _coerce(key, _cache[_skey(key)]), "file"
    env = _env_value(key)
    if env:
        return _coerce(key, env), "env"
    return _coerce(key, getattr(settings, key, None)), "default"


def get_value(key: str, fallback: Any = None) -> Any:
    value, _src = effective(key)
    return fallback if value in (None, "") else value


def is_customized(key: str) -> bool:
    """是否被 bootstrap.json 覆盖过（含只有哈希的初始口令）"""
    return _skey(key) in _cache


def admin_password_hash() -> str:
    """初始管理员口令的哈希：界面设过就用它，否则用环境变量/默认口令现算

    存哈希而不存明文，是因为这里根本不需要明文 —— 建账号要的就是哈希。
    顺带让 bootstrap.json 即便被读走也拿不到口令本身。
    """
    stored = _stored("admin_password")
    if stored:
        return stored
    from .auth import hash_password  # 延迟导入：auth 也依赖本模块
    return hash_password(str(get_value("admin_password", settings.admin_password)))


def _read_file() -> dict:
    try:
        raw = BOOTSTRAP_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        log.warning("读取 %s 失败，本次使用环境变量与默认值：%s", BOOTSTRAP_FILE, e)
        return {}
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        # 文件坏了不能静默当成空 —— 那会让「备份目录」悄悄退回默认值，
        # 而运维一直以为自己设的那个还在生效
        log.error("配置文件 %s 解析失败（%s），已忽略其内容", BOOTSTRAP_FILE, e)
        return {}
    items = data.get("items")
    return items if isinstance(items, dict) else {}


def _write_file(items: dict) -> None:
    """原子写：先写临时文件再 rename，避免中断留下半个 JSON

    配置写坏的后果是「服务行为诡异」，比库文件写坏更难查，
    所以这里不用「直接覆盖」这种图省事的写法。
    """
    BOOTSTRAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": items,
    }
    fd, tmp = tempfile.mkstemp(dir=str(BOOTSTRAP_FILE.parent),
                              prefix=".bootstrap-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)   # 含口令哈希，不给同容器其它进程读
        os.replace(tmp, BOOTSTRAP_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


async def reload() -> None:
    """把文件里的设置加载进缓存（启动时调一次，写盘后调一次）"""
    global _loaded
    items = await asyncio.to_thread(_read_file)
    _cache.clear()
    for k, v in items.items():
        if isinstance(k, str):
            _cache[k] = "" if v is None else str(v)
    _loaded = True
    if _cache:
        log.info("运行期设置已加载：%s（来自 %s）",
                 ", ".join(sorted(_cache)), BOOTSTRAP_FILE)


async def ensure_loaded() -> None:
    if not _loaded:
        await reload()


def _initial_load() -> None:
    """导入本模块时同步读一次配置文件

    为什么不等 lifespan：初始管理员口令要在**建库时**就可用，而
    `init_db → ensure_admin_user` 就发生在 lifespan 里 —— 那会儿再异步
    加载已经晚了，空库会拿到旧口令建出 admin。配置文件很小，
    同步读一次的开销可以忽略。
    """
    global _loaded
    _cache.clear()
    for k, v in _read_file().items():
        if isinstance(k, str):
            _cache[k] = "" if v is None else str(v)
    _loaded = True


_initial_load()


# ============================================================ 校验


def _is_separate_declared(path: str) -> bool:
    """该路径是否被部署方显式声明为「与数据盘物理隔离的备份盘」

    见 config.py 里 backup_separate_mounts 的说明：Docker Desktop 下
    容器内所有 bind mount 的设备号都一样，自动判断失效，只能靠声明。
    """
    real = os.path.realpath(path)
    raw = str(settings.backup_separate_mounts or "")
    for m in raw.replace(";", ",").split(","):
        root = os.path.realpath(m.strip())
        if not root or root == "/":
            continue
        if real == root or real.startswith(root.rstrip("/") + "/"):
            return True
    return False


def _blocked_reason(path: str) -> str:
    """备份目录的硬约束

    最要命的是「把备份目录放进文件原文目录里」：快照会把 `files/` 整个拷进去，
    而快照本身又落在 `files/` 里 —— 下一份快照再把它拷一遍，体积逐份翻倍，
    直到把盘写满。这种配置一旦存下来，故障要等到盘满才暴露，
    而那时连恢复用的空间都没了。

    数据库目录同样拒绝：备份和数据放在一起，单盘故障会同时带走两者，
    而 compose 已经给了 `/app/backups` 这个专门的挂载点。
    """
    real = os.path.realpath(path)
    for d, what in ((settings.file_store_dir, "文件原文目录"),
                    (settings.data_dir, "数据库目录")):
        root = os.path.realpath(d)
        if real == root or real.startswith(root.rstrip("/") + "/"):
            return (f"备份目录不能放在{what}（{root}）里 —— "
                    "否则快照会把自己也当成数据备份一遍，体积会失控")
    return ""


def probe_dir(path: str, *, create: bool = True) -> dict:
    """实测目录可用性：建目录 → 写文件 → 读回 → 删掉

    为什么不只看 `os.access(path, W_OK)`：只读挂载、磁盘配额耗尽、
    目录被别的文件占位，这几种情况下 access 都可能返回 True 而写入失败。
    备份目录选错的代价是「以为在备份、其实一次都没成功」，所以这里
    宁可多花几毫秒做一次真实写入。

    create=False 用于**只做展示**的候选路径：列出来看看它行不行，
    但不因为「界面刷新了一下」就在磁盘上留下一堆空目录。
    """
    out: dict[str, Any] = {"path": path, "ok": False, "error": "",
                           "persistent": False, "mount": "", "same_device_as_data": None}
    if not path or not path.startswith("/"):
        out["error"] = "必须是容器内的绝对路径（以 / 开头）"
        return out
    p = Path(path)
    if not create and not p.is_dir():
        out["error"] = "目录不存在"
        out["works_if_created"] = bool(mount_of(str(p)) or _writable_parent(p))
        out["mount"] = mount_of(str(p))
        return out
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        out["error"] = f"无法创建目录：{e}"
        return out
    if not p.is_dir():
        out["error"] = "目标路径已存在且不是目录"
        return out

    stamp = f".kb-write-test-{os.getpid()}-{int(time.time())}"
    probe = p / stamp
    try:
        probe.write_text("kb-workbench backup dir probe", encoding="utf-8")
        back = probe.read_text(encoding="utf-8")
        if "probe" not in back:
            raise OSError("写入后读回内容不一致")
    except OSError as e:
        out["error"] = f"目录不可写：{e}"
        return out
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

    out["ok"] = True
    out["mount"] = mount_of(str(p))
    out["persistent"] = bool(out["mount"])
    out["separate_declared"] = _is_separate_declared(str(p))
    try:
        usage = shutil.disk_usage(str(p))
        out["free_kb"] = int(usage.free / 1024)
        out["total_kb"] = int(usage.total / 1024)
        out["free_bytes"] = int(usage.free)
        out["total_bytes"] = int(usage.total)
    except OSError:
        pass
    if out["separate_declared"]:
        # 部署方声明过这里是与数据盘物理隔离的备份盘 —— 以声明为准，
        # 因为容器内的自动判断在 Docker Desktop 上不具备区分能力
        out["same_device_as_data"] = False
    else:
        try:
            out["same_device_as_data"] = (
                os.stat(str(p)).st_dev
                == os.stat(os.path.realpath(settings.data_dir)).st_dev
            )
        except OSError:
            out["same_device_as_data"] = None
    return out


# 容器里这些都不是「真的磁盘」，写进去等于写进容器可写层 —— 容器一重建就没了
_FAKE_FSTYPES = {
    "proc", "sysfs", "devpts", "devtmpfs", "tmpfs", "mqueue", "cgroup",
    "cgroup2", "overlay", "shm", "nsfs", "efivarfs", "securityfs",
    "debugfs", "tracefs", "pstore", "bpf", "autofs", "hugetlbfs", "configfs",
}


def mount_table() -> list[dict]:
    """列出容器内的持久挂载点

    /proc/mounts 是容器视角的挂载表：真实块设备、bind mount、volume
    都在这里；而容器根目录（overlay）与 tmpfs 之类的伪文件系统要过滤掉，
    否则界面会把「容器可写层」当成可以放备份的地方推荐出去。
    """
    out: list[dict] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, point, fstype = parts[0], parts[1], parts[2]
        if fstype in _FAKE_FSTYPES or point.startswith("/proc") or point.startswith("/sys"):
            continue
        if point == "/" and fstype != "overlay":
            # / 是真实块设备（裸机/特权容器）时也算持久点
            pass
        elif fstype == "overlay":
            continue
        # Docker 会把 /etc/hosts、/etc/resolv.conf 这类**单文件**挂进来。
        # 它们不是目录，出现在「备份目录候选」里只会干扰判断。
        if not os.path.isdir(point):
            continue
        try:
            usage = shutil.disk_usage(point)
            free_bytes, total_bytes = usage.free, usage.total
        except OSError:
            free_bytes = total_bytes = None
        out.append({
            "mount": point,
            "device": device,
            "fstype": fstype,
            "free_bytes": free_bytes,
            "total_bytes": total_bytes,
        })
    # 长的挂载点优先（/app/backups 比 / 更具体）
    out.sort(key=lambda m: len(m["mount"]), reverse=True)
    return out


def _writable_parent(p: Path) -> bool:
    """逐级向上找一个已存在的祖先目录，看它可不可写

    用于判断「这个目录还没建，但建得起来吗」——比如宿主机刚挂进来的空卷。
    """
    cur = p
    while True:
        parent = cur.parent
        if parent == cur:
            return False
        if parent.is_dir():
            return os.access(str(parent), os.W_OK)
        cur = parent


def mount_of(path: str) -> str:
    """路径落在哪个挂载点里；空串 = 不在任何持久挂载点上（容器可写层）

    返回空串是个**重要信号**：往那里写备份，容器一重建就全没了。
    """
    real = os.path.realpath(path)
    best = ""
    for m in mount_table():
        point = m["mount"].rstrip("/")
        if point == "" or point == "/":
            matched = True
            label = "/"
        else:
            matched = real == point or real.startswith(point + "/")
            label = point
        if matched and len(label) > len(best):
            best = label
    return best


def backup_targets() -> dict:
    """备份目录候选：容器内每个持久挂载点 + 当前值 + 探针结果

    这份列表是界面下拉框的数据源。它同时承担一个**解释性**作用：
    如果里面没有别的盘，就说明 compose 还没把宿主机的盘挂进来，
    这时界面要给出可复制的挂载片段，而不是让人对着空下拉框猜。
    """
    current, source = effective("backup_dir")
    cur_real = os.path.realpath(str(current)) if current else ""
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(path: str, note: str = "", *, create: bool = False) -> None:
        path = path.replace("//", "/")
        if path in seen:
            return
        real = os.path.realpath(path)
        # 当前备份目录里的子目录没有意义（快照不该嵌套在快照里）
        if cur_real and real != cur_real and real.startswith(cur_real.rstrip("/") + "/"):
            return
        seen.add(path)
        info = probe_dir(path, create=create)
        info["note"] = note
        info["is_current"] = os.path.realpath(path) == os.path.realpath(str(current))
        info["blocked"] = _blocked_reason(path)
        # 「推荐」= 能用 + 在持久盘上 + 不在数据/原文目录里 + 与数据不同盘。
        # 最后一条是关键：同盘备份只能防误删，界面上要能一眼看出哪个才是真隔离。
        info["recommended"] = bool(
            info["ok"] and info["persistent"] and not info["blocked"]
            and not info.get("same_device_as_data")
        )
        candidates.append(info)

    if current:
        add(str(current), "当前生效的备份目录")
    for m in mount_table():
        point = m["mount"].rstrip("/") or "/"
        add(point, f"容器内的持久挂载点（{m['fstype']}）")
        # 挂载点下的子目录才是**推荐**落点：挂载点本身常是盘的根，
        # 直接把快照铺在根上，以后想放别的东西就挤在一起了
        add(f"{point}/kb-backups", "该挂载点下的专用子目录（推荐）", create=True)
    add("/app/backups", "compose 默认位置")

    usable = [c for c in candidates if c["ok"] and c["persistent"] and not c["blocked"]]
    best = next((c for c in usable if c["recommended"] and not c["is_current"]), None)
    return {
        "current": current,
        "source": source,
        "candidates": sorted(
            candidates,
            key=lambda c: (not c["recommended"], c["blocked"] != "", not c["is_current"], c["path"]),
        ),
        "recommended": best["path"] if best else "",
        "has_alternate_disk": any(c["recommended"] for c in usable),
        "data_dir": os.path.abspath(settings.data_dir),
        "file_store_dir": os.path.abspath(settings.file_store_dir),
        "mounts": mount_table(),
        "guides": _mount_guide(),
    }


def _mount_guide() -> list[dict]:
    """把「怎么把另一块盘挂进来」写清楚

    这一层是 Docker 的边界：容器看不见宿主机的目录，除非显式挂载。
    应用层无论怎么做都绕不过它，所以界面要如实告诉用户下一步做什么，
    而不是假装「换个路径就好了」—— 那样只会让人把备份写到容器可写层里，
    容器一重建备份就没了，而当事人一直以为有备份。
    """
    return [
        {
            "title": "在 docker-compose.yml 里增加挂载",
            "snippet": (
                "services:\n"
                "  backend:\n"
                "    volumes:\n"
                "      - ./data:/app/data\n"
                "      - ./files:/app/files\n"
                "      # 宿主机上的另一块盘 / NAS：左边写宿主机路径，右边写容器内路径\n"
                "      - /Volumes/backup-disk/kb:/mnt/kb-backup"
            ),
        },
        {
            "title": "重启后回到本页",
            "snippet": "docker compose up -d",
        },
        {
            "title": "把备份目录指向它",
            "snippet": "/mnt/kb-backup",
        },
    ]


# ============================================================ 读写


def describe() -> list[dict]:
    """给界面的完整清单：当前值、来源、环境变量值、默认值、校验规则"""
    items: list[dict] = []
    for key, spec in EDITABLE.items():
        value, source = effective(key)
        env = _env_value(key)
        default = getattr(settings, key, None)
        node = {
            "key": key,
            "label": spec["label"],
            "group": spec["group"],
            "help": spec["help"],
            "kind": spec["kind"],
            "min": spec.get("min"),
            "max": spec.get("max"),
            "min_len": spec.get("min_len"),
            "source": source,
            "env_value": env,
            "default_value": default,
            "overridden_by_env": bool(env) and source == "env",
        }
        if spec["kind"] == "secret":
            # 不回显明文：只告诉界面「有没有自定义过」「是不是还在用默认弱口令」
            raw = "" if is_customized(key) else str(get_value(key, "") or "")
            node["value"] = ""
            node["is_set"] = is_customized(key)
            node["is_weak"] = raw.lower() in WEAK_DEFAULTS
            node["length"] = len(raw)
        else:
            node["value"] = value
        items.append(node)
    return items


def validate(key: str, value: Any) -> tuple[bool, Any, str, str]:
    """返回 (是否通过, 归一化后的值, 错误, 警告)"""
    spec = EDITABLE.get(key)
    if not spec:
        return False, None, f"不支持修改的配置项：{key}", ""
    kind = spec["kind"]
    warn = ""
    if kind == "int":
        try:
            num = int(str(value).strip())
        except (TypeError, ValueError):
            return False, None, "必须是整数", ""
        if num < spec.get("min", 0) or num > spec.get("max", 10 ** 9):
            return False, None, f"取值范围 {spec['min']} ~ {spec['max']}", ""
        return True, num, "", warn
    if kind == "secret":
        text = str(value or "")
        if len(text) < spec.get("min_len", 8):
            return False, None, f"口令至少 {spec['min_len']} 位", ""
        if text.lower() in WEAK_DEFAULTS:
            warn = "这是常见弱口令，生产环境建议换成更复杂的口令"
        return True, text, "", warn
    # path
    text = str(value or "").strip()
    blocked = _blocked_reason(text)
    if blocked:
        return False, None, blocked, ""
    info = probe_dir(text)
    if not info["ok"]:
        return False, None, f"目录不可用：{info['error']}", ""
    if not info["persistent"]:
        return False, None, (
            "该路径不在任何持久挂载点上，属于容器可写层 —— 容器重建后备份会全部丢失。"
            "请先在 docker-compose.yml 里把它挂载进来。"
        ), ""
    if info.get("same_device_as_data"):
        warn = "该目录与数据目录在同一块盘上：只能防误删，防不了磁盘故障"
    return True, text, "", warn


async def set_many(payload: dict[str, Any], who: str = "") -> dict:
    """批量保存。任何一项校验失败则整体不落库 —— 半套配置比旧配置更难排查。"""
    unknown = [k for k in payload if k not in EDITABLE]
    if unknown:
        return {"ok": False, "error": f"不支持修改的配置项：{', '.join(unknown)}"}

    normalized: dict[str, Any] = {}
    warnings: list[str] = []
    for key, raw in payload.items():
        ok, val, err, warn = validate(key, raw)
        if not ok:
            return {"ok": False, "error": f"「{EDITABLE[key]['label']}」{err}"}
        normalized[key] = val
        if warn:
            warnings.append(f"「{EDITABLE[key]['label']}」{warn}")

    if not normalized:
        return {"ok": True, "changed": [], "warnings": warnings}

    from . import audit as audit_svc
    from .auth import hash_password

    items = await asyncio.to_thread(_read_file)
    for key, val in normalized.items():
        # 口令只落哈希；其余项按原值存
        items[_skey(key)] = hash_password(str(val)) if EDITABLE[key]["kind"] == "secret" else val
    try:
        await asyncio.to_thread(_write_file, items)
    except OSError as e:
        return {"ok": False, "error": f"配置写入失败：{e}"}
    await reload()

    for key, val in normalized.items():
        # 口令只记「改过」，不记内容 —— 审计日志本身也不该成为泄密渠道
        await audit_svc.log_event(
            who or "system", "settings.update",
            detail={"key": key,
                    "value": "(已隐藏)" if EDITABLE[key]["kind"] == "secret" else str(val)},
        )

    log.info("运行期设置已更新：%s", ", ".join(sorted(normalized)))
    return {"ok": True, "changed": sorted(normalized), "warnings": warnings}


async def reset(key: str, who: str = "") -> dict:
    """把某项恢复成「环境变量/默认值」—— 即删掉文件里的覆盖"""
    if key not in EDITABLE:
        return {"ok": False, "error": f"不支持修改的配置项：{key}"}
    items = await asyncio.to_thread(_read_file)
    if _skey(key) in items:
        items.pop(_skey(key))
        await asyncio.to_thread(_write_file, items)
        await reload()
    log.info("运行期设置 %s 已恢复默认", key)
    value, source = effective(key)
    return {"ok": True, "key": key, "value": value, "source": source}
