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


def safe_budget(budget):
    # Historical counts/usage may concern candidates outside a new actor's
    # permission set. Replay exposes hard limits, never old observed counts.
    safe = {
        k: v
        for k, v in budget.items()
        if k
        in ("scan_limit", "object_limit", "source_limit", "term_limit", "result_limit")
    }
    for name in ("generation", "ranking"):
        if name in budget:
            limits = {
                k: v
                for k, v in budget[name].items()
                if k
                in (
                    "candidate_limit",
                    "input_char_limit",
                    "rerank_limit",
                    "max_tokens_ceiling",
                    "max_retries",
                )
            }
            # Token usage is intentionally omitted from the public replay.
            if name == "ranking" and limits:
                safe[name] = limits
    return safe


async def revalidate(db, p, ontology_id, refs, request):
    _, _, schema, _ = await policy.space(db, p, ontology_id)
    if refs.get("version") != 2:
        raise HTTPException(409, "旧运行缺少完整授权追溯，请重新查询")
    policy.require_types(p, schema, refs.get("type_ids", []))
    revisions = await sources.selected(db, p, ontology_id, refs.get("revision_ids", []))
    items = []
    by_id = {}
    for rid in refs.get("record_ids", []):
        obj, _ = await retrieval.object_scope(db, p, rid, ontology_id)
        by_id[rid] = obj
        items.append(retrieval.public_object(obj))
    facts = []
    for cid in refs.get("claim_ids", []):
        claim = await db.get(Claim, cid)
        if not claim or claim.ontology_id != ontology_id:
            raise HTTPException(404, "关联知识事实不可用")
        pinned = refs.get("claim_revisions", {}).get(cid)
        if not isinstance(pinned, dict) or set(pinned) != set(claim.evidence_ids):
            raise HTTPException(404, "原查询证据关联已不可用")
        f = await retrieval.fact(
            db, p, claim, revisions, request["as_of"], request=request, pinned=pinned
        )
        if not f:
            raise HTTPException(404, "原查询知识依据已不适用")
        if claim.target_id is not None:
            for rid in (claim.object_id, claim.target_id):
                obj = by_id.get(rid)
                if not obj or (
                    request.get("type_id") and obj["type_id"] != request["type_id"]
                ):
                    raise HTTPException(404, "原查询关系超出模型范围")
                if not retrieval.matches(obj["_semantic"], request, allow_unknown=True):
                    raise HTTPException(404, "原查询关系已超出适用范围")
        facts.append(f)
    return items, facts, revisions


async def read_run(db, p, run_id):
    run_id = schemas.identifier(run_id, "查询运行")
    key = (*sources.cache_key(p), run_id)
    cache = db.info.setdefault("knowledge_run_cache", {})
    if key in cache:
        result = cache[key]
        if isinstance(result, HTTPException):
            raise result
        return result
    try:
        run = await db.get(QueryRun, run_id)
        if not run or (run.actor != actor(p) and not policy.reviewer(p)):
            raise HTTPException(404, "查询运行不存在")
        items, facts, revisions = await revalidate(
            db, p, run.ontology_id, run.references, run.request
        )
        visible_facts, citations, truncated = retrieval.bounded_facts(facts, 50)
        result = dict(
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
            items=items[:50],
            facts=visible_facts,
            citations=list(citations.values()),
            sources=[await sources.public(db, p, r) for r in revisions[:50]],
            prompt_version=run.prompt_version,
            model_version=run.model_version,
            elapsed_ms=run.elapsed_ms,
            budget=safe_budget(run.budget),
            created_at=run.created_at,
            incomplete=truncated or len(items) > 50 or len(revisions) > 50,
        )
        cache[key] = result
        return result
    except HTTPException as error:
        cache[key] = error
        raise


async def target(db, p, payload):
    if "run_id" in payload:
        schemas.identifier(payload["run_id"], "查询运行", optional=True)
    if "record_id" in payload:
        schemas.identifier(
            payload["record_id"], "知识条目", optional=True, integer=True
        )
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
    feedback_id = schemas.identifier(feedback_id, "问题反馈")
    f = await db.get(Feedback, feedback_id)
    if not f or (f.actor != actor(p) and not policy.reviewer(p)):
        raise HTTPException(404, "问题反馈不存在")
    # Old feedback may reference an older object version; permissions still follow
    # the live object and complete original source set, not a cached response.
    if f.run_id:
        await read_run(db, p, f.run_id)
    if f.record_id:
        obj, oid = await retrieval.object_scope(db, p, f.record_id)
        if f.references:
            await revalidate(
                db, p, oid, f.references["dependencies"], f.references["request"]
            )
        elif not f.run_id:
            raise HTTPException(409, "旧反馈缺少来源依赖，请重新提交")
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
    item_references = {}
    if payload.get("record_id"):
        obj, oid = await retrieval.object_scope(db, p, payload["record_id"])
        detail = await retrieval.detail(db, p, payload["record_id"])
        rendered = {f["id"]: f for f in detail["facts"]}
        from datetime import date

        item_references = dict(
            request=dict(as_of=date.today().isoformat()),
            dependencies=retrieval.references(
                {obj["type_id"]}, {obj["id"]}, set(rendered), rendered
            ),
        )
    f = Feedback(
        actor=actor(p),
        run_id=payload.get("run_id"),
        record_id=payload.get("record_id"),
        record_version=payload.get("record_version"),
        references=item_references,
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
            detail=dict(version=f.version, status=f.status),
        )
    )
    await db.commit()
    return result


async def listing(db, p, limit, offset):
    statement = select(Feedback).order_by(Feedback.created_at.desc(), Feedback.id)
    if not policy.reviewer(p):
        statement = statement.where(Feedback.actor == actor(p))
    stream = await db.stream_scalars(statement.limit(2001))
    allowed = []
    scanned = 0
    exhausted = False
    try:
        async for row in stream:
            scanned += 1
            if scanned > 2000:
                exhausted = True
                break
            try:
                await read(db, p, row.id)
            except HTTPException as error:
                if error.status_code in (403, 404, 409):
                    continue
                raise
            allowed.append(schemas.row(row))
            if len(allowed) >= offset + limit:
                break
    finally:
        await stream.close()
    # A full page offers the next offset without a hidden-row total/lookahead.
    items = allowed[offset : offset + limit]
    return dict(
        items=items,
        incomplete=exhausted,
        next_offset=offset + limit if len(items) == limit else None,
    )
