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
    # Upgrade published jobs created before provenance was recorded for every row.
    await db.execute(
        text("""
        INSERT OR IGNORE INTO ontology_record_source(record_id, document_id)
        SELECT CAST(item.value AS INTEGER), job.document_id
        FROM ontology_ingestion_job AS job, json_each(job.result, '$.objects') AS item
        WHERE job.status = 'published' AND item.type = 'integer'
    """)
    )
    await db.commit()
