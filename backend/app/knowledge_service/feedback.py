"""Durable owner/reviewer feedback with transaction-scoped idempotency."""

from datetime import datetime
from hashlib import sha256
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from ..models import AuditLog
from ..ontology.changes import actor
from ..ontology.migrations import lock_writer
from ..ontology.registry import digest
from ..ontology.models import Claim, SourceSnapshot
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


async def revalidate(db, p, ontology_id, refs, request, *, selection=None):
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
    selected_views = {}
    if selection:
        for descriptor in selection.get("items", []):
            if descriptor["id"] not in by_id:
                raise HTTPException(409, "原展示条目不在授权依赖集合中")
            selected_views[descriptor["id"]] = await retrieval.historical_object(
                db, p, ontology_id, descriptor, current=by_id[descriptor["id"]]
            )
        items = [
            retrieval.public_object(selected_views.get(rid, obj))
            for rid, obj in by_id.items()
        ]
    facts = []
    for cid in refs.get("claim_ids", []):
        claim = await db.get(Claim, cid)
        if not claim or claim.ontology_id != ontology_id:
            raise HTTPException(404, "关联知识事实不可用")
        pinned = refs.get("claim_revisions", {}).get(cid)
        if not isinstance(pinned, dict) or set(pinned) != set(claim.evidence_ids):
            raise HTTPException(404, "原查询证据关联已不可用")
        f = await retrieval.fact(
            db,
            p,
            claim,
            revisions,
            request["as_of"],
            request=request,
            pinned=pinned,
            object_views=selected_views,
        )
        if not f:
            raise HTTPException(404, "原查询知识依据已不适用")
        if claim.target_id is not None:
            for rid in (claim.object_id, claim.target_id):
                obj = selected_views.get(rid, by_id.get(rid))
                if not obj or (
                    request.get("type_id") and obj["type_id"] != request["type_id"]
                ):
                    raise HTTPException(404, "原查询关系超出模型范围")
                if not retrieval.matches(obj["_semantic"], request, allow_unknown=True):
                    raise HTTPException(404, "原查询关系已超出适用范围")
        facts.append(f)
    return items, facts, revisions


