"""AI 操作中枢（Agent）：自然语言 → 结构化工具调用 → 受控执行

设计原则
--------
1. **只读直接执行，写操作两段式**：查询/统计类工具当场执行；新建/修改/删除
   这类会动数据的工具，Agent 只「提议」——返回结构化预览给前端，用户点
   确认后才真正落库。模型永远拿不到「直接改数据」的能力。
2. **不生成 SQL**：LLM 只负责「选工具 + 填参数」，聚合/过滤全部由
   本地代码执行。模型幻觉最多导致查不到东西，不会导致数据泄露或损坏。
3. **确认时重新校验**：待确认的参数会回传给后端，但执行前一律重新做
   权限 + 字段校验，不信任客户端回传的内容。
4. **权限随会话**：工具执行时用当前登录主体的模型级权限过滤，
   只读角色问「所有报销记录」也只会看到他被授权的部分；写工具额外要求
   write 权限。
5. **可追溯**：每次真正执行的写操作都写审计日志（谁、经 AI、改了什么）。
6. **上限约束**：最多 6 轮工具调用、单工具返回截断，防死循环与
   上下文爆炸。
"""
from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from . import ai_config as cfg_svc
from .ai import scrub_reasoning
from ..models import EntityType, FieldDefinition, EntityRecord

log = logging.getLogger("kb.agent")

MAX_ROUNDS = 6
MAX_TOOL_ITEMS = 20          # 工具结果最多带多少条明细回给模型
MAX_DATA_KEYS = 60           # 单次写入最多多少字段，防超大 payload


# ============ 工具定义（OpenAI function calling 规范）============

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "list_models",
            "description": "列出系统中所有数据模型（业务表）的名称、Key、字段数、记录数。用户问「有哪些模型/表/业务」时先调这个。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_model_schema",
            "description": "查看某个数据模型的完整字段定义（字段名/Key/类型/是否必填/选项）。不知道字段 Key 时先调这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_key": {"type": "string", "description": "模型 Key"},
                },
                "required": ["model_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_records",
            "description": "按关键词搜索业务记录。keyword 用记录里最可能出现的原文（人名、项目名、单号等），不要自己改写。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "model_key": {"type": "string", "description": "限定在某个模型里搜；不传则跨所有模型"},
                    "limit": {"type": "integer", "description": "最多返回几条，默认 10"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stats_records",
            "description": "统计某个模型的记录：总数，或对某个数字字段求和/平均，或按某个字段分组计数。用户问「多少条/总额/平均/按类别分布」时用这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_key": {"type": "string", "description": "模型 Key"},
                    "operation": {
                        "type": "string",
                        "enum": ["count", "sum", "avg", "min", "max"],
                        "description": "count=记录数；其余需配合 field_key 对数字字段运算",
                    },
                    "field_key": {"type": "string", "description": "数字字段的 Key（sum/avg/min/max 时必填）"},
                    "group_by": {"type": "string", "description": "按此字段分组统计，输出每组的数量"},
                },
                "required": ["model_key", "operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "在数据中心文件（文档正文）里做混合检索（关键词+语义向量）。用户找「文件/资料/文档」时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "最多返回几条，默认 8"},
                },
                "required": ["keyword"],
            },
        },
    },

    # ---------- 写工具：调用后不会立即执行，会生成待确认操作交给用户 ----------
    {
        "type": "function",
        "function": {
            "name": "create_record",
            "description": (
                "新建一条业务记录。只在用户明确要求「记一笔 / 新增 / 添加」时调用。"
                "调用前必须先 get_model_schema 拿到字段 Key。"
                "系统会自动生成确认卡片（无需你用文字征求同意），用户点确认后才真正落库。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_key": {"type": "string", "description": "目标模型 Key"},
                    "data": {
                        "type": "object",
                        "description": "字段 Key → 值。只填用户明确给出的信息，其余留空，不要编造。",
                    },
                },
                "required": ["model_key", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_record",
            "description": (
                "修改一条已有记录。只在用户明确要求「改 / 更新」时调用。"
                "不确定 record_id 时先用 search_records 找到它。"
                "data 里只放要修改的字段，未提及的字段保持原值。"
                "系统会自动生成确认卡片（无需你用文字征求同意）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_key": {"type": "string", "description": "记录所属模型 Key"},
                    "record_id": {"type": "integer", "description": "记录 ID"},
                    "data": {"type": "object", "description": "要修改的字段 Key → 新值"},
                },
                "required": ["model_key", "record_id", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_record",
            "description": (
                "删除一条记录（进回收站，可在「回收站」页恢复）。"
                "只在用户明确要求「删掉 / 移除」时调用；不确定 record_id 时先搜索。"
                "系统会自动生成确认卡片（无需你用文字征求同意）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_key": {"type": "string", "description": "记录所属模型 Key"},
                    "record_id": {"type": "integer", "description": "记录 ID"},
                },
                "required": ["model_key", "record_id"],
            },
        },
    },
]

