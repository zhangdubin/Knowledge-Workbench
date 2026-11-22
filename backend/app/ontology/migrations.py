from sqlalchemy import text


async def lock_writer(db):
    # Even an empty UPDATE starts a SQLite write transaction. Safe to nest.
    await db.execute(text("UPDATE ontology_installation SET version=version WHERE 0"))


async def install(db):
    await db.execute(
        text("INSERT OR IGNORE INTO ontology_installation(version) VALUES (1)")
    )
    from .capabilities import sync_definitions

    await sync_definitions(db)
    await db.commit()
