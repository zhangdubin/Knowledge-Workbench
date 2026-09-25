"""v5 迁移：软删除列（回收站）

entity_type / entity_record 加 deleted_at。
SQLite 的 `ALTER TABLE ... ADD COLUMN` 加可空列是安全且幂等可判定的
（列不存在才加）。必须在 create_all 之后、任何 ORM 查询之前执行：
ORM 的 SELECT 会带上新列，晚一步就是启动即崩。
"""
from __future__ import annotations

import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")

COLUMNS = [
    ("entity_type", "deleted_at"),
    ("entity_record", "deleted_at"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_entity_type_deleted_at ON entity_type(deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix_entity_record_deleted_at ON entity_record(deleted_at)",
]


async def _has_column(cur, table: str, column: str) -> bool:
    await cur.execute(f"pragma table_info({table})")
    return any(row[1] == column for row in await cur.fetchall())


async def migrate_soft_delete_v5() -> None:
    # sqlite+aiosqlite:///./data/kb.db → ./data/kb.db
    db_path = settings.database_url.split("///", 1)[-1]
    conn = await aiosqlite.connect(db_path)
    try:
        cur = await conn.cursor()
        changed = False
        for table, column in COLUMNS:
            if not await _has_column(cur, table, column):
                await cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} DATETIME"
                )
                changed = True
                log.info("v5: %s 补列 %s", table, column)
        for ddl in INDEXES:
            await cur.execute(ddl)
        if changed:
            await conn.commit()
            log.info("v5: 软删除列迁移完成")
    finally:
        await conn.close()
