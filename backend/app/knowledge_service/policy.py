from fastapi import HTTPException
from ..ontology import registry
from ..ontology.models import Ontology
from .models import KnowledgeSpace
from ..ontology.registry import digest
from ..ontology.changes import actor
from . import schemas


def entry(p):
    if not p.has_page("knowledge_service"):
        raise HTTPException(403, "缺少知识服务使用权限")


def reviewer(p):
    return p.has_feature("knowledge_review")


def manager(p):
    return (
        p.has_page("types")
        and p.has_feature("model_manage")
        and p.has_feature("relation_manage")
    )


async def space(db, p, ontology_id, write=False):
    entry(p)
    ontology_id = schemas.identifier(ontology_id, "知识空间")
    cache = db.info.setdefault("knowledge_space_cache", {})
    key = (actor(p), digest(p.perms), ontology_id, write)
    if key in cache:
        return cache[key]
    registration = await db.get(KnowledgeSpace, ontology_id)
    ontology = await db.get(Ontology, ontology_id)
    if not registration or not ontology or not ontology.current_revision_id:
        raise HTTPException(404, "知识空间不存在或尚未发布")
    schema = await registry.current(db, ontology)
    visible = [
        t
        for t in schema["types"]
        if p.can_model(t["key"], "write" if write else "read")
    ]
    if not visible or (write and len(visible) != len(schema["types"])):
        raise HTTPException(403, "缺少知识模型权限")
    result = (ontology, registration, schema, visible)
    cache[key] = result
    return result


def require_types(p, schema, type_ids):
    by_id = {t["id"]: t for t in schema["types"]}
    if any(tid not in by_id or not p.can_model(by_id[tid]["key"]) for tid in type_ids):
        raise HTTPException(403, "原查询所选知识模型已不可读")


def semantic_data(registration, schema, obj):
    roles = (registration.field_roles or {}).get(obj["type_id"])
    if not roles:
        raise HTTPException(409, "知识应用字段角色未登记，请重新安装明确的模板")
    current = next((t for t in schema["types"] if t["id"] == obj["type_id"]), None)
    fields = {f["id"]: f["key"] for f in (current or {}).get("fields", [])}
    if any(fid not in fields for fid in roles.values()):
        raise HTTPException(409, "知识字段发生不兼容变更，请维护稳定字段角色")
    return {role: obj["data"].get(fields[fid]) for role, fid in roles.items()}
