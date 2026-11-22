from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from ..models import AuditLog
from .migrations import lock_writer
from .models import Ontology, OntologyChangeSet
from .policy import require_schema
from .registry import assess, current, digest, publish, revision


def actor(principal):
    return str(principal.id) if principal.id is not None else principal.username


async def plan(db, principal, space, rev, migration):
    require_schema(principal, await current(db, space), write=True)
    require_schema(principal, rev.schema, write=True)
    impact, _ = await assess(db, space, rev, migration)
    if impact["blockers"]:
        raise HTTPException(409, impact)
    payload = dict(revision_id=rev.id, schema=rev.schema, migration=migration)
    change = OntologyChangeSet(
        kind="publish",
        actor=actor(principal),
        ontology_id=space.id,
        base_revision_id=space.current_revision_id,
        payload=payload,
        payload_digest=digest(payload),
        preconditions=impact,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    )
    db.add(change)
    await db.commit()
    return change


async def preview(db, principal, change_id):
    change = await db.get(OntologyChangeSet, change_id, populate_existing=True)
    if not change or change.actor != actor(principal):
        raise HTTPException(404, "变更计划不存在")
    require_schema(principal, change.payload["schema"], write=True)
    space = await db.get(Ontology, change.ontology_id)
    require_schema(principal, await current(db, space), write=True)
    return change


async def confirm_change(db, principal, change_id):
    await lock_writer(db)
    change = await preview(db, principal, change_id)
    if change.status == "succeeded":
        return change.result
    if change.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(409, "计划已过期")
    space = await db.get(Ontology, change.ontology_id)
    rev = await revision(db, space, change.payload["revision_id"])
    if (
        digest(change.payload) != change.payload_digest
        or rev.schema != change.payload["schema"]
    ):
        raise HTTPException(409, "草稿已变化")
    impact, rows = await assess(db, space, rev, change.payload["migration"])
    if impact != change.preconditions or impact["blockers"]:
        raise HTTPException(409, "受影响的数据已变化，请重新预览")
    await publish(db, space, rev, rows)
    change.status = "succeeded"
    change.result = dict(
        change_id=change.id,
        ontology_id=space.id,
        revision_id=rev.id,
        counts=impact["counts"],
    )
    db.add(
        AuditLog(
            user_id=principal.id,
            username=principal.username,
            action="ontology_publish",
            resource="ontology",
            resource_id=space.id,
            status=200,
            detail=change.result,
        )
    )
    await db.commit()
    return change.result
