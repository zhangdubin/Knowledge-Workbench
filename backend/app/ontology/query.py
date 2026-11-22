import json
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import or_, select

from . import knowledge, objects, registry
from .policy import require_workspace
from .models import Claim, ObjectBinding
from ..models import EntityRecord


async def search(db, principal, space, request, *, listing=False):
    require_workspace(principal)
    limit, depth = request.get("limit", 50), request.get("depth", 0)
    if (
        type(limit) is not int
        or not 1 <= limit <= 50
        or type(depth) is not int
        or not 0 <= depth <= 2
    ):
        raise HTTPException(422, "查询范围超限")
    allowed = {
        "limit",
        "depth",
        "status",
        "as_of",
        "type_id",
        "predicate_id",
        "object_id",
        "text",
        "document_id",
        "properties",
        "value",
    }
    if set(request) - allowed:
        raise HTTPException(422, "不支持的查询条件")
    for key in ("object_id", "document_id"):
        if request.get(key) is not None and type(request[key]) is not int:
            raise HTTPException(422, "无效的记录或文档 ID")
    for key in ("text", "type_id", "predicate_id"):
        if key in request and (
            not isinstance(request[key], str) or len(request[key]) > 500
        ):
            raise HTTPException(422, "查询参数过长或类型错误")
    properties = request.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > 16:
        raise HTTPException(422, "无效属性过滤条件")
    if request.get("status") not in (
        None,
        "accepted",
        "candidate",
        "rejected",
        "disputed",
        "superseded",
    ):
        raise HTTPException(422, "无效的声明状态")
    schema = await registry.current(db, space)
    visible_types = {
        t["id"]: t for t in schema["types"] if principal.can_model(t["key"])
    }
    mappings = {
        tid: {f["id"]: f["key"] for f in t["fields"]}
        for tid, t in visible_types.items()
    }

    def matches_properties(obj):
        fields = mappings.get(obj["type_id"], {})
        return all(
            key in fields
            and fields[key] in obj["data"]
            and json.dumps(obj["data"][fields[key]], sort_keys=True)
            == json.dumps(value, sort_keys=True)
            for key, value in properties.items()
        )

    at = knowledge.day(request.get("as_of"))
    base = select(Claim).where(
        Claim.ontology_id == space.id, Claim.type_id.in_(visible_types)
    )
    for name in ("type_id", "predicate_id"):
        if request.get(name):
            base = base.where(getattr(Claim, name) == request[name])
    status = request.get("status", None if listing else "accepted")
    if status:
        base = base.where(Claim.status == status)
    if at:
        base = base.where(
            or_(Claim.effective_from.is_(None), Claim.effective_from <= at),
            or_(Claim.effective_to.is_(None), Claim.effective_to >= at),
        )
    root = request.get("object_id")
    frontier = {root} if root is not None else None
    facts, paths, records, citations = {}, [], {}, {}
    text = str(request.get("text", "")).casefold()
    visited = 0
    budget_exhausted = False
    if not listing:
        stmt = (
            select(ObjectBinding.record_id)
            .join(EntityRecord)
            .where(
                ObjectBinding.type_id.in_(visible_types),
                EntityRecord.deleted_at.is_(None),
            )
        )
        if root is not None:
            stmt = stmt.where(ObjectBinding.record_id == root)
        if request.get("type_id"):
            stmt = stmt.where(ObjectBinding.type_id == request["type_id"])
        if text:
            stmt = stmt.where(EntityRecord.search_text.contains(text, autoescape=True))
        for rid in await db.scalars(stmt.order_by(ObjectBinding.record_id).limit(1001)):
            visited += 1
            if visited > 1000:
                budget_exhausted = True
                break
            obj = await objects.detail(db, principal, rid)
            if matches_properties(obj):
                records[rid] = obj
                if len(records) >= limit:
                    break
    for level in range(depth + 1):
        stmt = base
        if frontier is not None:
            stmt = stmt.where(Claim.object_id.in_(frontier))
        following = set()
        stream = await db.stream_scalars(stmt.order_by(Claim.recorded_at, Claim.id))
        try:
            async for claim in stream:
                visited += 1
                if visited > 2000:
                    budget_exhausted = True
                    break
                if claim.id in facts:
                    continue
                try:
                    fact = await knowledge.render(db, principal, claim)
                except HTTPException as error:
                    if error.status_code in (403, 404):
                        continue
                    raise
                subject = await objects.detail(db, principal, claim.object_id)
                if not matches_properties(subject):
                    continue
                if "value" in request and json.dumps(
                    request["value"], sort_keys=True
                ) != json.dumps(claim.value, sort_keys=True):
                    continue
                if request.get("document_id") is not None and not any(
                    ev["document_id"] == request["document_id"]
                    for ev in fact["evidence"]
                ):
                    continue
                if (
                    text
                    and text
                    not in json.dumps(fact, ensure_ascii=False, default=str).casefold()
                ):
                    continue
                facts[claim.id] = fact
                for citation in fact["evidence"]:
                    citations[citation["id"]] = citation
                records[claim.object_id] = subject
                if level < depth and claim.target_id is not None:
                    following.add(claim.target_id)
                    records[claim.target_id] = await objects.detail(
                        db, principal, claim.target_id
                    )
                    paths.append(
                        dict(
                            source=claim.object_id,
                            target=claim.target_id,
                            claim_id=claim.id,
                        )
                    )
                if len(facts) >= limit:
                    break
        finally:
            await stream.close()
        if budget_exhausted or not following or len(facts) >= limit or frontier is None:
            break
        frontier = following
    groups = defaultdict(list)
    for fact in facts.values():
        if fact["status"] == "accepted":
            groups[fact["object_id"], fact["predicate_id"]].append(fact)
    conflicts = []
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a["target_id"] or b["target_id"]:
                    continue
                overlaps = (a["effective_from"] or "") <= (
                    b["effective_to"] or "9999"
                ) and (b["effective_from"] or "") <= (a["effective_to"] or "9999")
                if overlaps and json.dumps(a["value"], sort_keys=True) != json.dumps(
                    b["value"], sort_keys=True
                ):
                    conflicts.append([a["id"], b["id"]])
    return dict(
        status="conflict" if conflicts else "supported" if facts else "unknown",
        facts=list(facts.values()),
        objects=list(records.values())[:limit],
        evidence=list(citations.values())[:limit],
        paths=paths[:limit],
        conflicts=conflicts[:limit],
        budget_exhausted=budget_exhausted,
    )
