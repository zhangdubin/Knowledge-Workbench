"""v7 迁移：给内置角色补上「养料 DNA」页面权限

为什么要单独做一次迁移，而不是在 PAGES 里加一项就完事：

    PAGES 只对**新建**的内置角色生效 ——
    bootstrap.ensure_builtin_roles 只在角色缺失时才建，
    不覆盖库里已经存好的 perms JSON（这是故意的，
    否则管理员调过的权限每次重启都被点回滚）。

    于是已经跑起来的库里，管理员 / 编辑 / 只读三个角色的 pages
    列表里都没有 "dna"。而左侧导航是按页面权限过滤的 ——
    「养料 DNA」这一项会对所有人隐形，页面成了摆设，
    而且升级路径根本不会自愈。

    所以这里一次性把 "dna" 补进内置角色的 pages，
    并在 sys_meta 记一笔，保证只做一次：
    管理员后来手动改过的权限不会被反复覆盖回去。
"""
from __future__ import annotations

import json
import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")

META_KEY = "migrated_dna_perm_v7"
PAGE_KEY = "dna"


async def migrate_dna_page_perm_v7() -> None:
    db_path = settings.database_url.split("///", 1)[-1]
    conn = await aiosqlite.connect(db_path)
    try:
        cur = await conn.cursor()
        await cur.execute("select value from sys_meta where key = ?", (META_KEY,))
        row = await cur.fetchone()
        if row:
            return

        await cur.execute("select id, key, perms from role where is_builtin = 1")
        roles = await cur.fetchall()
        touched = 0
        for rid, key, perms_raw in roles:
            perms = {}
            if perms_raw:
                try:
                    perms = json.loads(perms_raw)
                except (TypeError, ValueError):
                    perms = {}
            if not isinstance(perms, dict):
                perms = {}
            pages = perms.get("pages")
            if not isinstance(pages, list):
                pages = []
            if PAGE_KEY in pages:
                continue
            pages.append(PAGE_KEY)
            perms["pages"] = pages
            await cur.execute("update role set perms = ? where id = ?",
                              (json.dumps(perms, ensure_ascii=False), rid))
            touched += 1
            log.info("v7: 内置角色 %s 补上页面权限 %s", key, PAGE_KEY)

        await cur.execute("insert into sys_meta (key, value) values (?, ?)",
                          (META_KEY, f"done:{touched}"))
        await conn.commit()
        log.info("v7: 养料 DNA 页面权限迁移完成，改了 %s 个内置角色", touched)
    finally:
        await conn.close()
