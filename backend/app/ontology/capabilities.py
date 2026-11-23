"""Assistant proposals bind the reviewed record state to a persistent action."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ..models import AuditLog, Document, EntityRecord, EntityType
from ..services import access, record
from ..services.ai_config import get_full_config
from .changes import actor
from .migrations import lock_writer
from .models import ObjectBinding, RecordChange
from .registry import digest


async def readable_gene(db, principal, gene):
    if not principal.has_page("dna"):
        return False
    kind, ref = gene.source_kind, gene.source_ref or ""
    if kind == "document":
        prefix = "doc-"
        if not ref.startswith(prefix) or not ref[len(prefix) :].isdigit():
            return False
        doc = await db.get(Document, int(ref[len(prefix) :]))
        return bool(
            doc
            and not doc.deleted_at
            and await access.can_read_doc(db, principal, doc.id)
        )
    if kind in ("note", "record"):
        prefix = "record-" if ref.startswith("record-") else "note-"
        if not ref.startswith(prefix) or not ref[len(prefix) :].isdigit():
            return False
        row = await db.get(EntityRecord, int(ref[len(prefix) :]))
        if not row or row.deleted_at:
            return False
        from .provenance import readable
        from sqlalchemy import select

        if not await db.scalar(
            select(EntityRecord.id).where(
                EntityRecord.id == row.id, readable(principal)
            )
        ):
            return False
        model = await db.get(EntityType, row.entity_type_id)
        return bool(
            model
            and not model.deleted_at
            and principal.can_model(model.key)
            and (model.key != "note" or principal.has_page("notes"))
        )
    return kind in {"manual", "code", "openkb"}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def state(db, principal, args):
    from ..services.agent import _type_by_key

    if not get_full_config().get("agent_write", True):
        raise HTTPException(403, "AI 写操作已关闭")
    if not principal.can_model(args["model_key"], "write"):
        raise HTTPException(403, "缺少模型写权限")
    model = await _type_by_key(db, args["model_key"])
    if not model:
        raise HTTPException(404, "模型不存在")
    fields = sorted(
        [(f.id, f.key, f.name, f.type, f.required, f.options) for f in model.fields]
    )
    pre = dict(model_id=model.id, schema=digest(fields))
    rid = args.get("record_id")
    if rid is not None:
        row = await db.get(EntityRecord, rid, populate_existing=True)
        if not row or row.deleted_at or row.entity_type_id != model.id:
            raise HTTPException(409, "目标记录已变化")
        binding = await db.get(ObjectBinding, rid)
        pre.update(
            version=binding.version if binding else None,
            record_digest=digest([row.data, str(row.updated_at)]),
        )
    return pre


async def propose_record(db, principal, tool, args):
    from ..services.agent import prepare_write

    await lock_writer(db)
    prepared = await prepare_write(db, principal, tool, args)
    if "error" in prepared:
        return prepared
    pending = prepared["pending"]
    clean = pending["args"]
    payload = dict(tool=tool, args=clean)
    plan = RecordChange(
        actor=actor(principal),
        payload=payload,
        payload_digest=digest(payload),
        preconditions=await state(db, principal, clean),
        expires_at=now() + timedelta(hours=1),
    )
    db.add(plan)
    await db.commit()
    pending["change_id"] = plan.id
    pending["expires_at"] = plan.expires_at.isoformat() + "Z"
    return prepared


async def confirm_record(db, principal, change_id):
    await lock_writer(db)
    plan = await db.get(RecordChange, change_id, populate_existing=True)
    if not plan or plan.actor != actor(principal):
        raise HTTPException(404, "记录变更不存在")
    tool, args = plan.payload["tool"], plan.payload["args"]
    if not principal.can_model(args["model_key"], "write"):
        raise HTTPException(403, "缺少模型权限")
    if plan.status == "succeeded":
        return plan.payload, plan.result
    if plan.expires_at < now() or digest(plan.payload) != plan.payload_digest:
        raise HTTPException(409, "计划已过期或已变化")
    current = await state(db, principal, args)
    if current != plan.preconditions:
        raise HTTPException(409, "记录或模型已变化，请重新预览")
    try:
        if tool == "create_record":
            row = await record.create_record(
                db, current["model_id"], args["data"], commit=False
            )
            action = "created"
        else:
            row = await db.get(EntityRecord, args["record_id"])
            if tool == "update_record":
                await record.update_record(
                    db,
                    row.id,
                    {**row.data, **args["data"]},
                    expected_version=current["version"],
                    commit=False,
                )
                action = "updated"
            elif tool == "delete_record":
                await record.delete_record(
                    db, row.id, expected_version=current["version"], commit=False
                )
                action = "deleted"
            else:
                raise HTTPException(422, "无效记录变更")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = dict(
        ok=True,
        action=action,
        record_id=row.id,
        model=args["model_key"],
        change_id=plan.id,
    )
    db.add(
        AuditLog(
            username=principal.username,
            user_id=principal.id,
            action="ai_agent_" + action,
            resource="ai_agent",
            resource_id=str(row.id),
            status=200,
            detail=result,
        )
    )
    plan.status, plan.result = "succeeded", result
    await db.commit()
    return plan.payload, result


def descriptor(name, description, properties, required=(), mode="read"):
    return dict(
        name=name,
        description=description,
        mode=mode,
        parameters=dict(
            type="object",
            properties=properties,
            required=list(required),
            additionalProperties=False,
        ),
        result_schema={"type": "object"},
        scope="published_revision",
        permissions=["types", "model_read", "source_read"],
        budget={"max_results": 50, "max_depth": 2},
    )


STRING = {"type": "string"}
INTEGER = {"type": "integer"}
CAPABILITIES = [
    descriptor("list_ontologies", "列出可访问本体", {}),
    descriptor(
        "query_ontology",
        "查询带原文出处的对象、声明、冲突及路径",
        {
            "ontology_id": STRING,
            "object_id": INTEGER,
            "predicate_id": STRING,
            "type_id": STRING,
            "text": STRING,
            "as_of": STRING,
            "depth": {"type": "integer", "minimum": 0, "maximum": 2},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["ontology_id"],
    ),
    descriptor(
        "get_ontology_evidence",
        "读取获准访问的原文引文与位置",
        {"evidence_id": STRING},
        ["evidence_id"],
    ),
    descriptor(
        "propose_ingestion",
        "预览资料加工发布计划，须由用户确认",
        {"job_id": STRING},
        ["job_id"],
        mode="proposed_write",
    ),
]


async def list_ontologies(db, principal):
    from .router import list_spaces

    return {"items": await list_spaces(db, principal, 50, 0)}


async def query_ontology(db, principal, ontology_id, **filters):
    from .query import search
    from .router import space_row

    return await search(db, principal, await space_row(db, ontology_id), filters)


async def get_ontology_evidence(db, principal, evidence_id):
    from .router import evidence_detail

    return await evidence_detail(evidence_id, db, principal)


async def propose_ingestion(db, principal, job_id):
    from .ingestion import plan
    from .models import IngestionJob

    await lock_writer(db)
    change = await plan(db, principal, await db.get(IngestionJob, job_id))
    return dict(change_id=change.id, status=change.status, proposed=change.payload)


async def sync_definitions(db):
    from sqlalchemy.dialects.sqlite import insert
    from .models import CapabilityDefinition

    for entry in CAPABILITIES:
        stmt = insert(CapabilityDefinition).values(name=entry["name"], definition=entry)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["name"], set_={"definition": stmt.excluded.definition}
            )
        )


async def register_run(db, principal, result, change_id=None):
    from .models import AssistantRun

    if not change_id:
        change_id = (result.get("pending") or {}).get("change_id")
    if not change_id:
        change_id = next(
            (
                step["result"]["change_id"]
                for step in result.get("tool_calls", [])
                if isinstance(step.get("result"), dict)
                and step["result"].get("change_id")
            ),
            None,
        )
    row = AssistantRun(
        actor=actor(principal),
        status=result["status"],
        error=result.get("error"),
        tools=[step.get("name") for step in result.get("tool_calls", [])],
        rounds=result.get("rounds", 0),
        change_id=change_id,
    )
    db.add(row)
    await db.commit()
    return {**result, "run_id": row.id}
