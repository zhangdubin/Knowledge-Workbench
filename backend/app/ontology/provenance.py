"""Apply document provenance before returning records, counts or pages."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import event, exists, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from ..database import get_db
from ..models import Document, DocumentLink, EntityRecord, EntityType
from ..services.auth import current_principal
from .models import RecordSource


def readable(principal):
    source = RecordSource.__table__
    doc = Document.__table__
    link = DocumentLink.__table__
    record = EntityRecord.__table__.alias("source_link_record")
    model = EntityType.__table__.alias("source_link_model")
    links = link.join(record, link.c.record_id == record.c.id).join(
        model, record.c.entity_type_id == model.c.id
    )
    linked = (
        select(1)
        .select_from(links)
        .where(link.c.document_id == doc.c.id)
        .correlate(doc)
    )
    live = (
        select(1)
        .select_from(doc)
        .where(doc.c.id == source.c.document_id, doc.c.deleted_at.is_(None))
        .correlate(source)
    )
    if not principal.is_super:
        permissions = principal.perms.get("models") or {}
        fallback = permissions.get("*") in ("write", "read")
        keys = [
            k
            for k, v in permissions.items()
            if k != "*" and (v in ("write", "read")) != fallback
        ]
        model_allowed = model.c.key.not_in(keys) if fallback else model.c.key.in_(keys)
        permitted_link = linked.where(model_allowed).exists()
        if principal.has_page("library"):
            permitted_link = or_(permitted_link, ~linked.exists())
        live = live.where(permitted_link)
    hidden = (
        select(1)
        .select_from(source)
        .where(source.c.record_id == EntityRecord.id, ~live.exists())
        .correlate(EntityRecord)
    )
    return ~hidden.exists()


async def ensure_record_source(db, principal, record_id):
    if not await db.scalar(
        select(EntityRecord.id).where(EntityRecord.id == record_id, readable(principal))
    ):
        raise HTTPException(404, "记录不可用")


async def scope_record_reads(
    request: Request, db=Depends(get_db), principal=Depends(current_principal)
):
    # Scope read requests and assistant searches at the shared session, so aggregates,
    # exports, aliases and results use the same predicate. Integrity writers must see
    # the full database when validating cardinality or assessing migration impact.
    path = request.url.path
    if (
        request.method in ("GET", "HEAD")
        or path.endswith("/query")
        or path.startswith("/api/ai/")
    ):
        db.info["record_source_principal"] = principal


@event.listens_for(Session, "do_orm_execute")
def filter_source_records(state):
    principal = state.session.info.get("record_source_principal")
    if state.execution_options.get("source_policy_lookup"):
        return
    if state.is_select and principal is not None:
        state.statement = state.statement.options(
            with_loader_criteria(
                EntityRecord, readable(principal), include_aliases=True
            )
        )
