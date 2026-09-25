"""关系管理服务

关系两端各自是「业务记录」或「数据中心文件」，由 RelationDef 的
source_kind / target_kind 决定。本模块把「取另一端」这件事收敛成
一个统一形状，路由与图谱都只消费这个形状，不再各自判断类型。

统一出参（link）：
  {
    link_id, def_id, relation, direction,
    other_kind: "record"|"document",
    other_id, other_label, other_type_key, other_type_name, other_icon,
    other_meta: {...}          # 文件的 ext/size/kind 等，记录为空
  }
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Document, DocumentLink, EntityRecord, EntityType,
    FieldDefinition, RelationDef, RelationRecord,
)

KINDS = ("record", "document")

# 候选列表里给文件一个能看的图标（后端直接给，前端不必再维护一份映射）
_DOC_KIND_ICON = {
    "image": "🖼️", "doc": "📄", "sheet": "📊", "slide": "📽️",
    "pdf": "📕", "text": "📝", "code": "🧩", "archive": "🗜️",
    "audio": "🎵", "video": "🎬", "other": "📎",
}


def _fmt_size(n: int) -> str:
    """人类可读的大小。前端也有 formatSize，但候选列表的 sub 文案在后端拼，
    这里统一一下，避免出现「110359 B」这种要用户自己数位数的写法。"""
    v = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def label_of_record(rec: EntityRecord | None, rid: int) -> str:
    if not rec:
        return f"#{rid}"
    d = rec.data or {}
    for k in ("name", "title", "code", "label"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return f"#{rid}"


def label_of_document(doc: Document | None, did: int) -> str:
    if not doc:
        return f"文件 #{did}"
    return doc.title or doc.filename or f"文件 #{did}"


# ---------- 定义 ----------

async def list_relation_defs(db: AsyncSession) -> list[dict]:
    defs = (await db.execute(select(RelationDef).order_by(RelationDef.id))).scalars().all()
    types = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}
    counts = dict((await db.execute(
        select(RelationRecord.relation_def_id, func.count(RelationRecord.id))
        .group_by(RelationRecord.relation_def_id)
    )).all())

    out = []
    for d in defs:
        st = types.get(d.source_type_id)
        tt = types.get(d.target_type_id)
        out.append({
            "id": d.id, "key": d.key, "name": d.name,
            "source_kind": d.source_kind or "record",
            "target_kind": d.target_kind or "record",
            "source_type_id": d.source_type_id,
            "target_type_id": d.target_type_id,
            "source_label": (st.name if st else ("数据中心文件" if d.source_kind == "document" else "—")),
            "target_label": (tt.name if tt else ("数据中心文件" if d.target_kind == "document" else "—")),
            "source_icon": (st.icon if st else "🗂️"),
            "target_icon": (tt.icon if tt else "🗂️"),
            "cardinality": d.cardinality,
            "description": d.description or "",
            "link_count": counts.get(d.id, 0),
        })
    return out


async def create_relation_def(db: AsyncSession, payload: dict) -> RelationDef:
    key = (payload.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "请填写关联标识")
    if (await db.execute(select(RelationDef).where(RelationDef.key == key))).scalar_one_or_none():
        raise HTTPException(400, f"关联标识「{key}」已存在")

    clean = {}
    for side in ("source", "target"):
        kind = payload.get(f"{side}_kind") or "record"
        if kind not in KINDS:
            raise HTTPException(400, f"{side}_kind 只能是 record 或 document")
        type_id = payload.get(f"{side}_type_id")
        if kind == "record":
            if not type_id:
                raise HTTPException(400, "记录端必须指定业务模型")
            if not await db.get(EntityType, type_id):
                raise HTTPException(400, f"模型 #{type_id} 不存在")
        else:
            # 文件不属于业务模型；顺手把传进来的 type_id 丢掉，
            # 免得库里留下「文件端却挂着模型」的自相矛盾数据
            type_id = None
        clean[f"{side}_kind"] = kind
        clean[f"{side}_type_id"] = type_id

    rd = RelationDef(
        key=key,
        name=payload.get("name") or key,
        cardinality=payload.get("cardinality") or "many-to-many",
        description=payload.get("description") or "",
        **clean,
    )
    db.add(rd)
    await db.commit()
    await db.refresh(rd)
    return rd


async def update_relation_def(db: AsyncSession, def_id: int, payload: dict) -> RelationDef:
    rd = await db.get(RelationDef, def_id)
    if not rd:
        raise HTTPException(404, "关联定义不存在")
    if payload.get("name"):
        rd.name = payload["name"]
    if payload.get("description") is not None:
        rd.description = payload["description"]
    if payload.get("cardinality"):
        rd.cardinality = payload["cardinality"]
    await db.commit()
    await db.refresh(rd)
    return rd


async def delete_relation_def(db: AsyncSession, def_id: int) -> bool:
    rd = await db.get(RelationDef, def_id)
    if not rd:
        return False
    # 先清关系实例：SQLite 的外键级联只在连接开启 foreign_keys 时生效，
    # 显式删一遍更稳（也让 delete 的语义在两种配置下一致）
    for rr in (await db.execute(
        select(RelationRecord).where(RelationRecord.relation_def_id == def_id)
    )).scalars().all():
        await db.delete(rr)
    await db.delete(rd)
    await db.commit()
    return True


# ---------- 实例 ----------

def _side_ids(payload: dict, side: str, kind: str) -> int:
    """取某一端的 id，并校验「kind 与填的字段一致」"""
    rid = payload.get(f"{side}_record_id")
    did = payload.get(f"{side}_document_id")
    if kind == "record":
        if not rid:
            raise HTTPException(400, "请选择关联记录")
        if did:
            raise HTTPException(400, "记录端不应带文件 id")
        return int(rid)
    if not did:
        raise HTTPException(400, "请选择关联文件")
    if rid:
        raise HTTPException(400, "文件端不应带记录 id")
    return int(did)


async def create_relation_record(db: AsyncSession, payload: dict) -> RelationRecord:
    rd = await db.get(RelationDef, payload.get("relation_def_id") or 0)
    if not rd:
        raise HTTPException(400, "关联定义不存在")

    src_kind = rd.source_kind or "record"
    tgt_kind = rd.target_kind or "record"
    src_id = _side_ids(payload, "source", src_kind)
    tgt_id = _side_ids(payload, "target", tgt_kind)

    # 存在性 + 类型匹配校验。只判「存在」是不够的：调用方漏传 type_id 时
    # 能把任意记录挂到任意定义上，库里就会出现与定义自相矛盾的关联。
    async def check_record(rid: int, expected_type_id: int | None) -> None:
        rec = await db.get(EntityRecord, rid)
        if not rec:
            raise HTTPException(400, f"记录 #{rid} 不存在")
        if expected_type_id and rec.entity_type_id != expected_type_id:
            et = await db.get(EntityType, expected_type_id)
            raise HTTPException(
                400,
                f"记录 #{rid} 属于模型 #{rec.entity_type_id}，"
                f"与本关联定义要求的「{et.name if et else expected_type_id}」不一致",
            )

    if src_kind == "record":
        await check_record(src_id, rd.source_type_id)
    elif not await _live_document(db, src_id):
        raise HTTPException(400, f"文件 #{src_id} 不存在")
    if tgt_kind == "record":
        await check_record(tgt_id, rd.target_type_id)
    elif not await _live_document(db, tgt_id):
        raise HTTPException(400, f"文件 #{tgt_id} 不存在")

    # 去重：同一对端点只保留一条（SQLite 的唯一约束对 NULL 不生效，
    # 因为文件端必然有一列为 NULL，所以只能在应用层判重）
    dup_q = select(RelationRecord).where(
        RelationRecord.relation_def_id == rd.id,
        RelationRecord.source_record_id == (src_id if src_kind == "record" else None),
        RelationRecord.target_record_id == (tgt_id if tgt_kind == "record" else None),
        RelationRecord.source_document_id == (src_id if src_kind == "document" else None),
        RelationRecord.target_document_id == (tgt_id if tgt_kind == "document" else None),
    )
    existing = (await db.execute(dup_q)).scalars().first()
    if existing:
        return existing

    rr = RelationRecord(
        relation_def_id=rd.id,
        source_record_id=src_id if src_kind == "record" else None,
        target_record_id=tgt_id if tgt_kind == "record" else None,
        source_document_id=src_id if src_kind == "document" else None,
        target_document_id=tgt_id if tgt_kind == "document" else None,
        data=payload.get("data") or {},
    )
    db.add(rr)
    await db.commit()
    await db.refresh(rr)
    return rr


async def _live_document(db: AsyncSession, doc_id: int) -> Document | None:
    doc = await db.get(Document, doc_id)
    if not doc or doc.deleted_at is not None:
        return None
    return doc


async def delete_relation_record(db: AsyncSession, record_id: int) -> bool:
    rr = await db.get(RelationRecord, record_id)
    if not rr:
        return False
    await db.delete(rr)
    await db.commit()
    return True


# ---------- 查询：一条记录 / 一个文件的关系 ----------

async def _resolve_other(db, rr: RelationRecord, rd: RelationDef, self_side: str) -> dict | None:
    """返回「另一端」的统一描述

    self_side 表示「被查询的实体」位于定义的哪一端 —— 必须显式传入，
    不能由「是记录还是文件」推断：一条记录既可能是源端也可能是目标端，
    早先按 kind 推断会导致「入向」关联把本体当成另一端显示出来。
    """
    src_kind = rd.source_kind or "record"
    tgt_kind = rd.target_kind or "record"
    ids = {
        "source": rr.source_record_id if src_kind == "record" else rr.source_document_id,
        "target": rr.target_record_id if tgt_kind == "record" else rr.target_document_id,
    }
    kinds = {"source": src_kind, "target": tgt_kind}

    other_side = "target" if self_side == "source" else "source"
    other_kind = kinds[other_side]
    other_id = ids[other_side]
    if other_id is None:
        return None

    if other_kind == "record":
        rec = await db.get(EntityRecord, other_id)
        et = await db.get(EntityType, rec.entity_type_id) if rec else None
        return {
            "other_kind": "record",
            "other_id": other_id,
            "other_label": label_of_record(rec, other_id),
            "other_type_key": et.key if et else "",
            "other_type_name": et.name if et else "",
            "other_icon": et.icon if et else "📦",
            "other_type_id": et.id if et else None,
            "other_meta": {},
        }
    doc = await _live_document(db, other_id)
    return {
        "other_kind": "document",
        "other_id": other_id,
        "other_label": label_of_document(doc, other_id),
        "other_type_key": "document",
        "other_type_name": "数据中心文件",
        "other_icon": "🗂️",
        "other_type_id": None,
        "other_meta": ({
            "ext": doc.ext or "", "size": doc.size or 0,
            "kind": doc.kind or "other", "mime": doc.mime or "",
            "preview_url": f"/api/documents/{doc.id}/raw",
            "download_url": f"/api/documents/{doc.id}/download",
        } if doc else {}),
    }


async def _links(db: AsyncSession, *, record_id: int | None = None,
                 document_id: int | None = None) -> list[dict]:
    if record_id is not None:
        cond = (RelationRecord.source_record_id == record_id) | \
               (RelationRecord.target_record_id == record_id)
    else:
        cond = (RelationRecord.source_document_id == document_id) | \
               (RelationRecord.target_document_id == document_id)

    rows = (await db.execute(
        select(RelationRecord, RelationDef)
        .join(RelationDef, RelationRecord.relation_def_id == RelationDef.id)
        .where(cond)
        .order_by(RelationRecord.id.desc())
    )).all()

    out = []
    for rr, rd in rows:
        # 先判断本体落在哪一端，再据此取另一端与方向
        if record_id is not None:
            self_side = "source" if rr.source_record_id == record_id else "target"
        else:
            self_side = "source" if rr.source_document_id == document_id else "target"
        other = await _resolve_other(db, rr, rd, self_side)
        if not other:
            continue
        out.append({
            "link_id": rr.id,
            "def_id": rd.id,
            "relation": rd.name,
            "relation_key": rd.key,
            "direction": "out" if self_side == "source" else "in",
            "source_kind": rd.source_kind or "record",
            "target_kind": rd.target_kind or "record",
            **other,
        })
    return out


async def get_related_records(db: AsyncSession, record_id: int) -> list[dict]:
    return await _links(db, record_id=record_id)


async def get_related_documents(db: AsyncSession, document_id: int) -> list[dict]:
    return await _links(db, document_id=document_id)


# ---------- 文件端的选择器：可选记录 / 可选文件 ----------

async def pickable(db: AsyncSession, *, def_id: int, side: str,
                   keyword: str = "", limit: int = 30) -> dict:
    """给「添加关联」弹窗用的候选列表

    只返回该端 kind 对应的东西，前端不需要知道后端怎么判断。
    """
    rd = await db.get(RelationDef, def_id)
    if not rd:
        raise HTTPException(404, "关联定义不存在")
    kind = (rd.source_kind if side == "source" else rd.target_kind) or "record"

    if kind == "document":
        q = select(Document).where(Document.deleted_at.is_(None))
        if keyword.strip():
            kw = f"%{keyword.strip()}%"
            q = q.where(Document.title.like(kw) | Document.filename.like(kw))
        docs = (await db.execute(
            q.order_by(Document.id.desc()).limit(limit)
        )).scalars().all()
        return {"kind": "document", "items": [{
            "id": d.id, "label": d.title or d.filename,
            "sub": f"{d.ext or ''} · {_fmt_size(d.size or 0)}",
            # kind 一律表示「实体种类」（record/document），文件自己的类型另放
            # file_kind：同一个字段名在两支分支里各指一种东西，调用方迟早读错。
            "kind": "document", "file_kind": d.kind or "other",
            "icon": _DOC_KIND_ICON.get(d.kind or "other", "📄"),
        } for d in docs]}

    type_id = rd.source_type_id if side == "source" else rd.target_type_id
    et = await db.get(EntityType, type_id) if type_id else None
    if not et:
        return {"kind": "record", "items": []}

    # 记录没有独立的标题列，名称在各模型的 data 里（name/title/code），
    # 关键词匹配只能退化为「在整份 JSON 里找」，这里就按 Python 过滤。
    recs = (await db.execute(
        select(EntityRecord).where(EntityRecord.entity_type_id == et.id)
        .order_by(EntityRecord.id.desc()).limit(500)
    )).scalars().all()
    kw = keyword.strip().lower()
    items = []
    for r in recs:
        label = label_of_record(r, r.id)
        if kw and kw not in label.lower():
            continue
        items.append({"id": r.id, "label": label, "sub": f"{et.name} · #{r.id}",
                      "kind": "record", "icon": et.icon or "📦"})
        if len(items) >= limit:
            break
    return {"kind": "record", "items": items, "type": {"id": et.id, "name": et.name, "icon": et.icon}}


# ---------- 记录详情里的「关联文件」区块 ----------

async def documents_attached_to(db: AsyncSession, record_id: int) -> list[dict]:
    """记录通过 document_link 直接挂着的文件（字段上传/附件），
    与「关联定义」是两条通道，详情页要一起展示才不遗漏。"""
    rows = (await db.execute(
        select(Document, DocumentLink.field_key)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .where(DocumentLink.record_id == record_id, Document.deleted_at.is_(None))
        .order_by(Document.id.desc())
    )).all()
    return [{
        "id": d.id, "label": d.title or d.filename, "field_key": fk,
        "ext": d.ext or "", "size": d.size or 0, "kind": d.kind or "other",
    } for d, fk in rows]


async def field_labels(db: AsyncSession, type_id: int) -> dict:
    rows = (await db.execute(
        select(FieldDefinition.key, FieldDefinition.name)
        .where(FieldDefinition.entity_type_id == type_id)
    )).all()
    return {k: v for k, v in rows}
