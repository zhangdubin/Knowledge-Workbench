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
# Delete/Insert/Update 从 sqlalchemy.sql.expression 取：
# sqlalchemy 顶层这几个名字是 2.0 才有的，老版本（1.4）在顶层取不到。
from sqlalchemy.sql.expression import Delete, Insert, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import AsyncAdaptedQueuePool

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


def _engine_kwargs() -> dict:
    """引擎参数：连接池大小按「是不是文件库」分开给

    文件库放开连接数：WAL 模式下多个读请求可以真并行，
    这是「用户一多会不会互相拖慢」的关键 —— 默认 5 条连接，
    第 6 个并发请求就开始排队。

    内存库只能一条连接：多于一条就看不到彼此的数据了（StaticPool）。
    这类库只出现在测试里，但参数给错会直接起不来，所以单独判。
    """
    url = (settings.database_url or "")
    if ":memory:" in url or "mode=memory" in url:
        return {}
    return {
        # aiosqlite 方言默认给的是 NullPool —— 「用完就扔」。
        # 后果是每条语句背后都新建一条连接：重新设一遍 PRAGMA、
        # 重新 load 一次 sqlite-vec 扩展、还要起一个新线程。
        # 这些全是固定开销，却每次都付 —— 实测一条 SQL 的开销里
        # 有大半是它，不是 SQL 本身。
        # 换成带池的适配器后，连接被复用，开销只付一次。
        "poolclass": AsyncAdaptedQueuePool,
        "pool_size": max(1, int(settings.sqlite_pool_size)),
        "max_overflow": max(0, int(settings.sqlite_max_overflow)),
        # 连接是长期持有的，得确认它还活着（文件被替换过时会失效）
        "pool_pre_ping": False,
    }


engine = create_async_engine(settings.database_url, echo=False, future=True,
                              **_engine_kwargs())
# 会被当成「瞬时错误」重试的 SQLite 报错
#
# 为什么需要这一层：数据目录常常挂在外接盘 / 网络盘上（bind mount 进容器）。
# 这类挂载偶发返回 "disk I/O error" —— 一次读失败就变成 500，
# 而这种错误重试一次通常就过去了（是盘抖了一下，不是数据坏了）。
#
# 刻意**不**重试的错误：唯一约束冲突、语法错、类型错 —— 那些重试多少次都一样，
# 重试只会把真正的报错推迟一点才暴露出来。
_TRANSIENT_SQLITE_MARKERS = (
    "disk i/o error",
    "database is locked",
    "database table is locked",
    "unable to open database file",
)


def is_transient_db_error(exc: BaseException) -> bool:
    """这个异常是不是「再来一次说不定就好了」"""
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_SQLITE_MARKERS)


def _is_write_statement(stmt) -> bool:
    """这条语句会不会改数据

    为什么要判断：会话层重试前要 rollback 整个事务，
    而重试只重跑失败的那一条 —— 事务里已经有写入时不能这么干
    （见 RetryingAsyncSession 的注释）。
    """
    if stmt is None:
        return False
    # ORM 的 Insert / Update / Delete
    if isinstance(stmt, (Insert, Update, Delete)):
        return True
    # 原生 SQL：只能看开头那点关键字
    text_value = getattr(stmt, "text", None)
    if isinstance(text_value, str):
        head = text_value.strip().lower()[:12]
        return head.startswith(("insert ", "update ", "delete ", "insert\n", "replace "))
    return False


