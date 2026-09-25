"""后台定时维护

为什么必须有这一层：这是一个**长期运行**的服务，而在此之前所有维护动作
都只在启动/关停时执行一次 —— 意味着一个连续跑半年的实例里，
过期会话、审计日志、WAL 文件会一路涨到没人注意，直到某天写不进去。

四个循环，间隔都能配（见 config.py）：

  会话清理   过期会话在「被访问时」才会删，没人访问就一直留着。长期下来
             user_session 表会堆满死 token。
  审计清理   按 audit_keep_days 截断，然后 PRAGMA optimize 更新统计信息。
  检查点     PASSIVE 模式不阻塞写入，把 WAL 内容推回主库。WAL 无限增长是
             SQLite 部署里最常见的隐形故障：读性能不变差，但磁盘会满。
  健康探测   把 quick_check 结果缓存下来，让 /api/health 保持毫秒级 ——
             Docker healthcheck 每 10 秒打一次，不能每次都跑一遍库检查。

所有循环都「单次失败不影响下一轮」：网络/磁盘抖动不该让维护永久停摆，
但要留下日志和 last_error 供诊断页读取。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import delete

from ..config import settings
from ..database import SessionLocal

log = logging.getLogger("kb.scheduler")

# 供健康检查读取的最近一次探测结果（不查库，纯内存读）
HEALTH: dict = {
    "at": 0.0,
    "ok": None,
    "quick_check": "unknown",
    "bytes": 0,
    "freelist_kb": 0,
    "vec_available": False,
    "error": "",
    "last_session_sweep": None,
    "last_audit_sweep": None,
    "last_checkpoint": None,
}


async def _sweep_sessions() -> int:
    """删掉已过期的会话（含被停用账号遗留的）"""
    from ..models import UserSession

    async with SessionLocal() as db:
        res = await db.execute(
            delete(UserSession).where(UserSession.expires_at < datetime.now())
        )
        await db.commit()
        return res.rowcount or 0


async def _sweep_audit() -> int:
    from .audit import purge_old
    async with SessionLocal() as db:
        return await purge_old(db)


def _checkpoint_sync() -> list:
    """PASSIVE 检查点：不阻塞写入，只是尽量把 WAL 推回主库

    不用 TRUNCATE：那个需要所有连接都推到最新，运行中会直接返回 busy，
    而且把 WAL 截到 0 会让后续写入重新分配文件。TRUNCATE 留给关停流程用。
    """
    from ..database import direct_connection
    conn = direct_connection(busy_ms=10000)
    try:
        row = conn.execute("pragma wal_checkpoint(PASSIVE)").fetchone()
        return list(row or [])
    finally:
        conn.close()


def _optimize_sync() -> None:
    from ..database import direct_connection
    conn = direct_connection(busy_ms=10000)
    try:
        conn.execute("pragma optimize")
    finally:
        conn.close()


async def _probe() -> dict:
    from ..database import probe_health
    return await probe_health()


def _loop(name: str, interval_s: float, fn, *, on_done=None):
    """把一个同步/异步函数包成固定间隔的常驻循环

    先 sleep 再执行：启动瞬间正是初始化最忙的时候，不该再挤进一次全库扫描。
    """
    async def _run():
        while True:
            try:
                await asyncio.sleep(interval_s)
                started = time.time()
                out = fn()
                if asyncio.iscoroutine(out):
                    out = await out
                if on_done:
                    on_done(out)
                log.info("定时维护「%s」完成，耗时 %.2fs", name, time.time() - started)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 单轮失败绝不终止循环：磁盘抖动、临时锁冲突都只应影响这一轮
                log.warning("定时维护「%s」失败（将于下一轮重试）：%s", name, e)

    return asyncio.create_task(_run(), name=f"kb-maint-{name}")


class Scheduler:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []
        self.started_at: float = 0.0

    def prime_health(self, out: dict) -> None:
        """把启动自检的结果直接喂进健康缓存

        没有这一步的话，服务起来后到第一次定时探测之间（最长
        health_probe_minutes）健康接口会一直报 unknown —— 而上线自检脚本
        正好在这个窗口里跑，会误报「数据库自检未通过」。
        启动时本来就已经跑过一次 probe_health，结果直接复用即可。
        """
        self._on_probe(out)

    async def start(self) -> None:
        if not settings.maintenance_enabled:
            log.warning("后台定时维护已关闭（KB_MAINTENANCE_ENABLED=false）")
            return
        self.started_at = time.time()

        # 启动时先跑一轮会话清理 —— 上一轮可能停在上个月，过期会话正堆着
        try:
            n = await _sweep_sessions()
            if n:
                log.info("启动清理 %s 条过期会话", n)
        except Exception as e:
            log.warning("启动会话清理失败：%s", e)

        # 健康缓存还没被 prime 过（例如维护被关闭）就先探一次，
        # 保证 /api/health 永远给得出一个有依据的结论
        if HEALTH["at"] == 0.0:
            try:
                self._on_probe(await _probe())
            except Exception as e:
                log.warning("启动健康探测失败：%s", e)

        self.tasks = [
            _loop("会话清理", settings.session_sweep_minutes * 60, _sweep_sessions,
                  on_done=lambda n: HEALTH.update(last_session_sweep=time.time(), swept=n)),
            _loop("审计清理", settings.audit_sweep_minutes * 60, _sweep_audit,
                  on_done=lambda n: HEALTH.update(last_audit_sweep=time.time(),
                                                  purged=n)),
            _loop("WAL 检查点", settings.checkpoint_minutes * 60, _checkpoint_sync,
                  on_done=lambda r: HEALTH.update(last_checkpoint=time.time())),
            _loop("健康探测", settings.health_probe_minutes * 60, _probe,
                  on_done=self._on_probe),
        ]
        # optimize 与审计清理同频（统计信息要跟着数据量走）
        self.tasks.append(
            _loop("查询计划刷新", settings.audit_sweep_minutes * 60, _optimize_sync)
        )
        log.info("后台定时维护已启动：会话 %s 分钟 / 审计 %s 分钟 / 检查点 %s 分钟",
                 settings.session_sweep_minutes, settings.audit_sweep_minutes,
                 settings.checkpoint_minutes)

    def _on_probe(self, out: dict) -> None:
        HEALTH.update(
            at=time.time(),
            ok=bool(out.get("ok")),
            quick_check=str(out.get("quick_check") or "unknown"),
            bytes=int(out.get("bytes") or 0),
            freelist_kb=int(out.get("freelist_kb") or 0),
            vec_available=bool(out.get("vec_available")),
            error="" if out.get("ok") else str(out.get("quick_check") or ""),
        )

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.tasks = []


scheduler = Scheduler()


def health_snapshot() -> dict:
    """给健康检查用的一份只读快照（含「探测结果是否太旧」的判断）"""
    now = time.time()
    age = now - HEALTH["at"] if HEALTH["at"] else None
    fresh = age is not None and age < max(settings.health_probe_minutes * 60 * 3, 900)
    return {
        **HEALTH,
        "age_seconds": int(age) if age is not None else None,
        "fresh": fresh,
        "maintenance_enabled": settings.maintenance_enabled,
        "next_probe_in": settings.health_probe_minutes * 60,
    }
