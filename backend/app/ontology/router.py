from typing import Annotated
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityRecord, EntityType, FieldDefinition
from ..services.auth import Principal, current_principal
from ..services.record import create_record, update_record
from . import changes, objects, registry
from .migrations import lock_writer
from .models import (
    ObjectBinding,
    ObjectHistory,
    Ontology,
    OntologyRevision,
    Projection,
    uid,
)
from .policy import protect_projection, require_schema
from .schemas import EMPTY

router = APIRouter(prefix="/api/ontologies", tags=["ontology"])
DB = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


async def space_row(db, space_id):
    space = await db.get(Ontology, space_id)
    if not space:
        raise HTTPException(404, "本体不存在")
    return space


def revision_json(r):
    return dict(
        id=r.id, status=r.status, schema=r.schema, base_revision_id=r.base_revision_id
    )


async def describe(db, p, space, limit=25, offset=0, summary=False):
    current = await registry.current(db, space)
    require_schema(p, await registry.baseline(db, space))
    revisions = []
    visible = 0
    for rev in await db.scalars(
        select(OntologyRevision)
        .where(OntologyRevision.ontology_id == space.id)
        .order_by(OntologyRevision.created_at.desc(), OntologyRevision.id.desc())
    ):
        if all(p.can_model(t["key"]) for t in rev.schema["types"]):
            if summary:
                return dict(
                    id=space.id,
                    key=space.key,
                    name=space.name,
                    description=space.description,
                    current_revision_id=space.current_revision_id,
                )
            if visible >= offset:
                revisions.append(revision_json(rev))
            visible += 1
            if len(revisions) >= limit:
                break
    if not visible:
        raise HTTPException(403, "缺少模型权限")
    return dict(
        id=space.id,
        key=space.key,
        name=space.name,
        description=space.description,
        current_revision_id=space.current_revision_id,
        schema=current,
        revisions=revisions,
    )


@router.get("/")
async def list_spaces(
    db: DB, p: User, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
):
    visible = 0
    out = []
    for space in await db.scalars(select(Ontology).order_by(Ontology.key)):
        try:
            item = await describe(db, p, space, summary=True)
            if visible >= offset:
                out.append(item)
            visible += 1
            if len(out) >= limit:
                break
        except HTTPException as error:
            if error.status_code != 403:
                raise
    return out


async def create(db, p, payload, adoption=None):
    key = payload.get("key")
    if not isinstance(key, str) or not key or not isinstance(payload.get("name"), str):
        raise HTTPException(422, "请填写本体标识和名称")
    await lock_writer(db)
    require_schema(p, EMPTY, write=True)
    if await db.scalar(select(Ontology.id).where(Ontology.key == key)):
        raise HTTPException(409, "本体标识已占用")
    space = Ontology(
        key=key,
        name=payload["name"],
        description=payload.get("description", ""),
        adoption=adoption or {},
        adoption_schema=payload["schema"] if adoption else {},
    )
    db.add(space)
    await db.flush()
    await registry.save_draft(db, p, space, payload.get("schema", EMPTY))
    await db.commit()
    return await describe(db, p, space)


@router.post("/")
async def new_space(payload: dict, db: DB, p: User):
    return await create(db, p, payload)


@router.post("/from-model/{type_id}")
async def adopt(type_id: int, db: DB, p: User):
    await lock_writer(db)
    require_schema(p, EMPTY, write=True)
    model = await db.get(EntityType, type_id)
    if not model or model.deleted_at:
        raise HTTPException(404, "模型不存在")
    require_schema(p, {"types": [{"key": model.key}], "relations": []}, write=True)
    if model.key == "note":
        raise HTTPException(409, "note 使用专用笔记接口，暂不支持接管")
    await protect_projection(db, "type", type_id)
    tid = uid()
    mapping = {tid: type_id}
    fields = []
    for f in await db.scalars(
        select(FieldDefinition)
        .where(FieldDefinition.entity_type_id == type_id)
        .order_by(FieldDefinition.order, FieldDefinition.id)
    ):
        fid = uid()
        mapping[fid] = f.id
        fields.append(
            dict(
                id=fid,
                **{
                    k: getattr(f, k)
                    for k in ("key", "name", "type", "required", "options")
                },
            )
        )
    typ = dict(id=tid, key=model.key, name=model.name, fields=fields)
    return await create(
        db,
        p,
        dict(key=model.key, name=model.name, schema=dict(types=[typ], relations=[])),
        mapping,
    )


