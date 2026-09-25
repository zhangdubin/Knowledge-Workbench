from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ===== EntityType =====
class FieldDefIn(BaseModel):
    key: str
    name: str
    type: str
    required: bool = False
    options: dict = Field(default_factory=dict)
    order: int = 0


class FieldDefOut(FieldDefIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class EntityTypeIn(BaseModel):
    key: str
    name: str
    icon: str = "📦"
    description: str = ""
    app: str = "default"
    order: int = 0
    fields: list[FieldDefIn] = Field(default_factory=list)


class EntityTypeOut(BaseModel):
    id: int
    key: str
    name: str
    icon: str
    description: str
    app: str
    order: int
    created_at: datetime
    updated_at: datetime
    fields: list[FieldDefOut] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class EntityTypeListOut(BaseModel):
    id: int
    key: str
    name: str
    icon: str
    description: str
    app: str
    order: int
    field_count: int = 0
    record_count: int = 0
    model_config = ConfigDict(from_attributes=True)


# ===== Record =====
class RecordIn(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class RecordOut(BaseModel):
    id: int
    entity_type_id: int
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    entity_type_key: str = ""
    entity_type_name: str = ""
    model_config = ConfigDict(from_attributes=True)


# ===== Relation =====
class RelationDefIn(BaseModel):
    """关联定义：两端各自是「记录」或「文件」

    kind=record 必须带 type_id；kind=document 不能带 type_id
    （文件不属于任何业务模型），校验在 services/relation.py 里做。
    """
    key: str
    name: str
    source_kind: str = "record"          # record | document
    source_type_id: int | None = None
    target_kind: str = "record"
    target_type_id: int | None = None
    cardinality: str = "many-to-many"
    description: str = ""


class RelationDefOut(RelationDefIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RelationRecordIn(BaseModel):
    relation_def_id: int
    source_record_id: int | None = None
    target_record_id: int | None = None
    source_document_id: int | None = None
    target_document_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RelationRecordOut(RelationRecordIn):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ===== Attachment =====
class AttachmentOut(BaseModel):
    id: int
    record_id: int
    field_key: str
    filename: str
    size: int
    content_type: str
    url: str = ""
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ===== View =====
class ViewIn(BaseModel):
    name: str
    type: str = "list"
    config: dict = Field(default_factory=dict)
    order: int = 0


class ViewOut(ViewIn):
    id: int
    entity_type_id: int
    model_config = ConfigDict(from_attributes=True)


# ===== Search / Analytics =====
class SearchResult(BaseModel):
    record_id: int
    entity_type_id: int
    entity_type_key: str
    entity_type_name: str
    entity_type_icon: str
    snippet: str
    data: dict[str, Any]


class GraphNode(BaseModel):
    id: int
    label: str
    type: str  # entity_type_key
    type_name: str
    icon: str


class GraphEdge(BaseModel):
    id: int
    source: int
    target: int
    relation: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AppSummary(BaseModel):
    key: str
    name: str
    icon: str
    description: str
    entity_count: int
    record_count: int