# 会改动数据的工具：只提议、不直接执行
WRITE_TOOLS = {"create_record", "update_record", "delete_record"}

WRITE_LABELS = {
    "create_record": "新建记录",
    "update_record": "修改记录",
    "delete_record": "删除记录",
}


# ============ 工具实现（全部只读，权限随会话）============

async def _alive_types(db: AsyncSession) -> list[EntityType]:
    from sqlalchemy.orm import selectinload
    ets = (
        await db.execute(
            select(EntityType)
            .options(selectinload(EntityType.fields))
            .where(EntityType.deleted_at.is_(None))
            .order_by(EntityType.order, EntityType.id)
        )
    ).scalars().all()
    return list(ets)


async def _type_by_key(db: AsyncSession, key: str) -> EntityType | None:
    from sqlalchemy.orm import selectinload
    return (
        await db.execute(
            select(EntityType)
            .options(selectinload(EntityType.fields))
            .where(EntityType.key == key, EntityType.deleted_at.is_(None))
        )
    ).scalar_one_or_none()


def _record_label(data: dict) -> str:
    """记录的一行摘要：取前几个非空字符串值"""
    parts = []
    for v in (data or {}).values():
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        if len(parts) >= 4:
            break
    return " | ".join(parts) or "（空记录）"


async def tool_list_models(db: AsyncSession, principal) -> dict:
    ets = await _alive_types(db)
    counts = dict(
        (
            await db.execute(
                select(EntityRecord.entity_type_id, func.count(EntityRecord.id))
                .where(EntityRecord.deleted_at.is_(None))
                .group_by(EntityRecord.entity_type_id)
            )
        ).all()
    )
    out = []
    for t in ets:
        if not principal.can_model(t.key, "read"):
            continue
        out.append({
            "key": t.key,
            "name": t.name,
            "app": t.app,
            "field_count": len(t.fields or []),
            "record_count": counts.get(t.id, 0),
            "fields": [f"{f.key}({f.name},{f.type})" for f in (t.fields or [])][:12],
        })
    return {"models": out, "total": len(out)}


async def tool_get_model_schema(db: AsyncSession, principal, model_key: str) -> dict:
    t = await _type_by_key(db, model_key)
    if not t or not principal.can_model(t.key, "read"):
        return {"error": f"模型「{model_key}」不存在或无权访问"}
    return {
        "key": t.key,
        "name": t.name,
        "description": t.description or "",
        "fields": [
            {
                "key": f.key, "name": f.name, "type": f.type,
                "required": bool(f.required),
                "options": f.options or {},
            }
            for f in sorted(t.fields or [], key=lambda f: (f.order or 0, f.id))
        ],
    }


async def tool_search_records(
    db: AsyncSession, principal, keyword: str, model_key: str | None = None, limit: int = 10
) -> dict:
    limit = max(1, min(int(limit or 10), MAX_TOOL_ITEMS))
    like = f"%{keyword}%"
    q = select(EntityRecord).where(
        EntityRecord.search_text.like(like),
        EntityRecord.deleted_at.is_(None),
    )
    if model_key:
        t = await _type_by_key(db, model_key)
        if not t or not principal.can_model(t.key, "read"):
            return {"error": f"模型「{model_key}」不存在或无权访问"}
        q = q.where(EntityRecord.entity_type_id == t.id)
    q = q.order_by(EntityRecord.updated_at.desc()).limit(limit)
    records = (await db.execute(q)).scalars().all()

    ets = {t.id: t for t in await _alive_types(db)}
    out = []
    for r in records:
        et = ets.get(r.entity_type_id)
        if not et or not principal.can_model(et.key, "read"):
            continue
        out.append({
            "record_id": r.id,
            "model": et.key,
            "model_name": et.name,
            "summary": _record_label(r.data),
            "updated_at": str(r.updated_at or ""),
        })
    return {"items": out, "count": len(out)}


