"""关联分析服务：跨实体的图谱

节点 id 统一用带前缀的字符串（`r-12` / `d-3`）：
记录和文件是两张表，各自的 id 会撞（记录 #5 与文件 #5 同时存在），
前缀是让前端能把「点哪个节点跳哪里」判断清楚的最省事做法。

一个节点长这样：
  {id, kind, ref_id, label, type, type_name, icon, center?, meta?}
一条边：
  {id, source, target, relation, via}   # via: relation | reference | field
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Document, DocumentLink, EntityRecord, EntityType,
    FieldDefinition, RelationDef, RelationRecord,
)
from .relation import label_of_document, label_of_record

DEFAULT_NODE_LIMIT = 400


def rid_node_id(rid: int) -> str:
    return f"r-{rid}"


def did_node_id(did: int) -> str:
    return f"d-{did}"


def _record_node(rec: EntityRecord, et: EntityType | None) -> dict:
    return {
        "id": rid_node_id(rec.id),
        "kind": "record",
        "ref_id": rec.id,
        "label": label_of_record(rec, rec.id),
        "type": et.key if et else "",
        # type_id 让前端点节点就能直接跳转到对应模型的详情，不必再查一次接口
        "type_id": et.id if et else None,
        "type_name": et.name if et else "未知模型",
        "icon": et.icon if et else "📦",
    }


def _doc_node(doc: Document) -> dict:
    return {
        "id": did_node_id(doc.id),
        "kind": "document",
        "ref_id": doc.id,
        "label": label_of_document(doc, doc.id),
        "type": "document",
        "type_name": "数据中心文件",
        "icon": "🗂️",
        "meta": {
            "ext": doc.ext or "",
            "size": doc.size or 0,
            "file_kind": doc.kind or "other",
            "preview_url": f"/api/documents/{doc.id}/raw",
        },
    }


async def _record_ids_of_type(db: AsyncSession, type_id: int, limit: int) -> list[EntityRecord]:
    return (await db.execute(
        select(EntityRecord).where(EntityRecord.entity_type_id == type_id).limit(limit)
    )).scalars().all()


class _Collector:
    """节点/边收集器：去重 + 统一追加，避免每个分支各写一遍去重逻辑"""

    def __init__(self, limit: int = DEFAULT_NODE_LIMIT):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.limit = limit
        self.truncated = False

    def node(self, node: dict) -> bool:
        if node["id"] in self.nodes:
            return True
        if len(self.nodes) >= self.limit:
            self.truncated = True
            return False
        self.nodes[node["id"]] = node
        return True

    def edge(self, edge_id: str, source: str, target: str, relation: str, via: str) -> None:
        if source == target or edge_id in self.edges:
            return
        if source not in self.nodes or target not in self.nodes:
            return
        self.edges[edge_id] = {"id": edge_id, "source": source, "target": target,
                               "relation": relation, "via": via}

    def out(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values()),
                "truncated": self.truncated}


async def _load_documents(db: AsyncSession, ids: set[int]) -> dict[int, Document]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    docs = (await db.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
    return {d.id: d for d in docs if d.deleted_at is None}


async def _relation_rows_of(db: AsyncSession, *, record_ids: set[int] | None = None,
                            document_ids: set[int] | None = None) -> list[tuple]:
    """取出与给定端点相关的全部关系实例（含定义）"""
    q = select(RelationRecord, RelationDef).join(
        RelationDef, RelationRecord.relation_def_id == RelationDef.id
    )
    if record_ids:
        q = q.where(
            RelationRecord.source_record_id.in_(record_ids)
            | RelationRecord.target_record_id.in_(record_ids)
        )
    elif document_ids:
        q = q.where(
            RelationRecord.source_document_id.in_(document_ids)
            | RelationRecord.target_document_id.in_(document_ids)
        )
    return (await db.execute(q)).all()


async def _add_relation_edges(db: AsyncSession, col: _Collector,
                              rows: list[tuple]) -> set[int]:
    """把关系实例转成节点+边；返回本次涉及到的记录 id（供继续展开）"""
    rec_ids: set[int] = set()
    doc_ids: set[int] = set()
    for rr, _rd in rows:
        for rid in (rr.source_record_id, rr.target_record_id):
            if rid:
                rec_ids.add(rid)
        for did in (rr.source_document_id, rr.target_document_id):
            if did:
                doc_ids.add(did)

    # 先批量补齐节点，再连边 —— 边只有在两端节点都在时才画得出来
    ets = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}
    if rec_ids:
        for rec in (await db.execute(
            select(EntityRecord).where(EntityRecord.id.in_(rec_ids))
        )).scalars().all():
            col.node(_record_node(rec, ets.get(rec.entity_type_id)))
    docs = await _load_documents(db, doc_ids)
    for doc in docs.values():
        col.node(_doc_node(doc))

    for rr, rd in rows:
        src = rid_node_id(rr.source_record_id) if rr.source_record_id else did_node_id(rr.source_document_id)
        tgt = rid_node_id(rr.target_record_id) if rr.target_record_id else did_node_id(rr.target_document_id)
        if not src or not tgt:
            continue
        col.edge(f"rr-{rr.id}", src, tgt, rd.name, "relation")
    return rec_ids


async def _add_reference_edges(db: AsyncSession, col: _Collector,
                               records: list[EntityRecord]) -> set[int]:
    """把 reference 字段（数据里的外键）也画成边"""
    if not records:
        return set()
    by_type: dict[int, list[EntityRecord]] = {}
    for r in records:
        by_type.setdefault(r.entity_type_id, []).append(r)

    wanted: set[int] = set()
    meta: dict[int, list[FieldDefinition]] = {}
    for type_id, recs in by_type.items():
        fields = (await db.execute(
            select(FieldDefinition).where(
                FieldDefinition.entity_type_id == type_id,
                FieldDefinition.type == "reference",
            )
        )).scalars().all()
        meta[type_id] = fields
        for r in recs:
            for f in fields:
                t = (r.data or {}).get(f.key)
                if isinstance(t, int):
                    wanted.add(t)

    if not wanted:
        return set()

    ets = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}
    for rec in (await db.execute(
        select(EntityRecord).where(EntityRecord.id.in_(wanted))
    )).scalars().all():
        col.node(_record_node(rec, ets.get(rec.entity_type_id)))

    for type_id, recs in by_type.items():
        for r in recs:
            for f in meta[type_id]:
                t = (r.data or {}).get(f.key)
                if isinstance(t, int):
                    col.edge(f"ref-{r.id}-{f.key}-{t}", rid_node_id(r.id),
                             rid_node_id(t), f.name, "reference")
    return wanted


async def _add_attached_files(db: AsyncSession, col: _Collector,
                              record_ids: set[int]) -> set[int]:
    """记录通过字段上传 / 附件挂着的文件（document_link），也算一种关联"""
    if not record_ids:
        return set()
    rows = (await db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.id == DocumentLink.document_id)
        .where(DocumentLink.record_id.in_(record_ids), Document.deleted_at.is_(None))
    )).all()
    doc_ids = set()
    for link, doc in rows:
        col.node(_doc_node(doc))
        doc_ids.add(doc.id)
    field_names: dict[tuple[int, str], str] = {}
    for link, doc in rows:
        rn = rid_node_id(link.record_id)
        if rn not in col.nodes:
            continue
        key = (link.record_id, link.field_key or "")
        if key not in field_names:
            field_names[key] = link.field_key or "附件"
        col.edge(f"dl-{link.id}", rn, did_node_id(doc.id), field_names[key], "field")
    return doc_ids


# ---------- 对外：三种视图 ----------

async def get_record_graph(db: AsyncSession, record_id: int, depth: int = 2) -> dict:
    """以一条记录为中心展开（关系实例 + 外键 + 挂载文件），最多 depth 层"""
    col = _Collector()
    center = await db.get(EntityRecord, record_id)
    if not center:
        return {"nodes": [], "edges": [], "truncated": False}
    et = await db.get(EntityType, center.entity_type_id)
    col.node(_record_node(center, et))
    col.nodes[rid_node_id(record_id)]["center"] = True

    frontier = {record_id}
    for _ in range(max(depth, 1)):
        if not frontier or col.truncated:
            break
        rows = await _relation_rows_of(db, record_ids=frontier)
        next_ids = await _add_relation_edges(db, col, rows)
        attached_docs = await _add_attached_files(db, col, frontier)

        recs = (await db.execute(
            select(EntityRecord).where(EntityRecord.id.in_(frontier))
        )).scalars().all()
        next_ids |= await _add_reference_edges(db, col, recs)

        # 文件端不再继续展开（文件本身没有出边，展开只会白跑一趟）
        next_ids -= frontier
        if attached_docs:
            more = await _relation_rows_of(db, document_ids=attached_docs)
            next_ids |= await _add_relation_edges(db, col, more)
        next_ids -= frontier
        frontier = next_ids

    return col.out()


async def get_document_graph(db: AsyncSession, document_id: int, depth: int = 1) -> dict:
    """以文件为中心：它关联的记录/文件，以及这些记录挂着的其它文件"""
    col = _Collector()
    doc = await db.get(Document, document_id)
    if not doc or doc.deleted_at is not None:
        return {"nodes": [], "edges": [], "truncated": False}
    col.node(_doc_node(doc))
    col.nodes[did_node_id(document_id)]["center"] = True

    rows = await _relation_rows_of(db, document_ids={document_id})
    rec_ids = await _add_relation_edges(db, col, rows)

    # 通过 document_link 挂载关系补一条「附件」边
    links = (await db.execute(
        select(DocumentLink).where(DocumentLink.document_id == document_id)
    )).scalars().all()
    linked_records = {l.record_id for l in links if l.record_id}
    if linked_records:
        ets = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}
        for rec in (await db.execute(
            select(EntityRecord).where(EntityRecord.id.in_(linked_records))
        )).scalars().all():
            col.node(_record_node(rec, ets.get(rec.entity_type_id)))
        for l in links:
            if l.record_id:
                col.edge(f"dl-{l.id}", rid_node_id(l.record_id),
                         did_node_id(document_id), l.field_key or "附件", "field")
        rec_ids |= linked_records

    if depth > 1 and rec_ids:
        more = await _relation_rows_of(db, record_ids=rec_ids)
        nxt = await _add_relation_edges(db, col, more)
        nxt |= await _add_attached_files(db, col, rec_ids)
        if nxt:
            more2 = await _relation_rows_of(db, document_ids=nxt)
            await _add_relation_edges(db, col, more2)

    return col.out()


async def get_type_graph(db: AsyncSession, type_id: int, limit: int = 200) -> dict:
    """以一个实体类型为范围：该类型的记录 + 它们的关系（含文件端）"""
    col = _Collector(limit=max(limit, 50))
    et = await db.get(EntityType, type_id)
    if not et:
        return {"nodes": [], "edges": [], "truncated": False}

    records = await _record_ids_of_type(db, type_id, limit)
    for r in records:
        col.node(_record_node(r, et))

    rec_ids = {r.id for r in records}
    rows = await _relation_rows_of(db, record_ids=rec_ids)
    await _add_relation_edges(db, col, rows)
    await _add_reference_edges(db, col, records)
    await _add_attached_files(db, col, rec_ids)
    return col.out()


async def get_global_graph(db: AsyncSession, limit: int = 300,
                           include_documents: bool = True) -> dict:
    """全局：所有业务模型的记录 + 关系 + 文件

    这是「一屏看清业务网」的视图，节点上限卡在 limit。
    笔记（note）及其双链属于「知识图谱」，不在这里混入 —— 否则两个图谱
    职责重叠，全局视图会被笔记的双链占满，业务关联反而看不清。
    """
    col = _Collector(limit=limit * 2)
    all_ets = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}
    # 业务视图：笔记及其双链归入「知识图谱」，不在关联图谱全局视图里混排
    note_type_id = next((tid for tid, t in all_ets.items() if t.key == "note"), None)
    ets = {tid: t for tid, t in all_ets.items() if t.key != "note"}
    per_type = max(limit // max(len(ets), 1), 10)

    all_recs: list[EntityRecord] = []
    for type_id in ets:
        recs = await _record_ids_of_type(db, type_id, per_type)
        all_recs.extend(recs)
        if len(all_recs) >= limit:
            break
    all_recs = all_recs[:limit]
    for r in all_recs:
        col.node(_record_node(r, ets.get(r.entity_type_id)))

    # 过滤掉笔记双链：这些边属于知识图谱，关系名固定为 note_wikilink
    rows = [(rr, rd) for rr, rd in await _relation_rows_of(db)
            if rd.key != "note_wikilink"]
    rec_ids = {r.id for r in all_recs}

    # 边只在两端节点都在时才画，所以先把对端（记录/文件）补齐。
    # 已删除的文件补不进来 → 它的边自然不画，不会留下悬空节点。
    doc_ids: set[int] = set()
    want_recs: set[int] = set()
    for rr, _rd in rows:
        for did in (rr.source_document_id, rr.target_document_id):
            if did:
                doc_ids.add(did)
        for rid in (rr.source_record_id, rr.target_record_id):
            if rid and rid not in rec_ids:
                want_recs.add(rid)

    for doc in (await _load_documents(db, doc_ids)).values():
        col.node(_doc_node(doc))
    if want_recs:
        for rec in (await db.execute(
            select(EntityRecord).where(EntityRecord.id.in_(want_recs))
        )).scalars().all():
            # 对端也不应该是笔记：业务关联的「另一端」只能是业务记录或文件
            if note_type_id is not None and rec.entity_type_id == note_type_id:
                continue
            col.node(_record_node(rec, all_ets.get(rec.entity_type_id)))

    for rr, rd in rows:
        src = rid_node_id(rr.source_record_id) if rr.source_record_id else did_node_id(rr.source_document_id)
        tgt = rid_node_id(rr.target_record_id) if rr.target_record_id else did_node_id(rr.target_document_id)
        col.edge(f"rr-{rr.id}", src, tgt, rd.name, "relation")

    await _add_reference_edges(db, col, all_recs)
    if include_documents:
        await _add_attached_files(db, col, rec_ids)
    return col.out()


async def search_nodes(db: AsyncSession, keyword: str, limit: int = 20) -> dict:
    """图谱里的「搜索定位」：按名称找记录与文件，返回节点 id 供前端聚焦"""
    kw = (keyword or "").strip()
    if not kw:
        return {"items": []}
    like = f"%{kw}%"
    out = []
    ets = {t.id: t for t in (await db.execute(select(EntityType))).scalars().all()}

    recs = (await db.execute(
        select(EntityRecord).where(EntityRecord.search_text.like(like)).limit(limit)
    )).scalars().all()
    for r in recs:
        n = _record_node(r, ets.get(r.entity_type_id))
        out.append({"id": n["id"], "kind": "record", "ref_id": r.id, "type_id": n["type_id"],
                    "label": n["label"], "type_name": n["type_name"], "icon": n["icon"]})

    docs = (await db.execute(
        select(Document).where(
            Document.deleted_at.is_(None),
            Document.title.like(like) | Document.filename.like(like),
        ).limit(limit)
    )).scalars().all()
    for d in docs:
        n = _doc_node(d)
        out.append({"id": n["id"], "kind": "document", "ref_id": d.id, "type_id": None,
                    "label": n["label"], "type_name": n["type_name"], "icon": n["icon"]})
    return {"items": out[:limit * 2]}


async def get_stats(db: AsyncSession) -> dict:
    """全局统计：实体数、记录数、关联数、文件数（均不含回收站）"""
    type_count = (await db.execute(
        select(func.count(EntityType.id)).where(EntityType.deleted_at.is_(None))
    )).scalar() or 0
    rec_count = (await db.execute(
        select(func.count(EntityRecord.id)).where(EntityRecord.deleted_at.is_(None))
    )).scalar() or 0
    rel_count = (await db.execute(select(func.count(RelationRecord.id)))).scalar() or 0
    doc_count = (await db.execute(
        select(func.count(Document.id)).where(Document.deleted_at.is_(None))
    )).scalar() or 0

    app_q = (
        select(EntityType.app, func.count(EntityRecord.id))
        .join(EntityRecord, EntityRecord.entity_type_id == EntityType.id)
        .where(
            EntityType.deleted_at.is_(None),
            EntityRecord.deleted_at.is_(None),
        )
        .group_by(EntityType.app)
    )
    by_app = {app: count for app, count in (await db.execute(app_q)).all()}

    recent_q = (
        select(EntityRecord, EntityType)
        .join(EntityType, EntityType.id == EntityRecord.entity_type_id)
        .where(
            EntityType.deleted_at.is_(None),
            EntityRecord.deleted_at.is_(None),
        )
        .order_by(EntityRecord.updated_at.desc())
        .limit(10)
    )
    recent = []
    for r, t in (await db.execute(recent_q)).all():
        recent.append({
            "record_id": r.id,
            "entity_type_id": t.id,
            "entity_type_key": t.key,
            "entity_type_name": t.name,
            "entity_type_icon": t.icon,
            "data": r.data or {},
            "updated_at": r.updated_at,
        })

    return {
        "type_count": type_count,
        "record_count": rec_count,
        "relation_count": rel_count,
        "document_count": doc_count,
        "by_app": by_app,
        "recent": recent,
    }


async def get_notes_graph(db: AsyncSession, tag: str | None = None, limit: int = 300) -> dict:
    """笔记全局图谱：所有 Note 记录 + 双链"""
    et = (await db.execute(
        select(EntityType).where(EntityType.key == "note")
    )).scalar_one_or_none()
    if not et:
        return {"nodes": [], "edges": [], "truncated": False}

    records = (await db.execute(
        select(EntityRecord).where(EntityRecord.entity_type_id == et.id)
        .order_by(EntityRecord.updated_at.desc()).limit(limit)
    )).scalars().all()

    col = _Collector(limit=limit + 50)
    rec_ids = set()
    for r in records:
        if tag:
            tags = r.data.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if tag not in tags:
                continue
        node = _record_node(r, et)
        node["type_name"] = "笔记"
        node["icon"] = "📝"
        node["tags"] = list(r.data.get("tags") or [])
        col.node(node)
        rec_ids.add(r.id)

    if rec_ids:
        rows = (await db.execute(
            select(RelationRecord, RelationDef)
            .join(RelationDef, RelationDef.id == RelationRecord.relation_def_id)
            .where(
                RelationRecord.source_record_id.in_(rec_ids),
                RelationRecord.target_record_id.in_(rec_ids),
                RelationDef.key == "note_wikilink",
            )
        )).all()
        for rr, rd in rows:
            col.edge(f"rr-{rr.id}", rid_node_id(rr.source_record_id),
                     rid_node_id(rr.target_record_id), rd.name, "wikilink")

    data = col.out()
    # 笔记图谱默认只画双链，reference 字段（父笔记）单独标注成另一种边更清晰
    return data
