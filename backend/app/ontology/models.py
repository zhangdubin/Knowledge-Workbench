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