async def public_run_selection(db, p, run, selection, items, facts, revisions):
    if not isinstance(selection, dict) or selection.get("version") != 1:
        raise HTTPException(409, "旧运行缺少原展示选择，请重新查询")
    item_map = {obj["id"]: obj for obj in items}
    fact_map = {fact["id"]: fact for fact in facts}
    revision_map = {row.id: row for row in revisions}
    selected_items = []
    for descriptor in selection["items"]:
        obj = item_map.get(descriptor["id"])
        if (
            not obj
            or obj["version"] != descriptor["version"]
            or obj["revision_id"] != descriptor["revision_id"]
        ):
            raise HTTPException(409, "原查询条目版本不可用")
        selected_items.append(obj)
    selected_facts = []
    for descriptor in selection["facts"]:
        fact = fact_map.get(descriptor["id"])
        if not fact or fact["version"] != descriptor["version"]:
            raise HTTPException(409, "原查询事实版本已变化，请重新查询")
        selected_facts.append(fact)
    citation_map = {
        (e["id"], e["revision_id"]): e for fact in facts for e in fact["evidence"]
    }
    citations = []
    for descriptor in selection["citations"]:
        evidence = citation_map.get((descriptor["id"], descriptor["revision_id"]))
        if (
            not evidence
            or (evidence["start"], evidence["end"])
            != (descriptor["start"], descriptor["end"])
            or sha256(evidence["quote"].encode()).hexdigest() != descriptor["quote_sha"]
        ):
            raise HTTPException(404, "原查询引文位置不可用")
        citations.append(evidence)
    source_results = []
    for descriptor in selection["sources"]:
        revision = revision_map.get(descriptor["id"])
        if (
            not revision
            or revision.snapshot_id != descriptor["snapshot_id"]
            or not sources.active(revision, run.request["as_of"], revisions)
        ):
            raise HTTPException(404, "原查询摘录修订已不适用")
        snapshot = await db.get(SourceSnapshot, descriptor["snapshot_id"])
        if (
            not snapshot
            or sha256(snapshot.text.encode()).hexdigest() != snapshot.text_sha
        ):
            raise HTTPException(404, "原查询摘录快照不可用")
        start, end = descriptor["start"], descriptor["end"]
        if not 0 <= start < end <= len(snapshot.text):
            raise HTTPException(404, "原查询摘录区间不可用")
        quote = snapshot.text[start:end]
        if sha256(quote.encode()).hexdigest() != descriptor["quote_sha"]:
            raise HTTPException(404, "原查询摘录内容已变化")
        source_results.append(
            dict(
                **(await sources.public(db, p, revision)),
                quote=quote,
                start=start,
                end=end,
                verified=False,
                kind="source_excerpt",
            )
        )
    relations = []
    for edge in selection["relations"]:
        fact = fact_map.get(edge["claim_id"])
        if not fact or (fact["object_id"], fact["target_id"]) != (
            edge["source"],
            edge["target"],
        ):
            raise HTTPException(404, "原查询关联已不可用")
        relations.append(dict(edge))
    terms = []
    for descriptor in selection["terms"]:
        original = await retrieval.historical_object(db, p, run.ontology_id, descriptor)
        data = original["_semantic"]
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            import re

            aliases = [
                word.strip()
                for word in re.split(r"[,，;；、\n|]", aliases)
                if word.strip()
            ]
        terms.append(
            dict(
                id=original["id"],
                preferred=data.get("preferred") or "",
                aliases=aliases[:50] if isinstance(aliases, list) else [],
                definition=data.get("definition") or "",
                scope=data.get("scope") or "",
            )
        )
    selected_ids = {fact["id"] for fact in selected_facts}
    extra_ids = list(
        dict.fromkeys(
            cid
            for pair in selection["conflicts"]
            for cid in pair
            if cid not in selected_ids
        )
    )
    context = [fact_map[cid] for cid in extra_ids]
    conflict_facts, conflict_citations, conflict_truncated = retrieval.bounded_facts(
        context, 50
    )
    return dict(
        items=selected_items,
        facts=selected_facts,
        citations=citations,
        sources=source_results,
        relations=relations,
        terms=terms,
        conflicts=selection["conflicts"],
        conflict_facts=[
            dict(fact, purpose="conflict_evidence") for fact in conflict_facts
        ],
        conflict_citations=[
            dict(evidence, purpose="conflict_evidence")
            for evidence in conflict_citations.values()
        ],
        incomplete=selection["incomplete"],
        conflict_incomplete=conflict_truncated,
    )


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
        selection = run.references.get("public_selection")
        items, facts, revisions = await revalidate(
            db, p, run.ontology_id, run.references, run.request, selection=selection
        )
        public = await public_run_selection(
            db, p, run, selection, items, facts, revisions
        )
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
            **public,
            as_of=run.request["as_of"],
            scope=run.request.get("scope"),
            prompt_version=run.prompt_version,
            model_version=run.model_version,
            elapsed_ms=run.elapsed_ms,
            budget=safe_budget(run.budget),
            created_at=run.created_at,
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
        expected_version = obj["version"]
        if run:
            stored = await db.get(QueryRun, payload["run_id"])
            selections = {
                item["id"]: item
                for item in stored.references["public_selection"]["items"]
            }
            if oid != run["ontology_id"] or payload["record_id"] not in selections:
                raise HTTPException(422, "条目不属于本次查询入选结果")
            expected_version = selections[payload["record_id"]]["version"]
        if expected_version != payload["record_version"]:
            raise HTTPException(409, "知识条目版本与原选择不符，请重新读取")


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
    if payload.get("record_id") and not payload.get("run_id"):
        obj, oid = await retrieval.object_scope(db, p, payload["record_id"])
        authorities = {}
        detail = await retrieval.detail(db, p, payload["record_id"], authorities=authorities)
        rendered = {f["id"]: f for f in detail["facts"]}
        from datetime import date

        item_references = dict(
            request=dict(as_of=date.today().isoformat()),
            dependencies=retrieval.references(
                {obj["type_id"]}, {obj["id"]}, set(rendered), rendered, authorities=authorities
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
