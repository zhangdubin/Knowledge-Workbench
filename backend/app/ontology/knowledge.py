from datetime import date, datetime, timezone
from types import SimpleNamespace
from fastapi import HTTPException

from ..models import AuditLog
from . import evidence, objects, registry
from .policy import require_workspace
from .models import Claim
from .validation import validate_record


def day(value):
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(422, "有效日期格式错误")


async def render(db, principal, claim, *, write=False):
    require_workspace(principal)
    await objects.detail(db, principal, claim.object_id, write=write)
    if claim.target_id is not None:
        await objects.detail(db, principal, claim.target_id)
    citations = [
        await evidence.read_evidence(db, principal, eid) for eid in claim.evidence_ids
    ]
    result = {
        column.name: getattr(claim, column.name) for column in Claim.__table__.columns
    }
    result["evidence"] = citations
    return result


async def candidate(db, principal, space, payload, extractor="manual/1"):
    require_workspace(principal)
    obj = await objects.detail(db, principal, payload.get("object_id"), write=True)
    schema = await registry.current(db, space)
    typ = next((t for t in schema["types"] if t["id"] == obj["type_id"]), None)
    if not typ:
        raise HTTPException(422, "对象不属于本体")
    citations = payload.get("evidence")
    if not isinstance(citations, list) or not 1 <= len(citations) <= 16:
        raise HTTPException(422, "需要 1 至 16 条证据")
    for loc in citations:
        if not isinstance(loc, dict) or type(loc.get("document_id")) is not int:
            raise HTTPException(422, "缺少来源文件")
        await evidence.source(db, principal, loc["document_id"])
    predicate = payload.get("predicate_id")
    field = next((f for f in typ["fields"] if f["id"] == predicate), None)
    target_id = payload.get("target_id")
    if field:
        if "value" not in payload or target_id is not None:
            raise HTTPException(422, "属性声明需要值")
        try:
            await validate_record(
                db,
                [SimpleNamespace(**{**field, "required": True})],
                {field["key"]: payload["value"]},
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    else:
        rel = next(
            (
                r
                for r in schema["relations"]
                if r["id"] == predicate and r["source"] == typ["id"]
            ),
            None,
        )
        if not rel or type(target_id) is not int or "value" in payload:
            raise HTTPException(422, "关系声明的目标或谓词无效")
        target = await objects.detail(db, principal, target_id)
        if target["type_id"] != rel["target"]:
            raise HTTPException(422, "关系目标类型不符")
    start, end = day(payload.get("effective_from")), day(payload.get("effective_to"))
    if start and end and start > end:
        raise HTTPException(422, "有效区间无效")
    score = payload.get("confidence")
    if score is not None and (type(score) not in (int, float) or not 0 <= score <= 1):
        raise HTTPException(422, "抽取器评分超出范围")
    captured = [await evidence.capture(db, principal, loc) for loc in citations]
    ids = [item.id for item in captured]
    row = Claim(
        ontology_id=space.id,
        revision_id=space.current_revision_id,
        type_id=typ["id"],
        object_id=obj["id"],
        predicate_id=predicate,
        value=payload.get("value"),
        target_id=target_id,
        evidence_ids=ids,
        confidence=score,
        extractor=extractor,
        effective_from=start,
        effective_to=end,
    )
    db.add(row)
    await db.flush()
    for item in captured:
        item.claim_id = row.id
    return row


async def review(db, principal, claim_id, decision):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "声明不存在")
    await render(db, principal, claim, write=True)
    if set(decision) - {"action", "expected_version", "superseded_by"}:
        raise HTTPException(422, "不支持的审核参数")
    if type(decision.get("expected_version")) is not int:
        raise HTTPException(428, "缺少 expected_version")
    if decision["expected_version"] != claim.version:
        raise HTTPException(409, "声明版本已变化")
    statuses = dict(
        accept="accepted", reject="rejected", dispute="disputed", supersede="superseded"
    )
    status = statuses.get(decision.get("action"))
    if not status:
        raise HTTPException(422, "无效的审核决定")
    if status == "superseded":
        replacement = await db.get(Claim, decision.get("superseded_by"))
        if not replacement or replacement.id == claim.id:
            raise HTTPException(422, "需要替代声明")
        await render(db, principal, replacement)
        if (replacement.object_id, replacement.predicate_id) != (
            claim.object_id,
            claim.predicate_id,
        ) or replacement.status != "accepted":
            raise HTTPException(422, "替代声明须为同一对象和谓词的已接受声明")
        claim.superseded_by = replacement.id
    elif claim.superseded_by is not None:
        raise HTTPException(409, "已替代的声明不可再次审核")
    claim.version += 1
    claim.status = status
    claim.reviewed_by = principal.username
    claim.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        AuditLog(
            user_id=principal.id,
            username=principal.username,
            action="ontology_review",
            resource="claim",
            resource_id=claim.id,
            status=200,
            detail=dict(version=claim.version, status=status),
        )
    )
    return await render(db, principal, claim)
