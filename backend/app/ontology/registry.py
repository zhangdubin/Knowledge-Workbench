"""Draft registry, stable legacy projections and publication dry runs."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from ..models import (
    EntityRecord,
    EntityType,
    FieldDefinition,
    RelationDef,
    RelationRecord,
)
from ..services.record import build_search_text
from .models import (
    ObjectBinding,
    Ontology,
    OntologyRevision,
    Projection,
    RetiredProperty,
)
from .objects import snapshot
from .policy import require_schema
from .schemas import EMPTY, normalize
from .validation import validate_record


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


async def revision(db, space, revision_id):
    row = await db.get(OntologyRevision, revision_id)
    if not row or row.ontology_id != space.id:
        raise HTTPException(404, "本体修订不存在")
    return row


async def current(db, space):
    return (
        (await revision(db, space, space.current_revision_id)).schema
        if space.current_revision_id
        else EMPTY
    )


async def baseline(db, space):
    if space.current_revision_id:
        return await current(db, space)
    return space.adoption_schema or EMPTY


async def save_draft(db, principal, space, raw, existing=None):
    previous = await baseline(db, space)
    require_schema(principal, previous, write=True)
    if existing and existing.status not in ("draft", "validated"):
        raise HTTPException(409, "已发布修订不可修改")
    schema = normalize(raw, existing.schema if existing else previous)
    require_schema(principal, schema, write=True)
    row = existing or OntologyRevision(
        ontology_id=space.id, base_revision_id=space.current_revision_id
    )
    row.schema = schema
    row.status = "draft"
    db.add(row)
    await db.flush()
    return row


async def projections(db, space):
    mapping = dict(space.adoption or {})
    for p in await db.scalars(
        select(Projection).where(Projection.ontology_id == space.id)
    ):
        mapping[p.semantic_id] = p.legacy_id
    return mapping


def migrate(data, old, new, migration):
    result = deepcopy(data)
    new_fields = {f["id"]: f for f in new["fields"]}
    moves = {}
    for former in old.get("fields", []):
        key = former["key"]
        if key not in data:
            continue
        field = new_fields.get(former["id"])
        if not field and former["id"] in migration.get("field_map", {}):
            field = new_fields.get(migration["field_map"][former["id"]])
        if not field:
            if data[key] is not None:
                raise ValueError(f"删除的字段 {key} 含有数据")
            result.pop(key)
        elif key != field["key"]:
            if field["key"] in moves:
                raise ValueError("多个字段不能合并覆盖")
            moves[field["key"]] = result.pop(key)
    if moves.keys() & result.keys():
        raise ValueError("字段重命名会覆盖数据")
    result.update(moves)
    defaults = migration.get("defaults", {})
    for field in new["fields"]:
        if field["id"] in defaults:
            result.setdefault(field["key"], defaults[field["id"]])
    return result


async def assess(db, space, rev, migration):
    if rev.base_revision_id != space.current_revision_id or rev.status not in (
        "draft",
        "validated",
    ):
        raise HTTPException(409, "修订基线已变化")
    if (
        not isinstance(migration, dict)
        or migration.keys() - {"defaults", "field_map"}
        or any(not isinstance(v, dict) for v in migration.values())
    ):
        raise HTTPException(422, "迁移只支持 defaults 和 field_map")
    mapping = await projections(db, space)
    old = (
        (await current(db, space))
        if space.current_revision_id
        else (space.adoption_schema or EMPTY)
    )
    rows, evidence, blockers, changes = [], [], [], []
    if not space.current_revision_id and space.adoption_schema:
        for original in space.adoption_schema["types"]:
            rows_now = list(
                await db.scalars(
                    select(FieldDefinition).where(
                        FieldDefinition.entity_type_id == mapping[original["id"]]
                    )
                )
            )
            captured = {mapping[f["id"]]: f for f in original["fields"]}
            if len(captured) != len(rows_now) or any(
                row.id not in captured
                or any(
                    getattr(row, k) != captured[row.id][k]
                    for k in ("key", "name", "type", "required", "options")
                )
                for row in rows_now
            ):
                blockers.append("接管草稿建立后旧模型字段已变化，请重新核对")
    proposed_targets = {t["key"]: mapping.get(t["id"]) for t in rev.schema["types"]}
    renamed_keys = {t["key"] for t in old["types"]} - proposed_targets.keys()
    if renamed_keys:
        governed_types = {mapping[t["id"]] for t in old["types"] if t["id"] in mapping}
        inbound = await db.scalars(
            select(FieldDefinition).where(
                FieldDefinition.type == "reference",
                FieldDefinition.entity_type_id.not_in(governed_types),
            )
        )
        if any((f.options or {}).get("target") in renamed_keys for f in inbound):
            blockers.append("外部模型仍引用原标识，请先迁移引用")
    owners = {field["id"]: t["id"] for t in old["types"] for field in t["fields"]}
    old_types = {t["id"]: t for t in old["types"]}
    counts = {"types": 0, "records": 0, "relations": 0}
    definitions = []
    for typ in rev.schema["types"]:
        definitions.extend(
            [
                ("type", typ, EntityType),
                *(("field", f, FieldDefinition) for f in typ["fields"]),
            ]
        )
        for field in typ["fields"]:
            if owners.get(field["id"], typ["id"]) != typ["id"]:
                blockers.append(f"字段 {field['key']} 的归属模型已变化")
            if field["type"] == "reference":
                target = field["options"]["target"]
                if target in renamed_keys or (
                    target not in proposed_targets
                    and not await db.scalar(
                        select(EntityType.id).where(
                            EntityType.key == target, EntityType.deleted_at.is_(None)
                        )
                    )
                ):
                    blockers.append(f"引用字段 {field['key']} 的目标模型不存在")
        previous = old_types.get(typ["id"], {})
        if typ["id"] in mapping:
            for field in typ["fields"]:
                if field["id"] in mapping:
                    existing = await db.get(FieldDefinition, mapping[field["id"]])
                    if not existing or existing.entity_type_id != mapping[typ["id"]]:
                        blockers.append(f"字段 {field['key']} 的归属模型已变化")

        if previous != typ:
            before_fields = {field["id"]: field for field in previous.get("fields", [])}
            after_fields = {field["id"]: field for field in typ["fields"]}
            for field_id in sorted(before_fields.keys() | after_fields.keys()):
                before = before_fields.get(field_id, {})
                after = after_fields.get(field_id, {})
                if before != after:
                    changes.append(
                        f"字段 {before.get('key', '∅')} → {after.get('key', '∅')} "
                        f"({before.get('type', '∅')} → {after.get('type', '∅')}, "
                        f"必填 {before.get('required', False)} → {after.get('required', False)})"
                    )
            changes.append(f"更新类型 {typ['name']} ({typ['key']})")
        if typ == previous and space.current_revision_id:
            continue
        counts["types"] += 1
        if typ["id"] not in mapping:
            continue
        fields = [SimpleNamespace(**f) for f in typ["fields"]]
        for rec in await db.scalars(
            select(EntityRecord)
            .where(EntityRecord.entity_type_id == mapping[typ["id"]])
            .order_by(EntityRecord.id)
        ):
            counts["records"] += 1
            binding = await db.get(ObjectBinding, rec.id)
            evidence.append(
                (
                    rec.id,
                    rec.data,
                    rec.updated_at,
                    rec.deleted_at,
                    binding.version if binding else None,
                )
            )
            try:
                data = migrate(rec.data, previous, typ, migration)
                await validate_record(
                    db, fields, data, rec.data, reference_targets=proposed_targets
                )
                rows.append((rec, typ, data, fields))
            except ValueError as error:
                blockers.append(f"记录 #{rec.id}: {error}")
    for relation in rev.schema["relations"]:
        definitions.append(("relation", relation, RelationDef))
        if relation not in old["relations"]:
            changes.append(f"更新关系 {relation['name']} ({relation['key']})")
        src, tgt = set(), set()
        if relation["id"] in mapping:
            for link in await db.scalars(
                select(RelationRecord)
                .where(RelationRecord.relation_def_id == mapping[relation["id"]])
                .order_by(RelationRecord.id)
            ):
                counts["relations"] += 1
                evidence.append(
                    (link.id, link.source_record_id, link.target_record_id, link.data)
                )
                for side, seen, record_id, unique in [
                    (
                        "source",
                        src,
                        link.source_record_id,
                        relation["cardinality"].endswith("-one"),
                    ),
                    (
                        "target",
                        tgt,
                        link.target_record_id,
                        relation["cardinality"].startswith("one-"),
                    ),
                ]:
                    record = (
                        await db.get(EntityRecord, record_id) if record_id else None
                    )
                    if (
                        not record
                        or record.deleted_at
                        or record.entity_type_id != mapping.get(relation[side])
                        or (unique and record_id in seen)
                    ):
                        blockers.append(f"关联 #{link.id} 与新端点或基数不兼容")
                    seen.add(record_id)
    for kind, item, model in definitions:
        if await db.get(RetiredProperty, item["id"]):
            blockers.append(f"身份已停用 {item['id']}")
        binding = await db.get(Projection, item["id"])
        if binding and (binding.kind != kind or binding.ontology_id != space.id):
            blockers.append(f"身份已被占用 {item['id']}")
        if kind != "field":
            collision = await db.scalar(select(model).where(model.key == item["key"]))
            if collision and collision.id != mapping.get(item["id"]):
                blockers.append(f"标识已被占用 {item['key']}")
        if item["id"] in mapping:
            row = await db.get(model, mapping[item["id"]])
            if not row or getattr(row, "deleted_at", None):
                blockers.append(f"投影已删除 {item['key']}")
            else:
                evidence.append(
                    (
                        kind,
                        row.id,
                        {c.name: getattr(row, c.name) for c in model.__table__.columns},
                    )
                )
    active = {d["id"] for _, d, _ in definitions}
    for item in [*old["types"], *old["relations"]]:
        if item["id"] not in active:
            blockers.append(f"删除类型或关系需要先迁出实例 {item['key']}")
    return dict(
        blockers=blockers, changes=changes, counts=counts, fingerprint=digest(evidence)
    ), rows


async def publish(db, space, rev, rows):
    mapping = await projections(db, space)

    async def put(kind, model, definition, values):
        identity = definition["id"]
        row = await db.get(model, mapping[identity]) if identity in mapping else model()
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        await db.flush()
        if not await db.get(Projection, identity):
            db.add(
                Projection(
                    semantic_id=identity,
                    ontology_id=space.id,
                    kind=kind,
                    legacy_id=row.id,
                )
            )
        mapping[identity] = row.id
        return row

    old = (
        (await current(db, space))
        if space.current_revision_id
        else (space.adoption_schema or EMPTY)
    )
    active_fields = {f["id"] for t in rev.schema["types"] for f in t["fields"]}
    for t in old["types"]:
        for f in t["fields"]:
            if f["id"] not in active_fields:
                await db.delete(await db.get(FieldDefinition, mapping[f["id"]]))
                db.add(RetiredProperty(semantic_id=f["id"], owner_type_id=t["id"]))
                binding = await db.get(Projection, f["id"])
                if binding:
                    await db.delete(binding)
    for typ in rev.schema["types"]:
        et = await put("type", EntityType, typ, {k: typ[k] for k in ("key", "name")})
        for index, f in enumerate(typ["fields"]):
            await put(
                "field",
                FieldDefinition,
                f,
                dict(
                    entity_type_id=et.id,
                    order=index,
                    **{k: f[k] for k in ("key", "name", "type", "options", "required")},
                ),
            )
    for r in rev.schema["relations"]:
        await put(
            "relation",
            RelationDef,
            r,
            dict(
                source_type_id=mapping[r["source"]],
                target_type_id=mapping[r["target"]],
                **{k: r[k] for k in ("name", "key", "cardinality")},
            ),
        )
    for rec, typ, data, fields in rows:
        rec.data = data
        rec.search_text = build_search_text(fields, data)
        await snapshot(db, rec, typ["id"], rev.id)
    rev.status = "published"
    space.current_revision_id = rev.id
