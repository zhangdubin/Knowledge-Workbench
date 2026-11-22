"""Durable owner/reviewer feedback with transaction-scoped idempotency."""

from datetime import datetime
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from ..models import AuditLog
from ..ontology.changes import actor
from ..ontology.migrations import lock_writer
from ..ontology.registry import digest
from ..ontology.models import Claim
from .models import Feedback, FeedbackResolution, QueryRun, SourceRevision
from . import policy, schemas, retrieval, sources

CATEGORIES = {
    "引用不正确",
    "版本不适用",
    "回答不完整",
    "存在分歧",
    "希望补充资料",
    "incorrect_citation",
    "wrong_version",
    "incomplete_answer",
    "disagreement",
    "missing_material",
}


async def read_run(db, p, run_id):
    run = await db.get(QueryRun, run_id)
    if not run or (run.actor != actor(p) and not policy.reviewer(p)):
        raise HTTPException(404, "查询运行不存在")
    await policy.space(db, p, run.ontology_id)
    revisions = await sources.visible(db, p, run.ontology_id)
    # Revalidate the entire original selection; never return cached bodies.
    refs = run.references
    for rid in refs.get("revision_ids", []):
        rev = await db.get(SourceRevision, rid)
        if not rev:
            raise HTTPException(404, "关联资料修订不可用")
        await sources.readable(db, p, rev)
    items = []
    for rid in refs.get("record_ids", []):
        obj, _ = await retrieval.object_scope(db, p, rid, run.ontology_id)
        items.append(obj)
    facts = []
    for cid in refs.get("claim_ids", []):
        claim = await db.get(Claim, cid)
        if not claim or claim.ontology_id != run.ontology_id:
            raise HTTPException(404, "关联知识事实不可用")
        f = await retrieval.fact(db, p, claim, revisions, run.request["as_of"])
        if not f:
            raise HTTPException(404, "关联知识依据已不适用")
        facts.append(f)
    citations = {e["id"]: e for f in facts for e in f["evidence"]}
    return dict(
        run_id=run.id,
        id=run.id,
        version=1,
        actor=run.actor,
        ontology_id=run.ontology_id,
        revision_id=run.revision_id,
        request=run.request,
        status=run.status,
        generation=run.generation,
        answer=None,
        items=items,
        facts=facts,
        citations=list(citations.values()),
        sources=[
            schemas.row(r) for r in revisions if r.id in refs.get("revision_ids", [])
        ],
        prompt_version=run.prompt_version,
        model_version=run.model_version,
        elapsed_ms=run.elapsed_ms,
        budget=run.budget,
        created_at=run.created_at,
    )


async def target(db, p, payload):
    if not payload.get("run_id") and not payload.get("record_id"):
        raise HTTPException(422, "请关联查询运行或具体知识条目版本")
    run = None
    if payload.get("run_id"):
        run = await read_run(db, p, payload["run_id"])
    if payload.get("record_id") is not None:
        if (
            type(payload["record_id"]) is not int
            or type(payload.get("record_version")) is not int
        ):
            raise HTTPException(422, "请提供有效知识条目与读取时的版本")
        obj, oid = await retrieval.object_scope(db, p, payload["record_id"])
        if run and (
            oid != run["ontology_id"]
            or payload["record_id"] not in [i["id"] for i in run["items"]]
        ):
            raise HTTPException(422, "条目不属于本次查询结果")
        if obj["version"] != payload["record_version"]:
            raise HTTPException(409, "知识条目版本已变化，请重新读取")


async def read(db, p, feedback_id):
    f = await db.get(Feedback, feedback_id)
    if not f or (f.actor != actor(p) and not policy.reviewer(p)):
        raise HTTPException(404, "问题反馈不存在")
    # Old feedback may reference an older object version; permissions still follow
    # the live object and complete original source set, not a cached response.
    if f.run_id:
        await read_run(db, p, f.run_id)
    if f.record_id:
        await retrieval.object_scope(db, p, f.record_id)
    return f


async def create(db, p, payload):
    schemas.keys(
        payload,
        (
            "run_id",
            "record_id",
            "record_version",
            "category",
            "message",
            "idempotency_key",
        ),
    )
    category = schemas.text(payload.get("category"), "问题分类", 80, True)
    if category not in CATEGORIES:
        raise HTTPException(422, "请选择有效的问题分类")
    message = schemas.text(payload.get("message"), "问题说明", 2000, True)
    key = schemas.text(payload.get("idempotency_key"), "请求幂等标识", 120, True)
    await lock_writer(db)
    request_digest = digest(payload)
    old = await db.scalar(
        select(Feedback).where(
            Feedback.actor == actor(p), Feedback.idempotency_key == key
        )
    )
    if old:
        if old.request_digest != request_digest:
            raise HTTPException(409, "同一幂等标识不能提交不同的问题")
        await read(db, p, old.id)
        return schemas.row(old)
    await target(db, p, payload)
    f = Feedback(
        actor=actor(p),
        run_id=payload.get("run_id"),
        record_id=payload.get("record_id"),
        record_version=payload.get("record_version"),
        category=category,
        message=message,
        idempotency_key=key,
        request_digest=request_digest,
    )
    db.add(f)
    await db.commit()
    return schemas.row(f)


async def resolve(db, p, feedback_id, payload):
    if not policy.reviewer(p):
        raise HTTPException(403, "缺少知识反馈处理权限")
    schemas.keys(payload, ("expected_version", "resolution", "idempotency_key"))
    resolution = schemas.text(payload.get("resolution"), "处理说明", 2000, True)
    key = schemas.text(payload.get("idempotency_key"), "请求幂等标识", 120, True)
    if type(payload.get("expected_version")) is not int:
        raise HTTPException(422, "请提交读取时的问题版本")
    await lock_writer(db)
    f = await read(db, p, feedback_id)
    request_digest = digest(payload)
    previous = await db.scalar(
        select(FeedbackResolution).where(
            FeedbackResolution.feedback_id == f.id,
            FeedbackResolution.actor == actor(p),
            FeedbackResolution.idempotency_key == key,
        )
    )
    if previous:
        if previous.request_digest != request_digest:
            raise HTTPException(409, "同一幂等标识不能提交不同的处理说明")
        return previous.result
    if f.version != payload["expected_version"]:
        raise HTTPException(409, "问题反馈版本已变化，请重新读取")
    if f.status != "pending":
        raise HTTPException(409, "问题反馈已处理")
    f.version += 1
    f.status = "resolved"
    f.resolution = resolution
    f.resolved_by = actor(p)
    f.resolved_at = datetime.now()
    result = jsonable_encoder(schemas.row(f))
    db.add(
        FeedbackResolution(
            feedback_id=f.id,
            actor=actor(p),
            idempotency_key=key,
            request_digest=request_digest,
            result=result,
        )
    )
    db.add(
        AuditLog(
            user_id=p.id,
            username=p.username,
            action="knowledge_feedback_resolve",
            resource="knowledge_feedback",
            resource_id=f.id,
            status=200,
            detail=dict(version=f.version, resolution=resolution),
        )
    )
    await db.commit()
    return result


async def listing(db, p, limit, offset):
    statement = select(Feedback).order_by(Feedback.created_at.desc(), Feedback.id)
    if not policy.reviewer(p):
        statement = statement.where(Feedback.actor == actor(p))
    rows = list(await db.scalars(statement.limit(2001)))
    allowed = []
    for f in rows[:2000]:
        try:
            await read(db, p, f.id)
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
        allowed.append(schemas.row(f))
    return dict(items=allowed[offset : offset + limit], incomplete=len(rows) > 2000)