@router.get("/changes/{change_id}")
async def preview(change_id: str, db: DB, p: User):
    return await changes.preview(db, p, change_id)


@router.post("/changes/{change_id}/confirm")
async def confirm(change_id: str, db: DB, p: User):
    return await changes.confirm_change(db, p, change_id)


@router.get("/objects/{record_id}")
async def detail(record_id: int, db: DB, p: User):
    return await objects.detail(db, p, record_id)


@router.get("/objects/{record_id}/history")
async def history(
    record_id: int,
    db: DB,
    p: User,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    await objects.detail(db, p, record_id)
    rows = await db.scalars(
        select(ObjectHistory)
        .where(ObjectHistory.record_id == record_id)
        .order_by(ObjectHistory.version)
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.put("/objects/{record_id}")
async def edit_object(record_id: int, payload: dict, db: DB, p: User):
    await lock_writer(db)
    await objects.detail(db, p, record_id, write=True)
    try:
        if not isinstance(payload.get("data"), dict):
            raise ValueError("记录数据必须是对象")
        await update_record(
            db,
            record_id,
            payload["data"],
            expected_version=payload.get("expected_version"),
        )
    except (KeyError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return await detail(record_id, db, p)


@router.get("/{space_id}/objects")
async def list_objects(
    space_id: str,
    db: DB,
    p: User,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    space = await space_row(db, space_id)
    keys = [
        t["id"]
        for t in (await registry.current(db, space))["types"]
        if p.can_model(t["key"])
    ]
    ids = await db.scalars(
        select(ObjectBinding.record_id)
        .join(EntityRecord)
        .where(ObjectBinding.type_id.in_(keys), EntityRecord.deleted_at.is_(None))
        .order_by(ObjectBinding.record_id)
        .offset(offset)
        .limit(limit)
    )
    return [await objects.detail(db, p, i) for i in ids]


@router.post("/{space_id}/objects")
async def add_object(space_id: str, payload: dict, db: DB, p: User):
    await lock_writer(db)
    space = await space_row(db, space_id)
    typ = next(
        (
            t
            for t in (await registry.current(db, space))["types"]
            if t["id"] == payload.get("type_id")
        ),
        None,
    )
    if not typ:
        raise HTTPException(404, "本体类型不存在")
    if not p.can_model(typ["key"], "write"):
        raise HTTPException(403, "缺少模型权限")
    projection = await db.get(Projection, typ["id"])
    try:
        if not isinstance(payload.get("data"), dict):
            raise ValueError("记录数据必须是对象")
        record = await create_record(db, projection.legacy_id, payload["data"])
    except (KeyError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return await objects.detail(db, p, record.id)


@router.get("/capabilities")
async def available_capabilities(db: DB, p: User):
    from .models import CapabilityDefinition

    if not p.has_page("types"):
        return []
    return list(
        await db.scalars(
            select(CapabilityDefinition.definition).order_by(CapabilityDefinition.name)
        )
    )


@router.get("/{space_id}")
async def space_detail(
    space_id: str,
    db: DB,
    p: User,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await describe(db, p, await space_row(db, space_id), limit, offset)


@router.post("/{space_id}/revisions")
async def new_revision(space_id: str, payload: dict, db: DB, p: User):
    await lock_writer(db)
    row = await registry.save_draft(
        db, p, await space_row(db, space_id), payload.get("schema")
    )
    await db.commit()
    return revision_json(row)


@router.put("/{space_id}/revisions/{revision_id}")
async def update_revision(
    space_id: str, revision_id: str, payload: dict, db: DB, p: User
):
    await lock_writer(db)
    space = await space_row(db, space_id)
    rev = await registry.revision(db, space, revision_id)
    require_schema(p, rev.schema, write=True)
    row = await registry.save_draft(db, p, space, payload.get("schema"), rev)
    await db.commit()
    return revision_json(row)


@router.post("/{space_id}/revisions/{revision_id}/validate")
async def validate(
    space_id: str, revision_id: str, db: DB, p: User, payload: dict = Body(default={})
):
    await lock_writer(db)
    space = await space_row(db, space_id)
    rev = await registry.revision(db, space, revision_id)
    require_schema(p, await registry.baseline(db, space), write=True)
    require_schema(p, rev.schema, write=True)
    impact, _ = await registry.assess(db, space, rev, payload.get("migration", {}))
    rev.status = "draft" if impact["blockers"] else "validated"
    await db.commit()
    return impact


@router.post("/{space_id}/revisions/{revision_id}/plan")
async def plan(
    space_id: str, revision_id: str, db: DB, p: User, payload: dict = Body(default={})
):
    await lock_writer(db)
    space = await space_row(db, space_id)
    return await changes.plan(
        db,
        p,
        space,
        await registry.revision(db, space, revision_id),
        payload.get("migration", {}),
    )


@router.post("/{space_id}/claims")
async def create_claim(space_id: str, payload: dict, db: DB, p: User):
    from . import knowledge

    await lock_writer(db)
    row = await knowledge.candidate(db, p, await space_row(db, space_id), payload)
    result = await knowledge.render(db, p, row)
    await db.commit()
    return result


@router.get("/{space_id}/claims")
async def claims_list(
    space_id: str,
    db: DB,
    p: User,
    status: str | None = None,
    object_id: int | None = None,
    limit: int = Query(50, ge=1, le=50),
):
    from .query import search

    params = dict(status=status, object_id=object_id, limit=limit)
    return (await search(db, p, await space_row(db, space_id), params, listing=True))[
        "facts"
    ]


@router.post("/claims/{claim_id}/review")
async def review_claim(claim_id: str, payload: dict, db: DB, p: User):
    from . import knowledge

    await lock_writer(db)
    result = await knowledge.review(db, p, claim_id, payload)
    await db.commit()
    return result


@router.get("/claims/{claim_id}/history")
async def claim_history(claim_id: str, db: DB, p: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    from ..models import AuditLog
    from .knowledge import render
    from .models import Claim

    row = await db.get(Claim, claim_id)
    if not row:
        raise HTTPException(404, "声明不存在")
    await render(db, p, row)
    reviews = await db.scalars(
        select(AuditLog).where(
            AuditLog.action == "ontology_review", AuditLog.resource == "claim",
            AuditLog.resource_id == claim_id,
        ).order_by(AuditLog.id.desc()).offset(offset).limit(limit)
    )
    return [dict(version=r.detail["version"], status=r.detail["status"],
                 actor=r.username, recorded_at=r.created_at) for r in reviews]


@router.get("/evidence/{evidence_id}")
async def evidence_detail(evidence_id: str, db: DB, p: User):
    from .evidence import read_evidence
    from .knowledge import render
    from .models import Claim, Evidence

    row = await db.get(Evidence, evidence_id)
    claim = await db.get(Claim, row.claim_id) if row and row.claim_id else None
    if not claim:
        raise HTTPException(404, "证据不可用")
    await render(db, p, claim)
    return await read_evidence(db, p, evidence_id)


@router.post("/{space_id}/query")
async def query_space(space_id: str, payload: dict, db: DB, p: User):
    from .query import search

    return await search(db, p, await space_row(db, space_id), payload)


@router.post("/{space_id}/ingestions")
async def start_ingestion(space_id: str, payload: dict, db: DB, p: User):
    from . import ingestion

    return ingestion.serialize(
        await ingestion.run(db, p, await space_row(db, space_id), payload)
    )


@router.get("/ingestions/{job_id}")
async def get_ingestion(job_id: str, db: DB, p: User):
    from . import ingestion
    from .models import IngestionJob

    job = await db.get(IngestionJob, job_id)
    await ingestion.authorized(db, p, job)
    return ingestion.serialize(job)


@router.get("/{space_id}/ingestions")
async def list_ingestions(
    space_id: str, db: DB, p: User, limit: int = Query(50, ge=1, le=50)
):
    from . import ingestion
    from .models import IngestionJob

    out = []
    for job in await db.scalars(
        select(IngestionJob)
        .where(IngestionJob.ontology_id == space_id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id)
        .limit(1000)
    ):
        try:
            await ingestion.authorized(db, p, job)
        except HTTPException as error:
            if error.status_code in (403, 404):
                continue
            raise
        out.append(ingestion.serialize(job))
        if len(out) >= limit:
            break
    return out


@router.post("/ingestions/{job_id}/plan")
async def plan_ingestion(job_id: str, db: DB, p: User):
    from . import ingestion
    from .models import IngestionJob

    await lock_writer(db)
    return await ingestion.plan(db, p, await db.get(IngestionJob, job_id))
