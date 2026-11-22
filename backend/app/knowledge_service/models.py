"""Additive knowledge metadata. Source text and objects retain their authorities."""

from sqlalchemy import (
    Column,
    String,
    Integer,
    JSON,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from ..database import Base
from ..ontology.models import uid


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_service_space"
    ontology_id = Column(ForeignKey("ontology.id"), primary_key=True)
    item_type_id = Column(String, nullable=False)
    term_type_id = Column(String, nullable=False)
    change_id = Column(String, nullable=False)
    field_roles = Column(JSON, nullable=False, default=dict)


class SourceRevision(Base):
    __tablename__ = "knowledge_source_revision"
    id = Column(String, primary_key=True, default=uid)
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False, index=True)
    document_id = Column(Integer, nullable=False)
    snapshot_id = Column(ForeignKey("ontology_source_snapshot.id"), nullable=False)
    source_sha = Column(String, nullable=False)
    group_key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    scope = Column(String, nullable=False, default="")
    topic = Column(String, nullable=False, default="")
    effective_from = Column(String)
    effective_to = Column(String)
    supersedes_id = Column(ForeignKey("knowledge_source_revision.id"), index=True)
    actor = Column(String, nullable=False)
    recorded_at = Column(DateTime, server_default=func.now())


class QueryRun(Base):
    __tablename__ = "knowledge_query_run"
    id = Column(String, primary_key=True, default=uid)
    actor = Column(String, nullable=False, index=True)
    ontology_id = Column(String, nullable=False)
    revision_id = Column(String, nullable=False)
    request = Column(JSON, nullable=False)
    references = Column(JSON, nullable=False)
    status = Column(String, nullable=False)
    generation = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    model_version = Column(String)
    elapsed_ms = Column(Integer, nullable=False)
    budget = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Feedback(Base):
    __tablename__ = "knowledge_feedback"
    id = Column(String, primary_key=True, default=uid)
    actor = Column(String, nullable=False, index=True)
    run_id = Column(ForeignKey("knowledge_query_run.id"))
    record_id = Column(Integer)
    record_version = Column(Integer)
    references = Column(JSON, nullable=False, default=dict)
    category = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    idempotency_key = Column(String, nullable=False)
    request_digest = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    version = Column(Integer, nullable=False, default=1)
    resolution = Column(Text)
    resolved_by = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime)
    __table_args__ = (UniqueConstraint("actor", "idempotency_key"),)


class FeedbackResolution(Base):
    __tablename__ = "knowledge_feedback_resolution"
    id = Column(String, primary_key=True, default=uid)
    feedback_id = Column(ForeignKey("knowledge_feedback.id"), nullable=False)
    actor = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    request_digest = Column(String, nullable=False)
    result = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("feedback_id", "actor", "idempotency_key"),)
