"""Apply document provenance before returning records, counts or pages."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import event, exists, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from ..database import get_db
from ..models import Document, DocumentLink, EntityRecord, EntityType, RelationRecord
from ..services.auth import current_principal
from .models import Claim, RecordSource, RelationSupport


def model_readable(principal, model):
    permissions = principal.perms.get("models") or {}
    fallback = permissions.get("*") in ("write", "read")
    keys = [
        k
        for k, v in permissions.items()
        if k != "*" and (v in ("write", "read")) != fallback
    ]
    return model.c.key.not_in(keys) if fallback else model.c.key.in_(keys)


def document_readable(principal, doc):
    if principal.is_super:
        return True
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
    permitted = linked.where(model_readable(principal, model)).exists()
    if principal.has_page("library"):
        return or_(permitted, ~linked.exists())
    return permitted


def live_source(principal, source):
    doc = Document.__table__
    live = (
        select(1)
        .select_from(doc)
        .where(doc.c.id == source.c.document_id, doc.c.deleted_at.is_(None))
        .correlate(source)
    )
    live = live.where(document_readable(principal, doc))
    return live.exists()


def readable(principal):
    source = RecordSource.__table__
    hidden = (
        select(1)
        .select_from(source)
        .where(source.c.record_id == EntityRecord.id, ~live_source(principal, source))
        .correlate(EntityRecord)
    )
    return ~hidden.exists()


def readable_relation(principal):
    support = RelationSupport.__table__
    claim = Claim.__table__
    bound = select(1).select_from(support).where(
        support.c.relation_id == RelationRecord.id).correlate(RelationRecord)
    accepted = bound.join(claim, claim.c.id == support.c.claim_id).where(
        claim.c.status == "accepted", live_source(principal, support))
    endpoint = EntityRecord.__table__.alias("relation_endpoint")
    model = EntityType.__table__.alias("endpoint_model")
    source = RecordSource.__table__
    hidden = select(1).select_from(source).where(
        source.c.record_id == endpoint.c.id, ~live_source(principal, source)
    ).correlate(endpoint)
    visible = select(1).select_from(endpoint.join(model, endpoint.c.entity_type_id == model.c.id)).where(
        endpoint.c.deleted_at.is_(None), ~hidden.exists()
    ).correlate(RelationRecord)
    if not principal.is_super:
        visible = visible.where(model_readable(principal, model))
    return or_(~bound.exists(), (
        visible.where(endpoint.c.id == RelationRecord.source_record_id).exists()
        & visible.where(endpoint.c.id == RelationRecord.target_record_id).exists()
        & or_(bound.where(support.c.manual_origin == 1).exists(), accepted.exists())
    ))


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
            ),
            with_loader_criteria(RelationRecord, readable_relation(principal), include_aliases=True)
        )
