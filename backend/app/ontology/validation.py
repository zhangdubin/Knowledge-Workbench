"""Validate canonical JSON values at the record write boundary."""

import json
from datetime import date, datetime
from math import isfinite

from sqlalchemy import select

from ..models import EntityRecord, EntityType


async def validate_record(db, fields, data, previous=None, reference_targets=None):
    if not isinstance(data, dict):
        raise ValueError("记录数据必须是对象")
    previous = previous or {}
    known = {field.key for field in fields}
    for key in data.keys() - known - {"group_id"}:
        if key not in previous or json.dumps(data[key], sort_keys=True) != json.dumps(
            previous[key], sort_keys=True
        ):
            raise ValueError(f"未知字段 {key}")
    for field in fields:
        value = data.get(field.key)
        if (
            value is None
            or value == ""
            or (
                value == []
                and (
                    field.type == "multiselect" or (field.options or {}).get("multiple")
                )
            )
        ):
            if field.required:
                raise ValueError(f"{field.key} 为必填字段")
            continue
        options = field.options or {}
        multiple = field.type == "multiselect" or options.get("multiple") is True
        if multiple and not isinstance(value, list):
            raise ValueError(f"{field.key} 必须是数组")
        for item in value if multiple else [value]:
            kind = field.type
            valid = True
            if kind == "number":
                valid = type(item) is int or (type(item) is float and isfinite(item))
            elif kind == "boolean":
                valid = isinstance(item, bool)
            elif kind in {"text", "textarea", "richtext"}:
                valid = isinstance(item, str)
            elif kind in {"date", "datetime"}:
                try:
                    (date if kind == "date" else datetime).fromisoformat(item)
                except (ValueError, TypeError):
                    valid = False
            elif kind in {"select", "multiselect"}:
                choices = options.get("choices") or options.get("options") or []
                valid = isinstance(item, str) and (not choices or item in choices)
            elif kind == "reference":
                target = options.get("target")
                valid = type(item) is int and bool(
                    await db.scalar(
                        select(EntityRecord.id)
                        .join(EntityType)
                        .where(
                            EntityRecord.id == item,
                            EntityRecord.deleted_at.is_(None),
                            (
                                EntityType.id == reference_targets[target]
                                if reference_targets is not None
                                and target in reference_targets
                                else EntityType.key == target
                            ),
                            EntityType.deleted_at.is_(None),
                        )
                    )
                )
            if not valid:
                raise ValueError(f"{field.key} 的值不符合 {kind} 约束")
