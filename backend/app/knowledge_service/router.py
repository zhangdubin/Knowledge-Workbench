from time import perf_counter
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from ..database import get_db
from ..models import Document
from ..ontology.changes import actor
from ..ontology.models import Ontology
from ..ontology import evidence
from ..services.auth import Principal, current_principal
from . import policy, schemas, template, sources, retrieval, answers, feedback
from .models import KnowledgeSpace, QueryRun

DB = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


def require_entry(p: User):
    policy.entry(p)


router = APIRouter(
    prefix="/api/knowledge-service",
    tags=["knowledge_service"],
    dependencies=[Depends(require_entry)],
)


@router.get("/catalog")
async def catalog(db: DB, p: User):
    spaces = []
    can_manage_sources = False
    truncated = False
    registrations = list(
        await db.scalars(
            select(KnowledgeSpace).order_by(KnowledgeSpace.ontology_id).limit(201)
        )
    )
    for registration in registrations[:200]:
        try:
            ont, _, schema, visible = await policy.space(
                db, p, registration.ontology_id
            )
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
        revisions = await sources.visible(db, p, ont.id)
        truncated = (
            truncated
            or revisions.incomplete
            or len({r.scope for r in revisions if r.scope}) > 50
            or len({r.topic for r in revisions if r.topic}) > 50
        )
        write = p.has_feature("file_write") and all(
            p.can_model(t["key"], "write") for t in schema["types"]
        )
        can_manage_sources = can_manage_sources or write
        spaces.append(
            dict(
                id=ont.id,
                name=ont.name,
                types=[dict(id=t["id"], key=t["key"], name=t["name"]) for t in visible],
                scopes=sorted({r.scope for r in revisions if r.scope})[:50],
                topics=sorted({r.topic for r in revisions if r.topic})[:50],
                incomplete=revisions.incomplete
                or len({r.scope for r in revisions if r.scope}) > 50
                or len({r.topic for r in revisions if r.topic}) > 50,
                can_manage_sources=write,
            )
        )
    candidates = []
    candidates_incomplete = False
    if can_manage_sources:
        documents = list(
            await db.scalars(
                select(Document)
                .options(defer(Document.data), defer(Document.extracted_text))
                .where(Document.deleted_at.is_(None))
                .order_by(Document.id.desc())
                .limit(501)
            )
        )
        candidates_incomplete = len(documents) > 500
        for doc in documents[:500]:
            try:
                await evidence.source(db, p, doc.id)
            except HTTPException as e:
                if e.status_code in (403, 404):
                    continue
                raise
            candidates.append(
                dict(
                    id=doc.id,
                    title=doc.title or doc.filename,
                    filename=doc.filename,
                    sha256=doc.sha256,
                )
            )
    return dict(
        spaces=spaces[:50],
        can_manage=policy.manager(p),
        can_review=policy.reviewer(p),
        can_manage_sources=can_manage_sources,
        source_candidates=candidates[:50],
        source_candidates_incomplete=candidates_incomplete or len(candidates) > 50,
        incomplete=truncated
        or len(registrations) > 200
        or len(spaces) > 50
        or candidates_incomplete
        or len(candidates) > 50,
    )


@router.get("/template")
async def get_template(p: User):
    return template.definition()


@router.post("/template")
async def preview_template(payload: dict, db: DB, p: User):
    return await template.preview(db, p, payload)


@router.post("/template/{change_id}/confirm")
async def confirm_template(change_id: str, db: DB, p: User):
    return await template.confirm(db, p, change_id)


@router.post("/sources")
async def create_source(payload: dict, db: DB, p: User):
    return await sources.create(db, p, payload)


@router.get("/sources")
async def list_sources(
    ontology_id: str,
    db: DB,
    p: User,
    limit: int = Query(50, ge=1, le=50),
    offset: int = Query(0, ge=0, le=2000),
):
    return await sources.page(db, p, ontology_id, limit, offset)


@router.get("/sources/{revision_id}")
async def read_source(revision_id: str, db: DB, p: User):
    return await sources.detail(db, p, revision_id)


@router.get("/terms")
async def get_terms(
    ontology_id: str,
    db: DB,
    p: User,
    q: str = Query("", max_length=500),
    scope: str | None = None,
):
    return await retrieval.terms(db, p, ontology_id, q, scope)


@router.post("/query")
async def query(payload: dict, db: DB, p: User):
    request = schemas.query(payload)
    start = perf_counter()
    result = await retrieval.search(db, p, request)
    await answers.generate(p, request, result)
    references = result.pop(
        "_references",
        dict(
            record_ids=[i["id"] for i in result["items"]],
            claim_ids=[f["id"] for f in result["facts"]],
            evidence_ids=[c["id"] for c in result["citations"]],
            revision_ids=sorted(
                {s["id"] for s in result["sources"]}
                | {c["revision_id"] for c in result["citations"]}
            ),
        ),
    )
    run = QueryRun(
        actor=actor(p),
        ontology_id=request["ontology_id"],
        revision_id=result["revision_id"],
        request=request,
        references=references,
        status=result["status"],
        generation=result["generation"],
        prompt_version=answers.PROMPT_VERSION,
        model_version=result.get("model_version"),
        elapsed_ms=int((perf_counter() - start) * 1000),
        budget=result["budget"],
    )
    db.add(run)
    await db.commit()
    result.update(
        run_id=run.id,
        version=1,
        elapsed_ms=run.elapsed_ms,
        prompt_version=run.prompt_version,
    )
    return result


@router.get("/items/{record_id}")
async def get_item(record_id: int, db: DB, p: User):
    return await retrieval.detail(db, p, record_id)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: DB, p: User):
    return await feedback.read_run(db, p, run_id)


@router.post("/feedback")
async def submit_feedback(payload: dict, db: DB, p: User):
    return await feedback.create(db, p, payload)


@router.get("/feedback")
async def list_feedback(
    db: DB, p: User, limit: int = Query(50, ge=1, le=50), offset: int = Query(0, ge=0)
):
    return await feedback.listing(db, p, limit, offset)


@router.get("/feedback/{feedback_id}")
async def get_feedback(feedback_id: str, db: DB, p: User):
    return schemas.row(await feedback.read(db, p, feedback_id))


@router.post("/feedback/{feedback_id}/resolve")
async def resolve_feedback(feedback_id: str, payload: dict, db: DB, p: User):
    return await feedback.resolve(db, p, feedback_id, payload)
