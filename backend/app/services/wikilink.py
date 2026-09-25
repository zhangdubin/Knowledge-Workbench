"""Obsidian 风格的双向链接（wikilink）服务

[[笔记标题]] → 自动建立 RelationRecord（note_wikilink 关系）
反向链接 = 查"指向我"的 RelationRecord
"""
import re
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EntityType, EntityRecord, RelationDef, RelationRecord

WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")


async def extract_titles(content: str) -> list[str]:
    """从文本中提取 [[标题]] 列表"""
    if not content:
        return []
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(content) if m.group(1).strip()]


async def get_or_create_note_defs(db: AsyncSession) -> tuple[RelationDef, EntityType]:
    """获取 wikilink 关系定义 + note 实体类型；如不存在则创建"""
    et_q = select(EntityType).where(EntityType.key == "note")
    note_et = (await db.execute(et_q)).scalar_one_or_none()
    if not note_et:
        raise RuntimeError("note 实体类型不存在，请先在数据模型中创建")

    rd_q = select(RelationDef).where(RelationDef.key == "note_wikilink")
    rd = (await db.execute(rd_q)).scalar_one_or_none()
    if not rd:
        rd = RelationDef(
            key="note_wikilink",
            name="双向链接",
            source_type_id=note_et.id,
            target_type_id=note_et.id,
            cardinality="many-to-many",
            description="由 [[双链]] 自动生成",
        )
        db.add(rd)
        await db.commit()
        await db.refresh(rd)
    return rd, note_et


async def get_record_id_by_title(
    db: AsyncSession, note_et_id: int, title: str
) -> int | None:
    """按 title 字段找记录 id"""
    q = select(EntityRecord).where(
        EntityRecord.entity_type_id == note_et_id,
    )
    res = await db.execute(q)
    for r in res.scalars().all():
        if r.data.get("title") == title:
            return r.id
    return None


async def sync_wikilinks(
    db: AsyncSession, source_record_id: int, content: str
) -> dict:
    """同步一条笔记的双链：
    - 删除该 source 的所有旧 wikilink 关系
    - 解析 content 中的 [[title]]
    - 找到/创建对应记录（如不存在则创建占位笔记）
    - 创建新的 wikilink 关系
    """
    rd, note_et = await get_or_create_note_defs(db)

    # 删旧的
    await db.execute(
        delete(RelationRecord).where(
            RelationRecord.relation_def_id == rd.id,
            RelationRecord.source_record_id == source_record_id,
        )
    )

    titles = await extract_titles(content)
    title = ""  # 用于错误提示

    created = []
    for t in titles:
        title = t
        target_id = await get_record_id_by_title(db, note_et.id, t)
        if not target_id:
            # 自动创建占位笔记
            new_rec = EntityRecord(
                entity_type_id=note_et.id,
                data={"title": t, "content": "", "tags": []},
                search_text=t,
            )
            db.add(new_rec)
            await db.flush()
            target_id = new_rec.id
        if target_id == source_record_id:
            continue  # 自引用忽略
        db.add(RelationRecord(
            relation_def_id=rd.id,
            source_record_id=source_record_id,
            target_record_id=target_id,
            data={"title": t},
        ))
        created.append(target_id)

    await db.commit()
    return {"linked_count": len(created), "links": titles}


async def get_backlinks(
    db: AsyncSession, record_id: int
) -> list[dict]:
    """获取一条笔记的反向链接（被哪些笔记引用）"""
    rd_q = select(RelationDef).where(RelationDef.key == "note_wikilink")
    rd = (await db.execute(rd_q)).scalar_one_or_none()
    if not rd:
        return []

    q = (
        select(RelationRecord, EntityRecord)
        .join(EntityRecord, EntityRecord.id == RelationRecord.source_record_id)
        .where(
            RelationRecord.relation_def_id == rd.id,
            RelationRecord.target_record_id == record_id,
        )
    )
    res = await db.execute(q)
    out = []
    for rr, src in res.all():
        out.append({
            "source_record_id": src.id,
            "title": src.data.get("title") or f"#{src.id}",
            "snippet": (src.data.get("content") or "")[:200],
            "link_title": rr.data.get("title") if rr.data else "",
            "updated_at": src.updated_at,
        })
    return out


async def get_outgoing_links(
    db: AsyncSession, record_id: int
) -> list[dict]:
    """获取一条笔记的正向链接（指向哪些笔记）"""
    rd_q = select(RelationDef).where(RelationDef.key == "note_wikilink")
    rd = (await db.execute(rd_q)).scalar_one_or_none()
    if not rd:
        return []

    q = (
        select(RelationRecord, EntityRecord)
        .join(EntityRecord, EntityRecord.id == RelationRecord.target_record_id)
        .where(
            RelationRecord.relation_def_id == rd.id,
            RelationRecord.source_record_id == record_id,
        )
    )
    res = await db.execute(q)
    out = []
    for rr, tgt in res.all():
        out.append({
            "target_record_id": tgt.id,
            "title": tgt.data.get("title") or f"#{tgt.id}",
            "link_title": rr.data.get("title") if rr.data else "",
            "exists": bool(tgt.data.get("content")),
            "placeholder": not bool(tgt.data.get("content")),
            "updated_at": tgt.updated_at,
        })
    return out