"""关系表结构升级（v3）：两端支持「数据中心文件」

背景
----
v2 的 relation_def.source_type_id / target_type_id 是 NOT NULL 外键，
relation_record 也只有 record 两端的列。要让关系定义支持文件，
必须放开 NOT NULL 并加 document 端 —— SQLite 不支持把列改成可空，
只能按官方推荐的「建新表 → 拷数据 → 删旧表 → 改名」重排。

为什么用独立的 aiosqlite 连接而不是 SQLAlchemy session
------------------------------------------------------
迁移期间必须先关掉外键约束（旧表被 DROP 时子表还引用着它），
而 `PRAGMA foreign_keys` 在事务内是**静默无效**的。SQLAlchemy 的
begin() 一定在事务里，所以这里另开一条 autocommit 连接，
在事务外切换 PRAGMA，做完再恢复。

迁移是幂等的：已经是新结构就直接跳过。
"""
from __future__ import annotations

import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")

RELATION_DEF_NEW = """
CREATE TABLE relation_def__v3 (
  id INTEGER NOT NULL PRIMARY KEY,
  key VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  source_kind VARCHAR(16) DEFAULT 'record',
  source_type_id INTEGER REFERENCES entity_type(id) ON DELETE CASCADE,
  target_kind VARCHAR(16) DEFAULT 'record',
  target_type_id INTEGER REFERENCES entity_type(id) ON DELETE CASCADE,
  cardinality VARCHAR(16) DEFAULT 'many-to-many',
  description VARCHAR(256) DEFAULT '',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

RELATION_RECORD_NEW = """
CREATE TABLE relation_record__v3 (
  id INTEGER NOT NULL PRIMARY KEY,
  relation_def_id INTEGER NOT NULL REFERENCES relation_def(id) ON DELETE CASCADE,
  source_record_id INTEGER REFERENCES entity_record(id) ON DELETE CASCADE,
  target_record_id INTEGER REFERENCES entity_record(id) ON DELETE CASCADE,
  source_document_id INTEGER REFERENCES document(id) ON DELETE CASCADE,
  target_document_id INTEGER REFERENCES document(id) ON DELETE CASCADE,
  data JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

RECORD_INDEXES = [
    "CREATE INDEX ix_relation_record_source_record_id ON relation_record(source_record_id)",
    "CREATE INDEX ix_relation_record_target_record_id ON relation_record(target_record_id)",
    "CREATE INDEX ix_relrec_src_doc ON relation_record(source_document_id)",
    "CREATE INDEX ix_relrec_tgt_doc ON relation_record(target_document_id)",
]


def _db_path() -> str:
    # sqlite+aiosqlite:///./data/kb.db → ./data/kb.db
    return settings.database_url.split("///", 1)[-1]


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    await cur.close()
    return {r[1] for r in rows}


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    row = await cur.fetchone()
    await cur.close()
    return bool(row)


async def _upgrade_relation_def(db: aiosqlite.Connection) -> bool:
    cols = await _columns(db, "relation_def")
    if "source_kind" in cols:
        return False
    await db.execute(RELATION_DEF_NEW)
    await db.execute("""
        INSERT INTO relation_def__v3
          (id, key, name, source_kind, source_type_id, target_kind, target_type_id,
           cardinality, description, created_at)
        SELECT id, key, name, 'record', source_type_id, 'record', target_type_id,
               COALESCE(cardinality, 'many-to-many'), COALESCE(description, ''), created_at
        FROM relation_def
    """)
    await db.execute("DROP TABLE relation_def")
    await db.execute("ALTER TABLE relation_def__v3 RENAME TO relation_def")
    return True


async def _upgrade_relation_record(db: aiosqlite.Connection) -> bool:
    cols = await _columns(db, "relation_record")
    if "source_document_id" in cols:
        return False
    await db.execute(RELATION_RECORD_NEW)
    await db.execute("""
        INSERT INTO relation_record__v3
          (id, relation_def_id, source_record_id, target_record_id, data, created_at)
        SELECT id, relation_def_id, source_record_id, target_record_id,
               COALESCE(data, '{}'), created_at
        FROM relation_record
    """)
    await db.execute("DROP TABLE relation_record")
    await db.execute("ALTER TABLE relation_record__v3 RENAME TO relation_record")
    for ddl in RECORD_INDEXES:
        await db.execute(ddl)
    return True


async def migrate_relations_v3() -> dict:
    """返回 {'relation_def': bool, 'relation_record': bool}（True=本次改过）"""
    path = _db_path()
    changed = {"relation_def": False, "relation_record": False}
    try:
        async with aiosqlite.connect(path, isolation_level=None) as db:
            touched = False
            await db.execute("PRAGMA foreign_keys=OFF")
            try:
                if await _table_exists(db, "relation_def"):
                    changed["relation_def"] = await _upgrade_relation_def(db)
                    touched = touched or changed["relation_def"]
                if await _table_exists(db, "relation_record"):
                    changed["relation_record"] = await _upgrade_relation_record(db)
                    touched = touched or changed["relation_record"]
            finally:
                # 无论中途是否报错，都要把外键约束恢复回来
                await db.execute("PRAGMA foreign_keys=ON")
            if touched:
                log.warning(
                    "关系表已升级到 v3（两端支持文件）：%s", changed
                )
    except Exception as e:
        log.error("关系表升级失败：%s", e)
        raise
    return changed
