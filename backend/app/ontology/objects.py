from copy import deepcopy
from fastapi import HTTPException
from ..models import EntityRecord, EntityType
from .models import ObjectBinding, ObjectHistory, Ontology
from .policy import legacy_projection


async def snapshot(db, record, type_id, revision_id):
    binding = await db.get(ObjectBinding, record.id)
    if binding is None:
        binding = ObjectBinding(record_id=record.id, type_id=type_id, version=0)
        db.add(binding)
    binding.version += 1
    binding.revision_id = revision_id
    db.add(
        ObjectHistory(
            record_id=record.id,
            version=binding.version,
            revision_id=revision_id,
            data=deepcopy(record.data),
        )
    )


async def check_version(db, record, expected_version):
    projection = await legacy_projection(db, "type", record.entity_type_id)
    if not projection:
        return
    current = await db.get(ObjectBinding, record.id, populate_existing=True)
    if expected_version is None:
        raise HTTPException(428, "请提交读取时的 expected_version")
    if (
        type(expected_version) is not int
        or not current
        or current.version != expected_version
    ):
        raise HTTPException(
            409,
            {
                "message": "对象版本已变化",
                "current_version": current.version if current else None,
                "data": record.data,
            },
        )


async def track(db, record):
    projection = await legacy_projection(db, "type", record.entity_type_id)
    if not projection:
        return
    space = await db.get(Ontology, projection.ontology_id)
    await snapshot(db, record, projection.semantic_id, space.current_revision_id)


async def detail(db, principal, record_id, *, write=False):
    binding = await db.get(ObjectBinding, record_id)
    rec = await db.get(EntityRecord, record_id)
    if not binding or not rec or rec.deleted_at:
        raise HTTPException(404, "对象不存在")
    from .provenance import ensure_record_source

    await ensure_record_source(db, principal, record_id)
    et = await db.get(EntityType, rec.entity_type_id)
    if not et or et.deleted_at:
        raise HTTPException(404, "模型不存在")
    if not principal.can_model(et.key, "write" if write else "read"):
        raise HTTPException(403, "缺少模型权限")
    return dict(
        id=rec.id,
        record_id=rec.id,
        type_id=binding.type_id,
        revision_id=binding.revision_id,
        version=binding.version,
        data=rec.data,
    )