async def tool_stats_records(
    db: AsyncSession, principal,
    model_key: str, operation: str = "count",
    field_key: str | None = None, group_by: str | None = None,
) -> dict:
    t = await _type_by_key(db, model_key)
    if not t or not principal.can_model(t.key, "read"):
        return {"error": f"模型「{model_key}」不存在或无权访问"}
    fields = {f.key: f for f in (t.fields or [])}

    base = select(EntityRecord).where(
        EntityRecord.entity_type_id == t.id,
        EntityRecord.deleted_at.is_(None),
    ).subquery()

    if group_by:
        if group_by not in fields:
            return {"error": f"模型「{model_key}」没有字段「{group_by}」"}
        # JSON 字段分组：SQLite json_extract；空值归为「未填」
        expr = func.json_extract(base.c.data, f"$.{group_by}")
        q = (
            select(expr, func.count(base.c.id))
            .group_by(expr)
            .order_by(func.count(base.c.id).desc())
            .limit(MAX_TOOL_ITEMS)
        )
        rows = (await db.execute(q)).all()
        return {
            "model": model_key, "operation": "group_count", "group_by": group_by,
            "groups": [{"value": r[0] if r[0] is not None else "（未填）", "count": r[1]} for r in rows],
        }

    if operation == "count":
        n = (await db.execute(select(func.count(base.c.id)))).scalar() or 0
        return {"model": model_key, "operation": "count", "count": n}

    # sum/avg/min/max：只允许数字字段，防 LLM 拿文本字段瞎算
    f = fields.get(field_key or "")
    if not f:
        return {"error": f"请提供要统计的数字字段 Key；模型「{model_key}」的字段有：{'、'.join(fields) or '（无）'}"}
    if f.type != "number":
        return {"error": f"字段「{f.name}」类型是 {f.type}，只有 number 字段能做 {operation}"}
    expr = func.json_extract(base.c.data, f"$.{field_key}")
    agg = {
        "sum": func.sum(expr), "avg": func.avg(expr),
        "min": func.min(expr), "max": func.max(expr),
    }[operation]
    val = (await db.execute(select(agg))).scalar()
    return {
        "model": model_key, "operation": operation, "field": field_key,
        "value": round(float(val), 2) if val is not None else None,
    }


async def tool_search_documents(db: AsyncSession, keyword: str, limit: int = 8) -> dict:
    from . import document as doc_svc
    limit = max(1, min(int(limit or 8), MAX_TOOL_ITEMS))
    try:
        res = await doc_svc.search_documents(db, keyword, limit=limit, mode="hybrid")
        items = [
            {
                "document_id": it.get("id"),
                "title": it.get("title") or "",
                "kind": it.get("kind") or "",
                "summary": (it.get("summary") or "")[:100],
            }
            for it in res.get("items", [])
        ]
        return {"items": items, "count": len(items)}
    except Exception as e:
        log.warning("agent 文档检索失败：%s", e)
        return {"items": [], "count": 0, "note": "文档索引暂不可用"}


# ============ 写工具：校验 → 预览（待确认） → 执行 ============

def _display(value) -> str:
    """把字段值渲染成给人看的一行字"""
    if value is None:
        return "（空）"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return "、".join(_display(v) for v in value) or "（空）"
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False)[:120]
        except Exception:
            return str(value)[:120]
    return str(value)[:200]


def _normalize(field: FieldDefinition, raw):
    """按字段类型归一化模型给的值。

    模型可能给 JSON 原生类型（380）也可能给字符串（"380 元"）：
    结构化值直接放行，字符串走和 CSV 导入**同一套**转换函数，
    避免两条写入路径的宽严程度不一致。
    """
    from . import record as rec_svc
    if raw is None:
        return None
    if isinstance(raw, str):
        return rec_svc.coerce_field_value(field, raw)
    if field.type == "number" and isinstance(raw, (int, float)):
        v = float(raw)
        return int(v) if v == int(v) else v
    if field.type == "boolean" and not isinstance(raw, bool):
        return bool(raw)
    if field.type == "multiselect" and isinstance(raw, list):
        return [str(x) for x in raw]
    return raw


