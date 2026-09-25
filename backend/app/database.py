"""数据库引擎与初始化

v0.2 起，kb.db 不再只是元数据库——它同时承载：
  1. document 表里的文件原文（BLOB）
  2. FTS5 全文索引
  3. sqlite-vec 向量索引

因此引擎初始化多了两件事：
  - 每个新连接都要加载 sqlite-vec 扩展（扩展是连接级的，不加载则
    vec0 虚拟表不可用）
  - 开启 WAL，让「写文件」与「查询」不再互相阻塞

已验证的关键细节：sqlite-vec 的 loadable_path() 返回的是不带后缀的路径，
由 SQLite 自行补平台后缀（Linux .so / macOS .dylib），所以不要手动拼后缀，
也不要用 os.path.exists 判断有效性 —— 会误判为不存在。
"""
import asyncio
import logging
import os
import sqlite3

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

log = logging.getLogger("kb.db")

# 扩展是否加载成功（供状态接口展示）
VEC_AVAILABLE = False


def _load_sqlite_vec(dbapi_conn) -> bool:
    """在已建立的 DBAPI 连接上加载 sqlite-vec 扩展

    SQLAlchemy 的 aiosqlite 适配器把驱动的协程方法藏在 await_() 后面，
    必须通过 driver_connection 拿到原生 aiosqlite 连接再 await。
    """
    try:
        import sqlite_vec

        raw = dbapi_conn.driver_connection
        dbapi_conn.await_(raw.enable_load_extension(True))
        dbapi_conn.await_(raw.load_extension(sqlite_vec.loadable_path()))
        dbapi_conn.await_(raw.enable_load_extension(False))
        return True
    except Exception as e:  # 扩展缺失不应导致整个服务起不来
        log.warning("sqlite-vec 扩展加载失败，向量检索将不可用：%s", e)
        return False


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _on_connect(dbapi_conn, connection_record):
    """每个新连接：设置 PRAGMA + 加载向量扩展

    PRAGMA 分两类：`journal_mode` 是写进库文件头部的持久化设置，只需设一次；
    这里全部是连接级设置，所以每条新连接都必须重设——连接池里换一条连接就
    等于换了配置，漏设某条会让性能悄悄退回默认值。
    """
    global VEC_AVAILABLE

    cur = dbapi_conn.cursor()
    try:
        # 写锁等待：SQLite 单写者，并发写时靠它排队而不是立刻报 database is locked
        cur.execute("pragma busy_timeout=15000")
        cur.execute("pragma foreign_keys=ON")
        # WAL + NORMAL：崩溃不丢已提交事务，仅在操作系统/断电级故障下可能丢最后几个事务
        cur.execute("pragma synchronous=NORMAL")
        # 页缓存：默认 2MB 对小库够用，一旦热数据超过就得反复回读
        cur.execute(f"pragma cache_size=-{max(settings.sqlite_cache_mb, 2) * 1024}")
        # 内存映射读：省掉 read() 系统调用，读多写少的场景收益最大
        if settings.sqlite_mmap_mb > 0:
            cur.execute(f"pragma mmap_size={settings.sqlite_mmap_mb * 1024 * 1024}")
        # 排序/临时 B 树放内存，避免 GROUP BY、VACUUM 时落盘
        cur.execute("pragma temp_store=MEMORY")
        cur.execute(f"pragma wal_autocheckpoint={max(settings.sqlite_wal_autocheckpoint, 100)}")
    finally:
        cur.close()

    if _load_sqlite_vec(dbapi_conn):
        VEC_AVAILABLE = True


def _pragma_report(conn) -> dict:
    """在原生连接上读库状态（同步实现，由调用方决定放哪个线程跑）"""
    cur = conn.cursor()
    try:
        quick = str(cur.execute("pragma quick_check").fetchone()[0] or "")
        page_size = int(cur.execute("pragma page_size").fetchone()[0] or 4096)
        page_count = int(cur.execute("pragma page_count").fetchone()[0] or 0)
        free_pages = int(cur.execute("pragma freelist_count").fetchone()[0] or 0)
    finally:
        cur.close()
    return {
        "quick_check": quick,
        "ok": quick.lower() == "ok",
        "page_count": page_count,
        "bytes": page_count * page_size,
        "freelist_kb": free_pages * page_size // 1024,
    }


def db_file_path() -> str:
    """库文件的绝对路径。

    从引擎的 URL 取而不是拼 settings.database_url：URL 可能带查询参数、
    也可能是相对路径，交给 SQLAlchemy 解析才不会出错。
    """
    p = engine.url.database or "./data/kb.db"
    return os.path.abspath(p)


def direct_connection(busy_ms: int = 30000):
    """直连 SQLite 的同步连接（autocommit），专供诊断与维护用。

    为什么不复用 `engine.sync_engine.raw_connection()`：在 async 引擎上，
    那个入口被 greenlet 包着，一旦在 `asyncio.to_thread` 里调用就会抛
    「greenlet_spawn has not been called」。而诊断/维护这类操作本来也不该
    沾 ORM 的事务语义 —— PRAGMA、VACUUM、dbstat 在事务里行为都会变。

    注意：这个连接**不会**加载 sqlite-vec 扩展，所以不能用它查
    document_vec 这类虚拟表；需要向量表的查询请走正常的 async session。
    """
    conn = sqlite3.connect(db_file_path(), timeout=busy_ms / 1000.0,
                           isolation_level=None)
    conn.execute(f"pragma busy_timeout={int(busy_ms)}")
    return conn


