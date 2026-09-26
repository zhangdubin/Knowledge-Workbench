"""文档服务：文件原文外置存储 + 正文抽取 + 索引维护 + 混合检索

与 v0.1 附件服务的根本差别：
  - 文件二进制外置到文件系统（内容寻址、去重、原子写），库里只留 path
  - 文件与业务记录解耦（document_link.record_id 可空），
    数据中心上传文件不必再伪造一条笔记当容器
  - 上传即抽取正文 → 建 FTS5 索引 → 向量化，AI 可直接检索到文件内容
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..config import settings
from ..models import (
    Document,
    DocumentChunk,
    DocumentLink,
    EntityRecord,
    EntityType,
)
from . import docindex
from . import embedding as embed_svc
from . import filepreview as fp
from . import filestore
from . import jsontree as json_svc

log = logging.getLogger("kb.doc")


# ---------- 原文读写 ----------

def load_bytes(doc: Document) -> bytes:
    """按文档记录的归属读出原文（外置读盘 / 内置读列）

    这是全后端唯一应该直接碰原文的地方：迁移期间两种存储共存，
    散落各处的 `doc.data` 一定会漏掉某一侧。
    """
    return filestore.load(storage=doc.storage, path=doc.path, data=doc.data)


def store_bytes(data: bytes, *, sha: str, ext: str) -> tuple[str, str]:
    """落盘并返回 (storage, path)

    file_store=db 时返回 ('db', '')，调用方据此决定写不写 data 列 ——
    保留这条分支是为了出问题时能一键退回旧形态，不必改代码。
    """
    if not filestore.enabled():
        return filestore.MODE_DB, ""
    rel = filestore.put(data, sha, ext)
    filestore.invalidate_usage()
    return filestore.MODE_FS, rel


async def _file_bytes_or_empty(doc: Document) -> bytes:
    """读原文，文件缺失时返回空而不是抛错

    抽取/重建索引这类增强环节不该因为文件丢了就把整个请求打断：
    抽取失败会被记进 extract_status，用户能在界面上看见原因。
    """
    try:
        return load_bytes(doc)
    except FileNotFoundError as e:
        log.error("文档 %s 原文缺失：%s", doc.id, e)
        return b""


def file_headers(doc: Document, *, inline: bool) -> dict:
    """Content-Disposition 必须做 RFC 5987 编码，否则中文名会让 header 非法

    inline 用于预览（PDF/图片才能在 iframe 里渲染），attachment 用于下载。
    v0.1 的 bug 就在于全部走 attachment，导致所有文件都被强制下载。
    """
    from urllib.parse import quote
    disp = "inline" if inline else "attachment"
    return {
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(doc.filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=600",
    }


def _parse_range(value: str, size: int):
    """解析 `Range: bytes=start-end`

    返回 (start, end)，或 None 表示无法满足（应回 416）。
    只支持单段 range —— 多段（`bytes=0-99,200-299`）需要 multipart/byteranges，
    浏览器实际只会对同一资源发单段请求，为它引入 multipart 编码不值得。
    """
    v = (value or "").strip().lower()
    if not v.startswith("bytes="):
        return None
    spec = v[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    head, tail = spec.split("-", 1)
    try:
        if head == "":
            # bytes=-500 → 末尾 500 字节
            n = int(tail)
            if n <= 0:
                return None
            start = max(0, size - n)
            end = size - 1
        else:
            start = int(head)
            end = int(tail) if tail else size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        return None
    return start, min(end, size - 1)


def _file_response(path, *, mime: str, headers: dict, size: int,
                   range_header: str | None):
    """发文件：支持 Range 的流式响应

    为什么要自己实现 Range 而不是用 Starlette 的 FileResponse：
    当前锁定的 Starlette 0.38 的 FileResponse **不支持 Range**，实测
    `Range: bytes=0-1023` 会返回 200 + 整个文件。后果很实际：
      - 视频/音频拖动进度条会先整份下载完才动
      - 大 PDF 在 iframe 里要等全文传完才渲染第一页
      - 下载中断只能从头再来
    所以这里自己发 206 + Content-Range，读文件也用分片生成器，
    超大文件的切片不会整块进内存。
    """
    from fastapi.responses import StreamingResponse

    base = {**headers, "Accept-Ranges": "bytes"}

    if not range_header:
        return StreamingResponse(_iter_file(path, 0, size - 1),
                                 media_type=mime, headers=base)

    rng = _parse_range(range_header, size)
    if rng is None:
        # 416 必须带 Content-Range 告诉客户端实际长度，否则客户端无法重试
        return StreamingResponse(
            iter(()), status_code=416,
            headers={**base, "Content-Range": f"bytes */{size}"},
        )
    start, end = rng
    return StreamingResponse(
        _iter_file(path, start, end), status_code=206, media_type=mime,
        headers={**base,
                 "Content-Range": f"bytes {start}-{end}/{size}",
                 "Content-Length": str(end - start + 1)},
    )


_FILE_CHUNK = 256 * 1024


def _iter_file(path, start: int, end: int):
    """按 256KB 分片读文件，避免大文件整块进内存"""
    remaining = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            data = f.read(min(_FILE_CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def file_response(doc: Document, *, inline: bool, range_header: str | None = None):
    """把原文发出去：外置走流式（支持 Range），库内 BLOB 直接回字节

    外置文件的两个实质收益：
      1. 支持 Range —— 视频可拖动、大 PDF 边下边看、断点续传
      2. 分片流式发送 —— 不经过「整块进内存」，并发下载大文件不会打爆进程
    """
    from fastapi.responses import Response

    mime = fp.resolve_mime(doc.filename, doc.mime)
    headers = file_headers(doc, inline=inline)

    if doc.storage == filestore.MODE_FS and doc.path:
        p = filestore.abs_path(doc.path)
        if not p.is_file():
            log.error("文档 %s 原文文件缺失：%s", doc.id, doc.path)
            raise FileNotFoundError(f"文件内容缺失：{doc.path}")
        return _file_response(p, mime=mime, headers=headers,
                              size=p.stat().st_size, range_header=range_header)

    if doc.data is None:
        raise FileNotFoundError("文件内容缺失")
    headers = {**headers, "Accept-Ranges": "bytes"}
    return Response(content=doc.data, media_type=mime, headers=headers)



# ---------- 分块 ----------

def build_chunks(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """把正文切成检索用的块，优先在段落边界断开"""
    size = size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    text = (text or "").strip()
    if not text:
        return []

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf)
            buf = ""

    for p in paras:
        if len(p) <= size:
            merged = f"{buf}\n{p}".strip() if buf else p
            if len(merged) <= size:
                buf = merged
            else:
                flush()
                buf = p
        else:
            flush()
            step = max(1, size - overlap)
            for start in range(0, len(p), step):
                piece = p[start:start + size].strip()
                if piece:
                    chunks.append(piece)
                if start + size >= len(p):
                    break
    flush()
    # 过滤掉过短的碎片（纯符号/页码等噪声）
    return [c for c in chunks if len(c) >= 12]


# ---------- 序列化 ----------

def serialize(doc: Document, *, with_text: bool = False,
              links: list[dict] | None = None) -> dict:
    mime = fp.resolve_mime(doc.filename, doc.mime)
    out = {
        "id": doc.id,
        "title": doc.title or doc.filename,
        "filename": doc.filename,
        "ext": doc.ext,
        "mime": mime,
        "size": doc.size,
        "kind": doc.kind,
        "sha256": doc.sha256,
        "storage": doc.storage or "db",
        "tags": doc.tags or [],
        "summary": doc.summary or "",
        "description": doc.description or "",
        "source": doc.source,
        "app": doc.app,
        "mode": fp.preview_mode(doc.filename, mime),
        "extract_status": doc.extract_status,
        "extract_error": doc.extract_error or "",
        "extract_kind": doc.extract_kind or "",
        "extract_chars": len(doc.extracted_text or ""),
        "embed_status": doc.embed_status,
        "embed_error": doc.embed_error or "",
        "embed_dim": doc.embed_dim or 0,
        "chunk_count": 0,
        "indexed_at": doc.indexed_at,
        "deleted_at": doc.deleted_at,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "url": f"/api/documents/{doc.id}/download",
        "preview_url": f"/api/documents/{doc.id}/raw",
        "extract_url": f"/api/documents/{doc.id}/content",
    }
    if with_text:
        out["extracted_text"] = doc.extracted_text or ""
    if links is not None:
        out["links"] = links
    return out


async def _links_of(db: AsyncSession, doc_id: int) -> list[dict]:
    q = (
        select(DocumentLink, EntityRecord, EntityType)
        .join(EntityRecord, EntityRecord.id == DocumentLink.record_id, isouter=True)
        .join(EntityType, EntityType.id == EntityRecord.entity_type_id, isouter=True)
        .where(DocumentLink.document_id == doc_id)
    )
    rows = (await db.execute(q)).all()
    out = []
    for link, rec, et in rows:
        label = ""
        if rec:
            d = rec.data or {}
            label = d.get("name") or d.get("title") or d.get("code") or f"#{rec.id}"
        out.append({
            "link_id": link.id,
            "record_id": link.record_id,
            "field_key": link.field_key,
            "record_label": label,
            "entity_type_id": et.id if et else None,
            "entity_type_key": et.key if et else None,
            "entity_type_name": et.name if et else None,
            "entity_type_icon": et.icon if et else None,
        })
    return out


# ---------- 结构化元数据（JSON） ----------

def _meta_link(link: dict) -> dict:
    """元数据里的「关联记录」节点：只保留有值的字段，避免一堆 null"""
    obj: dict = {"record_id": link.get("record_id"), "field_key": link.get("field_key")}
    if link.get("record_label"):
        obj["record_label"] = link["record_label"]
    if link.get("entity_type_key"):
        obj["entity_type"] = link["entity_type_key"]
    return obj


def _stamp(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def meta_json(doc: Document, *, links: list[dict] | None = None) -> str:
    """文件的结构化元数据（标准 JSON 文本）

    用 JSON 而不是自定义语法：大模型能直接读懂、能原样喂给下游工具，
    前端也能用同一套 JSON 树组件渲染，不需要额外写解析器。
    根键叫 attachment 是为了和历史附件语义对齐（详情页、试验场样例都用这个词）。
    """
    return json_svc.dumps({
        "attachment": {
            "id": doc.id,
            "title": doc.title or doc.filename,
            "filename": doc.filename,
            "ext": doc.ext or "",
            "kind": doc.kind or "other",
            "mime": fp.resolve_mime(doc.filename, doc.mime),
            "size": doc.size or 0,
            "storage": "sqlite-blob",
            "sha256": doc.sha256 or "",
            "tags": list(doc.tags or []),
            "summary": doc.summary or "",
            "description": doc.description or "",
            "text_length": len(doc.extracted_text or ""),
            "extract_status": doc.extract_status or "pending",
            "embed_status": doc.embed_status or "pending",
            "uploaded_at": _stamp(doc.created_at),
            "links": [_meta_link(link) for link in (links or [])],
            "download_url": f"/api/documents/{doc.id}/download",
        }
    })


def meta(doc: Document, *, links: list[dict] | None = None) -> dict:
    """一次拿到元数据的文本 + 节点树（前端展开某个文件时按需取用）

    列表接口不内联元数据：500 个文件的节点树会让响应白白膨胀近 1MB，
    展开哪个拉哪个更划算。
    """
    text = meta_json(doc, links=links)
    try:
        tree = json_svc.to_tree(json_svc.parse(text))
    except Exception:  # 理论上不会发生；真出问题也不能让接口整体 500
        tree = []
    return {"json_text": text, "json_tree": tree}


# ---------- 写入 ----------

async def create_document(
    db: AsyncSession,
    *,
    data: bytes,
    filename: str,
    title: str = "",
    tags: list | None = None,
    mime: str = "",
    source: str = "upload",
    app: str = "default",
    description: str = "",
    record_id: int | None = None,
    field_key: str | None = None,
    do_embed: bool = True,
) -> dict:
    """新建文档：落盘 → 入库 → 抽取 → 建 FTS → 分块 → 向量化

    任何一步增强环节失败都不会让上传失败 —— 文件本身一定存得进去。
    """
    safe_name = Path(filename or "file").name
    resolved_mime = fp.resolve_mime(safe_name, mime)
    ext = Path(safe_name).suffix.lower()
    digest = hashlib.sha256(data).hexdigest()

    # 同一内容是否已存在（不合并，只提示，避免删除时互相牵连）
    dup = (await db.execute(
        select(Document.id).where(
            Document.sha256 == digest, Document.deleted_at.is_(None)
        ).limit(1)
    )).scalar()

    # 先落盘再入库：反过来会出现「元数据已提交、文件没写成」的孤儿记录，
    # 而落盘是内容寻址的幂等操作，重传同一份文件零成本
    storage, rel = store_bytes(data, sha=digest, ext=ext)

    doc = Document(
        title=(title or "").strip() or safe_name,
        filename=safe_name,
        ext=ext,
        mime=resolved_mime,
        size=len(data),
        sha256=digest,
        storage=storage,
        path=rel,
        data=data if storage == filestore.MODE_DB else None,
        kind=fp.doc_kind(safe_name, resolved_mime),
        tags=list(tags or []),
        source=source,
        app=app,
        description=description,
        extract_status="pending",
        embed_status="pending",
    )
    db.add(doc)
    await db.flush()

    # 正文抽取（同步，快）
    text_body = ""
    try:
        text_body = fp.plain_text(data, safe_name)
        if text_body:
            doc.extracted_text = text_body[:400_000]
            doc.extract_status = "ok"
            doc.extract_kind = _guess_extract_kind(safe_name, resolved_mime)
        else:
            doc.extract_status = "skipped"
            doc.extract_kind = ""
    except Exception as e:
        doc.extract_status = "failed"
        doc.extract_error = f"{type(e).__name__}: {e}"[:500]

    # FTS 索引
    await docindex.index_document(
        db, doc.id, doc.title, safe_name, doc.tags, "", doc.extracted_text or ""
    )

    await db.commit()
    await db.refresh(doc)

    if record_id:
        await link_document(db, doc.id, record_id, field_key)

    embed_ok = None
    if do_embed and (doc.extracted_text or "").strip():
        embed_ok = await embed_document(db, doc)

    # updated_at 是 onupdate=func.now()（服务端表达式）。embed_document 提交过 UPDATE，
    # SQLAlchemy 会把该列标记为过期以便回读库里的新值；若此时直接 serialize，
    # 访问 doc.updated_at 会在 greenlet 之外触发懒加载 → MissingGreenlet。
    # 统一在序列化之前 refresh，与 reindex/update/restore 保持一致。
    await db.refresh(doc)

    result = serialize(doc)
    result["chunk_count"] = (await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc.id)
    )).scalar() or 0
    result["duplicate_of"] = dup if dup and dup != doc.id else None
    result["embed_ok"] = embed_ok
    result["warning"] = _size_warning(len(data))
    return result


def _guess_extract_kind(filename: str, mime: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in fp.OFFICE_EXTS:
        return ext.lstrip(".")
    if ext == ".pdf":
        return "pdf"
    if ext in (".csv", ".tsv"):
        return "csv"
    if ext in fp.TEXT_EXTS or (mime or "").startswith("text/"):
        return "text"
    return ""


def _size_warning(size: int) -> str:
    limit = settings.large_file_warn_mb
    if limit and size > limit * 1024 * 1024:
        if filestore.enabled():
            return (f"该文件 {size / 1024 / 1024:.1f}MB，超过 {limit}MB 提示阈值。"
                    "原文已存到文件目录；下载走流式发送不占内存，"
                    "但正文抽取仍需整块读入，大文件较多时请关注容器内存。")
        return (f"该文件 {size / 1024 / 1024:.1f}MB，超过 {limit}MB 提示阈值。"
                "文件已存入数据库；SQLite 读取 BLOB 会整块进内存，"
                "大文件较多时建议关注容器内存。")
    return ""


# ---------- 向量化 ----------

async def embed_document(db: AsyncSession, doc: Document) -> bool:
    """对文档正文分块并向量化；失败时标记但不影响文件可用性"""
    text_body = doc.extracted_text or ""
    if not text_body.strip():
        doc.embed_status = "skipped"
        doc.embed_error = "无可索引正文"
        await db.commit()
        return False

    chunks = build_chunks(text_body)
    if not chunks:
        doc.embed_status = "skipped"
        doc.embed_error = "正文过短，无需向量化"
        await db.commit()
        return False

    # 重建分块（幂等：重跑不会累积）
    existing = (await db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )).scalars().all()
    old_ids = [c.id for c in existing]
    if old_ids:
        await _delete_vectors(db, old_ids)
    for c in existing:
        await db.delete(c)
    await db.flush()

    rows = []
    for i, chunk in enumerate(chunks):
        row = DocumentChunk(document_id=doc.id, seq=i, text=chunk, char_len=len(chunk))
        db.add(row)
        rows.append(row)
    await db.flush()
    chunk_ids = [r.id for r in rows]

    vectors = await embed_svc.embed_texts(chunks, kind="db")
    if not vectors or len(vectors) != len(chunks):
        doc.embed_status = "failed"
        doc.embed_error = "向量化接口未返回结果（额度/网络/模型不支持）"
        doc.indexed_at = datetime.utcnow()
        await db.commit()
        return False

    dim = len(vectors[0])

    # 维度首次确定 / 发生变化时，确保向量表匹配
    await docindex.ensure_vec_table(db, dim)
    doc.embed_dim = dim
    await db.execute(
        text("insert into sys_meta(key, value, updated_at) values (:k, :v, datetime('now')) "
             "on conflict(key) do update set value=:v, updated_at=datetime('now')"),
        {"k": docindex.META_EMBED_MODEL, "v": embed_svc.get_embed_config()["model"]},
    )

    # 记下「真正写进去的是哪几块」，而不是写进去几块。
    # 早先用 chunk_ids[:ok] 假定成功的一定是前 ok 个，中间某块失败时
    # 标记就会整体错位：没进库的分块被标成已嵌入，向量检索反而漏掉真正入库的。
    stored: list[int] = []
    for cid, vec in zip(chunk_ids, vectors):
        try:
            import sqlite_vec
            await db.execute(
                text(f"insert into {docindex.VEC_TABLE}(rowid, embedding) values (:r, :e)"),
                {"r": cid, "e": sqlite_vec.serialize_float32(vec)},
            )
            stored.append(cid)
        except Exception as e:
            log.warning("向量写入失败 chunk=%s：%s", cid, e)

    if not stored:
        doc.embed_status = "failed"
        doc.embed_error = "向量表写入失败"
        await db.commit()
        return False

    await db.execute(
        text("update document_chunk set embedded = 1 where id in "
             f"({','.join(str(i) for i in stored)})")
    )
    ok = len(stored)
    doc.embed_status = "ok" if ok == len(chunks) else "partial"
    doc.embed_error = "" if ok == len(chunks) else f"{len(chunks) - ok} 块未入库"
    doc.indexed_at = datetime.utcnow()
    await db.commit()

    # 向量化成功顺带用 LLM 生成摘要（失败忽略）
    if not (doc.summary or "").strip():
        try:
            from . import ai as ai_svc
            doc.summary = (await ai_svc.summarize(text_body[:3000]))[:1000]
            await db.commit()
        except Exception:
            pass
    return True


async def _delete_vectors(db: AsyncSession, chunk_ids: list[int]) -> None:
    for cid in chunk_ids:
        try:
            await db.execute(
                text(f"delete from {docindex.VEC_TABLE} where rowid = :r"), {"r": cid}
            )
        except Exception:
            pass


async def reindex_document(db: AsyncSession, doc: Document, *, do_embed: bool = True) -> dict:
    """重新抽取 + 重建全文/向量索引

    注意 remove_document 会「FTS 与向量一起删」，所以只在确实要重新向量化时
    才对向量动手：do_embed=False 时若照删不误，分块会退化成「标记着已嵌入、
    向量却已没了」的假状态，语义检索从此静默漏检且无从察觉。
    """
    try:
        doc.extracted_text = fp.plain_text(await _file_bytes_or_empty(doc), doc.filename)[:400_000]
        doc.extract_status = "ok" if doc.extracted_text else "skipped"
        doc.extract_error = ""
    except Exception as e:
        doc.extract_status = "failed"
        doc.extract_error = f"{type(e).__name__}: {e}"[:500]

    if do_embed:
        await docindex.remove_document(db, doc.id)
    else:
        # 只重建全文索引，向量原封不动
        await docindex.remove_fts(db, doc.id)
    await docindex.index_document(
        db, doc.id, doc.title, doc.filename, doc.tags, doc.summary, doc.extracted_text or ""
    )
    await db.commit()
    if do_embed:
        await embed_document(db, doc)
    await db.refresh(doc)
    return serialize(doc)


# ---------- 读取 ----------

async def get_document(db: AsyncSession, doc_id: int, *,
                       with_data: bool = False) -> Document | None:
    """按 id 取文档。

    默认不加载原文 BLOB（defer）—— 详情、改元数据、加关联等场景都用不到，
    对存了大文件的库能省下可观的 IO 与内存。真正要发文件（raw/download/
    抽取/重建索引）时传 with_data=True。
    """
    opts = [] if with_data else [defer(Document.data)]
    doc = await db.get(Document, doc_id, options=opts)
    if doc and doc.deleted_at is not None:
        return None
    return doc


async def list_documents(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 24,
    keyword: str = "",
    kind: str = "",
    tag: str = "",
    record_id: int | None = None,
    embed_status: str = "",
    include_deleted: bool = False,
) -> dict:
    conds = []
    if not include_deleted:
        conds.append(Document.deleted_at.is_(None))
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        conds.append(
            Document.title.like(like)
            | Document.filename.like(like)
            | Document.extracted_text.like(like)
            | Document.summary.like(like)
        )
    if kind:
        conds.append(Document.kind == kind)
    if embed_status:
        conds.append(Document.embed_status == embed_status)
    if tag:
        conds.append(Document.tags.like(f"%{tag}%"))
    if record_id:
        conds.append(
            Document.id.in_(
                select(DocumentLink.document_id).where(DocumentLink.record_id == record_id)
            )
        )

    base = select(Document)
    for c in conds:
        base = base.where(c)

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    q = base.order_by(Document.id.desc()).offset((page - 1) * page_size).limit(page_size)
    # 列表只看元数据，务必排除 BLOB —— 否则每列一条就要把整个文件读进内存
    q = q.options(defer(Document.data))
    docs = (await db.execute(q)).scalars().all()

    items = []
    for d in docs:
        item = serialize(d, links=await _links_of(db, d.id))
        item["chunk_count"] = (await db.execute(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == d.id)
        )).scalar() or 0
        items.append(item)

    # 一次性补「关联定义」通道（按源/目标的文件 id 命中 doc_ids 归组）
    try:
        from . import relation as rel_svc
        rel_map = await rel_svc.documents_relations(db, [d.id for d in docs])
        for it in items:
            it["relations"] = rel_map.get(it["id"], [])
    except Exception as e:
        log.warning("关联通道合并失败（不影响列表展示）：%s", e)
        for it in items:
            it.setdefault("relations", [])

    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "counts": await stats(db)}


async def stats(db: AsyncSession) -> dict:
    live = Document.deleted_at.is_(None)

    async def cnt(*extra):
        return (await db.execute(
            select(func.count(Document.id)).where(live, *extra)
        )).scalar() or 0

    return {
        "total": await cnt(),
        "doc": await cnt(Document.kind == "doc"),
        "image": await cnt(Document.kind == "image"),
        "video": await cnt(Document.kind == "video"),
        "audio": await cnt(Document.kind == "audio"),
        "other": await cnt(Document.kind == "other"),
        "indexed": await cnt(Document.embed_status == "ok"),
        "pending": await cnt(Document.embed_status.in_(("pending", "partial"))),
        "failed": await cnt(Document.embed_status == "failed"),
        "totalSize": (await db.execute(
            select(func.coalesce(func.sum(Document.size), 0)).where(live)
        )).scalar() or 0,
        "deleted": (await db.execute(
            select(func.count(Document.id)).where(Document.deleted_at.is_not(None))
        )).scalar() or 0,
    }


async def all_tags(db: AsyncSession) -> list[dict]:
    docs = (await db.execute(
        select(Document.tags).where(Document.deleted_at.is_(None))
    )).scalars().all()
    counter: dict[str, int] = {}
    for tg in docs:
        for t in (tg or []):
            counter[str(t)] = counter.get(str(t), 0) + 1
    return [{"tag": k, "count": v}
            for k, v in sorted(counter.items(), key=lambda x: -x[1])]


# ---------- 修改 ----------

async def update_document(db: AsyncSession, doc: Document, **fields) -> dict:
    touched_index = False
    for key in ("title", "tags", "summary", "description", "app"):
        if key in fields and fields[key] is not None:
            setattr(doc, key, fields[key])
            if key in ("title", "tags", "summary"):
                touched_index = True
    await db.commit()
    if touched_index:
        await docindex.index_document(
            db, doc.id, doc.title, doc.filename, doc.tags, doc.summary,
            doc.extracted_text or "",
        )
        await db.commit()
    await db.refresh(doc)
    return serialize(doc, links=await _links_of(db, doc.id))


async def delete_document(db: AsyncSession, doc: Document, *, hard: bool = False) -> bool:
    """默认软删除（可在数据中心恢复）；hard=True 时彻底抹掉原文与索引

    软删除**不动**文件：回收站的意义就是还能恢复。代价是原文继续占盘，
    存储页单独列出「回收站占用」，避免这部分空间隐形。
    """
    await docindex.remove_document(db, doc.id)
    if hard:
        # 顺序：先删记录再删文件。
        # 反过来的话，删文件成功但删记录失败，就留下一条「有元数据、无内容」
        # 的死档；而先删记录、后删文件失败，最坏只是留一个无人引用的文件，
        # 可以被存储页的孤儿扫描发现并清理 —— 后者的故障可自愈。
        rel = doc.path if doc.storage == filestore.MODE_FS else ""
        await db.delete(doc)
        await db.commit()
        if rel:
            others = (await db.execute(
                select(func.count(Document.id)).where(Document.path == rel)
            )).scalar() or 0
            if not others:
                filestore.remove(rel)
                filestore.invalidate_usage()
    else:
        doc.deleted_at = datetime.utcnow()
        await db.commit()
    return True


async def restore_document(db: AsyncSession, doc: Document) -> dict:
    doc.deleted_at = None
    await db.commit()
    await docindex.index_document(
        db, doc.id, doc.title, doc.filename, doc.tags, doc.summary, doc.extracted_text or ""
    )
    await db.commit()
    await db.refresh(doc)
    return serialize(doc)


# ---------- 关联 ----------

async def link_document(db: AsyncSession, doc_id: int, record_id: int,
                        field_key: str | None = None, note: str = "") -> dict:
    existing = (await db.execute(
        select(DocumentLink).where(
            DocumentLink.document_id == doc_id,
            DocumentLink.record_id == record_id,
            DocumentLink.field_key.is_(field_key) if field_key is None
            else DocumentLink.field_key == field_key,
        )
    )).scalar_one_or_none()
    if existing:
        return {"ok": True, "link_id": existing.id, "created": False}
    link = DocumentLink(document_id=doc_id, record_id=record_id,
                        field_key=field_key, note=note)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {"ok": True, "link_id": link.id, "created": True}


async def unlink_document(db: AsyncSession, doc_id: int, link_id: int) -> bool:
    link = await db.get(DocumentLink, link_id)
    if not link or link.document_id != doc_id:
        return False
    await db.delete(link)
    await db.commit()
    return True


# ---------- 混合检索 ----------

async def search_documents(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 20,
    mode: str = "hybrid",
) -> dict:
    """FTS5 关键词 + 向量语义，用 RRF 融合

    RRF（Reciprocal Rank Fusion）的好处是不需要把 bm25 分数和余弦距离
    归一化到同一量纲 —— 只按各自排名融合，稳健且无需调参。
    """
    q = (query or "").strip()
    if not q:
        return {"items": [], "query": q, "mode": mode,
                "channels": {"fts": 0, "vector": 0}}

    fts_hits: list[dict] = []
    vec_hits: list[dict] = []

    if mode in ("hybrid", "keyword"):
        fts_hits = await docindex.fts_search(db, q, limit * 3)

    if mode in ("hybrid", "semantic"):
        qvec = await embed_svc.embed_query(q)
        if qvec:
            vec_hits = await docindex.vec_search(db, qvec, limit * 3)

    ranked: dict[int, float] = {}
    K = 60
    for rank, hit in enumerate(fts_hits):
        ranked[hit["document_id"]] = ranked.get(hit["document_id"], 0.0) + 1.0 / (K + rank + 1)
    for rank, hit in enumerate(vec_hits):
        ranked[hit["document_id"]] = ranked.get(hit["document_id"], 0.0) + 1.0 / (K + rank + 1)

    if not ranked:
        return {"items": [], "query": q, "mode": mode,
                "channels": {"fts": 0, "vector": 0}}

    order = sorted(ranked.items(), key=lambda x: -x[1])[:limit]
    ids = [i for i, _ in order]

    docs = (await db.execute(
        select(Document).where(Document.id.in_(ids), Document.deleted_at.is_(None))
        .options(defer(Document.data))
    )).scalars().all()
    by_id = {d.id: d for d in docs}

    fts_ids = {h["document_id"] for h in fts_hits}
    vec_ids = {h["document_id"] for h in vec_hits}

    items = []
    for did, score in order:
        d = by_id.get(did)
        if not d:
            continue
        item = serialize(d)
        item["score"] = round(score, 6)
        item["matched_by"] = [
            m for m, s in (("keyword", fts_ids), ("semantic", vec_ids)) if did in s
        ]
        item["snippet"] = _snippet(d, q)
        items.append(item)

    return {
        "items": items,
        "query": q,
        "mode": mode,
        "channels": {"fts": len(fts_hits), "vector": len(vec_hits)},
    }


def _snippet(doc: Document, query: str, width: int = 160) -> str:
    """截取命中位置附近的片段"""
    text_src = doc.extracted_text or doc.summary or ""
    if not text_src:
        return ""
    q = (query or "").strip()
    pos = text_src.find(q) if q else -1
    if pos < 0:
        # 中文按单字退一步找
        for ch in q:
            pos = text_src.find(ch)
            if pos >= 0:
                break
    if pos < 0:
        return text_src[:width]
    start = max(0, pos - width // 3)
    return ("…" if start > 0 else "") + text_src[start:start + width] + "…"


async def build_ai_context(db: AsyncSession, question: str,
                           document_ids: list[int] | None = None,
                           max_docs: int = 5) -> dict:
    """为 AI 问答组装上下文

    返回 {"chunks": [...], "sources": [...]}：
    chunks 是真正喂给模型的内容，sources 是命中的来源（供前端展示
    「这句话是从哪份文件里找出来的」），两者分开是因为模型只需要文本，
    而人需要知道出处。
    """
    chunks: list[str] = []
    sources: list[dict] = []

    if document_ids:
        docs = (await db.execute(
            select(Document).where(Document.id.in_(document_ids),
                                   Document.deleted_at.is_(None))
        )).scalars().all()
        hit_kind = "selected"
    else:
        found = await search_documents(db, question, limit=max_docs)
        docs = []
        for item in found["items"]:
            d = await db.get(Document, item["id"])
            if d:
                docs.append(d)
                sources.append({
                    "type": "document",
                    "id": d.id,
                    "title": d.title or d.filename,
                    "matched_by": item.get("matched_by") or [],
                    "snippet": item.get("snippet") or "",
                })
        hit_kind = "retrieved"

    if document_ids and docs:
        for d in docs:
            sources.append({
                "type": "document", "id": d.id,
                "title": d.title or d.filename,
                "matched_by": [hit_kind], "snippet": "",
            })

    for d in docs:
        body = (d.extracted_text or d.summary or "").strip()
        if not body:
            continue
        chunks.append(f"【文件：{d.title}】\n{body[:3000]}")

    # 再补上知识库笔记（原有能力）
    try:
        notes = await _search_notes(db, question, limit=3)
        for n in notes:
            chunks.append(n["chunk"])
            sources.append(n["source"])
    except Exception:
        pass

    return {"chunks": chunks, "sources": sources}


async def _search_notes(db: AsyncSession, question: str, limit: int = 3) -> list[dict]:
    """在知识库笔记里做关键词检索（笔记沿用 entity_record 存储）"""
    from ..models import EntityType
    note_type = (await db.execute(
        select(EntityType).where(EntityType.key == "note")
    )).scalar_one_or_none()
    if not note_type:
        return []

    kw = (question or "").strip()[:40]
    if not kw:
        return []
    rows = (await db.execute(
        select(EntityRecord).where(
            EntityRecord.entity_type_id == note_type.id,
            EntityRecord.search_text.like(f"%{kw}%"),
        ).limit(limit)
    )).scalars().all()

    out = []
    for r in rows:
        d = r.data or {}
        title = d.get("title") or f"#{r.id}"
        out.append({
            "chunk": f"【笔记：{title}】\n{(d.get('content') or '')[:2000]}",
            "source": {"type": "note", "id": r.id, "title": title,
                       "matched_by": ["keyword"], "snippet": ""},
        })
    return out

