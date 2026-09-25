"""记录 ↔ 知识库（笔记）关联服务

设计要点：
- 复用 RelationDef / RelationRecord，不引入新表 —— 这样关联会自动
  出现在「关联图谱」里，双向可见（记录详情能看到笔记，笔记详情能看到业务记录）。
- 关系定义按（源模型 → 笔记）惰性创建，用户无需手工配置即可使用。
- 提供「把业务记录沉淀为笔记」能力，这是结构化数据进入知识库的正向通道。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EntityType, EntityRecord, FieldDefinition, RelationDef, RelationRecord

NOTE_KEY = "note"
LINK_KEY_PREFIX = "kb_link"


def _type_brief(et: EntityType | None) -> dict | None:
    if not et:
        return None
    return {"id": et.id, "key": et.key, "name": et.name, "icon": et.icon}


async def get_note_type(db: AsyncSession) -> EntityType | None:
    q = select(EntityType).where(EntityType.key == NOTE_KEY)
    return (await db.execute(q)).scalar_one_or_none()


async def get_or_create_link_def(
    db: AsyncSession, source_type: EntityType, note_type: EntityType
) -> RelationDef:
    """取得（必要时创建）"源模型 → 笔记" 的关联定义"""
    key = f"{LINK_KEY_PREFIX}_{source_type.id}"
    rd = (
        await db.execute(select(RelationDef).where(RelationDef.key == key))
    ).scalar_one_or_none()
    if rd:
        return rd
    rd = RelationDef(
        key=key,
        name="关联知识",
        source_type_id=source_type.id,
        target_type_id=note_type.id,
        cardinality="many-to-many",
        description=f"{source_type.name} 记录挂接到知识库笔记",
    )
    db.add(rd)
    await db.commit()
    await db.refresh(rd)
    return rd


def _record_label(data: dict, rid: int) -> str:
    d = data or {}
    return d.get("name") or d.get("title") or d.get("code") or f"#{rid}"


async def list_notes_for_record(db: AsyncSession, record_id: int) -> dict:
    """某条业务记录关联了哪些笔记"""
    rec = await db.get(EntityRecord, record_id)
    if not rec:
        return {"notes": [], "source_type": None, "note_type": None, "is_note": False}
    source_type = await db.get(EntityType, rec.entity_type_id)
    note_type = await get_note_type(db)
    if not source_type or not note_type:
        return {"notes": [], "source_type": None, "note_type": None, "is_note": False}

    # 记录本身就是笔记 → 由双链机制负责，不重复挂接
    if source_type.id == note_type.id:
        return {
            "notes": [], "source_type": _type_brief(source_type),
            "note_type": _type_brief(note_type), "is_note": True,
        }

    link_def = await get_or_create_link_def(db, source_type, note_type)
    q = (
        select(EntityRecord, RelationRecord)
        .join(RelationRecord, RelationRecord.target_record_id == EntityRecord.id)
        .where(
            RelationRecord.relation_def_id == link_def.id,
            RelationRecord.source_record_id == record_id,
        )
    )
    rows = (await db.execute(q)).all()
    notes = []
    for note, rr in rows:
        d = note.data or {}
        notes.append({
            "note_id": note.id,
            "title": d.get("title") or f"#{note.id}",
            "tags": d.get("tags") or [],
            "snippet": (d.get("content") or "")[:180],
            "empty": not bool(d.get("content")),
            "relation_record_id": rr.id,
            "updated_at": note.updated_at,
        })
    notes.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return {
        "notes": notes,
        "source_type": _type_brief(source_type),
        "note_type": _type_brief(note_type),
        "link_def_id": link_def.id,
        "is_note": False,
    }


async def list_records_for_note(db: AsyncSession, note_id: int) -> dict:
    """某条笔记被哪些业务记录引用（反向）"""
    note_type = await get_note_type(db)
    if not note_type:
        return {"records": [], "total": 0}

    # 所有 target 指向 note 类型的关系定义
    defs = (
        await db.execute(
            select(RelationDef).where(RelationDef.target_type_id == note_type.id)
        )
    ).scalars().all()
    # 排除双链（由笔记页单独展示）
    defs = [d for d in defs if d.key != "note_wikilink"]
    if not defs:
        return {"records": [], "total": 0}

    def_ids = [d.id for d in defs]
    q = (
        select(RelationRecord, EntityRecord, EntityType, RelationDef)
        .join(EntityRecord, EntityRecord.id == RelationRecord.source_record_id)
        .join(EntityType, EntityType.id == EntityRecord.entity_type_id)
        .join(RelationDef, RelationDef.id == RelationRecord.relation_def_id)
        .where(
            RelationRecord.relation_def_id.in_(def_ids),
            RelationRecord.target_record_id == note_id,
        )
    )
    rows = (await db.execute(q)).all()
    records = []
    for rr, rec, et, rd in rows:
        records.append({
            "record_id": rec.id,
            "entity_type_id": et.id,
            "entity_type_key": et.key,
            "entity_type_name": et.name,
            "entity_type_icon": et.icon,
            "label": _record_label(rec.data, rec.id),
            "relation_name": rd.name,
            "relation_record_id": rr.id,
            "updated_at": rec.updated_at,
        })
    records.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return {"records": records, "total": len(records)}


async def link(db: AsyncSession, record_id: int, note_id: int) -> dict:
    """建立关联（幂等）"""
    rec = await db.get(EntityRecord, record_id)
    note = await db.get(EntityRecord, note_id)
    note_type = await get_note_type(db)
    if not rec or not note or not note_type:
        raise ValueError("记录或笔记不存在")
    if note.entity_type_id != note_type.id:
        raise ValueError("目标记录不是笔记")
    source_type = await db.get(EntityType, rec.entity_type_id)
    if source_type.id == note_type.id:
        raise ValueError("笔记之间的关联请使用 [[双链]]")
    if record_id == note_id:
        raise ValueError("不能关联自身")

    rd = await get_or_create_link_def(db, source_type, note_type)
    existing = (
        await db.execute(
            select(RelationRecord).where(
                RelationRecord.relation_def_id == rd.id,
                RelationRecord.source_record_id == record_id,
                RelationRecord.target_record_id == note_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"ok": True, "id": existing.id, "created": False}
    rr = RelationRecord(
        relation_def_id=rd.id,
        source_record_id=record_id,
        target_record_id=note_id,
        data={"via": "manual"},
    )
    db.add(rr)
    await db.commit()
    await db.refresh(rr)
    return {"ok": True, "id": rr.id, "created": True}


async def unlink(db: AsyncSession, record_id: int, note_id: int) -> bool:
    note_type = await get_note_type(db)
    if not note_type:
        return False
    defs = (
        await db.execute(
            select(RelationDef).where(RelationDef.target_type_id == note_type.id)
        )
    ).scalars().all()
    def_ids = [d.id for d in defs]
    if not def_ids:
        return False
    rr = (
        await db.execute(
            select(RelationRecord).where(
                RelationRecord.relation_def_id.in_(def_ids),
                RelationRecord.source_record_id == record_id,
                RelationRecord.target_record_id == note_id,
            )
        )
    ).scalar_one_or_none()
    if not rr:
        return False
    await db.delete(rr)
    await db.commit()
    return True


def _render_record_markdown(
    source_type: EntityType, rec: EntityRecord, fields: list[FieldDefinition]
) -> str:
    """把一条业务记录渲染成 Markdown 笔记正文"""
    lines = [f"# {_record_label(rec.data, rec.id)}", ""]
    if source_type.description:
        lines += [f"> {source_type.description}", ""]
    lines += [f"来源：**{source_type.name}** 记录 #{rec.id}", ""]
    for f in fields:
        if f.type in ("file", "image"):
            continue
        val = (rec.data or {}).get(f.key)
        if val is None or val == "" or val == []:
            continue
        if isinstance(val, list):
            val = "、".join(str(x) for x in val)
        elif isinstance(val, bool):
            val = "是" if val else "否"
        lines.append(f"- **{f.name}**：{val}")
    lines.append("")
    return "\n".join(lines)


async def note_from_record(db: AsyncSession, record_id: int) -> dict:
    """把业务记录沉淀为一条笔记并自动关联"""
    rec = await db.get(EntityRecord, record_id)
    if not rec:
        raise ValueError("记录不存在")
    source_type = await db.get(EntityType, rec.entity_type_id)
    note_type = await get_note_type(db)
    if not source_type or not note_type:
        raise ValueError("笔记模型不存在")
    if source_type.id == note_type.id:
        raise ValueError("记录本身已是笔记")

    fields = (
        await db.execute(
            select(FieldDefinition)
            .where(FieldDefinition.entity_type_id == source_type.id)
            .order_by(FieldDefinition.order)
        )
    ).scalars().all()

    title = f"{_record_label(rec.data, rec.id)} · {source_type.name}"
    content = _render_record_markdown(source_type, rec, list(fields))
    note = EntityRecord(
        entity_type_id=note_type.id,
        data={"title": title, "content": content, "tags": [source_type.name]},
        search_text=f"{title} {content}",
    )
    db.add(note)
    await db.flush()

    rd = await get_or_create_link_def(db, source_type, note_type)
    db.add(RelationRecord(
        relation_def_id=rd.id,
        source_record_id=record_id,
        target_record_id=note.id,
        data={"via": "materialize"},
    ))
    await db.commit()
    await db.refresh(note)
    return {"ok": True, "note_id": note.id, "title": title, "content": content}
