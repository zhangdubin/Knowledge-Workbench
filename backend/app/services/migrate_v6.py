"""v6 迁移：dashboard 表补 settings 列（大屏显示设置）

全屏大屏需要按驾驶舱保存主题 / 自动刷新等显示偏好。加可空 JSON 列，
幂等（列不存在才加），必须在 create_all 之后、任何 ORM 查询之前执行。
"""
from __future__ import annotations

import logging

import aiosqlite

from ..config import settings

log = logging.getLogger("kb.migrate")


async def _has_column(cur, table: str, column: str) -> bool:
    await cur.execute(f"pragma table_info({table})")
    return any(row[1] == column for row in await cur.fetchall())


async def migrate_dashboard_settings_v6() -> None:
    db_path = settings.database_url.split("///", 1)[-1]
    conn = await aiosqlite.connect(db_path)
    try:
        cur = await conn.cursor()
        if not await _has_column(cur, "dashboard", "settings"):
            await cur.execute("ALTER TABLE dashboard ADD COLUMN settings JSON")
            await conn.commit()
            log.info("v6: dashboard 补列 settings")
    finally:
        await conn.close()
