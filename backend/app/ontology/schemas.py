from copy import deepcopy
from fastapi import HTTPException
from ..services.model_json import FIELD_TYPES, KEY_RE
from .models import uid

EMPTY = {"types": [], "relations": []}
CARDINALITIES = {"one-to-one", "one-to-many", "many-to-one", "many-to-many"}


def normalize(raw, previous):
    schema = deepcopy(raw)
    seen = set()

    def items(rows, old):
        if not isinstance(rows, list):
            raise HTTPException(422, "定义必须是数组")
        by_key = {item["key"]: item for item in old}
        keys = set()
        for item in rows:
            if not isinstance(item, dict):
                raise HTTPException(422, "定义必须是对象")
            key = item.get("key")
            if (
                not isinstance(key, str)
                or not KEY_RE.fullmatch(key)
                or len(key) > 64
                or key in keys
            ):
                raise HTTPException(422, "标识无效或重复")
            keys.add(key)
            former = by_key.get(key, {})
            identity = item.get("id") or former.get("id") or uid()
            if (
                not isinstance(identity, str)
                or identity in seen
                or former.get("id", identity) != identity
            ):
                raise HTTPException(422, "身份冲突")
            if (
                not item.get("id")
                and not former
                and any(
                    o["key"] not in [r.get("key") for r in rows if isinstance(r, dict)]
                    for o in old
                )
            ):
                raise HTTPException(422, "重命名时须保留原 ID")
            if not isinstance(item.get("name", key), str):
                raise HTTPException(422, "名称必须是文本")
            seen.add(identity)
            item.update(id=identity, name=item.get("name") or key)
            yield item, next((o for o in old if o["id"] == identity), {})

    if not isinstance(schema, dict):
        raise HTTPException(422, "模式必须是对象")
    for t, old in items(schema.setdefault("types", []), previous["types"]):
        if t["key"] == "note":
            raise HTTPException(422, "note 使用专用笔记接口")
        for f, _ in items(t.setdefault("fields", []), old.get("fields", [])):
            if f.get("type") not in FIELD_TYPES or not isinstance(
                f.setdefault("options", {}), dict
            ):
                raise HTTPException(422, "字段类型或选项无效")
            options = f["options"]
            if f["type"] == "reference" and not isinstance(options.get("target"), str):
                raise HTTPException(422, "引用字段必须指定目标模型 options.target")
            if f["type"] in {"select", "multiselect"}:
                choices = options.get("choices", [])
                if not isinstance(choices, list) or any(
                    not isinstance(c, str) for c in choices
                ):
                    raise HTTPException(422, "枚举选项必须是文本数组")
            if not isinstance(f.setdefault("required", False), bool):
                raise HTTPException(422, "required 必须是布尔值")
    type_ids = {t["id"] for t in schema["types"]}
    for r, _ in items(schema.setdefault("relations", []), previous["relations"]):
        if not all(
            isinstance(r.get(k), str) for k in ("source", "target", "cardinality")
        ):
            raise HTTPException(422, "关系端点或基数无效")
        if (
            r.get("source") not in type_ids
            or r.get("target") not in type_ids
            or r.get("cardinality") not in CARDINALITIES
        ):
            raise HTTPException(422, "关系端点或基数无效")
    return schema
