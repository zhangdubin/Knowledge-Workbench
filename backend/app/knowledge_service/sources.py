from hashlib import sha256
from fastapi import HTTPException
from sqlalchemy import select
from ..ontology import evidence
from ..ontology.models import SourceSnapshot
from ..ontology.changes import actor
from ..ontology.migrations import lock_writer
from ..ontology.knowledge import day
from .models import SourceRevision
from . import policy, schemas


SOURCE_BUDGET = 2000


class VisibleRevisions(list):
    def __init__(self, *, incomplete=False):
        super().__init__()
        self.incomplete = incomplete


async def readable(db, p, row):
    await policy.space(db, p, row.ontology_id)
    await evidence.source(db, p, row.document_id)
    return row


def active(row, at, rows):
    stopped_at = getattr(row, "_successor_from", None)
    if stopped_at and stopped_at <= at:
        return False
    if row.effective_from and row.effective_from > at:
        return False
    if row.effective_to and row.effective_to < at:
        return False
    # Explicit authority only takes effect when its replacement becomes applicable.
    return True


async def visible(db, p, ontology_id):
    await policy.space(db, p, ontology_id)
    # This metadata enumeration is bounded; query records its truncation separately.
    metadata = list(
        await db.scalars(
            select(SourceRevision)
            .where(SourceRevision.ontology_id == ontology_id)
            .order_by(SourceRevision.recorded_at, SourceRevision.id)
            .limit(SOURCE_BUDGET + 1)
        )
    )
    # The old authority stops even if the reader cannot read its replacement.
    # Only the old source's applicability changes; hidden replacement details never escape.
    successors = {
        n.supersedes_id: n.effective_from
        for n in metadata
        if n.supersedes_id and n.effective_from
    }
    rows = VisibleRevisions(incomplete=len(metadata) > SOURCE_BUDGET)
    for r in metadata[:SOURCE_BUDGET]:
        r._successor_from = successors.get(r.id)
    for r in metadata[:SOURCE_BUDGET]:
        try:
            await readable(db, p, r)
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
        rows.append(r)
    return rows


async def detail(db, p, revision_id):
    r = await db.get(SourceRevision, revision_id)
    if not r:
        raise HTTPException(404, "资料修订不存在")
    await readable(db, p, r)
    snapshot = await db.get(SourceSnapshot, r.snapshot_id)
    if (
        not snapshot
        or snapshot.document_id != r.document_id
        or sha256(snapshot.text.encode()).hexdigest() != snapshot.text_sha
    ):
        raise HTTPException(409, "原文快照校验失败")
    doc = await evidence.source(db, p, r.document_id)
    current_sha = doc.sha256 or (sha256(doc.data).hexdigest() if doc.data else "")
    group = [
        schemas.row(v)
        for v in await visible(db, p, r.ontology_id)
        if v.group_key == r.group_key and v.scope == r.scope
    ]
    return dict(
        **schemas.row(r),
        text=snapshot.text,
        document=dict(
            id=doc.id,
            title=doc.title,
            filename=doc.filename,
            url=f"/api/documents/{doc.id}/raw",
            download_url=f"/api/documents/{doc.id}/download",
        ),
        original_document_url=f"/api/documents/{doc.id}/raw",
        original_document_changed=current_sha != snapshot.source_sha
        or sha256((doc.extracted_text or "").encode()).hexdigest() != snapshot.text_sha,
        snapshot_text_sha=snapshot.text_sha,
        group_revisions=group,
    )


async def create(db, p, payload):
    schemas.keys(
        payload,
        (
            "ontology_id",
            "document_id",
            "group_key",
            "label",
            "scope",
            "topic",
            "effective_from",
            "effective_to",
            "supersedes_id",
        ),
    )
    oid = schemas.text(payload.get("ontology_id"), "知识空间", required=True)
    await policy.space(db, p, oid, write=True)
    if not p.has_feature("file_write"):
        raise HTTPException(403, "缺少资料写入权限")
    did = payload.get("document_id")
    if type(did) is not int:
        raise HTTPException(422, "请选择原始资料")
    doc = await evidence.source(db, p, did)
    values = {
        k: schemas.text(payload.get(k, ""), n, 200, k in ("group_key", "label"))
        for k, n in [
            ("group_key", "资料分组"),
            ("label", "修订名称"),
            ("scope", "适用范围"),
            ("topic", "业务主题"),
        ]
    }
    start, end = day(payload.get("effective_from")), day(payload.get("effective_to"))
    if start and end and start > end:
        raise HTTPException(422, "资料适用日期区间无效")
    await lock_writer(db)
    supersedes = payload.get("supersedes_id")
    if supersedes:
        old = await db.get(SourceRevision, supersedes)
        if not old:
            raise HTTPException(404, "被替代修订不存在")
        await readable(db, p, old)
        if (
            old.ontology_id != oid
            or old.group_key != values["group_key"]
            or old.scope != values["scope"]
            or not start
            or (old.effective_from and start <= old.effective_from)
        ):
            raise HTTPException(422, "只能明确替代同一分组和范围的较早修订")
        if await db.scalar(
            select(SourceRevision.id).where(SourceRevision.supersedes_id == old.id)
        ):
            raise HTTPException(409, "该修订已有明确替代资料")
    text = doc.extracted_text or ""
    identity = dict(
        document_id=did,
        source_sha=doc.sha256 or (sha256(doc.data).hexdigest() if doc.data else ""),
        text_sha=sha256(text.encode()).hexdigest(),
        parser=f"{doc.extract_kind or 'text'}/1",
    )
    snapshot = await db.scalar(select(SourceSnapshot).filter_by(**identity))
    if snapshot is None:
        snapshot = SourceSnapshot(**identity, text=text)
        db.add(snapshot)
        await db.flush()
    duplicate = await db.scalar(
        select(SourceRevision.id).filter_by(
            ontology_id=oid,
            snapshot_id=snapshot.id,
            effective_from=start,
            effective_to=end,
            **values,
        )
    )
    if duplicate:
        raise HTTPException(409, "该资料修订已登记")
    revision = SourceRevision(
        ontology_id=oid,
        document_id=did,
        snapshot_id=snapshot.id,
        source_sha=identity["source_sha"] or identity["text_sha"],
        effective_from=start,
        effective_to=end,
        supersedes_id=supersedes,
        actor=actor(p),
        **values,
    )
    db.add(revision)
    await db.commit()
    return schemas.row(revision)