def _validate_payload(
    fields: list[FieldDefinition], data: dict, *, partial: bool, model_key: str = ""
) -> tuple[dict, list[str], list[str]]:
    """校验模型填的数据 → (干净数据, 错误, 警告)

    - 未知字段 Key 直接报错并列出合法 Key：让模型下一轮自己改对，
      而不是静默丢弃造成「以为改了其实没改」
    - 必填缺失：新建时算错误；修改时（partial）不算，因为原值还在
    - 数字字段转不成数字 → 错误
    - 单选值不在选项里 → 警告（选项可能没配全，不拦）
    """
    by_key = {f.key: f for f in fields}
    if not isinstance(data, dict) or not data:
        return {}, ["没有提供任何字段值"], []
    if len(data) > MAX_DATA_KEYS:
        return {}, [f"一次最多填写 {MAX_DATA_KEYS} 个字段"], []

    clean: dict = {}
    errors: list[str] = []
    warnings: list[str] = []

    for key, raw in data.items():
        f = by_key.get(str(key))
        if not f:
            errors.append(
                f"字段「{key}」不存在；模型「{model_key or '该模型'}」的合法字段 Key 是："
                f"{'、'.join(by_key) or '（无）'}"
            )
            continue
        val = _normalize(f, raw)
        if f.type == "number" and val is not None and not isinstance(val, (int, float)):
            errors.append(f"字段「{f.name}」是数字类型，得到「{raw}」")
            continue
        if f.type in ("select", "multiselect"):
            opts = (f.options or {}).get("choices") or (f.options or {}).get("options") or []
            if opts:
                picked = val if isinstance(val, list) else [val]
                bad = [str(p) for p in picked if p not in [str(o) for o in opts]]
                if bad:
                    warnings.append(
                        f"「{f.name}」的值 { '、'.join(bad) } 不在预设选项中"
                        f"（可选：{'、'.join(str(o) for o in opts)}）"
                    )
        clean[f.key] = val

    if not partial:
        missing = [f.name for f in fields if f.required and not clean.get(f.key)]
        if missing:
            errors.append(f"必填字段缺失：{'、'.join(missing)}")

    return clean, errors, warnings


async def _load_target(db: AsyncSession, principal, model_key: str):
    """解析目标模型并检查写权限 → (EntityType, error)"""
    key = (model_key or "").strip()
    if not key:
        return None, "缺少 model_key"
    t = await _type_by_key(db, key)
    if not t:
        return None, f"模型「{key}」不存在或已在回收站"
    if not principal.can_model(t.key, "write"):
        return None, f"当前账号对模型「{t.name}」没有写权限，不能执行这个操作"
    return t, None


async def prepare_write(db: AsyncSession, principal, name: str, args: dict) -> dict:
    """把一次写调用整理成「待确认操作」。

    成功：{"pending": {...}}；失败：{"error": "给人看的原因"}。
    失败原因会被回灌给模型（作为工具结果），模型据此自我修正或如实告知用户。
    """
    args = args or {}
    if name not in WRITE_TOOLS:
        return {"error": f"「{name}」不是可执行的写操作"}
    t, err = await _load_target(db, principal, args.get("model_key"))
    if err:
        return {"error": err}
    fields = sorted(t.fields or [], key=lambda f: (f.order or 0, f.id or 0))

    if name == "create_record":
        clean, errors, warnings = _validate_payload(
            fields, args.get("data") or {}, partial=False, model_key=t.key)
        if errors:
            return {"error": "；".join(errors)}
        rows = [
            {"key": f.key, "name": f.name, "type": f.type,
             "value": _display(clean.get(f.key)) if f.key in clean else "",
             "changed": f.key in clean}
            for f in fields
        ]
        pending = {
            "tool": name, "title": WRITE_LABELS[name], "risk": "create",
            "args": {"model_key": t.key, "data": clean},
            "model": {"key": t.key, "name": t.name, "id": t.id},
            "record_id": None, "record_label": "",
            "fields": rows,
            "warnings": warnings,
            "summary": f"在「{t.name}」新建 1 条记录（填写了 {len(clean)} 个字段）",
            "note": "确认后立即写入，可在记录页查看",
        }
        return {"pending": pending}

    # ---- 定位记录 ----
    try:
        rid = int(args.get("record_id"))
    except (TypeError, ValueError):
        return {"error": "record_id 必须是整数；不确定时先用 search_records 找到目标记录"}
    rec = await db.get(EntityRecord, rid)
    if not rec or rec.deleted_at:
        return {"error": f"记录 #{rid} 不存在或已在回收站"}
    if rec.entity_type_id != t.id:
        return {"error": f"记录 #{rid} 不属于模型「{t.name}」"}

    by_key = {f.key: f for f in fields}
    old_data = rec.data or {}
    label = _record_label(old_data)

    if name == "update_record":
        clean, errors, warnings = _validate_payload(
            fields, args.get("data") or {}, partial=True, model_key=t.key)
        if errors:
            return {"error": "；".join(errors)}
        if not clean:
            return {"error": "没有提供任何要修改的字段值"}
        unchanged = [
            by_key[k].name for k, v in clean.items()
            if k in old_data and _display(old_data.get(k)) == _display(v)
        ]
        changed = {k: v for k, v in clean.items()
                   if _display(old_data.get(k)) != _display(v)}
        if not changed:
            return {"error": f"这些字段的值与原值完全相同（{'、'.join(unchanged)}），无需修改"}
        rows = [
            {"key": k, "name": by_key[k].name, "type": by_key[k].type,
             "old": _display(old_data.get(k)), "value": _display(v), "changed": True}
            for k, v in changed.items()
        ]
        pending = {
            "tool": name, "title": WRITE_LABELS[name], "risk": "update",
            "args": {"model_key": t.key, "record_id": rid, "data": changed},
            "model": {"key": t.key, "name": t.name, "id": t.id},
            "record_id": rid, "record_label": label,
            "fields": rows, "warnings": warnings,
            "summary": f"修改「{t.name}」的记录 #{rid}（{len(changed)} 个字段）",
            "note": f"未提及的字段保持原值；原值：{'；'.join(f'{by_key[k].name}={_display(old_data.get(k))}' for k in changed)}",
        }
        return {"pending": pending}

    # ---- delete_record ----
    pending = {
        "tool": name, "title": WRITE_LABELS[name], "risk": "delete",
        "args": {"model_key": t.key, "record_id": rid},
        "model": {"key": t.key, "name": t.name},
        "record_id": rid, "record_label": label,
        "fields": [], "warnings": [],
        "danger": True,
        "summary": f"删除「{t.name}」的记录 #{rid}",
        "note": "记录会进回收站，可在「回收站」页恢复；不是物理删除",
    }
    return {"pending": pending}


