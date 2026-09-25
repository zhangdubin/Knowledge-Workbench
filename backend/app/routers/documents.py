"""文档路由：原文外置到文件系统，库内只留元数据

注意路由顺序：/search、/stats、/tags 这类静态路径必须声明在 /{doc_id} 之前，
否则会被当成 id 参数吞掉。
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..config import settings
from ..database import get_db
from ..models import Document, DocumentChunk
from ..services import audit as audit_svc
from ..services import document as svc
from ..services import embedding as embed_svc
from ..services import filepreview as fp
from ..services.auth import require_feature

router = APIRouter(prefix="/api/documents", tags=["documents"])

# 文件的写/删是跨模型的功能位权限：文件不属于任何业务模型，
# 用不到模型级权限，但「能不能删」必须能单独授权。
_WRITE = [Depends(require_feature("file_write"))]
_DELETE = [Depends(require_feature("file_delete"))]


# ---------- 入参模型 ----------

class UpdateIn(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    summary: str | None = None
    description: str | None = None
    app: str | None = None


class LinkIn(BaseModel):
    record_id: int
    field_key: str | None = None
    note: str = ""


class AskIn(BaseModel):
    question: str


class ReindexIn(BaseModel):
    embed: bool = True


# ---------- 静态路径（必须在 /{doc_id} 之前） ----------

@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    data = await svc.stats(db)
    data["vector"] = embed_svc.config_summary()
    data["storage"] = "sqlite-blob"
    return data


@router.get("/tags")
async def tags(db: AsyncSession = Depends(get_db)):
    return {"items": await svc.all_tags(db)}


@router.get("/search")
async def search(
    q: str = Query("", description="检索词"),
    limit: int = Query(20, ge=1, le=100),
    mode: str = Query("hybrid", pattern="^(hybrid|keyword|semantic)$"),
    db: AsyncSession = Depends(get_db),
):
    """混合检索：FTS5 关键词 + 向量语义（RRF 融合）"""
    return await svc.search_documents(db, q, limit=limit, mode=mode)


@router.post("/upload", dependencies=_WRITE)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    tags: str = Form(""),          # 逗号分隔
    description: str = Form(""),
    app: str = Form("default"),
    record_id: int | None = Form(None),
    field_key: str | None = Form(None),
    embed: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """上传文件 —— 直接写入文件存储，不需要先创建任何记录"""
    # 上传体是整块读进内存的（抽取正文也需要完整字节），所以必须先卡上限。
    # 不设上限等于把进程内存的支配权交给上传方：一个 8GB 的请求就能打爆容器。
    limit_mb = settings.upload_max_mb
    if limit_mb:
        declared = request.headers.get("content-length")
        if declared and int(declared) > limit_mb * 1024 * 1024:
            raise HTTPException(
                413, f"文件超过上限 {limit_mb}MB（可在 KB_UPLOAD_MAX_MB 调整）"
            )
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    if limit_mb and len(data) > limit_mb * 1024 * 1024:
        raise HTTPException(
            413, f"文件 {len(data) / 1048576:.1f}MB 超过上限 {limit_mb}MB"
        )

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    out = await svc.create_document(
        db,
        data=data,
        filename=file.filename or "file",
        title=title,
        tags=tag_list,
        mime=file.content_type or "",
        source="upload",
        app=app or "default",
        description=description,
        record_id=record_id,
        field_key=field_key or None,
        do_embed=embed,
    )
    if isinstance(out, dict) and out.get("id"):
        audit_svc.mark_created(request, out["id"])
    return out


@router.get("")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=500),
    keyword: str = "",
    kind: str = "",
    tag: str = "",
    record_id: int | None = None,
    embed_status: str = "",
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_documents(
        db, page=page, page_size=page_size, keyword=keyword, kind=kind,
        tag=tag, record_id=record_id, embed_status=embed_status,
        include_deleted=include_deleted,
    )


# ---------- 单个文档 ----------

async def _need(db: AsyncSession, doc_id: int, *, include_deleted: bool = False,
                with_data: bool = False):
    if include_deleted:
        # 回收站里的文件也要能被查到（彻底删除 / 恢复都需要）；
        # 这两种操作都不碰原文 BLOB，故 defer 掉，避免把大文件读进内存
        opts = [] if with_data else [defer(Document.data)]
        doc = await db.get(Document, doc_id, options=opts)
    else:
        doc = await svc.get_document(db, doc_id, with_data=with_data)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return doc


@router.get("/{doc_id}")
async def detail(doc_id: int, with_text: bool = False,
                 db: AsyncSession = Depends(get_db)):
    doc = await _need(db, doc_id)
    out = svc.serialize(doc, with_text=with_text,
                        links=await svc._links_of(db, doc_id))
    out["chunk_count"] = (await db.execute(
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == doc_id)
    )).scalar() or 0
    return out


@router.get("/{doc_id}/meta")
async def meta(doc_id: int, db: AsyncSession = Depends(get_db)):
    """该文件的结构化元数据（JSON 文本 + 节点树）

    单独开接口而不是塞进列表：列表要一次返回几百条，
    内联元数据树会让响应膨胀近 1MB，而用户只会展开其中一两个。
    """
    doc = await _need(db, doc_id)
    return svc.meta(doc, links=await svc._links_of(db, doc_id))


@router.get("/{doc_id}/raw")
async def raw(doc_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """内联预览：外置文件走流式（支持 Range），库内 BLOB 直接回字节"""
    doc = await _need(db, doc_id, with_data=True)
    try:
        return svc.file_response(doc, inline=True,
                                 range_header=request.headers.get("range"))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/{doc_id}/download")
async def download(doc_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    doc = await _need(db, doc_id, with_data=True)
    try:
        return svc.file_response(doc, inline=False,
                                 range_header=request.headers.get("range"))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/{doc_id}/content")
async def content(doc_id: int, full: bool = True, db: AsyncSession = Depends(get_db)):
    """抽取出的可渲染结构（docx/xlsx/pptx/csv/文本）"""
    doc = await _need(db, doc_id, with_data=True)
    mime = fp.resolve_mime(doc.filename, doc.mime)
    try:
        parsed = fp.extract_bytes(svc.load_bytes(doc), doc.filename)
    except FileNotFoundError as e:
        return {"ok": False, "kind": None, "filename": doc.filename,
                "mode": fp.preview_mode(doc.filename, mime),
                "error": f"文件内容缺失：{e}"}
    except Exception as e:
        return {"ok": False, "kind": None, "filename": doc.filename,
                "mode": fp.preview_mode(doc.filename, mime),
                "error": f"{type(e).__name__}: {e}"}
    if parsed is None:
        return {"ok": False, "kind": None, "filename": doc.filename,
                "mode": fp.preview_mode(doc.filename, mime),
                "error": "该格式暂不支持内容抽取"}
    return {"ok": True, "filename": doc.filename, "content_type": mime,
            "mode": fp.preview_mode(doc.filename, mime), **parsed}


@router.patch("/{doc_id}", dependencies=_WRITE)
async def update(doc_id: int, payload: UpdateIn, db: AsyncSession = Depends(get_db)):
    doc = await _need(db, doc_id)
    return await svc.update_document(db, doc, **payload.model_dump(exclude_none=True))


@router.delete("/{doc_id}", dependencies=_DELETE)
async def remove(doc_id: int, hard: bool = False, db: AsyncSession = Depends(get_db)):
    # 软删除时文件一定还在库里；彻底删除通常发生在回收站里，
    # 此时它已经是软删除状态，必须把 include_deleted 打开才找得到。
    doc = await _need(db, doc_id, include_deleted=hard)
    await svc.delete_document(db, doc, hard=hard)
    return {"ok": True, "hard": hard}


@router.post("/{doc_id}/restore", dependencies=_DELETE)
async def restore(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id, options=[defer(Document.data)])
    if not doc:
        raise HTTPException(404, "文档不存在")
    return await svc.restore_document(db, doc)


@router.post("/{doc_id}/reindex", dependencies=_WRITE)
async def reindex(doc_id: int, payload: ReindexIn | None = None,
                  db: AsyncSession = Depends(get_db)):
    doc = await _need(db, doc_id, with_data=True)
    do_embed = payload.embed if payload else True
    return await svc.reindex_document(db, doc, do_embed=do_embed)


@router.post("/{doc_id}/link", dependencies=_WRITE)
async def link(doc_id: int, payload: LinkIn, db: AsyncSession = Depends(get_db)):
    await _need(db, doc_id)
    return await svc.link_document(
        db, doc_id, payload.record_id, payload.field_key, payload.note
    )


@router.delete("/{doc_id}/link/{link_id}", dependencies=_WRITE)
async def unlink(doc_id: int, link_id: int, db: AsyncSession = Depends(get_db)):
    ok = await svc.unlink_document(db, doc_id, link_id)
    if not ok:
        raise HTTPException(404, "关联不存在")
    return {"ok": True}


@router.post("/{doc_id}/resummarize", dependencies=_WRITE)
async def resummarize(doc_id: int, db: AsyncSession = Depends(get_db)):
    """用 LLM 重新生成摘要"""
    from ..services import ai as ai_svc
    doc = await _need(db, doc_id)
    body = (doc.extracted_text or "").strip()
    if not body:
        raise HTTPException(400, "该文件没有可摘要的正文（可能是图片或扫描件）")
    summary = await ai_svc.summarize(body[:6000])
    doc.summary = (summary or "")[:2000]
    await db.commit()
    await db.refresh(doc)
    return svc.serialize(doc)


@router.post("/{doc_id}/ask")
async def ask_document(doc_id: int, payload: AskIn, db: AsyncSession = Depends(get_db)):
    """针对单个文件提问"""
    from ..services import ai as ai_svc
    doc = await _need(db, doc_id)
    body = (doc.extracted_text or "").strip()
    if not body:
        raise HTTPException(400, "该文件没有可检索的正文")
    answer = await ai_svc.ask(
        payload.question, [f"【文件：{doc.title}】\n{body[:6000]}"]
    )
    return {"answer": answer, "document_id": doc.id, "title": doc.title}
