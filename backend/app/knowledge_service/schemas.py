"""Small explicit Chinese validation contracts."""

from datetime import date
from fastapi import HTTPException
from ..ontology.knowledge import day


def text(value, label, maximum=500, required=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (required and not value.strip())
    ):
        raise HTTPException(422, f"{label}不能为空或超过允许长度")
    return value.strip()


def keys(payload, allowed):
    if set(payload) - set(allowed):
        raise HTTPException(422, "请求包含不支持的字段")


def query(payload):
    keys(
        payload,
        (
            "ontology_id",
            "question",
            "type_id",
            "scope",
            "topic",
            "as_of",
            "limit",
            "depth",
            "generate",
        ),
    )
    out = dict(payload)
    out["ontology_id"] = text(out.get("ontology_id"), "知识空间", required=True)
    out["question"] = text(out.get("question"), "问题", required=True)
    for name in ("scope", "topic", "type_id"):
        if out.get(name) is not None:
            out[name] = text(out[name], "筛选条件")
    for name, default, low, high in [("limit", 50, 1, 50), ("depth", 0, 0, 2)]:
        value = out.setdefault(name, default)
        if type(value) is not int or not low <= value <= high:
            raise HTTPException(422, "查询范围超限")
    if type(out.setdefault("generate", False)) is not bool:
        raise HTTPException(422, "生成选项必须为布尔值")
    out["as_of"] = day(out.get("as_of")) or date.today().isoformat()
    return out


def row(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
