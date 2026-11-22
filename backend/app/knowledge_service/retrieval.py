"""Bounded retrieval over current authorization and stable application roles."""

import json
import re
import unicodedata
from datetime import date
from hashlib import sha256
from fastapi import HTTPException
from sqlalchemy import select
from ..ontology import objects, evidence, registry
from ..ontology.models import (
    Claim,
    ObjectBinding,
    ObjectHistory,
    Projection,
    SourceSnapshot,
)
from . import policy, schemas, sources, ranking

SCAN_BUDGET = 2000
OBJECT_BUDGET = 1000
RESULT_LIMIT = 50


def normalize(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", str(value)).casefold())


def anchors(data):
    values = [data.get(k, "") for k in ("title", "summary", "preferred", "aliases")]
    return {
        normalize(part)
        for value in values
        if isinstance(value, str)
        for part in re.split(r"[\W\d_]+", unicodedata.normalize("NFKC", value))
        if len(part) >= 2
    }


def matches(data, request, *, allow_unknown=False):
    return all(
        not request.get(k)
        or data.get(k) == request[k]
        or (allow_unknown and not data.get(k))
        for k in ("scope", "topic")
    )


def public_object(obj):
    result = {k: v for k, v in obj.items() if not k.startswith("_")}
    data = obj.get("_semantic", {})
    result.update({k: v for k, v in data.items() if v is not None})
    result.update(
        title=data.get("title") or data.get("preferred") or "知识条目",
        summary=data.get("summary") or "",
        scope=data.get("scope") or "",
        topic=data.get("topic") or "",
    )
    return result


async def object_scope(db, p, record_id, ontology_id=None):
    schemas.identifier(record_id, "知识条目", integer=True)
    obj = await objects.detail(db, p, record_id)
    projection = await db.get(Projection, obj["type_id"])
    if not projection or (ontology_id and projection.ontology_id != ontology_id):
        raise HTTPException(404, "知识条目不属于当前空间")
    _, registration, schema, _ = await policy.space(db, p, projection.ontology_id)
    obj["_semantic"] = policy.semantic_data(registration, schema, obj)
    return obj, projection.ontology_id


async def fact(
    db, p, claim, revisions, at, *, request=None, pinned=None, object_views=None
):
    obj, _ = await object_scope(db, p, claim.object_id, claim.ontology_id)
    if object_views and claim.object_id in object_views:
        obj = object_views[claim.object_id]
    data = obj["_semantic"]
    if claim.target_id is not None:
        await object_scope(db, p, claim.target_id, claim.ontology_id)
    if (
        claim.status != "accepted"
        or (claim.effective_from and claim.effective_from > at)
        or (claim.effective_to and claim.effective_to < at)
    ):
        return None
    if request and not matches(data, request, allow_unknown=True):
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
                not data.get(k) or getattr(r, k) in ("", data[k])
                for k in ("scope", "topic")
            )
            and all(
                not (request or {}).get(k) or getattr(r, k) in ("", request[k])
                for k in ("scope", "topic")
            )
            and (pinned is None or r.id == pinned.get(eid))
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
    domains = sorted({c["scope"] for c in citations if c["scope"]})
    if data.get("scope"):
        domains = [data["scope"]]
    elif (request or {}).get("scope"):
        domains = [request["scope"]]
    return dict(
        **schemas.row(claim),
        scope=domains[0] if len(domains) == 1 else "",
        scopes=domains,
        evidence=citations
    )


