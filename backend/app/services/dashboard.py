"""可视化驾驶舱：卡片配置 → 计算结果

设计要点
--------
1. **卡片配置整体存 JSON**（Dashboard.layout），不拆 Widget 表：
   卡片永远是「随驾驶舱一起读、一起写」的展示产物，拆表会把
   「保存一次布局」变成 N 次增删改，还会引入顺序与孤儿问题。

2. **计算放在服务端一次性完成**（/data 接口返回全部卡片的成品数据）：
   浏览器只负责画，不再逐个卡片发请求 —— N 张卡片就是 N 次往返，
   首屏体验会明显变差。前端只保留「编辑时的单卡预览」接口。

3. **过滤/聚合在 Python 里做**，不下推 SQL：
   字段值是 JSON 里的任意类型（字符串/数字/数组/多选），
   在 SQL 里对 JSON 做类型归一（`"12"` 与 `12` 要能一起比较、
   多选字段要按元素匹配）比在 Python 里难得多，而驾驶舱的数据量
   （单模型几千行以内）完全撑得住内存计算。上限 MAX_SCAN 兜底。

卡片 schema（前端编辑器与这里共用）：
  {
    id, type: stat|chart|gauge|rank|table|list|text,
    title, span: 1..4, unit, color, height: ''|'lg'|'xl',
    text,                                  # type=text 时的 Markdown
    source: {
      kind: entity|document|relation,
      type_id,                             # kind=entity 时的模型 id
      metric: count|sum|avg|min|max,
      field,                               # 指标字段 / 分组字段
      goal,                                # gauge 的目标值（达成率=当前/目标）
      group_by, chart: bar|line|area|bar_h|pie|donut|radar,
      filters: [{field, op, value}],
      sort: desc|asc, limit,
      columns: [...],                      # table 展示列
      range_field, days,                   # 时间窗口（含环比）
    }
  }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Document, EntityRecord, EntityType, FieldDefinition,
    RelationDef, RelationRecord,
)

log = logging.getLogger("kb.dashboard")

MAX_SCAN = 5000          # 单个卡片最多扫描的行数
EMPTY_LABEL = "（空）"

WIDGET_TYPES = ["stat", "chart", "gauge", "rank", "progress", "status", "kpi", "table", "list", "text"]
FILTER_OPS = ["eq", "ne", "contains", "not_contains", "gt", "lt", "gte", "lte",
              "not_empty", "empty", "in"]
METRICS = ["count", "sum", "avg", "min", "max"]
CHART_KINDS = ["bar", "line", "area", "bar_h", "pie", "donut", "radar"]


# ---------- 取值/归一化 ----------

def _flatten(value: Any) -> list:
    """字段值 → 参与比较的标量列表（多选/数组按元素展开）"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for v in value:
            out.extend(_flatten(v))
        return out
    return [value]


def _num(value: Any) -> float | None:
    """尽量转成数字；带千分位/百分号/货币符号的字符串也能认"""
    for v in _flatten(value):
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", "").replace("¥", "").replace("￥", "").replace("%", "")
            try:
                return float(s)
            except ValueError:
                continue
    return None


def _text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(_text(v)) for v in value if v not in (None, ""))
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _label_of(row: dict) -> str:
    for k in ("name", "title", "label", "code", "filename"):
        v = _text(row.get(k))
        if v:
            return v
    return f"#{row.get('id')}"


# ---------- 取数 ----------

async def _entity_rows(db: AsyncSession, type_id: int) -> tuple[list[dict], list[dict]]:
    et = await db.get(EntityType, type_id)
    if not et:
        return [], []
    fields = (await db.execute(
        select(FieldDefinition).where(FieldDefinition.entity_type_id == type_id)
        .order_by(FieldDefinition.order)
    )).scalars().all()
    recs = (await db.execute(
        select(EntityRecord).where(EntityRecord.entity_type_id == type_id)
        .order_by(EntityRecord.id.desc()).limit(MAX_SCAN)
    )).scalars().all()
    rows = []
    for r in recs:
        data = dict(r.data or {})
        data["id"] = r.id
        data["_created_at"] = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
        data["_updated_at"] = r.updated_at.strftime("%Y-%m-%d %H:%M:%S") if r.updated_at else ""
        rows.append(data)
    meta = [{"key": f.key, "name": f.name, "type": f.type} for f in fields]
    return rows, meta


