"""文档表结构升级（v4）：原文位置双列 + 外迁进度标注

背景
----
v0.2 的文件原文直接存在 document.data（BLOB）。v0.3 起改为外置到文件系统，
需要两列描述原文归属：
  - storage：'db' | 'fs'
  - path   ：storage='fs' 时的相对路径

为什么用 aiosqlite 直连而不是 SQLAlchemy
----------------------------------------
`ALTER TABLE ... ADD COLUMN` 本身能在事务里跑，但迁移必须跑在
Base.metadata.create_all 之前无法保证的时机上（create_all 只建缺失的表，
不会给已有表补列）。直连 autocommit 连接最省事，也与 v3 的写法保持一致。

幂等：两列都有了就直接返回 False，不重复改。

回填规则
--------
老的 BLOB 行必须显式标成 storage='db'：列默认值虽然也是 'db'，
但 ADD COLUMN 时 SQLite 会把已有行填成默认值，而**已软删除的文件**
同样要保留原文（回收站里还能恢复），所以不能顺手清空任何一行的 data。
"""
from __future__ import annotations

import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")

NEW_COLUMNS = [
    ("storage", "VARCHAR(8) DEFAULT 'db'"),
    ("path", "VARCHAR(256) DEFAULT ''"),
]

NEW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_document_storage ON document(storage)",
]


def _db_path() -> str:
    return settings.database_url.split("///", 1)[-1]


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    await cur.close()
    return {r[1] for r in rows}


async def migrate_documents_v4() -> dict:
    """返回 {'added': [...], 'counts': {'db': n, 'fs': m}}"""
    path = _db_path()
    added: list[str] = []
    counts = {"db": 0, "fs": 0}
    try:
        async with aiosqlite.connect(path, isolation_level=None) as db:
            cols = await _columns(db, "document")
            if not cols:
                # 全新库：create_all 已经建好新结构，不需要迁移
                return {"added": [], "counts": counts}

            for name, ddl in NEW_COLUMNS:
                if name not in cols:
                    await db.execute(f"ALTER TABLE document ADD COLUMN {name} {ddl}")
                    added.append(name)

            if added:
                # 已有行的 storage 由 ADD COLUMN 的默认值兜底，这里显式确认一次，
                # 防止某些 SQLite 版本对 DEFAULT 的处理差异留下 NULL
                await db.execute("UPDATE document SET storage='db' WHERE storage IS NULL")
                await db.execute("UPDATE document SET path='' WHERE path IS NULL")
                for ddl in NEW_INDEXES:
                    await db.execute(ddl)
                log.warning("document 表已升级到 v4（原文位置双列）：新增 %s", added)

            cur = await db.execute(
                "SELECT storage, count(*) FROM document GROUP BY storage"
            )
            for mode, n in await cur.fetchall():
                counts[str(mode or "db")] = int(n)
            await cur.close()
    except Exception as e:
        log.error("document 表升级失败：%s", e)
        raise
    return {"added": added, "counts": counts}