async def exec_write(db: AsyncSession, principal, name: str, args: dict) -> dict:
    """真正执行写操作。**执行前一定重新校验** —— 参数可能来自前端回传。"""
    from . import record as rec_svc
    from . import audit as audit_svc

    prep = await prepare_write(db, principal, name, args)
    if prep.get("error"):
        return {"ok": False, "error": prep["error"]}
    p = prep["pending"]
    clean = p["args"]

    who = str(principal.id if principal.id is not None else principal.username)
    if not _dedup_allow(who, name, {k: v for k, v in clean.items()}):
        return {"ok": False, "error": "这个操作刚刚已经执行过了（重复提交已拦截），"
                                      "请不要重复提交；如果确实要再记一笔一样的，"
                                      f"请等待 {int(DEDUP_WINDOW)} 秒后再试。"}

    t = await _type_by_key(db, clean["model_key"])
    if not t:
        return {"ok": False, "error": f"模型「{clean['model_key']}」不存在"}

    if name == "create_record":
        rec = await rec_svc.create_record(db, t.id, clean["data"])
        if not rec:
            return {"ok": False, "error": "写入失败：模型不存在或已在回收站"}
        result = {"ok": True, "action": "created", "model": t.key,
                  "model_name": t.name, "record_id": rec.id}
    elif name == "update_record":
        rec = await db.get(EntityRecord, clean["record_id"])
        if not rec or rec.deleted_at:
            return {"ok": False, "error": f"记录 #{clean['record_id']} 不存在"}
        merged = {**(rec.data or {}), **clean["data"]}      # 只覆盖要改的字段
        rec = await rec_svc.update_record(db, clean["record_id"], merged)
        if not rec:
            return {"ok": False, "error": "写入失败：记录不存在"}
        result = {"ok": True, "action": "updated", "model": t.key,
                  "model_name": t.name, "record_id": rec.id,
                  "changed": {k: _display(v) for k, v in clean["data"].items()}}
    else:
        ok = await rec_svc.delete_record(db, clean["record_id"])
        if not ok:
            return {"ok": False, "error": f"记录 #{clean['record_id']} 不存在或已在回收站"}
        result = {"ok": True, "action": "deleted", "model": t.key,
                  "model_name": t.name, "record_id": clean["record_id"],
                  "note": "已移入回收站，可在「回收站」页恢复"}

    # 审计：AI 代执行必须留痕（谁、经哪个工具、动了哪条记录、改了哪些字段）
    try:
        await audit_svc.log_event(
            principal.username, f"ai_agent_{result['action']}",
            user_id=principal.id,
            detail={
                "ai": True, "tool": name, "model": t.key,
                "record_id": result.get("record_id"),
                # 保留原始类型（数字就是数字），审计里才看得出到底写进去了什么
                "data": {
                    k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200])
                    for k, v in (clean.get("data") or {}).items()
                },
            },
            resource="ai_agent", method="POST", path="/api/ai/agent/confirm",
        )
    except Exception as e:      # 审计失败不能影响业务
        log.warning("AI 写操作审计失败：%s", e)

    result["label"] = p.get("record_label") or _record_label(clean.get("data") or {})
    return result