async def probe_health() -> dict:
    """启动期自检：库能不能读、有没有结构性损坏、体积与空洞

    quick_check 与 integrity_check 的区别：前者只校验 B 树与索引的结构一致性，
    不做逐行内容比对，通常毫秒级返回；后者是完整校验，大库上可能要跑几分钟。
    启动路径只用前者，完整校验交给运维在备份后主动触发。
    """
    info = {"ok": False, "quick_check": "unknown", "bytes": 0,
            "page_count": 0, "freelist_kb": 0, "vec_available": VEC_AVAILABLE}

    def _run() -> dict:
        conn = direct_connection()
        try:
            return _pragma_report(conn)
        finally:
            conn.close()

    try:
        info.update(await asyncio.to_thread(_run))
    except Exception as e:
        info["quick_check"] = f"失败：{e}"
    info["vec_available"] = VEC_AVAILABLE
    return info


def _do_maintenance(conn) -> dict:
    cur = conn.cursor()
    out = {"optimized": False, "wal_truncated": False, "checkpoint": None}
    try:
        cur.execute("pragma optimize")
        out["optimized"] = True
    except Exception as e:
        log.warning("PRAGMA optimize 失败：%s", e)
    try:
        # TRUNCATE 会把 WAL 文件缩回 0 字节——正常运行时留着它反而更快，
        # 但关停时截断能让「拷 data 目录」这种朴素备份方式至少是完整的
        row = cur.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()
        out["wal_truncated"] = True
        out["checkpoint"] = list(row or [])
    except Exception as e:
        log.warning("WAL checkpoint 失败：%s", e)
    finally:
        cur.close()
    return out


async def shutdown_maintenance() -> dict:
    """关停前维护：刷新查询计划统计 + 截断 WAL

    `PRAGMA optimize` 是 SQLite 官方建议的「长期运行后必做」动作：它会根据
    实际查询分布更新 sqlite_stat1，否则 ANALYZE 之后数据长了几倍，查询计划
    仍按旧基数估算，可能一直选错索引。默认只在需要时写统计，开销很小。

    调用前必须先把连接池 dispose 掉：checkpoint(TRUNCATE) 需要把所有连接
    都推到最新，池里留着活跃连接时它会直接返回 busy。
    """

    def _run() -> dict:
        conn = direct_connection()
        try:
            return _do_maintenance(conn)
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        log.warning("关停维护未完成：%s", e)
        return {"optimized": False, "wal_truncated": False}



async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def init_db():
    """初始化：建表 → 启动补全 → 种子 → 索引（FTS5 / vec0）→ 存量迁移"""
    from . import models  # noqa: F401  让 Base.metadata 知道所有模型

    async with engine.begin() as conn:
        # WAL 是持久化设置，写进库文件头部，只需设置一次
        try:
            await conn.execute(text("pragma journal_mode=WAL"))
        except Exception as e:
            log.warning("开启 WAL 失败：%s", e)
        await conn.run_sync(Base.metadata.create_all)

    # 文档表补列（storage / path）—— 必须紧跟在 create_all 之后：
    # create_all 只建缺失的表，不会给已存在的 document 表补列，
    # 而此后的任何 ORM 查询都会 SELECT 这两列，晚一步就是启动即崩。
    try:
        from .services.migrate_v4 import migrate_documents_v4
        await migrate_documents_v4()
    except Exception as e:
        log.error("document 表补列失败，文件功能可能不可用：%s", e)

    # v5：软删除列（回收站）—— 同样必须紧跟 create_all：
    # 此后 bootstrap/seed 的任何 ORM 查询都会 SELECT deleted_at。
    try:
        from .services.migrate_v5 import migrate_soft_delete_v5
        await migrate_soft_delete_v5()
    except Exception as e:
        log.error("软删除列迁移失败，回收站功能可能不可用：%s", e)

    # v6：dashboard 大屏设置列 —— 同样紧跟 create_all，理由同上
    try:
        from .services.migrate_v6 import migrate_dashboard_settings_v6
        await migrate_dashboard_settings_v6()
    except Exception as e:
        log.error("dashboard 设置列迁移失败，大屏设置可能不可用：%s", e)

    async with SessionLocal() as session:
        from .services.bootstrap import run_bootstrap
        await run_bootstrap(session)
        from .services.seed import run_seed
        await run_seed(session)

    # 索引表（FTS5 + vec0）不是 SQLAlchemy 模型，单独建
    from .services import docindex
    async with engine.begin() as conn:
        await docindex.ensure_index_tables(conn)

    # 存量迁移 + 启动期修补（均为幂等，只在需要时动手）
    try:
        from .services.migrate_v2 import migrate_legacy_files, run_startup_repairs
        async with SessionLocal() as session:
            await migrate_legacy_files(session)
        async with SessionLocal() as session:
            await run_startup_repairs(session)
    except Exception as e:
        log.warning("存量迁移/修补跳过：%s", e)

    # 关系表结构升级（两端支持文件）—— 必须在 create_all 之后、任何关系查询之前
    try:
        from .services.migrate_v3 import migrate_relations_v3
        await migrate_relations_v3()
    except Exception as e:
        log.error("关系表升级失败，关系功能可能不可用：%s", e)
