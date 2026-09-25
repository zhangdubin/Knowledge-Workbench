"""附件服务 —— v0.2 起是「文档服务」的兼容适配层

保留这个模块的原因很实际：v0.1 时代前端把整个附件对象（含
`url: /api/attachments/3/preview`）一起存进了记录 JSON。也就是说
**历史数据的链接是硬编码在数据库里的**，直接删掉旧接口会让已有
记录里的附件全部变成死链。

所以这里不改 URL，只把存储换成 document（v0.3 起原文外置到文件系统）：
  - 上传 → document + document_link
  - 读取 → document
  - id 语义保持一一对应（迁移时旧附件 id 原样写进 document.id）
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..models import Document, DocumentLink
from . import document as doc_svc


async def save_attachment(db: AsyncSession, record_id: int, field_key: str, file) -> Document:
    """保存上传文件（落文件存储），并挂到指定记录的字段上"""
    from fastapi import HTTPException

    from ..config import settings

    data = await file.read()
    limit = settings.upload_max_mb
    if limit and len(data) > limit * 1024 * 1024:
        raise HTTPException(
            413, f"文件 {len(data) / 1048576:.1f}MB 超过上限 {limit}MB"
        )
    result = await doc_svc.create_document(
        db,
        data=data,
        filename=file.filename or "file",
        mime=getattr(file, "content_type", "") or "",
        source="upload",
        record_id=record_id,
        field_key=field_key,
    )
    doc = await db.get(Document, result["id"])
    return doc


async def list_attachments(
    db: AsyncSession, record_id: int, field_key: str | None = None
) -> list[Document]:
    q = (
        select(Document)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .where(
            DocumentLink.record_id == record_id,
            Document.deleted_at.is_(None),
        )
    )
    if field_key:
        q = q.where(DocumentLink.field_key == field_key)
    q = q.order_by(Document.id).options(defer(Document.data))   # 列表不需要原文
    return list((await db.execute(q)).scalars().all())


async def get_attachment(db: AsyncSession, attachment_id: int) -> Document | None:
    doc = await db.get(Document, attachment_id)
    if doc is None or doc.deleted_at is not None:
        return None
    return doc


async def delete_attachment(db: AsyncSession, attachment_id: int) -> bool:
    doc = await db.get(Document, attachment_id)
    if not doc:
        return False
    # 只解除与该记录的挂接更符合直觉，但旧语义是「删附件」，
    # 这里保持删除文档本体（软删除，可在数据中心恢复）
    await doc_svc.delete_document(db, doc)
    return True