# ============ 执行循环 ============

TOOL_IMPLS = {}     # name -> impl(db, principal, **args)


def _register(impl):
    TOOL_IMPLS[impl.__name__.replace("tool_", "")] = impl
    return impl


_register(tool_list_models)
_register(tool_get_model_schema)
_register(tool_search_records)
_register(tool_stats_records)
_register(tool_search_documents)


SYSTEM_PROMPT = """你是知识工作台里的 AI 助理，可以调用一组工具查询系统数据、并按用户要求改写数据。

查询类工具（list_models / get_model_schema / search_records / stats_records / search_documents）
会立即执行，规则：
1. 回答数据相关问题前，优先调用工具获取真实数据，不要凭空编造数字。
2. 不知道模型或字段名时，先 list_models / get_model_schema 再操作。
3. 工具返回不了的信息（比如用户问的数据不存在），如实告知，不要脑补。
4. 回答用简体中文，简洁自然；数字给出时注明单位和统计口径。

写入类工具（create_record / update_record / delete_record）不会立即生效：
调用后系统会把操作整理成清单，交给用户在界面上确认，用户点确认才真正落库。
规则：
5. 只在用户**明确要求**增删改时才调用写工具；用户只是问问，就只用查询工具回答。
6. 调用写工具前先用 get_model_schema 确认字段 Key；模型和字段必须用真实存在的 Key。
7. 字段值只填用户明确给出的信息。用户没说的字段留空，**绝不编造**（尤其是金额、日期、人名）。
8. 用户要改/删的记录如果没给出 ID，先用 search_records 找到它再动手；找不到就如实说找不到。
9. 一次只做用户说的那一件事。不要顺手改别的字段、不要批量操作。
10. **直接调用写工具**，不要在回复里用文字或表格罗列字段、再问用户「是否确认」——
    那是在重复系统的工作：只要工具被调用，界面会自动弹出确认卡片让用户逐项核对。
    你只需要在调用前用一句话说明打算做什么。

回答怎么排版（回答显示在一条**宽度有限的对话气泡**里，排版不当会非常难读）：
11. 先用一句话给结论（如「系统里共有 9 个数据模型：」），再给展开内容；不要一上来就是大表格。
12. 表格最多 5 列，单元格里只放短值（数字、状态、姓名）。
    像「主要字段」这种偏长的列，宁可挪出来改成「每个模型一行」的列表，也不要塞进表格挤成一团。
13. 表格第一行必须是表头，第二行是 |---|---| 分隔行；列数在每一行保持一致。
14. 不要输出 HTML 标签；不要用 # 一级标题（气泡里没有那么大地方）；
    不要用连续空行或大段分隔线凑高度。
"""


