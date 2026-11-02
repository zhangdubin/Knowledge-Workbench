"""v8 迁移：基因评分（表达度/置信度）、可复用产出、外部开源项目来源

这一版把「知识库」从「存得下」推向「学得会、用得上」：

    dna_gene            补两列：expressiveness（表达度镜像）、score_version（评分口径版本）
    dna_gene_score      评分明细表：分数 + 分项 + 依据 + 履历计数
    dna_asset           可复用产出：代码片段 / 接口契约 / 操作步骤
    dna_asset_use       产出的使用事件（证据链：哪个项目、什么结果）
    dna_openkb_source   外部开源项目的来源档案（仓库、许可证、吸收统计）

为什么要单独做一次迁移，而不是改 ORM 模型就完事：

    1. dna_gene 是**老表**。SQLAlchemy 的 create_all 只建缺���的表，
       不会给已存在的表加列 —— 新列必须用 ALTER TABLE 补。
       而且补列必须发生在**任何一条 SELECT DnaGene 之前**，
       否则 ORM 会带着不存在的列去查，整张表都用不了。
    2. 新表虽然 create_all 也会建，但离线包导入、老库升级、
       只跑迁移脚本的维护场景下，迁移文件必须是自足的那一份。
    3. 迁移要**幂等**：跑第二遍不能报错、不能清数据。
       —— 这一条对「绝不删现有数据」是硬要求。

脚本入口：scripts/dna_rescore.py（回填新分数）会调用这里的结构补齐函数。
"""
from __future__ import annotations

import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")

META_KEY = "migrated_dna_learning_v8"

# dna_gene 要补的列：{列名: SQL 片段}
GENE_COLUMNS = {
    "expressiveness": "real default 0",
    "score_version": "integer default 0",
}

# 新表：{表名: 建表 SQL}
TABLES = {
    "dna_gene_score": (
        "create table if not exists dna_gene_score ("
        "id integer primary key autoincrement,"
        "gene_id integer not null unique,"
        "expressiveness real default 0,"
        "confidence real default 0,"
        "express_parts text default '{}',"
        "confidence_parts text default '{}',"
        "evidence text default '{}',"
        "use_success integer default 0,"
        "use_fail integer default 0,"
        "corrections integer default 0,"
        "corroborations integer default 0,"
        "distinct_sources integer default 1,"
        "extraction_confidence real default 0.7,"
        "version integer default 0,"
        "last_scored_at datetime,"
        "created_at datetime default (datetime('now')),"
        "updated_at datetime default (datetime('now')))"
    ),
    "dna_asset": (
        "create table if not exists dna_asset ("
        "id integer primary key autoincrement,"
        "uid text not null unique,"
        "kind text default 'note',"
        "title text default '',"
        "content text default '',"
        "language text default '',"
        "gene_id integer,"
        "source_kind text default '',"
        "source_title text default '',"
        "use_count integer default 0,"
        "use_success integer default 0,"
        "use_fail integer default 0,"
        "last_project text default '',"
        "last_used_at datetime,"
        "meta text default '{}',"
        "created_at datetime default (datetime('now')),"
        "updated_at datetime default (datetime('now')))"
    ),
    "dna_asset_use": (
        "create table if not exists dna_asset_use ("
        "id integer primary key autoincrement,"
        "asset_id integer not null,"
        "gene_id integer,"
        "project text default '',"
        "task text default '',"
        "outcome text default 'unknown',"
        "note text default '',"
        "actor text default '',"
        "used_at datetime default (datetime('now')),"
        "created_at datetime default (datetime('now')))"
    ),
    "dna_openkb_source": (
        "create table if not exists dna_openkb_source ("
        "id integer primary key autoincrement,"
        "repo text not null,"
        "url text default '',"
        "license text default '',"
        "copyleft integer default 0,"
        "star_count integer default 0,"
        "default_branch text default '',"
        # commit 是 SQLite 的关键字（COMMIT），建表时必须加引号，
        # 否则整条 create table 直接语法报错 —— 表建不出来，
        # 后面吸收开源项目时一存就炸。
        "\"commit\" text default '',"
        "local_path text default '',"
        "status text default 'pending',"
        "genes integer default 0,"
        "assets integer default 0,"
        "files integer default 0,"
        "error text default '',"
        "notice text default '',"
        "meta text default '{}',"
        "principal text default '',"
        "created_at datetime default (datetime('now')),"
        "updated_at datetime default (datetime('now')))"
    ),
}

