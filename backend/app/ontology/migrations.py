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
    # Recover provenance for earlier notes with a retained materialization link.
    await db.execute(text("""
        INSERT OR IGNORE INTO ontology_record_source(record_id, document_id)
        SELECT link.target_record_id, provenance.document_id
        FROM relation_record AS link
        JOIN ontology_record_source AS provenance ON provenance.record_id = link.source_record_id
        WHERE link.target_record_id IS NOT NULL AND json_valid(link.data)
              AND json_extract(link.data, '$.via') = 'materialize'
    """))
    # Older publications wrote relationship IDs in order after the ordinary claims.
    # Match the projection and both endpoints as well as the stored row ID.
    upgrade = await db.execute(text(
        "INSERT OR IGNORE INTO ontology_installation(version) VALUES (2)"
    ))
    if upgrade.rowcount:
        await db.execute(text("""
            WITH imported AS (
                SELECT c.id AS claim_id, rr.id AS relation_id, job.document_id,
                    rr.created_at AS edge_created_at,
                    MIN(c.recorded_at) OVER (PARTITION BY rr.id) AS first_import
                FROM ontology_ingestion_job AS job, json_each(job.result, '$.relationships') AS item
                JOIN ontology_claim AS c ON c.id = json_extract(job.result,
                    '$.claims[' || (COALESCE(json_array_length(job.candidates, '$.claims'), 0)
                    + item.key) || ']')
                JOIN ontology_projection AS p ON p.semantic_id = c.predicate_id
                JOIN relation_record AS rr ON rr.id = item.value AND rr.relation_def_id = p.legacy_id
                    AND rr.source_record_id = c.object_id AND rr.target_record_id = c.target_id
                WHERE job.status = 'published'
            )
            INSERT OR IGNORE INTO ontology_relation_support(claim_id, relation_id, document_id, manual_origin)
            SELECT claim_id, relation_id, document_id, edge_created_at < first_import OR EXISTS (
                SELECT 1 FROM audit_log WHERE path = '/api/relations/records'
                AND action = 'create' AND resource_id = CAST(imported.relation_id AS TEXT)
                AND status BETWEEN 200 AND 299 AND created_at >= imported.edge_created_at
            ) FROM imported
        """))
    await db.commit()
