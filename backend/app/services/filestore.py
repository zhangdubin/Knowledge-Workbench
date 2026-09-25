"""文件原文外置存储（内容寻址）

为什么要从 SQLite BLOB 换成文件系统：
  1. 库文件体积 = 原文 + FTS + 向量。原文留在库里，库越大，备份窗口、
     VACUUM 耗时、崩溃恢复时间一起线性变差；拆出去后库只装元数据与索引，
     体积增长慢一个量级。
  2. SQLite 读 BLOB 是「整块进内存」，一个 500MB 的文件就够把进程内存抬起来；
     落到文件后下载可以直接走内核 sendfile + Range，不必先进 Python 内存。
  3. 内容寻址天然去重：同一份文件重复上传零额外占用，这是 BLOB 方案给不了的。

目录布局：<root>/<sha[0:2]>/<sha[2:4]>/<sha[4:]><ext>
  - 两级前缀共 65536 个桶，单目录不会堆到几万个文件（ext4 大目录检索会变慢）
  - 文件名就是内容摘要：相同内容 → 相同路径 → 自动去重
  - 写入走「临时文件 + rename」：同一文件系统内 rename 是原子的，
    不会出现「库里已记下路径、盘上却是半个文件」的半成品状态

为什么 DB 里仍要保留 storage/path 两列而不是只靠 sha256 推算：
  历史数据（v0.2 上传的）原文还在 BLOB 里，没有对应文件；迁移是分批进行的，
  过程中两种存储必然共存。用显式列标注来源，读取路径才能对两种数据都正确，
  也才能一眼看出「还有多少没迁」。
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from ..config import settings

log = logging.getLogger("kb.filestore")

# storage 列取值
MODE_DB = "db"      # 原文在 document.data（历史数据 / 显式回退）
MODE_FS = "fs"      # 原文在文件系统

# 目录用量统计缓存（秒）。walk 一个大目录要几十毫秒到几秒，
# 存储页会反复刷新，不做缓存会把接口拖慢。
_USAGE_TTL = 20.0
_usage_cache: dict = {"at": 0.0, "value": None}


def root() -> Path:
    """文件根目录的绝对路径"""
    return Path(settings.file_store_dir).resolve()


def ensure_root() -> Path:
    p = root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def enabled() -> bool:
    """是否启用外置存储（关闭时新文件仍进数据库，用于回退排查）"""
    return (settings.file_store or MODE_FS).lower() != MODE_DB


def _safe_sha(sha: str) -> str:
    """只接受 64 位十六进制的 sha256；其余情况用随机名兜底

    摘要来自服务端计算，但因为要拼进文件路径，仍然必须白名单校验 ——
    一旦某天 sha 变成外部可控，`../` 就能写到目录外。
    """
    s = (sha or "").strip().lower()
    if len(s) == 64 and all(c in "0123456789abcdef" for c in s):
        return s
    return hashlib.sha256(os.urandom(32)).hexdigest()


def _safe_ext(ext: str) -> str:
    e = (ext or "").strip().lower()
    if not e.startswith(".") or len(e) > 12:
        return ""
    return e if all(c.isalnum() or c == "." for c in e) else ""


def rel_path(sha: str, ext: str = "") -> str:
    """内容摘要 → 相对路径（存进 document.path 的就是这个）"""
    s = _safe_sha(sha)
    return f"{s[0:2]}/{s[2:4]}/{s[4:]}{_safe_ext(ext)}"


def abs_path(rel: str) -> Path:
    """相对路径 → 绝对路径。做一次越界校验，杜绝 `..` 逃逸。"""
    r = (rel or "").lstrip("/")
    p = (root() / r).resolve()
    base = root()
    if base != p and base not in p.parents:
        raise ValueError(f"非法文件路径：{rel}")
    return p


def exists(rel: str) -> bool:
    try:
        return bool(rel) and abs_path(rel).is_file()
    except Exception:
        return False


def put(data: bytes, sha: str, ext: str = "") -> str:
    """写入文件，返回相对路径。

    内容寻址（幂等）：目标路径已存在就直接返回，不重复写盘 ——
    这就是「秒传」：同一份文件第二次上传时零 IO。
    """
    rel = rel_path(sha, ext)
    dst = abs_path(rel)
    if dst.is_file() and dst.stat().st_size == len(data):
        return rel

    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            if settings.file_store_fsync:
                os.fsync(f.fileno())
        os.replace(tmp, dst)          # 原子替换：要么旧文件、要么完整新文件
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return rel


def load(*, storage: str | None, path: str | None, data: bytes | None) -> bytes:
    """统一的原文读取入口：外置读盘、内置读列。

    调用方不需要知道文件在哪 —— 迁移过程中两种来源会同时存在。
    """
    if storage == MODE_FS:
        if not path:
            return b""
        try:
            return abs_path(path).read_bytes()
        except FileNotFoundError:
            log.error("原文文件缺失：%s（元数据仍在，请从备份恢复 files 目录）", path)
            raise FileNotFoundError(f"文件内容缺失：{path}") from None
    return data or b""


def open_stream(*, storage: str | None, path: str | None):
    """返回 (类文件对象, 字节数)，供 FileResponse 流式发送。

    外置文件直接给句柄，让 uvicorn 走 sendfile；BLOB 只能先读成 bytes，
    用 BytesIO 包一层保持接口一致。
    """
    if storage == MODE_FS:
        if not path:
            return None, 0
        p = abs_path(path)
        if not p.is_file():
            raise FileNotFoundError(f"文件内容缺失：{path}")
        return p.open("rb"), p.stat().st_size
    return None, 0


def remove(rel: str) -> bool:
    """删除一个文件（以及随之变空的目录）

    只做物理删除，「还有没有别的记录在引用」由调用方判断 ——
    文件层不该知道 document 表的存在。
    """
    if not rel:
        return False
    try:
        p = abs_path(rel)
    except ValueError:
        return False
    try:
        p.unlink()
    except FileNotFoundError:
        return False
    except OSError as e:
        log.warning("删除文件失败 %s：%s", rel, e)
        return False
    # 顺手清掉空目录，避免迁移/删除后留下一堆空桶
    for d in (p.parent, p.parent.parent):
        try:
            d.rmdir()
        except OSError:
            break
    return True


def usage(*, refresh: bool = False) -> dict:
    """扫描文件根目录的占用（文件数 / 字节数 / 目录数）"""
    now = time.time()
    if not refresh and _usage_cache["value"] and now - _usage_cache["at"] < _USAGE_TTL:
        return _usage_cache["value"]

    files = 0
    bytes_ = 0
    dirs = 0
    err = ""
    try:
        base = root()
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirs += len(dirnames)
                for name in filenames:
                    if name.startswith(".tmp-"):
                        continue
                    files += 1
                    try:
                        bytes_ += os.path.getsize(os.path.join(dirpath, name))
                    except OSError:
                        pass
    except Exception as e:      # 目录不存在 / 权限不足都不该让存储页挂掉
        err = f"{type(e).__name__}: {e}"

    value = {"files": files, "bytes": bytes_, "dirs": dirs,
             "root": str(root()), "error": err}
    _usage_cache["at"] = now
    _usage_cache["value"] = value
    return value


def invalidate_usage() -> None:
    _usage_cache["at"] = 0.0


def disk_free() -> dict:
    """所在磁盘的余量 —— 原文外置后，「盘满」变成比「库大」更早触发的风险"""
    try:
        u = shutil.disk_usage(root())
        return {"total": u.total, "used": u.used, "free": u.free,
                "pct_used": round(100.0 * u.used / u.total, 1) if u.total else 0.0}
    except Exception as e:
        return {"total": 0, "used": 0, "free": 0, "pct_used": 0.0,
                "error": f"{type(e).__name__}: {e}"}


def status() -> dict:
    """给存储页/健康检查用的一览"""
    u = usage()
    d = disk_free()
    return {
        "mode": (settings.file_store or MODE_FS).lower(),
        "enabled": enabled(),
        "root": u["root"],
        "files": u["files"],
        "bytes": u["bytes"],
        "dirs": u["dirs"],
        "fsync": settings.file_store_fsync,
        "disk": d,
        "error": u["error"],
    }