INDEXES = (
    "create index if not exists ix_gene_score_conf on dna_gene_score(confidence)",
    "create index if not exists ix_gene_score_expr on dna_gene_score(expressiveness)",
    "create index if not exists ix_asset_kind_gene on dna_asset(kind, gene_id)",
    "create index if not exists ix_asset_use_asset on dna_asset_use(asset_id)",
    "create index if not exists ix_asset_use_gene on dna_asset_use(gene_id)",
    "create index if not exists ix_openkb_repo on dna_openkb_source(repo)",
)


async def _table_exists(cur, name: str) -> bool:
    await cur.execute(
        "select name from sqlite_master where type='table' and name=? limit 1",
        (name,))
    row = await cur.fetchone()
    return row is not None


async def _columns(cur, table: str) -> set[str]:
    await cur.execute(f"pragma table_info({table})")
    return {r[1] for r in await cur.fetchall()}


async def migrate_dna_learning_v8() -> dict:
    """补齐评分/产出/开源来源这套结构（幂等）

    返回 {"columns": n, "tables": n, "skipped": bool}。
    skipped=True 表示已经迁移过（第二次调用直接返回，什么都不做）。
    """
    db_path = settings.database_url.split("///", 1)[-1]
    conn = await aiosqlite.connect(db_path)
    try:
        cur = await conn.cursor()
        # sys_meta 还没有（全新库）就当没迁过：
        # 迁移得能在「刚建好表」与「跑了半年」两种库上都跑得动。
        row = None
        if await _table_exists(cur, "sys_meta"):
            await cur.execute("select value from sys_meta where key = ?",
                              (META_KEY,))
            row = await cur.fetchone()
        if row:
            # 已经迁过了：仍然把表结构核对一遍。
            # 迁移标记存在但表被手工删掉的情况是真实发生过的，
            # 只认标记不认表，缺口就永远补不上。
            created = await _ensure_tables(cur)
            await conn.commit()
            return {"columns": 0, "tables": created, "skipped": True}

        added = 0
        if await _table_exists(cur, "dna_gene"):
            cols = await _columns(cur, "dna_gene")
            for name, spec in GENE_COLUMNS.items():
                if name in cols:
                    continue
                await cur.execute(f"alter table dna_gene add column {name} {spec}")
                added += 1
                log.info("v8: dna_gene 补列 %s", name)

        created = await _ensure_tables(cur)

        if await _table_exists(cur, "sys_meta"):
            await cur.execute("insert into sys_meta (key, value) values (?, ?)",
                              (META_KEY, f"columns:{added},tables:{created}"))
        # sys_meta 都没有（全新库）就不写标记：
        # 标记只是「省一次检查」，没有它顶多多跑一次，结构照样对。
        await conn.commit()
        log.info("v8: 知识学习与产出结构迁移完成，补列 %s 张表 %s",
                 added, created)
        return {"columns": added, "tables": created, "skipped": False}
    finally:
        await conn.close()


async def _ensure_tables(cur) -> int:
    created = 0
    for name, ddl in TABLES.items():
        await cur.execute(ddl)
        created += 1
    for ddl in INDEXES:
        await cur.execute(ddl)
    return created


if __name__ == "__main__":  # pragma: no cover - 手工执行入口
    import asyncio

    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(migrate_dna_learning_v8()))