class RetryingAsyncSession(AsyncSession):
    """遇到瞬时 I/O 错误自动重试的会话

    为什么放在会话这一层，而不是让每个接口自己 try/except：
    几十个查询点，逐个加 try/except 一定会漏；
    而漏掉的那个，表现就是「有时候刷新一下页面又好了」——
    最像玄学的一类故障。

    重试前必须 rollback：失败的语句已经把事务打断了，
    不回滚的话下一次执行会带着一个坏掉的事务去跑，
    报错会变得莫名其妙（「cannot start a transaction within a transaction」）。

    ⚠️ 但**事务里已经有写操作时不重试**（见 _kb_has_writes）：
    rollback() 回滚的是整个事务，而重试只重跑失败的那一条语句 ——
    于是「前面已经写进去的东西」被冲掉了，「重试成功的那一条」却留下了。
    踩过：文档入库时先 flush 写了文档行，紧接着的 FTS 插入遇到瞬时锁，
    回滚把文档行冲掉 → 重试成功 → commit 提交了 FTS 行 →
    库里留下指向不存在文档的 FTS 行，接口照样返回 200，文件静默丢失。
    这种「成功返回一个缺了数据的库」比直接报错难查得多，
    所以宁可把错误抛出去（整个事务回滚、调用方看得见），也不在有写入时重试。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 本事务里是否已经写进过东西（由 execute / after_flush 标记）
        self._kb_has_writes = False

    async def execute(self, *args, **kwargs):
        # 写语句先记一笔：后面遇到瞬时错误时靠它决定能不能重试
        stmt = args[0] if args else kwargs.get("statement")
        if _is_write_statement(stmt):
            self._kb_has_writes = True

        attempts = 3
        for attempt in range(attempts):
            try:
                return await super().execute(*args, **kwargs)
            except Exception as e:
                if attempt >= attempts - 1 or not is_transient_db_error(e):
                    raise
                if self._kb_has_writes:
                    log.warning(
                        "数据库瞬时错误，但本事务已有写操作，不再重试（避免回滚丢掉已写入的数据）：%s",
                        e,
                    )
                    raise
                log.warning("数据库瞬时错误，重试第 %d 次：%s", attempt + 1, e)
                try:
                    await self.rollback()
                except Exception:
                    pass
                await asyncio.sleep(0.15 * (attempt + 1))


SessionLocal = async_sessionmaker(engine, class_=RetryingAsyncSession,
                                 expire_on_commit=False)


@event.listens_for(Session, "after_flush")
def _mark_session_has_writes(session, flush_context):
    """ORM 刷过盘就算「这个事务写进东西了」

    为什么单独挂一个监听：add()/delete() 之后 flush 才真正写库，
    而 flush 可能发生在任何一条语句之前 —— 只有 flush 事件能准确回答
    「事务里已经有写入了吗」。
    """
    session._kb_has_writes = True


@event.listens_for(engine.sync_engine, "connect")
def _on_connect(dbapi_conn, connection_record):
    """每个新连接：设置 PRAGMA + 加载向量扩展

    PRAGMA 分两类：`journal_mode` 是写进库文件头部的持久化设置，只需设一次；
    这里全部是连接级设置，所以每条新连接都必须重设——连接池里换一条连接就
    等于换了配置，漏设某条会让性能悄悄退回默认值。
    """
    global VEC_AVAILABLE

    # 注册 SQLite 自定义函数：记录级倒排索引的触发器要用它做 bigram 切分。
    #
    # 为什么用触发器而不是在 Python 里维护索引：触发器写在库里，
    # 任何写入路径（ORM、批量 update、迁移脚本、将来新增的接口）都自动生效；
    # 靠 Python 钩子的话，只要漏掉一条写入路径，索引就悄悄过期了 ——
    # 表现是「搜不到某些记录」而且不报错，最难查的一类问题。
    #
    # 为什么每个连接都要注册：自定义函数是**连接级**的，
    # 连接池里换一条连接就等于换了一份函数表，漏注册会让触发器在那一刻报错。
    try:
        from .services import docindex as _docindex
        raw = dbapi_conn.driver_connection
        dbapi_conn.await_(raw.create_function(
            "kb_seg_bigram", 1, _docindex.seg_bigram_sql, deterministic=True))
    except Exception as e:
        log.warning("注册 kb_seg_bigram 失败，记录级倒排索引将不可用：%s", e)

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
    # 自定义函数也是连接级的：这条直连虽然不查向量表，
    # 但它照样可能触发 entity_record 的索引触发器，所以也得注册。
    try:
        from .services import docindex as _docindex
        conn.create_function("kb_seg_bigram", 1, _docindex.seg_bigram_sql,
                             deterministic=True)
    except Exception as e:
        log.warning("直连未注册 kb_seg_bigram：%s", e)
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
    finally:
        # 共享的 embedding HTTP 客户端要在关停时关掉，
        # 否则连接池会一直挂着（httpx 会打印 "Unclosed client" 警告）。
        # 放在这里是因为关停流程本来就归这一段管，
        # 不必为了一个 close 去改 main.py 的生命周期钩子。
        try:
            from .services import embedding as _embed_svc
            await _embed_svc.aclose_client()
        except Exception as e:
            log.warning("关闭 embedding 客户端失败：%s", e)



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

    # 注：知识库分组（note_group）**不需要迁移** —— 它是一张新表，
    # create_all 会把缺的表建出来。分组归属存在记录 data JSON 里，
    # 没有给任何既有表加列，所以这里没有 ALTER TABLE 的活。

    async with SessionLocal() as session:
        from .services.bootstrap import run_bootstrap
        await run_bootstrap(session)
        from .services.seed import run_seed
        await run_seed(session)

    # v7：给内置角色补「养料 DNA」页面权限 ——
    # 排在 bootstrap 之后：迁移改的是已存在角色的 perms，
    # 角色还没建出来的时候它什么也改不到。
    # （全新库里 bootstrap 建的角色本来就带 dna，迁移会跳过。）
    try:
        from .services.migrate_v7 import migrate_dna_page_perm_v7
        await migrate_dna_page_perm_v7()
    except Exception as e:
        log.error("养料 DNA 页面权限迁移失败，左侧导航可能看不到这一项：%s", e)

    # 索引表（FTS5 + vec0）不是 SQLAlchemy 模型，单独建
    from .services import docindex
    async with engine.begin() as conn:
        await docindex.ensure_index_tables(conn)
        # 记录级索引：记录检索原来靠 LIKE 全表扫描，
        # 记录一多（经验数据正是最会长大的那批）就越搜越慢。
        # 这张倒排索引让「候选」先被索引缩到几十条，再做精确过滤。
        await docindex.ensure_record_fts(conn)
        # 基因级索引：养料库自己的全文索引。
        # 与块级索引分开的理由：基因的粒度、生命周期、检索口径都不同
        # （块随文档重切，基因跨文档长期存在）。
        from .services import dna_library
        await dna_library.ensure_gene_fts(conn)

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
