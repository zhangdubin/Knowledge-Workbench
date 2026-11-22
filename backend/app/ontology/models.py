"""Additive ontology metadata. Record data remains in EntityRecord."""

from uuid import uuid4
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from ..database import Base


def uid():
    return str(uuid4())


class Ontology(Base):
    __tablename__ = "ontology"
    id = Column(String, primary_key=True, default=uid)
    key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    current_revision_id = Column(String)
    adoption = Column(JSON, default=dict)
    adoption_schema = Column(JSON, default=dict)


class OntologyRevision(Base):
    __tablename__ = "ontology_revision"
    id = Column(String, primary_key=True, default=uid)
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False, index=True)
    base_revision_id = Column(String)
    schema = Column(JSON, nullable=False)
    status = Column(String, default="draft")
    created_at = Column(DateTime, server_default=func.now())


class Projection(Base):
    __tablename__ = "ontology_projection"
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False, index=True)
    semantic_id = Column(String, primary_key=True)
    kind = Column(String, nullable=False)
    legacy_id = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("kind", "legacy_id"),)


class RetiredProperty(Base):
    __tablename__ = "ontology_retired_property"
    semantic_id = Column(String, primary_key=True)
    owner_type_id = Column(String, nullable=False)


class ObjectBinding(Base):
    __tablename__ = "ontology_object"
    record_id = Column(ForeignKey("entity_record.id"), primary_key=True)
    type_id = Column(ForeignKey("ontology_projection.semantic_id"), nullable=False)
    revision_id = Column(ForeignKey("ontology_revision.id"), nullable=False)
    version = Column(Integer, nullable=False)


class ObjectHistory(Base):
    __tablename__ = "ontology_object_history"
    record_id = Column(Integer, primary_key=True)
    version = Column(Integer, primary_key=True)
    revision_id = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class OntologyChangeSet(Base):
    __tablename__ = "ontology_change_set"
    id = Column(String, primary_key=True, default=uid)
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False)
    base_revision_id = Column(String)
    kind = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    payload_digest = Column(String, nullable=False)
    preconditions = Column(JSON, nullable=False)
    status = Column(String, default="proposed")
    expires_at = Column(DateTime, nullable=False)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class OntologyInstallation(Base):
    __tablename__ = "ontology_installation"
    version = Column(Integer, primary_key=True)
    installed_at = Column(DateTime, server_default=func.now())


class SourceSnapshot(Base):
    __tablename__ = "ontology_source_snapshot"
    id = Column(String, primary_key=True, default=uid)
    document_id = Column(Integer, nullable=False, index=True)
    source_sha = Column(String, nullable=False)
    text_sha = Column(String, nullable=False)
    parser = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("document_id", "source_sha", "text_sha", "parser"),
    )


class Evidence(Base):
    __tablename__ = "ontology_evidence"
    id = Column(String, primary_key=True, default=uid)
    claim_id = Column(ForeignKey("ontology_claim.id"), index=True)
    snapshot_id = Column(ForeignKey("ontology_source_snapshot.id"), nullable=False)
    quote = Column(Text, nullable=False)
    start = Column(Integer, nullable=False)
    end = Column(Integer, nullable=False)
    chunk_id = Column(Integer)
    actor = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Claim(Base):
    __tablename__ = "ontology_claim"
    id = Column(String, primary_key=True, default=uid)
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False, index=True)
    revision_id = Column(ForeignKey("ontology_revision.id"), nullable=False)
    type_id = Column(String, nullable=False)
    object_id = Column(Integer, nullable=False, index=True)
    predicate_id = Column(String, nullable=False)
    value = Column(JSON)
    target_id = Column(Integer)
    evidence_ids = Column(JSON, nullable=False)
    confidence = Column(JSON)
    extractor = Column(String, nullable=False)
    status = Column(String, nullable=False, default="candidate")
    effective_from = Column(String)
    effective_to = Column(String)
    version = Column(Integer, default=1, nullable=False)
    superseded_by = Column(String)
    reviewed_by = Column(String)
    reviewed_at = Column(DateTime)
    recorded_at = Column(DateTime, server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ontology_ingestion_job"
    id = Column(String, primary_key=True, default=uid)
    ontology_id = Column(ForeignKey("ontology.id"), nullable=False, index=True)
    revision_id = Column(String, nullable=False)
    document_id = Column(Integer, nullable=False)
    input_hash = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False)
    parser = Column(String, nullable=False)
    extractor = Column(String, nullable=False)
    source_hash = Column(String, nullable=False)
    budget = Column(JSON, nullable=False)
    status = Column(String, nullable=False)
    candidates = Column(JSON, nullable=False)
    error = Column(String)
    result = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())


class SourceObject(Base):
    __tablename__ = "ontology_source_object"
    ontology_id = Column(String, primary_key=True)
    document_id = Column(Integer, primary_key=True)
    type_id = Column(String, primary_key=True)
    source_id = Column(String, primary_key=True)
    record_id = Column(Integer, nullable=False)


class RecordChange(Base):
    """Legacy records can be proposed before any ontology exists."""

    __tablename__ = "ontology_record_change"
    id = Column(String, primary_key=True, default=uid)
    actor = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    payload_digest = Column(String, nullable=False)
    preconditions = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="proposed")
    result = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())


class AssistantRun(Base):
    __tablename__ = "ontology_assistant_run"
    id = Column(String, primary_key=True, default=uid)
    actor = Column(String, nullable=False)
    status = Column(String, nullable=False)
    error = Column(String)
    tools = Column(JSON, nullable=False)
    change_id = Column(String)
    rounds = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class CapabilityDefinition(Base):
    __tablename__ = "ontology_capability_definition"
    name = Column(String, primary_key=True)
    definition = Column(JSON, nullable=False)
