from fastapi import HTTPException
from ..ontology import registry
from ..ontology.models import Ontology
from .models import KnowledgeSpace


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
    return ontology, registration, schema, visible
