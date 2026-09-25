"""附件路由（兼容层）—— URL 不变，底层改为读外置文件（或库内 BLOB）

为什么保留这套 URL：历史记录 JSON 里存着 `/api/attachments/N/preview`
这样的绝对路径，改路径会让老数据的附件全部失效。
详情见 services/attachment.py 顶部说明。
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..database import get_db
from ..models import Document, DocumentLink, EntityRecord, EntityType
from ..services import attachment as svc
from ..services import document as doc_svc
from ..services import filepreview as fp
from ..services import jsontree as json_svc
from ..services.auth import require_feature

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

_WRITE = [Depends(require_feature("file_write"))]
_DELETE = [Depends(require_feature("file_delete"))]


def _serialize(doc: Document, record_id: int | None = None,
               field_key: str | None = None) -> dict:
    """保持 v0.1 的出参字段名（前端与历史数据都依赖）"""
    mime = fp.resolve_mime(doc.filename, doc.mime)
    return {
        "id": doc.id,
        "record_id": record_id,
        "field_key": field_key,
        "filename": doc.filename,
        "title": doc.title,
        "size": doc.size,
        "content_type": mime,
        "stored_content_type": doc.mime,
        "mode": fp.preview_mode(doc.filename, mime),
        "kind": doc.kind,
        # 指向新接口，前端优先用这两个字段
        "url": f"/api/documents/{doc.id}/download",
        "preview_url": f"/api/documents/{doc.id}/raw",
        "extract_url": f"/api/documents/{doc.id}/content",
        "extract_status": doc.extract_status,
        "embed_status": doc.embed_status,
        "tags": doc.tags or [],
        "summary": doc.summary or "",
        "sha256": doc.sha256,
        "storage": doc.storage or "db",
        "created_at": doc.created_at,
    }


async def _link_of(db: AsyncSession, doc_id: int) -> tuple[int | None, str | None]:
    row = (await db.execute(
        select(DocumentLink.record_id, DocumentLink.field_key)
        .where(DocumentLink.document_id == doc_id).limit(1)
    )).first()
    return (row[0], row[1]) if row else (None, None)


@router.post("/upload", dependencies=_WRITE)
async def upload(
    record_id: int = Form(...),
    field_key: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    doc = await svc.save_attachment(db, record_id, field_key, file)
    return _serialize(doc, record_id, field_key)


@router.get("/{att_id}/download")
async def download(att_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    doc = await svc.get_attachment(db, att_id)
    if not doc:
        raise HTTPException(404, "附件不存在")
    try:
        return doc_svc.file_response(doc, inline=False,
                                     range_header=request.headers.get("range"))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/{att_id}/preview")
async def preview(att_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """内联预览：Content-Disposition=inline

    PDF / 图片 / 音视频能在 iframe、<img>、<video> 中直接渲染的关键。
    此前走 /download 收到 attachment 头，浏览器只会下载。
    """
    doc = await svc.get_attachment(db, att_id)
    if not doc:
        raise HTTPException(404, "附件不存在")
    try:
        return doc_svc.file_response(doc, inline=True,
                                     range_header=request.headers.get("range"))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/{att_id}/extract")
async def extract(att_id: int, db: AsyncSession = Depends(get_db)):
    """服务端抽取文档内容（docx / xlsx / pptx / csv / 文本）"""
    doc = await svc.get_attachment(db, att_id)
    if not doc:
        raise HTTPException(404, "附件不存在")
    mime = fp.resolve_mime(doc.filename, doc.mime)
    try:
        parsed = fp.extract_bytes(doc_svc.load_bytes(doc), doc.filename)
    except FileNotFoundError as e:
        return {"ok": False, "kind": None, "mode": fp.preview_mode(doc.filename, mime),
                "filename": doc.filename, "error": f"文件内容缺失：{e}"}
    except Exception as e:
        return {"ok": False, "kind": None, "mode": fp.preview_mode(doc.filename, mime),
                "filename": doc.filename, "error": f"{type(e).__name__}: {e}"}
    if parsed is None:
        return {"ok": False, "kind": None, "mode": fp.preview_mode(doc.filename, mime),
                "filename": doc.filename, "error": "该格式暂不支持内容抽取"}
    return {"ok": True, "filename": doc.filename, "content_type": mime,
            "mode": fp.preview_mode(doc.filename, mime), **parsed}


@router.get("/for-record/{record_id}")
async def list_for_record(
    record_id: int, field_key: str | None = None, db: AsyncSession = Depends(get_db)
):
    docs = await svc.list_attachments(db, record_id, field_key)
    out = []
    for d in docs:
        rid, fk = await _link_of(db, d.id)
        out.append(_serialize(d, rid, fk))
    return out


@router.delete("/{att_id}", dependencies=_DELETE)
async def delete(att_id: int, db: AsyncSession = Depends(get_db)):
    ok = await svc.delete_attachment(db, att_id)
    if not ok:
        raise HTTPException(404, "附件不存在")
    return {"ok": True}


def _tree_of(json_text: str) -> list[dict]:
    """JSON 文本 → 节点树，供前端直接渲染（失败也不能拖垮整个列表）"""
    try:
        return json_svc.to_tree(json_svc.parse(json_text))
    except Exception:
        return []


@router.get("/all")
async def list_all(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """列出所有附件（数据中心旧入口，保留以兼容）"""
    total = (await db.execute(
        select(func.count(Document.id)).where(Document.deleted_at.is_(None))
    )).scalar() or 0

    q = (
        select(Document, DocumentLink.record_id, DocumentLink.field_key)
        .join(DocumentLink, DocumentLink.document_id == Document.id, isouter=True)
        .where(Document.deleted_at.is_(None))
        .options(defer(Document.data))          # 列表不拉 BLOB
        .order_by(Document.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    rows = (await db.execute(q)).all()

    items = []
    for doc, rid, fk in rows:
        rec = await db.get(EntityRecord, rid) if rid else None
        et = await db.get(EntityType, rec.entity_type_id) if rec else None
        label = ""
        if rec:
            d = rec.data or {}
            label = d.get("name") or d.get("title") or d.get("code") or f"#{rec.id}"

        # 元数据与 /api/documents/{id}/meta 共用同一套生成逻辑，
        # 关联信息也按同一种形状喂进去，两个入口的 JSON 完全一致。
        links = ([{
            "record_id": rid,
            "field_key": fk,
            "record_label": label,
            "entity_type_key": et.key if et else None,
        }] if rid else [])
        json_text = doc_svc.meta_json(doc, links=links)
        json_tree = _tree_of(json_text)

        items.append({
            **_serialize(doc, rid, fk),
            "record_entity": et.key if et else "",
            "record_entity_name": et.name if et else "",
            "record_label": label,
            "json_text": json_text,
            "json_tree": json_tree,
        })

    counts = await doc_svc.stats(db)
    return {
        "items": items,
        "total": total,
        "counts": {
            "totalFiles": counts["total"],
            "images": counts["image"],
            "docs": counts["doc"],
            "totalSize": counts["totalSize"],
        },
    }
