"""Immutable source citations. Offsets count Unicode code points."""

from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Document, DocumentChunk
from ..services.document import ensure_readable
from .models import Evidence, SourceSnapshot


async def source(db, principal, document_id):
    doc = await db.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(404, "来源文件不可用")
    await ensure_readable(db, principal, doc)
    return doc


async def capture(db, principal, location):
    doc = await source(db, principal, location["document_id"])
    text = doc.extracted_text or ""
    start, end, quote = (location.get(key) for key in ("start", "end", "quote"))
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or not isinstance(quote, str)
        or len(quote) > 8192
        or text[start:end] != quote
    ):
        raise HTTPException(422, "引文与原文字符区间不符")
    chunk_id = location.get("chunk_id")
    if chunk_id is not None:
        chunk = await db.get(DocumentChunk, chunk_id)
        if not chunk or chunk.document_id != doc.id or quote not in (chunk.text or ""):
            raise HTTPException(422, "引文与原始分块不符")
    text_sha = sha256(text.encode()).hexdigest()
    identity = dict(
        document_id=doc.id,
        source_sha=doc.sha256 or (sha256(doc.data).hexdigest() if doc.data else ""),
        text_sha=text_sha,
        parser=f"{doc.extract_kind or 'text'}/1",
    )
    snapshot = await db.scalar(select(SourceSnapshot).filter_by(**identity))
    if snapshot is None:
        snapshot = SourceSnapshot(**identity, text=text)
        db.add(snapshot)
        await db.flush()
    evidence = Evidence(
        snapshot_id=snapshot.id,
        start=start,
        end=end,
        quote=quote,
        chunk_id=chunk_id,
        actor=principal.username,
    )
    db.add(evidence)
    await db.flush()
    return evidence


async def read_evidence(db, principal, evidence_id):
    evidence = await db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(404, "证据不存在")
    snapshot = await db.get(SourceSnapshot, evidence.snapshot_id)
    doc = await source(db, principal, snapshot.document_id)
    return dict(
        id=evidence.id,
        document_id=doc.id,
        title=doc.title,
        snapshot_id=snapshot.id,
        source_sha=snapshot.source_sha,
        text_sha=snapshot.text_sha,
        parser=snapshot.parser,
        quote=evidence.quote,
        start=evidence.start,
        end=evidence.end,
        chunk_id=evidence.chunk_id,
        actor=evidence.actor,
        created_at=evidence.created_at,
    )
