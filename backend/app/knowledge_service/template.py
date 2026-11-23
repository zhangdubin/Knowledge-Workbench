from fastapi import HTTPException
from sqlalchemy import select
from ..ontology import registry, changes
from ..ontology.models import Ontology
from ..ontology.policy import require_schema
from ..ontology.migrations import lock_writer
from .models import KnowledgeSpace
from . import schemas


def definition(key="knowledge"):
    item, term = key + "_item", key + "_term"
    # Stable semantic identities are assigned by the existing registry.
    types = [
        dict(
            key=item,
            name="知识条目",
            fields=[
                dict(key=k, name=n, type="text")
                for k, n in [
                    ("title", "标题"),
                    ("summary", "摘要"),
                    ("scope", "适用范围"),
                    ("topic", "业务主题"),
                ]
            ],
        ),
        dict(
            key=term,
            name="术语",
            fields=[
                dict(key=k, name=n, type="text")
                for k, n in [
                    ("preferred", "首选词"),
                    ("aliases", "别名"),
                    ("definition", "释义"),
                    ("scope", "适用范围"),
                ]
            ],
        ),
    ]
    # Normalize once to resolve relation endpoints; registry preserves these IDs.
    normalized = registry.normalize(
        dict(types=types, relations=[]), dict(types=[], relations=[])
    )
    a, b = [t["id"] for t in normalized["types"]]
    normalized["relations"] = [
        dict(
            key=key + "_" + k,
            name=n,
            source=a,
            target=target,
            cardinality="many-to-many",
        )
        for k, n, target in [
            ("basis", "引用依据", a),
            ("topic", "属于业务主题", a),
            ("term", "术语相关", b),
            ("supersedes", "明确替代", a),
        ]
    ]
    return dict(
        name="中文知识服务模板",
        description="明确预览和确认后建立知识条目、术语及关系；不接管已有数据。",
        schema=normalized,
    )


async def preview(db, p, payload):
    schemas.keys(payload, ("key", "name"))
    key = schemas.text(payload.get("key"), "空间标识", 48, True)
    name = schemas.text(payload.get("name"), "空间名称", 120, True)
    require_schema(p, dict(types=[], relations=[]), write=True)
    if not p.has_feature("relation_manage"):
        raise HTTPException(403, "缺少关联管理权限")
    await lock_writer(db)
    if await db.scalar(select(Ontology.id).where(Ontology.key == key)):
        raise HTTPException(409, "知识空间标识已占用")
    ont = Ontology(key=key, name=name, description="knowledge_service/1")
    db.add(ont)
    await db.flush()
    rev = await registry.save_draft(db, p, ont, definition(key)["schema"])
    change = await changes.plan(db, p, ont, rev, {}, commit=False)
    db.add(
        KnowledgeSpace(
            ontology_id=ont.id,
            item_type_id=rev.schema["types"][0]["id"],
            term_type_id=rev.schema["types"][1]["id"],
            change_id=change.id,
            field_roles={
                t["id"]: {f["key"]: f["id"] for f in t["fields"]}
                for t in rev.schema["types"]
            },
        )
    )
    await db.commit()
    return dict(
        space_id=ont.id,
        change_id=change.id,
        preview=dict(schema=rev.schema, impact=change.preconditions),
    )


async def confirm(db, p, change_id):
    registration = await db.scalar(
        select(KnowledgeSpace).where(KnowledgeSpace.change_id == change_id)
    )
    if not registration:
        raise HTTPException(404, "知识模板预览不存在")
    result = await changes.confirm_change(db, p, change_id)
    return dict(space_id=registration.ontology_id, **result)