async def _document_rows(db: AsyncSession) -> tuple[list[dict], list[dict]]:
    docs = (await db.execute(
        select(Document).where(Document.deleted_at.is_(None))
        .order_by(Document.id.desc()).limit(MAX_SCAN)
    )).scalars().all()
    rows = []
    for d in docs:
        rows.append({
            "id": d.id, "name": d.title or d.filename, "title": d.title or d.filename,
            "filename": d.filename, "ext": d.ext or "", "kind": d.kind or "other",
            "mime": d.mime or "", "size": d.size or 0, "tags": list(d.tags or []),
            "summary": d.summary or "", "description": d.description or "",
            "extract_status": d.extract_status or "", "embed_status": d.embed_status or "",
            "text_length": len(d.extracted_text or ""),
            "_created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else "",
            "_updated_at": d.updated_at.strftime("%Y-%m-%d %H:%M:%S") if d.updated_at else "",
        })
    meta = [
        {"key": "name", "name": "文件名", "type": "text"},
        {"key": "ext", "name": "扩展名", "type": "text"},
        {"key": "kind", "name": "类型", "type": "select"},
        {"key": "size", "name": "大小", "type": "number"},
        {"key": "tags", "name": "标签", "type": "multiselect"},
        {"key": "extract_status", "name": "抽取状态", "type": "select"},
    ]
    return rows, meta