async def _chat_once(messages: list[dict]) -> dict:
    """单次对话：返回 {content, tool_calls}。真实 API 不可用时返回错误标记。"""
    cfg = cfg_svc.get_full_config()
    if not (cfg.get("enabled") and cfg.get("api_key") and cfg.get("base_url")):
        return {"error": "not_configured"}
    payload = {
        "model": cfg.get("model") or "gpt-3.5-turbo",
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 1024),
        "tools": TOOL_SPECS,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
            r = await client.post(
                cfg["base_url"],
                json=payload,
                headers={
                    "Authorization": f"Bearer {(cfg.get('api_key') or '').strip()}",
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        detail = ""
        if isinstance(e, httpx.HTTPStatusError):
            from .ai import STATUS_HINT
            detail = f"{e.response.status_code} {STATUS_HINT.get(e.response.status_code, '')}"
        log.warning("agent 调用失败：%s %s", detail or type(e).__name__, e)
        return {"error": f"AI 接口调用失败：{detail or type(e).__name__}"}

    msg = data["choices"][0]["message"]
    tool_calls = msg.get("tool_calls") or []
    def _tc_args(fn: dict) -> str:
        # OpenAI 规范是 arguments；MiniMax 等厂商返回 args，两者都收
        return fn.get("arguments") or fn.get("args") or "{}"
    return {
        # MiniMax 等推理模型会把思考链混进 content，进 UI 前剥掉
        "content": scrub_reasoning(msg.get("content") or ""),
        "tool_calls": [
            {
                "id": tc["id"],
                "name": tc["function"]["name"],
                "args": json.loads(_tc_args(tc["function"])),
            }
            for tc in tool_calls
        ],
    }


def _call_key(name: str, args: dict) -> str:
    try:
        return f"{name}:{json.dumps(args or {}, sort_keys=True, ensure_ascii=False)}"
    except Exception:
        return f"{name}:{args}"


# 重复提交闸门：确认按钮被双击、或前端重试时，同一个人对同一份参数的
# 写操作在窗口期内只允许落库一次。否则「记一笔」会变成记两笔，
# 而且第二笔和第一笔长得一模一样，事后很难发现。
_RECENT_WRITES: dict[str, float] = {}
DEDUP_WINDOW = 15.0      # 秒


def _dedup_allow(who: str, name: str, args: dict) -> bool:
    import time
    now = time.monotonic()
    for k, ts in list(_RECENT_WRITES.items()):      # 顺手清过期项，防无限增长
        if now - ts > DEDUP_WINDOW:
            _RECENT_WRITES.pop(k, None)
    key = f"{who}|{_call_key(name, args)}"
    if key in _RECENT_WRITES:
        return False
    _RECENT_WRITES[key] = now
    return True


def _read_digest(trace: list[dict], limit: int = 4000) -> list[str]:
    """把只读工具的查询结果压成清单，供「用户确认后」把这轮上下文带回给模型。

    写操作确认是新一轮请求，服务端不保存会话状态，所以本轮查到的数据
    必须随待确认操作一起带走，否则模型确认后就成了睁眼瞎。
    """
    out = []
    total = 0
    for t in trace:
        if t.get("name") in WRITE_TOOLS:
            continue
        try:
            body = json.dumps(t.get("result"), ensure_ascii=False, default=str)
        except Exception:
            body = str(t.get("result"))
        line = f"{t['name']}({json.dumps(t.get('args') or {}, ensure_ascii=False)}) → {body[:600]}"
        total += len(line)
        if total > limit:
            out.append("（更多查询结果已省略）")
            break
        out.append(line)
    return out


async def run_agent(
    db: AsyncSession, question: str, principal,
    history: list[dict] | None = None,
    *,
    confirmed: dict | None = None,
    allow_write: bool | None = None,
) -> dict:
    """Agent 主循环：question → (工具调用×N) → 最终回答

    confirmed 非空时表示「用户已确认执行某个写操作」：先执行它、
    把结果作为已知事实喂给模型，再让模型继续用只读工具收尾。

    返回 {status, answer, tool_calls, pending, rounds, error}
    - status='done' 正常回答；status='awaiting_confirmation' 有写操作待确认
    """
    question = (question or "").strip()
    if not question:
        return {"status": "done", "answer": "问题为空", "tool_calls": [], "rounds": 0}

    if allow_write is None:
        allow_write = bool(cfg_svc.get_full_config().get("agent_write", True))

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-8:]:          # 带上最近几轮，支持追问
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            messages.append({"role": role, "content": str(h["content"])[:4000]})
    messages.append({"role": "user", "content": question})

    trace: list[dict] = []
    done_keys: set[str] = set()

    # ---------- 用户已确认：先执行，再让模型收尾 ----------
    if confirmed:
        name = (confirmed.get("tool") or "").strip()
        args = confirmed.get("args") or {}
        if name not in WRITE_TOOLS:
            return {"status": "done", "answer": f"不认识的写操作「{name}」",
                    "tool_calls": [], "rounds": 0, "error": "bad_tool"}
        result = await exec_write(db, principal, name, args)
        trace.append({"name": name, "args": args, "result": result,
                      "write": True, "confirmed": True})
        done_keys.add(_call_key(name, args))

        facts = [f"[你之前查到的数据]\n" + "\n".join(confirmed.get("digest") or [])] \
            if confirmed.get("digest") else []
        outcome = (
            f"已成功执行" if result.get("ok")
            else f"执行失败：{result.get('error')}"
        )
        extra = json.dumps(
            {k: v for k, v in result.items() if k in ("action", "record_id", "model_name", "note")},
            ensure_ascii=False,
        )
        messages.append({
            "role": "user",
            "content": (
                "【系统通知】用户已在界面上确认执行你提议的操作。\n"
                f"工具：{name}\n参数：{json.dumps(args, ensure_ascii=False, default=str)}\n"
                f"结果：{outcome} {extra}\n"
                + ("\n".join(facts) + "\n" if facts else "")
                + "请用一两句话向用户说明结果（成功了告诉他记录在哪能看，失败了说明原因），"
                  "不要重复调用同一个操作，也不要再提议别的写操作。"
            ),
        })

    for round_no in range(1, MAX_ROUNDS + 1):
        resp = await _chat_once(messages)
        if resp.get("error"):
            if resp["error"] == "not_configured":
                return {
                    "status": "done",
                    "answer": "还没有配置 AI 服务。请到「AI 设置」页填入接口地址与 Key，"
                              "之后我就能直接查询系统数据、按你的要求记账改数据了。",
                    "tool_calls": [], "rounds": 0, "error": "not_configured",
                }
            return {
                "status": "done", "answer": resp["error"], "tool_calls": trace,
                "rounds": round_no, "error": resp["error"],
            }

        calls = resp["tool_calls"]
        if not calls:
            return {
                "status": "done", "answer": resp["content"],
                "tool_calls": trace, "rounds": round_no,
            }

        messages.append({
            "role": "assistant",
            "content": resp["content"] or None,
            "tool_calls": [
                {
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)},
                }
                for c in calls
            ],
        })

        pending_call = None
        for c in calls:
            # ---- 写工具：只提议，不执行 ----
            if c["name"] in WRITE_TOOLS:
                if not allow_write:
                    messages.append(_tool_msg(c["id"], {"error":
                        "AI 写操作已被管理员关闭，请引导用户到对应页面手动操作。"}))
                    trace.append({"name": c["name"], "args": c["args"],
                                  "result": {"error": "写操作已关闭"}, "write": True})
                    continue
                if _call_key(c["name"], c["args"]) in done_keys:
                    messages.append(_tool_msg(c["id"], {"error":
                        "这个操作刚刚已经执行过了，不要重复执行。"}))
                    trace.append({"name": c["name"], "args": c["args"],
                                  "result": {"error": "重复操作已拦截"}, "write": True})
                    continue
                prep = await prepare_write(db, principal, c["name"], c["args"])
                if prep.get("error"):
                    # 参数/权限不对：当作工具结果回灌，让模型自我修正
                    messages.append(_tool_msg(c["id"], {"error": prep["error"]}))
                    trace.append({"name": c["name"], "args": c["args"],
                                  "result": {"error": prep["error"]}, "write": True})
                    continue
                if pending_call is None:
                    p = prep["pending"]
                    p["tool_call_id"] = c["id"]
                    p["digest"] = _read_digest(trace)
                    pending_call = p
                    trace.append({"name": c["name"], "args": c["args"],
                                  "result": {"status": "等待用户确认"}, "write": True,
                                  "pending": True})
                else:
                    messages.append(_tool_msg(c["id"], {"error":
                        "一次只处理一个写操作，请先让用户确认上一个。"}))
                continue

            # ---- 只读工具：直接执行 ----
            impl = TOOL_IMPLS.get(c["name"])
            try:
                if not impl:
                    result = {"error": f"没有工具「{c['name']}」"}
                elif c["name"] == "search_documents":
                    # 文档检索不涉及模型级权限（文件可见性由文档接口自身控制）
                    result = await impl(db, **c["args"])
                else:
                    result = await impl(db, principal, **c["args"])
            except Exception as e:
                log.warning("agent 工具 %s 执行失败：%s", c["name"], e)
                result = {"error": f"工具执行出错：{e}"}
            trace.append({
                "name": c["name"], "args": c["args"],
                "result": result if len(json.dumps(result, ensure_ascii=False, default=str)) < 4000
                          else {"note": "结果过长已截断"},
            })
            messages.append(_tool_msg(c["id"], result))

        if pending_call:
            lead = (resp["content"] or "").strip()
            return {
                "status": "awaiting_confirmation",
                "answer": lead or f"我准备{pending_call['summary']}，确认后执行。",
                "pending": pending_call,
                "tool_calls": trace,
                "rounds": round_no,
            }

    return {
        "status": "done",
        "answer": "这个问题需要的查询步骤太多，我没能完成。换个更具体的问法试试？",
        "tool_calls": trace, "rounds": MAX_ROUNDS, "error": "too_many_rounds",
    }


def _tool_msg(tool_call_id: str, result) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(result, ensure_ascii=False, default=str),
    }