async def terms(db, p, ontology_id, q="", scope=None, *, internal=False):
    _, registration, _, visible = await policy.space(db, p, ontology_id)
    if registration.term_type_id not in {t["id"] for t in visible}:
        return dict(
            items=[],
            ambiguous=False,
            incomplete=False,
            **({"_dependencies": [], "_selections": []} if internal else {})
        )
    ids = list(
        await db.scalars(
            select(ObjectBinding.record_id)
            .where(ObjectBinding.type_id == registration.term_type_id)
            .order_by(ObjectBinding.record_id)
            .limit(OBJECT_BUDGET + 1)
        )
    )
    items = []
    selections = []
    for rid in ids[:OBJECT_BUDGET]:
        try:
            obj, _ = await object_scope(db, p, rid, ontology_id)
        except HTTPException as error:
            if error.status_code in (403, 404):
                continue
            raise
        data = obj["_semantic"]
        if scope and data.get("scope") != scope:
            continue
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [
                s.strip() for s in re.split(r"[,，;；、\n|]", aliases) if s.strip()
            ]
        if not isinstance(aliases, list):
            aliases = []
        words = [data.get("preferred") or "", *aliases]
        if q and not any(
            normalize(q) in normalize(w)
            or (len(normalize(w)) >= 2 and normalize(w) in normalize(q))
            for w in words
        ):
            continue
        selections.append(object_descriptor(obj))
        items.append(
            dict(
                id=rid,
                preferred=data.get("preferred") or "",
                aliases=aliases[:50],
                definition=data.get("definition") or "",
                scope=data.get("scope") or "",
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
    result = dict(
        items=items[:RESULT_LIMIT],
        ambiguous=len({(t["preferred"], t["scope"]) for t in exact}) > 1,
        incomplete=len(ids) > OBJECT_BUDGET or len(items) > RESULT_LIMIT,
    )
    if internal:
        result["_dependencies"] = [t["id"] for t in items]
        result["_selections"] = selections[:RESULT_LIMIT]
    return result


def conflict_sample(facts, limit=RESULT_LIMIT):
    """Linear representative sampling, never materialize all N*(N-1)/2 pairs."""
    groups = {}
    overall = {}
    pairs = []
    seen = set()
    found = False

    def remember(bucket, value, fact):
        if all(old_value != value for old_value, _ in bucket) and len(bucket) < 2:
            bucket.append((value, fact))

    for fact in facts:
        if fact["target_id"] is not None:
            continue
        key = (fact["object_id"], fact["predicate_id"])
        value = json.dumps(fact["value"], sort_keys=True, ensure_ascii=False)
        domains = fact.get("scopes") or (
            [fact["scope"]] if fact.get("scope") else [None]
        )
        for domain in domains:
            comparison = (
                overall.get(key, [])
                if domain is None
                else [*groups.get((*key, domain), []), *groups.get((*key, None), [])]
            )
            for old_value, other in comparison:
                if old_value == value:
                    continue
                found = True
                pair = tuple(sorted((other["id"], fact["id"])))
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(list(pair))
                    if len(pairs) >= limit:
                        return pairs, True
            remember(groups.setdefault((*key, domain), []), value, fact)
        remember(overall.setdefault(key, []), value, fact)
    return pairs, found


def excerpt(text, needles, width=500):
    # Keep the map back to original Unicode offsets through NFKC/punctuation.
    normalized = []
    positions = []
    for index, char in enumerate(text):
        part = normalize(char)
        normalized.extend(part)
        positions.extend([index] * len(part))
    haystack = "".join(normalized)
    for needle in sorted((n for n in needles if n), key=lambda n: (-len(n), n)):
        hit = haystack.find(needle)
        if hit < 0:
            continue
        hit_start = positions[hit]
        hit_end = positions[hit + len(needle) - 1] + 1
        start = max(0, hit_start - 150)
        end = min(len(text), max(start + width, hit_end))
        start = max(0, end - width)
        return dict(quote=text[start:end], start=start, end=end)
    return None


def bounded_facts(facts, limit):
    selected = []
    citations = {}
    for fact in facts:
        extra = {e["id"]: e for e in fact["evidence"]}
        if len(selected) >= limit or len(set(citations) | set(extra)) > RESULT_LIMIT:
            return selected, citations, True
        selected.append(fact)
        citations.update(extra)
    return selected, citations, False


def references(type_ids, record_ids, claim_ids, rendered, revisions=()):
    facts = [rendered[cid] for cid in sorted(claim_ids)]
    records = (
        set(record_ids)
        | {f["object_id"] for f in facts}
        | {f["target_id"] for f in facts if f["target_id"] is not None}
    )
    citations = [e for f in facts for e in f["evidence"]]
    return dict(
        version=2,
        type_ids=sorted(type_ids),
        record_ids=sorted(records),
        claim_ids=sorted(claim_ids),
        evidence_ids=sorted({e["id"] for e in citations}),
        revision_ids=sorted(set(revisions) | {e["revision_id"] for e in citations}),
        claim_revisions={
            f["id"]: {e["id"]: e["revision_id"] for e in f["evidence"]} for f in facts
        },
    )


def object_descriptor(obj):
    return {key: obj[key] for key in ("id", "version", "revision_id", "type_id")}


async def historical_object(db, p, ontology_id, selection, current=None):
    if current is None:
        current, _ = await object_scope(db, p, selection["id"], ontology_id)
    if current["type_id"] != selection["type_id"]:
        raise HTTPException(409, "原查询条目类型已变化，无法回放原版本")
    if (
        current["version"] == selection["version"]
        and current["revision_id"] == selection["revision_id"]
    ):
        return current
    history = await db.get(ObjectHistory, (selection["id"], selection["version"]))
    if not history or history.revision_id != selection["revision_id"]:
        raise HTTPException(409, "原查询条目版本不可用，请重新查询")
    ontology, registration, _, _ = await policy.space(db, p, ontology_id)
    revision = await registry.revision(db, ontology, history.revision_id)
    original = {
        **current,
        "data": history.data,
        "version": history.version,
        "revision_id": history.revision_id,
    }
    original["_semantic"] = policy.semantic_data(
        registration, revision.schema, original
    )
    return original


def public_selection(result, limit):
    # Only IDs, versions and exact excerpt locations are persisted, not cached
    # object bodies or generated text. ObjectHistory and immutable snapshots
    # remain the authorities for reconstructing historical public results.
    return dict(
        version=1,
        limit=limit,
        incomplete=result["incomplete"],
        items=[object_descriptor(obj) for obj in result["items"]],
        facts=[dict(id=f["id"], version=f["version"]) for f in result["facts"]],
        citations=[
            dict(
                id=e["id"],
                revision_id=e["revision_id"],
                start=e["start"],
                end=e["end"],
                quote_sha=sha256(e["quote"].encode()).hexdigest(),
            )
            for e in result["citations"]
        ],
        sources=[
            dict(
                id=r["id"],
                snapshot_id=r["snapshot_id"],
                start=r["start"],
                end=r["end"],
                quote_sha=sha256(r["quote"].encode()).hexdigest(),
            )
            for r in result["sources"]
        ],
        relations=[dict(edge) for edge in result["relations"]],
        terms=result.pop("_term_selections", []),
        conflicts=result["conflicts"],
    )


async def search(db, p, request):
    ont, registration, schema, visible = await policy.space(
        db, p, request["ontology_id"]
    )
    selected = request.get("type_id")
    role_types = set((registration.field_roles or {}).keys())
    visible_ids = {t["id"] for t in visible} & role_types
    if selected and selected not in visible_ids:
        raise HTTPException(403, "缺少所选知识模型权限或应用语义角色")
    selection_types = {selected} if selected else visible_ids
    revisions = await sources.visible(db, p, ont.id)
    term_result = await terms(
        db, p, ont.id, request["question"], request.get("scope"), internal=True
    )
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
        incomplete=revisions.incomplete or term_result["incomplete"],
        reasons=[],
        terms=term_result["items"],
        _term_selections=term_result["_selections"],
        as_of=request["as_of"],
        scope=request.get("scope"),
        budget=dict(
            scan_limit=SCAN_BUDGET,
            object_limit=OBJECT_BUDGET,
            source_limit=sources.SOURCE_BUDGET,
            term_limit=OBJECT_BUDGET,
            result_limit=request["limit"],
            scanned=0,
        ),
        revision_id=ont.current_revision_id,
    )
    term_dependencies = term_result["_dependencies"]
    dependency_types = set(selection_types)
    if term_dependencies:
        dependency_types.add(registration.term_type_id)
    if term_result["ambiguous"]:
        result.update(
            status="ambiguous",
            reasons=["术语存在多个含义，请选择适用范围或首选词。"],
            _references=references(dependency_types, term_dependencies, set(), {}),
        )
        return result
    needles = {normalize(request["question"])}
    for term in term_result["items"]:
        if any(
            normalize(w) and normalize(w) in normalize(request["question"])
            for w in [term["preferred"], *term["aliases"]]
        ):
            needles.add(normalize(term["preferred"]))
    object_ids = list(
        await db.scalars(
            select(ObjectBinding.record_id)
            .where(ObjectBinding.type_id.in_(selection_types))
            .order_by(ObjectBinding.record_id)
            .limit(OBJECT_BUDGET + 1)
        )
    )
    records = {}
    roots = set()
    exhausted = result["incomplete"] or len(object_ids) > OBJECT_BUDGET
    for rid in object_ids[:OBJECT_BUDGET]:
        try:
            obj, _ = await object_scope(db, p, rid, ont.id)
        except HTTPException as error:
            if error.status_code in (403, 404):
                continue
            raise
        if not matches(obj["_semantic"], request, allow_unknown=True):
            continue
        records[rid] = obj
        haystack = normalize(json.dumps(obj["_semantic"], ensure_ascii=False))
        if any(
            n in haystack or any(anchor in n for anchor in anchors(obj["_semantic"]))
            for n in needles
            if n
        ):
            roots.add(rid)
    candidates = list(
        await db.scalars(
            select(Claim)
            .where(
                Claim.ontology_id == ont.id,
                Claim.type_id.in_(selection_types),
                Claim.status == "accepted",
            )
            .order_by(Claim.recorded_at, Claim.id)
            .limit(SCAN_BUDGET + 1)
        )
    )
    exhausted = exhausted or len(candidates) > SCAN_BUDGET
    rendered = {}
    for claim in candidates[:SCAN_BUDGET]:
        if claim.object_id not in records:
            continue
        try:
            item = await fact(
                db, p, claim, revisions, request["as_of"], request=request
            )
        except HTTPException as error:
            if error.status_code in (403, 404, 409, 422):
                continue
            raise
        if not item:
            continue
        result["budget"]["scanned"] += 1
        rendered[claim.id] = item
        if claim.target_id is None and any(
            n in normalize(json.dumps(item["value"], ensure_ascii=False))
            for n in needles
            if n
        ):
            roots.add(claim.object_id)
    scalar_facts = {}
    for item in rendered.values():
        if item["target_id"] is None:
            scalar_facts.setdefault(item["object_id"], []).append(item)
    rank_candidates = []
    for rid in sorted(scalar_facts):
        obj = public_object(records[rid])
        text = " ".join(
            [
                obj["title"],
                obj["summary"],
                *[str(f["value"]) for f in scalar_facts[rid]],
                *[e["quote"] for f in scalar_facts[rid] for e in f["evidence"]],
            ]
        )
        rank_candidates.append(dict(id=rid, text=text[: ranking.TEXT_LIMIT]))
    scores, recalled, rank_dependencies = await ranking.rank(
        p, request["question"], rank_candidates, roots, result["budget"]
    )
    roots |= recalled
    exhausted = exhausted or result["budget"]["ranking"].get("truncated", False)
    # A last-level outedge never becomes a selected relation fact. Both endpoints
    # must meet the actual type/scope/topic filter before following the edge.
    valid_nodes = {
        rid
        for rid, obj in records.items()
        if matches(obj["_semantic"], request)
        or (
            rid in scalar_facts
            and matches(obj["_semantic"], request, allow_unknown=True)
        )
    }
    frontier = set(roots) & valid_nodes
    reached = set(roots)
    edges = []
    edge_ids = set()
    for _ in range(request["depth"]):
        following = set()
        for item in rendered.values():
            if (
                item["target_id"] is not None
                and item["object_id"] in frontier
                and item["target_id"] in valid_nodes
            ):
                following.add(item["target_id"])
                edge_ids.add(item["id"])
                edges.append(
                    dict(
                        source=item["object_id"],
                        target=item["target_id"],
                        claim_id=item["id"],
                    )
                )
        frontier = following - reached
        reached |= following
    facts = [
        f
        for f in rendered.values()
        if f["object_id"] in reached and (f["target_id"] is None or f["id"] in edge_ids)
    ]
    facts.sort(key=lambda f: (-scores.get(f["object_id"], 0), f["object_id"], f["id"]))
    conflicts, has_conflicts = conflict_sample(facts)
    selected_facts, citations, citation_truncated = bounded_facts(
        facts, request["limit"]
    )
    claimed_objects = {c.object_id for c in candidates}
    live_objects = {f["object_id"] for f in facts} | {
        f["target_id"] for f in facts if f["target_id"] is not None
    }
    item_ids = [
        rid
        for rid in sorted(reached, key=lambda rid: (-scores.get(rid, 0), rid))
        if rid in records
        and (rid not in claimed_objects or rid in live_objects)
        and (matches(records[rid]["_semantic"], request) or rid in live_objects)
    ]
    items = [public_object(records[rid]) for rid in item_ids[: request["limit"]]]
    excerpt_needles = set(needles)
    anchor_dependencies = set()
    for rid in roots:
        if rid in records:
            expanded = anchors(records[rid]["_semantic"])
            if expanded:
                excerpt_needles |= expanded
                anchor_dependencies.add(rid)
    excerpts = []
    for revision in revisions:
        if not sources.active(revision, request["as_of"], revisions) or not matches(
            dict(scope=revision.scope, topic=revision.topic), request
        ):
            continue
        snapshot = await db.get(SourceSnapshot, revision.snapshot_id)
        if (
            not snapshot
            or sha256(snapshot.text.encode()).hexdigest() != snapshot.text_sha
        ):
            continue
        hit = excerpt(snapshot.text, excerpt_needles)
        if hit:
            excerpts.append(
                dict(
                    **(await sources.public(db, p, revision)),
                    **hit,
                    verified=False,
                    kind="source_excerpt"
                )
            )
            if len(excerpts) >= request["limit"]:
                break
    reference_claims = (
        {f["id"] for f in selected_facts}
        | {cid for pair in conflicts for cid in pair}
        | edge_ids
    )
    reference_claims |= {
        f["id"]
        for rid in set(rank_dependencies) | reached
        for f in scalar_facts.get(rid, [])
    }
    dependency_records = (
        set(item_ids[: request["limit"]])
        | set(term_dependencies)
        | set(rank_dependencies)
        | anchor_dependencies
    )
    dependency_records |= {edge["source"] for edge in edges} | {
        edge["target"] for edge in edges
    }
    result.update(
        items=items,
        facts=selected_facts,
        citations=list(citations.values()),
        sources=excerpts,
        conflicts=conflicts,
        relations=edges[: request["limit"]],
        incomplete=exhausted or citation_truncated,
        _references=references(
            dependency_types,
            dependency_records,
            reference_claims,
            rendered,
            [s["id"] for s in excerpts],
        ),
    )
    if has_conflicts:
        result.update(
            status="conflict",
            reasons=["同一对象、属性及适用范围存在不同的已接受事实，请核对资料。"],
        )
    elif result["incomplete"]:
        result.update(
            status="incomplete",
            reasons=["扫描或结果预算已耗尽，请缩小知识空间或筛选条件。"],
        )
    elif selected_facts:
        result["status"] = "supported"
    else:
        result["reasons"] = ["未找到适用且有已接受证据的知识；资料摘录仅供核对。"]
    return result


async def detail(db, p, record_id):
    obj, oid = await object_scope(db, p, record_id)
    revisions = await sources.visible(db, p, oid)
    rows = list(
        await db.scalars(
            select(Claim)
            .where(
                Claim.ontology_id == oid,
                Claim.object_id == record_id,
                Claim.status == "accepted",
            )
            .order_by(Claim.id)
            .limit(SCAN_BUDGET + 1)
        )
    )
    found = []
    for claim in rows[:SCAN_BUDGET]:
        try:
            item = await fact(db, p, claim, revisions, date.today().isoformat())
        except HTTPException as error:
            if error.status_code in (403, 404, 409, 422):
                continue
            raise
        if item:
            found.append(item)
            if len(found) > RESULT_LIMIT:
                break
    facts, citations, truncated = bounded_facts(found, RESULT_LIMIT)
    relations = []
    for item in facts:
        if item["target_id"] is not None:
            target, _ = await object_scope(db, p, item["target_id"], oid)
            relations.append(
                dict(
                    source=record_id,
                    target=item["target_id"],
                    claim_id=item["id"],
                    title=public_object(target)["title"],
                )
            )
    history_rows = list(
        await db.scalars(
            select(ObjectHistory)
            .where(ObjectHistory.record_id == record_id)
            .order_by(ObjectHistory.version.desc())
            .limit(RESULT_LIMIT + 1)
        )
    )
    history = [
        dict(
            version=h.version,
            data=h.data,
            revision_id=h.revision_id,
            created_at=h.created_at,
        )
        for h in history_rows[:RESULT_LIMIT]
    ]
    return dict(
        **public_object(obj),
        facts=facts,
        citations=list(citations.values()),
        sources=[
            await sources.public(db, p, r)
            for r in revisions
            if r.id in {e["revision_id"] for e in citations.values()}
        ][:RESULT_LIMIT],
        relations=relations[:RESULT_LIMIT],
        history=history,
        incomplete=truncated
        or len(rows) > SCAN_BUDGET
        or revisions.incomplete
        or len(history_rows) > RESULT_LIMIT
    )