async def _relation_rows(db: AsyncSession) -> tuple[list[dict], list[dict]]:
    defs = {d.id: d for d in (await db.execute(select(RelationDef))).scalars().all()}
    ets = {e.id: e for e in (await db.execute(select(EntityType))).scalars().all()}
    recs = (await db.execute(
        select(RelationRecord).order_by(RelationRecord.id.desc()).limit(MAX_SCAN)
    )).scalars().all()
    rows = []
    for r in recs:
        rd = defs.get(r.relation_def_id)
        rows.append({
            "id": r.id,
            "name": rd.name if rd else f"#{r.relation_def_id}",
            "relation": rd.name if rd else "",
            "relation_key": rd.key if rd else "",
            "source_type": ets.get(rd.source_type_id).name if rd and ets.get(rd.source_type_id) else "",
            "cardinality": rd.cardinality if rd else "many-to-many",
            "source_record_id": r.source_record_id,
            "target_record_id": r.target_record_id,
            "_created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        })
    meta = [
        {"key": "name", "name": "关联名称", "type": "text"},
        {"key": "source_type", "name": "源模型", "type": "text"},
        {"key": "cardinality", "name": "基数", "type": "select"},
    ]
    return rows, meta


async def load_source(db: AsyncSession, source: dict) -> tuple[list[dict], list[dict]]:
    kind = (source or {}).get("kind") or "entity"
    if kind == "document":
        return await _document_rows(db)
    if kind == "relation":
        return await _relation_rows(db)
    type_id = (source or {}).get("type_id")
    if not type_id:
        return [], []
    return await _entity_rows(db, int(type_id))


# ---------- 过滤 ----------

def _cmp(op: str, actual_list: list, expect: Any) -> bool:
    if op == "empty":
        return all(_text(a) == "" for a in actual_list)
    if op == "not_empty":
        return any(_text(a) != "" for a in actual_list)
    if op == "eq":
        return any(_text(a) == _text(expect) for a in actual_list)
    if op == "ne":
        return all(_text(a) != _text(expect) for a in actual_list)
    if op == "contains":
        return any(_text(expect) and _text(expect) in _text(a) for a in actual_list)
    if op == "not_contains":
        return all(not (_text(expect) and _text(expect) in _text(a)) for a in actual_list)
    if op == "in":
        wants = [x for x in (_flatten(expect) or [])]
        return any(any(_text(a) == _text(w) for w in wants) for a in actual_list)
    # 数值比较：两边都转不出数字时视为不匹配（而不是比较字符串）
    a_nums = [n for n in (_num(v) for v in actual_list) if n is not None]
    b = _num(expect)
    if not a_nums or b is None:
        return False
    if op == "gt":
        return any(n > b for n in a_nums)
    if op == "lt":
        return any(n < b for n in a_nums)
    if op == "gte":
        return any(n >= b for n in a_nums)
    if op == "lte":
        return any(n <= b for n in a_nums)
    return True


def _field_values(row: dict, key: str) -> list:
    """字段取值；支持 `_created_at` 这类内置伪字段与 `tags` 数组字段"""
    if not key:
        return []
    if key in row:
        return _flatten(row.get(key))
    return []


def apply_filters(rows: list[dict], filters: list[dict] | None) -> list[dict]:
    out = rows
    for f in filters or []:
        key = (f or {}).get("field")
        op = (f or {}).get("op") or "eq"
        if not key or op not in FILTER_OPS:
            continue
        expect = (f or {}).get("value")
        out = [r for r in out if _cmp(op, _field_values(r, key), expect)]
    return out


# ---------- 聚合 ----------

def _metric_value(rows: list[dict], metric: str, field: str) -> float:
    if metric == "count" or not field:
        return float(len(rows))
    nums = [n for n in (_num(_field_values(r, field)) for r in rows) if n is not None]
    if not nums:
        return 0.0
    if metric == "sum":
        return float(sum(nums))
    if metric == "avg":
        return float(sum(nums) / len(nums))
    if metric == "min":
        return float(min(nums))
    if metric == "max":
        return float(max(nums))
    return float(len(rows))


def _fmt_value(value: float, metric: str) -> str:
    if metric in ("sum", "avg"):
        if abs(value) >= 1_0000_0000:
            return f"{value / 1_0000_0000:.2f}亿"
        if abs(value) >= 1_0000:
            return f"{value / 1_0000:.2f}万"
    if metric == "avg":
        return f"{value:.1f}"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _group(rows: list[dict], key: str, metric: str, field: str) -> list[tuple[str, float]]:
    """按字段分组聚合；多选字段会被计到每个取值上（总和大于行数是正常的）"""
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        vals = _field_values(r, key) or [""]
        seen = set()
        for v in vals:
            label = _text(v) or EMPTY_LABEL
            if label in seen:
                continue
            seen.add(label)
            buckets.setdefault(label, []).append(r)
    items = [(k, _metric_value(v, metric, field)) for k, v in buckets.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def _date_bucket(row: dict, range_field: str, fmt: str) -> str:
    raw = _text(_field_values(row, range_field))[:10] or ""
    return raw[:7] if fmt == "month" else raw


# ---------- 单卡计算 ----------

async def compute_widget(db: AsyncSession, widget: dict) -> dict:
    wtype = widget.get("type") or "stat"
    out = {
        "id": widget.get("id") or "",
        "type": wtype,
        "title": widget.get("title") or "",
        "span": int(widget.get("span") or 1),
        "unit": widget.get("unit") or "",
        "color": widget.get("color") or "",
        "height": widget.get("height") or "",
        "text": widget.get("text") or "",
        "source": widget.get("source") or {},
        "data": None,
        "error": "",
    }
    if wtype == "text":
        return out

    source = widget.get("source") or {}
    try:
        rows, meta = await load_source(db, source)
    except Exception as e:                     # 配置改坏时只让这一张卡报错
        out["error"] = f"取数失败：{e}"
        return out

    labels = {m["key"]: m["name"] for m in meta}
    rows = apply_filters(rows, source.get("filters"))

    # 时间窗口：给了 range_field + days 就裁一次，
    # 顺带按窗口长度取上一段用于环比（指标卡的价值一半在趋势）
    cutoff = prev_cutoff = None
    days = int(source.get("days") or 0)
    rng = source.get("range_field") or ""
    if days > 0 and rng:
        cutoff = datetime.now() - timedelta(days=days)
        prev_cutoff = cutoff - timedelta(days=days)

    def in_range(row, start, end=None):
        raw = _text(_field_values(row, rng))
        if len(raw) < 10:
            return False
        try:
            ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                ts = datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                return False
        if start and ts < start:
            return False
        if end and ts >= end:
            return False
        return True

    current = rows
    previous = []
    if cutoff:
        current = [r for r in rows if in_range(r, cutoff)]
        previous = [r for r in rows if in_range(r, prev_cutoff, cutoff)]

    metric = source.get("metric") or "count"
    field = source.get("field") or ""
    limit = int(source.get("limit") or 10)
    sort_desc = (source.get("sort") or "desc") != "asc"

    # ---- 指标卡 ----
    if wtype == "stat":
        value = _metric_value(current, metric, field)
        data = {
            "value": _fmt_value(value, metric),
            "raw": round(value, 4),
            "metric": metric,
            "field": field,
            "field_label": labels.get(field, field),
            "count": len(current),
        }
        if cutoff:
            prev_value = _metric_value(previous, metric, field)
            diff = value - prev_value
            data["delta"] = {
                "value": _fmt_value(abs(diff), metric),
                "pct": (round(diff / prev_value * 100, 1) if prev_value else None),
                "direction": "up" if diff > 0 else ("down" if diff < 0 else "flat"),
                "compared": f"对比前 {days} 天",
            }
            # 迷你趋势：把当前窗口按天切开
            series = {}
            for r in current:
                day = _date_bucket(r, rng, "day")
                if day:
                    series[day] = series.get(day, 0) + 1
            data["spark"] = [series.get(
                (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"), 0
            ) for i in range(min(days, 30))]
        out["data"] = data

    # ---- 图表 ----
    elif wtype == "chart":
        chart = source.get("chart") or "bar"
        group_key = source.get("group_by") or ""
        if not group_key:
            out["error"] = "图表需要选择「分组字段」"
            return out
        items = _group(current, group_key, metric, field)
        if not items:
            items = [(EMPTY_LABEL, 0.0)]
        items = sorted(items, key=lambda x: x[1], reverse=sort_desc)[:max(limit, 1)]
        if chart == "line":
            # 折线按时间/字典序排，不按大小 —— 排序错会让趋势完全失真
            items = sorted(items, key=lambda x: x[0])
        out["data"] = {
            "chart": chart,
            "field_label": labels.get(group_key, group_key),
            "metric": metric,
            "categories": [k for k, _ in items],
            "series": [{"name": labels.get(field, field) or "数量", "data": [v for _, v in items]}],
            "total": round(sum(v for _, v in items), 2),
        }

    # ---- 仪表盘（gauge）：当前值 / 目标值 → 达成率 ----
    elif wtype == "gauge":
        try:
            goal = float(source.get("goal") or 0)
        except (TypeError, ValueError):
            goal = 0.0
        if goal <= 0:
            out["error"] = "仪表盘需要填写大于 0 的目标值"
            return out
        value = _metric_value(current, metric, field)
        out["data"] = {
            "value": _fmt_value(value, metric),
            "raw": round(value, 4),
            "goal": round(goal, 4),
            "goal_text": _fmt_value(goal, metric),
            "percent": round(min(value / goal, 9.99) * 100, 1),
            "metric": metric,
            "field": field,
            "field_label": labels.get(field, field),
            "count": len(current),
        }

    # ---- 排行榜（rank）：分组聚合 Top-N，前端用进度条渲染 ----
    elif wtype == "rank":
        group_key = source.get("group_by") or ""
        if not group_key:
            out["error"] = "排行榜需要选择「分组字段」"
            return out
        items = _group(current, group_key, metric, field)
        items = sorted(items, key=lambda x: x[1], reverse=True)[:max(limit, 1)]
        out["data"] = {
            "field_label": labels.get(group_key, group_key),
            "metric": metric,
            "items": [{"name": k, "value": round(v, 4)} for k, v in items],
            "total": round(sum(v for _, v in items), 2),
        }

    # ---- 进度条（progress）：分组占比 / 目标达成 ----
    elif wtype == "progress":
        goal = _num(source.get("goal"))
        group_key = source.get("group_by") or ""
        if group_key:
            items = _group(current, group_key, metric, field)
            items = sorted(items, key=lambda x: x[1], reverse=True)[:max(limit, 1)]
            total = sum(v for _, v in items)
            out["data"] = {
                "mode": "group",
                "field_label": labels.get(group_key, group_key),
                "metric": metric,
                "total": round(total, 4),
                "segments": [
                    {"name": k, "value": round(v, 4),
                     "percent": round(v / total * 100, 1) if total else 0}
                    for k, v in items
                ],
            }
        elif goal and goal > 0:
            value = _metric_value(current, metric, field)
            out["data"] = {
                "mode": "goal",
                "metric": metric,
                "value": round(value, 4),
                "value_text": _fmt_value(value, metric),
                "goal": round(goal, 4),
                "goal_text": _fmt_value(goal, metric),
                "percent": round(min(value / goal, 9.99) * 100, 1),
            }
        else:
            out["error"] = "进度条需要选择「分组字段」或填写大于 0 的目标值"
            return out

    # ---- 状态板（status）：按状态字段分组，红绿灯矩阵 ----
    elif wtype == "status":
        group_key = source.get("group_by") or ""
        if not group_key:
            if source.get("kind") == "document":
                group_key = "extract_status"
            else:
                out["error"] = "状态板需要选择「状态字段」"
                return out
        items = _group(current, group_key, metric, field)
        items = sorted(items, key=lambda x: x[1], reverse=True)[:max(limit, 1)]
        total = sum(v for _, v in items)
        out["data"] = {
            "field_label": labels.get(group_key, group_key),
            "metric": metric,
            "total": round(total, 4),
            "items": [
                {"name": k, "value": round(v, 4),
                 "percent": round(v / total * 100, 1) if total else 0}
                for k, v in items
            ],
        }

    # ---- KPI 卡（kpi）：大数字 + 趋势 + 目标达成 ----
    elif wtype == "kpi":
        value = _metric_value(current, metric, field)
        goal = _num(source.get("goal")) or 0
        data = {
            "value": _fmt_value(value, metric),
            "raw": round(value, 4),
            "metric": metric,
            "field": field,
            "field_label": labels.get(field, field),
            "count": len(current),
            "goal": round(goal, 4) if goal else None,
            "goal_text": _fmt_value(goal, metric) if goal else None,
            "percent": round(min(value / goal, 9.99) * 100, 1) if goal and goal > 0 else None,
        }
        if cutoff:
            prev_value = _metric_value(previous, metric, field)
            diff = value - prev_value
            data["delta"] = {
                "value": _fmt_value(abs(diff), metric),
                "pct": (round(diff / prev_value * 100, 1) if prev_value else None),
                "direction": "up" if diff > 0 else ("down" if diff < 0 else "flat"),
                "compared": f"对比前 {days} 天",
            }
            series = {}
            for r in current:
                day = _date_bucket(r, rng, "day")
                if day:
                    series[day] = series.get(day, 0) + 1
            data["spark"] = [series.get(
                (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"), 0
            ) for i in range(min(days, 30))]
        out["data"] = data

    # ---- 表格 ----
    elif wtype == "table":
        cols = source.get("columns") or []
        if not cols:
            cols = [m["key"] for m in meta[:5]]
        if rng and source.get("sort_by_range", True) and rng in ("_created_at", "_updated_at"):
            rows_sorted = sorted(current, key=lambda r: _text(_field_values(r, rng)), reverse=True)
        else:
            sort_field = source.get("sort_field") or ""
            rows_sorted = (
                sorted(current, key=lambda r: (_num(_field_values(r, sort_field)) or 0), reverse=sort_desc)
                if sort_field else current
            )
        out["data"] = {
            "columns": [{"key": c, "label": labels.get(c, c)} for c in cols],
            "rows": [
                {"_id": r.get("id"), "_label": _label_of(r),
                 **{c: _text(_field_values(r, c)) for c in cols}}
                for r in rows_sorted[:max(limit, 1)]
            ],
            "total": len(rows_sorted),
        }

    # ---- 列表 ----
    elif wtype == "list":
        items = []
        for r in current[:max(limit, 1)]:
            items.append({
                "id": r.get("id"),
                "title": _label_of(r),
                "sub": _text(r.get("summary") or r.get("description") or r.get("ext") or ""),
                "time": _text(r.get("_updated_at") or r.get("_created_at")),
                "tags": [t for t in (_flatten(r.get("tags")) or [])][:3],
                "kind": _text(r.get("kind") or r.get("ext") or ""),
            })
        out["data"] = {"items": items, "total": len(current)}

    else:
        out["error"] = f"未知卡片类型：{wtype}"
    return out


async def compute_layout(db: AsyncSession, layout: list[dict] | None) -> list[dict]:
    return [await compute_widget(db, w) for w in (layout or [])]


# ---------- 数据源选项（供编辑器下拉） ----------

async def source_options(db: AsyncSession) -> dict:
    types = (await db.execute(
        select(EntityType)
        .where(EntityType.deleted_at.is_(None))
        .order_by(EntityType.order, EntityType.id)
    )).scalars().all()
    out = []
    for t in types:
        rows, meta = await _entity_rows(db, t.id)
        out.append({
            "id": t.id, "key": t.key, "name": t.name, "icon": t.icon,
            "count": len(rows), "fields": meta,
        })
    _, doc_meta = await _document_rows(db)
    _, rel_meta = await _relation_rows(db)
    return {
        "entity_types": out,
        "document_fields": doc_meta,
        "relation_fields": rel_meta,
        "kinds": [
            {"key": "entity", "name": "业务模型"},
            {"key": "document", "name": "数据中心文件"},
            {"key": "relation", "name": "关联关系"},
        ],
        "metrics": METRICS,
        "charts": CHART_KINDS,
        "ops": FILTER_OPS,
        "widget_types": WIDGET_TYPES,
    }


# ---------- 模板 ----------

# 自由画布的基准（与前端 frontend/src/utils/canvas.js 保持一致）
CANVAS_WIDTH = 1440
CANVAS_GAP = 16
LEGACY_COLS = 4
_COL_W = (CANVAS_WIDTH - (LEGACY_COLS - 1) * CANVAS_GAP) / LEGACY_COLS      # 348

# 各类型的默认高度，同样对齐前端 DEFAULT_SIZE
_DEFAULT_H = {"stat": 132, "gauge": 248, "chart": 320, "rank": 300,
              "progress": 180, "status": 240, "kpi": 180,
              "table": 320, "list": 300, "text": 168}
_HEIGHT_STEP = {"": 0, "lg": 80, "xl": 160}


def pack_layout(items: list[dict]) -> list[dict]:
    """把「占几列宽」的老写法换算成自由画布的 w/h，坐标留给前端按容器宽度归一化。

    不在这里直接算 x/y：不同屏幕宽度差异大，后端不知道用户浏览器视口，
    提前写死坐标反而会让右侧出现大量空白。前端在 mount 时用容器宽度做
    shelf-pack + 自动拉伸，刚好铺满一行。
    """
    sized: list[dict] = []
    for raw in items:
        item = dict(raw)
        try:
            span = int(item.pop("span", 1) or 1)
        except (TypeError, ValueError):
            span = 1
        span = max(1, min(span, LEGACY_COLS))
        step = item.pop("height", "") or ""
        item["w"] = round(span * _COL_W + (span - 1) * CANVAS_GAP)
        item["h"] = _DEFAULT_H.get(item.get("type", "stat"), 200) + _HEIGHT_STEP.get(step, 0)
        # 去掉旧字段，避免前后端各算一遍坐标对不上
        item.pop("x", None)
        item.pop("y", None)
        sized.append(item)
    return sized


def templates(types: list[dict], has_docs: bool = True) -> list[dict]:
    """预置驾驶舱：先给一个能用的成品，再让用户改"""
    def t(key, name, icon, desc, layout, settings=None):
        return {"key": key, "name": name, "icon": icon, "description": desc,
                "layout": pack_layout(layout), "settings": settings or {}}

    first = types[0] if types else None
    stat_source = {"kind": "entity", "type_id": first["id"] if first else None,
                   "metric": "count", "field": "", "limit": 10}
    docs = {"kind": "document", "metric": "count", "field": "", "limit": 10}

    return [
        t("overview", "运营总览", "📊", "记录与文件的核心指标，适合放在工作台第一屏", [
            {"id": "w1", "type": "stat", "title": "记录总数", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 30}},
            {"id": "w2", "type": "stat", "title": "文件总数", "span": 1,
             "source": {**docs, "range_field": "_created_at", "days": 30}},
            {"id": "w3", "type": "stat", "title": "近 30 天新增记录", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 30}},
            {"id": "w4", "type": "stat", "title": "关联关系数", "span": 1,
             "source": {"kind": "relation", "metric": "count"}},
            {"id": "w5", "type": "chart", "title": "文件类型分布", "span": 2,
             "source": {"kind": "document", "metric": "count", "group_by": "kind",
                        "chart": "pie", "limit": 8}},
            {"id": "w6", "type": "list", "title": "最近更新", "span": 2,
             "source": {"kind": "document", "limit": 8}},
        ]),
        t("files", "文件资产", "🗂️", "看清文件构成、抽取与向量化进度", [
            {"id": "f1", "type": "stat", "title": "文件数", "span": 1,
             "source": {"kind": "document", "metric": "count"}},
            {"id": "f2", "type": "stat", "title": "占用空间", "span": 1, "unit": "byte",
             "source": {"kind": "document", "metric": "sum", "field": "size"}},
            {"id": "f3", "type": "gauge", "title": "向量化进度", "span": 1,
             "source": {"kind": "document", "metric": "count", "goal": 100,
                        "filters": [{"field": "embed_status", "op": "eq", "value": "ok"}]}},
            {"id": "f4", "type": "chart", "title": "按扩展名", "span": 1,
             "source": {"kind": "document", "metric": "count", "group_by": "ext",
                        "chart": "bar", "limit": 8}},
            {"id": "f5", "type": "table", "title": "文件明细", "span": 4,
             "source": {"kind": "document", "limit": 12,
                        "columns": ["name", "ext", "size", "kind", "extract_status"]}},
        ]),
        t("screen", "经营大屏", "🖥️", "全屏投放用：指标 + 排行榜 + 仪表盘 + 趋势，深色科技风",
          [
            {"id": "s1", "type": "stat", "title": "记录总数", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 30}},
            {"id": "s2", "type": "stat", "title": "文件总数", "span": 1,
             "source": {**docs, "range_field": "_created_at", "days": 30}},
            {"id": "s3", "type": "gauge", "title": "本月新增 vs 目标", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 30, "goal": 50}},
            {"id": "s4", "type": "stat", "title": "关联关系数", "span": 1,
             "source": {"kind": "relation", "metric": "count"}},
            {"id": "s5", "type": "chart", "title": "近 30 天新增趋势", "span": 2,
             "source": {**stat_source, "range_field": "_created_at", "days": 30,
                        "group_by": "_created_at", "chart": "area", "limit": 30}},
            {"id": "s6", "type": "rank", "title": "文件类型排行", "span": 2,
             "source": {"kind": "document", "metric": "count", "group_by": "kind", "limit": 8}},
          ],
          {"theme": "nebula", "auto_refresh": 30, "show_clock": True}),
        t("system", "系统状态", "🚦", "科技感状态矩阵 + 进度 + KPI，适合监控业务健康度",
          [
            {"id": "x1", "type": "kpi", "title": "总记录数", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 30}},
            {"id": "x2", "type": "kpi", "title": "本周新增", "span": 1,
             "source": {**stat_source, "range_field": "_created_at", "days": 7}},
            {"id": "x3", "type": "gauge", "title": "文件向量化进度", "span": 1,
             "source": {"kind": "document", "metric": "count", "goal": 100,
                        "filters": [{"field": "embed_status", "op": "eq", "value": "ok"}]}},
            {"id": "x4", "type": "progress", "title": "文件类型占比", "span": 1,
             "source": {"kind": "document", "metric": "count", "group_by": "kind", "limit": 8}},
            {"id": "x5", "type": "status", "title": "文件抽取状态", "span": 2,
             "source": {"kind": "document", "metric": "count"}},
            {"id": "x6", "type": "chart", "title": "近 30 天活跃趋势", "span": 2,
             "source": {**stat_source, "range_field": "_created_at", "days": 30,
                        "group_by": "_created_at", "chart": "area", "limit": 30}},
          ],
          {"theme": "aurora", "auto_refresh": 60}),
    ]
