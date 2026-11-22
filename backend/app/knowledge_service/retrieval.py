"""Bounded authorized retrieval. No workspace permission is borrowed or elevated."""

import json
import re
import unicodedata
from datetime import date
from hashlib import sha256
from fastapi import HTTPException
from sqlalchemy import select
from ..ontology import objects, evidence
from ..ontology.models import (
    Claim,
    ObjectBinding,
    ObjectHistory,
    Projection,
    SourceSnapshot,
)
from ..models import EntityRecord
from . import policy, schemas, sources

SCAN_BUDGET = 2000
OBJECT_BUDGET = 1000


def normalize(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", str(value)).casefold())


def anchors(data):
    # Deterministic Chinese/title anchors handle ordinary questions without
    # sending text to a model or expanding an unauthorized vocabulary.
    values = [data.get(k, "") for k in ("title", "summary", "preferred", "aliases")]
    return {
        normalize(part)
        for value in values
        if isinstance(value, str)
        for part in re.split(r"[\W\d_]+", unicodedata.normalize("NFKC", value))
        if len(part) >= 2
    }


def matches(data, request):
    return all(
        not request.get(k) or str(data.get(k, "")) == request[k]
        for k in ("scope", "topic")
    )


async def object_scope(db, p, record_id, ontology_id=None):
    obj = await objects.detail(db, p, record_id)
    projection = await db.get(Projection, obj["type_id"])
    if not projection or (ontology_id and projection.ontology_id != ontology_id):
        raise HTTPException(404, "知识条目不属于当前空间")
    await policy.space(db, p, projection.ontology_id)
    return obj, projection.ontology_id


async def fact(db, p, claim, revisions, at):
    obj, _ = await object_scope(db, p, claim.object_id, claim.ontology_id)
    if claim.target_id is not None:
        await object_scope(db, p, claim.target_id, claim.ontology_id)
    if (
        claim.status != "accepted"
        or (claim.effective_from and claim.effective_from > at)
        or (claim.effective_to and claim.effective_to < at)
    ):
        return None
    citations = []
    for eid in claim.evidence_ids:
        ev = await evidence.read_evidence(db, p, eid)
        snap = await db.get(SourceSnapshot, ev["snapshot_id"])
        if (
            not snap
            or sha256(snap.text.encode()).hexdigest() != snap.text_sha
            or not 0 <= ev["start"] < ev["end"] <= len(snap.text)
            or snap.text[ev["start"] : ev["end"]] != ev["quote"]
        ):
            raise HTTPException(422, "引文与原文字符区间不符")
        applicable = [
            r
            for r in revisions
            if r.snapshot_id == ev["snapshot_id"]
            and sources.active(r, at, revisions)
            and all(
                not obj["data"].get(k) or getattr(r, k) == obj["data"][k]
                for k in ("scope", "topic")
            )
        ]
        if not applicable:
            return None
        rev = applicable[-1]
        ev.update(
            {
                k: getattr(rev, k)
                for k in ("label", "scope", "effective_from", "effective_to")
            }
        )
        ev["revision_id"] = rev.id
        citations.append(ev)
    if not citations:
        return None
    return dict(
        **schemas.row(claim), scope=obj["data"].get("scope", ""), evidence=citations
    )


async def terms(db, p, ontology_id, q="", scope=None):
    ontology, registration, schema, visible = await policy.space(db, p, ontology_id)
    if registration.term_type_id not in {t["id"] for t in visible}:
        return dict(items=[], ambiguous=False, incomplete=False)
    items = []
    ids = list(
        await db.scalars(
            select(ObjectBinding.record_id)
            .where(ObjectBinding.type_id == registration.term_type_id)
            .order_by(ObjectBinding.record_id)
            .limit(OBJECT_BUDGET + 1)
        )
    )
    for rid in ids[:OBJECT_BUDGET]:
        try:
            obj, _ = await object_scope(db, p, rid, ontology_id)
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
        data = obj["data"]
        if scope and data.get("scope") != scope:
            continue
        aliases = data.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [
                s.strip() for s in re.split(r"[,，;；、\n|]", aliases) if s.strip()
            ]
        if not isinstance(aliases, list):
            aliases = []
        words = [data.get("preferred", ""), *aliases]
        if q and not any(
            normalize(q) in normalize(w)
            or (len(normalize(w)) >= 2 and normalize(w) in normalize(q))
            for w in words
        ):
            continue
        items.append(
            dict(
                id=rid,
                preferred=data.get("preferred", ""),
                aliases=aliases,
                definition=data.get("definition", ""),
                scope=data.get("scope", ""),
            )
        )
    exact = [
        t
        for t in items
        if any(
            normalize(w) and normalize(w) in normalize(q)
            for w in [t["preferred"], *t["aliases"]]
        )
    ]
    return dict(
        items=items[:50],
        ambiguous=len({(t["preferred"], t["scope"]) for t in exact}) > 1,
        incomplete=len(ids) > OBJECT_BUDGET,
    )


async def search(db, p, request):
    ont, registration, schema, visible = await policy.space(
        db, p, request["ontology_id"]
    )
    selected = request.get("type_id")
    if selected and selected not in {t["id"] for t in visible}:
        raise HTTPException(403, "缺少所选知识模型权限")
    revisions = await sources.visible(db, p, ont.id)
    term_result = await terms(db, p, ont.id, request["question"], request.get("scope"))
    result = dict(
        status="insufficient",
        answer=None,
        generation="not_requested",
        items=[],
        facts=[],
        citations=[],
        sources=[],
        conflicts=[],
        relations=[],
        incomplete=False,
        reasons=[],
        terms=term_result["items"],
        as_of=request["as_of"],
        scope=request.get("scope"),
        budget=dict(scan_limit=SCAN_BUDGET, object_limit=OBJECT_BUDGET, scanned=0),
        revision_id=ont.current_revision_id,
    )
    if term_result["ambiguous"]:
        result.update(
            status="ambiguous", reasons=["术语存在多个含义，请选择适用范围或首选词。"]
        )
        return result
    needles = {normalize(request["question"])}
    for t in term_result["items"]:
        if any(
            normalize(w) and normalize(w) in normalize(request["question"])
            for w in [t["preferred"], *t["aliases"]]
        ):
            needles.add(normalize(t["preferred"]))
    visible_ids = {t["id"] for t in visible}
    object_ids = list(
        await db.scalars(
            select(ObjectBinding.record_id)
            .where(ObjectBinding.type_id.in_(visible_ids))
            .order_by(ObjectBinding.record_id)
            .limit(OBJECT_BUDGET + 1)
        )
    )
    records = {}
    roots = set()
    exhausted = (
        len(object_ids) > OBJECT_BUDGET
        or getattr(revisions, "incomplete", False)
        or term_result["incomplete"]
    )
    for rid in object_ids[:OBJECT_BUDGET]:
        try:
            obj, _ = await object_scope(db, p, rid, ont.id)
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
        if not matches(obj["data"], request) or (
            selected and obj["type_id"] != selected
        ):
            continue
        records[rid] = obj
        haystack = normalize(json.dumps(obj["data"], ensure_ascii=False))
        if any(
            n in haystack or any(anchor in n for anchor in anchors(obj["data"]))
            for n in needles
            if n
        ):
            roots.add(rid)
    candidates = list(
        await db.scalars(
            select(Claim)
            .where(
                Claim.ontology_id == ont.id,
                Claim.type_id.in_(visible_ids),
                Claim.status == "accepted",
            )
            .order_by(Claim.recorded_at, Claim.id)
            .limit(SCAN_BUDGET + 1)
        )
    )
    exhausted = exhausted or len(candidates) > SCAN_BUDGET
    rendered = {}
    for claim in candidates[:SCAN_BUDGET]:
        result["budget"]["scanned"] += 1
        if claim.object_id not in records:
            continue
        try:
            f = await fact(db, p, claim, revisions, request["as_of"])
        except HTTPException as e:
            if e.status_code in (403, 404, 409, 422):
                continue
            raise
        if not f:
            continue
        rendered[claim.id] = f
        if any(
            n in normalize(json.dumps(f["value"], ensure_ascii=False))
            for n in needles
            if n
        ):
            roots.add(claim.object_id)
    # Traverse accepted documentary relations only, at most two hops.
    reached = set(roots)
    frontier = set(roots)
    edges = []
    for _ in range(request["depth"]):
        following = set()
        for f in rendered.values():
            if f["object_id"] in frontier and f["target_id"] in records:
                following.add(f["target_id"])
                edges.append(
                    dict(source=f["object_id"], target=f["target_id"], claim_id=f["id"])
                )
        frontier = following - reached
        reached |= following
    facts = [
        f
        for f in rendered.values()
        if f["object_id"] in reached
        and (f["target_id"] is None or request["depth"] > 0)
    ]
    conflicts = []
    grouped = {}
    for f in facts:
        if f["target_id"] is not None:
            continue
        key = (f["object_id"], f["predicate_id"], f["scope"])
        for other in grouped.get(key, []):
            if json.dumps(other["value"], sort_keys=True) != json.dumps(
                f["value"], sort_keys=True
            ):
                conflicts.append([other["id"], f["id"]])
        grouped.setdefault(key, []).append(f)
    limit = request["limit"]
    selected_facts = facts[:limit]
    citations = {ev["id"]: ev for f in selected_facts for ev in f["evidence"]}
    # Items with documentary claims outside the requested period are not displayed.
    claim_objects = {c.object_id for c in candidates}
    live_objects = {f["object_id"] for f in facts} | {
        f["target_id"] for f in facts if f["target_id"] is not None
    }
    items = [
        dict(
            **records[rid],
            title=records[rid]["data"].get("title")
            or records[rid]["data"].get("preferred")
            or "知识条目",
            scope=records[rid]["data"].get("scope", "")
        )
        for rid in sorted(reached)
        if rid in records and (rid not in claim_objects or rid in live_objects)
    ]
    excerpts = []
    for rev in revisions[:2000]:
        if not sources.active(rev, request["as_of"], revisions) or not matches(
            dict(scope=rev.scope, topic=rev.topic), request
        ):
            continue
        snap = await db.get(SourceSnapshot, rev.snapshot_id)
        if not snap or sha256(snap.text.encode()).hexdigest() != snap.text_sha:
            continue
        if any(n in normalize(snap.text) for n in needles if n):
            excerpts.append(
                dict(
                    **schemas.row(rev),
                    quote=snap.text[:500],
                    start=0,
                    end=min(500, len(snap.text)),
                    verified=False,
                    kind="source_excerpt"
                )
            )
    reference_claim_ids = sorted(
        {f["id"] for f in selected_facts}
        | {cid for pair in conflicts[:50] for cid in pair}
    )
    reference_facts = [rendered[cid] for cid in reference_claim_ids]
    reference_citations = {
        ev["id"]: ev for f in reference_facts for ev in f["evidence"]
    }
    result["_references"] = dict(
        record_ids=sorted(
            {i["id"] for i in items[:limit]}
            | {f["object_id"] for f in reference_facts}
            | {f["target_id"] for f in reference_facts if f["target_id"] is not None}
        ),
        claim_ids=reference_claim_ids,
        evidence_ids=sorted(reference_citations),
        revision_ids=sorted(
            {s["id"] for s in excerpts[:limit]}
            | {e["revision_id"] for e in reference_citations.values()}
        ),
    )
    result.update(
        items=items[:limit],
        facts=selected_facts,
        citations=list(citations.values()),
        sources=excerpts[:limit],
        conflicts=conflicts[:50],
        relations=edges[:limit],
        incomplete=exhausted,
    )
    if conflicts:
        result.update(
            status="conflict",
            reasons=["同一对象、属性及范围存在不同的已接受事实，请核对资料。"],
        )
    elif exhausted:
        result.update(
            status="incomplete", reasons=["扫描预算已耗尽，请缩小知识空间或筛选条件。"]
        )
    elif selected_facts:
        result["status"] = "supported"
    else:
        result["reasons"] = ["未找到适用且有已接受证据的知识；资料摘录仅供核对。"]
    return result


async def detail(db, p, record_id):
    obj, oid = await object_scope(db, p, record_id)
    revisions = await sources.visible(db, p, oid)
    facts = []
    relations = []
    rows = list(
        await db.scalars(
            select(Claim)
            .where(
                Claim.ontology_id == oid,
                Claim.object_id == record_id,
                Claim.status == "accepted",
            )
            .order_by(Claim.id)
            .limit(201)
        )
    )
    for c in rows[:200]:
        try:
            f = await fact(db, p, c, revisions, date.today().isoformat())
        except HTTPException as e:
            if e.status_code in (403, 404, 409, 422):
                continue
            raise
        if f:
            facts.append(f)
            if f["target_id"] is not None:
                target, _ = await object_scope(db, p, f["target_id"], oid)
                relations.append(
                    dict(
                        source=record_id,
                        target=f["target_id"],
                        claim_id=f["id"],
                        title=target["data"].get("title")
                        or target["data"].get("preferred")
                        or "相关条目",
                    )
                )
    citations = {e["id"]: e for f in facts for e in f["evidence"]}
    history = [
        dict(
            version=h.version,
            data=h.data,
            revision_id=h.revision_id,
            created_at=h.created_at,
        )
        for h in await db.scalars(
            select(ObjectHistory)
            .where(ObjectHistory.record_id == record_id)
            .order_by(ObjectHistory.version.desc())
            .limit(50)
        )
    ]
    return dict(
        **obj,
        title=obj["data"].get("title") or obj["data"].get("preferred") or "知识条目",
        scope=obj["data"].get("scope", ""),
        facts=facts,
        citations=list(citations.values()),
        sources=[
            schemas.row(r)
            for r in revisions
            if r.id in {e["revision_id"] for e in citations.values()}
        ],
        relations=relations,
        history=history,
        incomplete=len(rows) > 200 or getattr(revisions, "incomplete", False)
    )
