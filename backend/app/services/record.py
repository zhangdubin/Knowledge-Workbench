"""实体记录 CRUD + 全文检索"""
import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EntityType, FieldDefinition, EntityRecord


def build_search_text(fields: list[FieldDefinition], data: dict[str, Any]) -> str:
    """把记录数据拼接成可全文检索的文本"""
    parts = []
    for f in fields:
        v = data.get(f.key)
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            continue
        parts.append(str(v))
    return " ".join(parts)


async def create_record(
    db: AsyncSession, type_id: int, data: dict
) -> EntityRecord | None:
    et = await db.get(EntityType, type_id)
    if not et or et.deleted_at:
        return None
    # 取字段定义用于构造 search_text
    f_q = select(FieldDefinition).where(FieldDefinition.entity_type_id == type_id)
    fields = (await db.execute(f_q)).scalars().all()

    rec = EntityRecord(
        entity_type_id=type_id,
        data=data,
        search_text=build_search_text(fields, data),
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


async def update_record(
    db: AsyncSession, record_id: int, data: dict
) -> EntityRecord | None:
    rec = await db.get(EntityRecord, record_id)
    if not rec or rec.deleted_at:
        return None
    rec.data = data
    # 重建 search_text
    f_q = select(FieldDefinition).where(FieldDefinition.entity_type_id == rec.entity_type_id)
    fields = (await db.execute(f_q)).scalars().all()
    rec.search_text = build_search_text(fields, data)
    await db.commit()
    await db.refresh(rec)
    return rec


async def delete_record(db: AsyncSession, record_id: int) -> bool:
    """软删除：进回收站，可恢复"""
    rec = await db.get(EntityRecord, record_id)
    if not rec or rec.deleted_at:
        return False
    rec.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ============ 回收站 ============

async def list_deleted_records(
    db: AsyncSession, type_id: int | None = None, limit: int = 200
) -> list[dict]:
    """回收站里的记录（跨模型；限制条数避免超大库拖垮列表）"""
    q = select(EntityRecord).where(EntityRecord.deleted_at.is_not(None))
    if type_id:
        q = q.where(EntityRecord.entity_type_id == type_id)
    q = q.order_by(EntityRecord.deleted_at.desc()).limit(limit)
    records = (await db.execute(q)).scalars().all()

    ets = {
        t.id: t
        for t in (
            await db.execute(
                select(EntityType).where(EntityType.deleted_at.is_(None))
            )
        ).scalars().all()
    }
    out = []
    for r in records:
        et = ets.get(r.entity_type_id)
        out.append({
            "id": r.id,
            "entity_type_id": r.entity_type_id,
            "entity_type_key": et.key if et else "",
            "entity_type_name": et.name if et else "（模型已入回收站）",
            "entity_type_icon": et.icon if et else "📦",
            "data": r.data or {},
            "search_text": r.search_text or "",
            "deleted_at": r.deleted_at,
        })
    return out


async def restore_record(db: AsyncSession, record_id: int) -> dict | None:
    """从回收站恢复记录；模型本身已入回收站时一并恢复模型"""
    rec = await db.get(EntityRecord, record_id)
    if not rec or not rec.deleted_at:
        return None
    rec.deleted_at = None
    et = await db.get(EntityType, rec.entity_type_id)
    model_restored = False
    if et and et.deleted_at:
        et.deleted_at = None
        model_restored = True
    await db.commit()
    # commit 会过期实例；同一会话里再次读取时避免懒加载触发隐式 IO
    await db.refresh(rec)
    return {"record_id": rec.id, "model_restored": model_restored}


async def purge_record(db: AsyncSession, record_id: int) -> bool:
    """彻底删除单条记录（物理删除，不可恢复）"""
    rec = await db.get(EntityRecord, record_id)
    if not rec or not rec.deleted_at:
        return False
    await db.delete(rec)
    await db.commit()
    return True


# ============ 批量导入 / 导出 ============

def coerce_field_value(field: "FieldDefinition", raw: str):
    """按字段类型把文本转成结构化值；转不动就原样返回交给校验报错

    导入 CSV 与 AI 写工具共用：AI 填错类型（比如把「380元」写进数字字段）
    也必须落到同一套判定上，否则两条写入路径的严格程度会不一致。
    """
    if raw is None:
        return None
    v = raw.strip()
    if field.type == "number":
        if v == "":
            return None
        try:
            f = float(v)
            return int(f) if f == int(f) else f
        except ValueError:
            return raw          # 保留原值，让校验层报「不是数字」
    if field.type == "boolean":
        return v.lower() in ("1", "true", "是", "y", "yes")
    if field.type == "multiselect":
        return [s.strip() for s in v.split(",") if s.strip()] if v else []
    return v


async def _fields_of(db: AsyncSession, type_id: int) -> list["FieldDefinition"]:
    """显式加载字段定义（db.get 之后的关系懒加载在 async 会话里不可用）"""
    return (
        await db.execute(
            select(FieldDefinition)
            .where(FieldDefinition.entity_type_id == type_id)
            .order_by(FieldDefinition.order, FieldDefinition.id)
        )
    ).scalars().all()


async def export_records_csv(db: AsyncSession, type_id: int) -> tuple[str, str] | None:
    """全部记录 → CSV 文本（UTF-8 无 BOM，Content-Disposition 由路由层加）

    返回 (filename, csv_text)。列头用字段 key，导入端按 key 映射，
    这样导出→改→导入是闭环。
    """
    import csv, io

    et = await db.get(EntityType, type_id)
    if not et or et.deleted_at:
        return None
    fields = await _fields_of(db, type_id)
    keys = [f.key for f in fields]

    q = (
        select(EntityRecord)
        .where(EntityRecord.entity_type_id == type_id, EntityRecord.deleted_at.is_(None))
        .order_by(EntityRecord.id)
    )
    records = (await db.execute(q)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(keys)
    for r in records:
        data = r.data or {}
        writer.writerow([
            data.get(k) if not isinstance(data.get(k), (list, dict)) else json.dumps(data.get(k), ensure_ascii=False)
            for k in keys
        ])
    fname = f"{et.key or 'records'}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return fname, buf.getvalue()


async def import_records(
    db: AsyncSession, type_id: int, content: str, fmt: str = "csv"
) -> dict:
    """CSV / JSON 批量导入

    CSV 列头必须用字段 key（导出文件天然满足）。
    逐行校验：未知列忽略并在 warnings 里点名；必填缺失/类型不合法记入 errors，
    合法行照常入库——一次导入能救多少救多少，错误行号留给用户改。
    """
    import csv, io, json as _json

    et = await db.get(EntityType, type_id)
    if not et or et.deleted_at:
        return {"error": "数据模型不存在或已在回收站"}
    fields = await _fields_of(db, type_id)
    by_key = {f.key: f for f in fields}

    rows: list[dict] = []
    warnings: list[str] = []
    if fmt == "json":
        try:
            arr = _json.loads(content)
            if isinstance(arr, dict):
                arr = arr.get("items") or arr.get("records") or []
            rows = [r if isinstance(r, dict) else {} for r in arr]
        except _json.JSONDecodeError as e:
            return {"error": f"JSON 解析失败：{e}"}
    else:
        # UTF-8 BOM（Excel 导出的常见形态）顺手剥掉
        if content.startswith("\ufeff"):
            content = content[1:]
        try:
            reader = csv.DictReader(io.StringIO(content))
            header = reader.fieldnames or []
            unknown = [h for h in header if h and h.strip() not in by_key]
            if unknown:
                warnings.append(f"忽略未识别的列：{ '、'.join(unknown) }")
            for i, row in enumerate(reader, start=2):   # 第 1 行是列头
                rows.append({(k or "").strip(): v for k, v in row.items()})
                rows[-1]["__row__"] = i
        except csv.Error as e:
            return {"error": f"CSV 解析失败：{e}"}

    created, errors = 0, []
    for row in rows:
        line_no = row.pop("__row__", None)
        data: dict = {}
        row_errors: list[str] = []
        for f in fields:
            raw = row.get(f.key)
            if raw is None or (isinstance(raw, str) and raw.strip() == ""):
                if f.required:
                    row_errors.append(f"必填字段「{f.name}」缺失")
                continue
            if isinstance(raw, str):
                val = coerce_field_value(f, raw)
                if f.type == "number" and isinstance(val, str):
                    row_errors.append(f"字段「{f.name}」应为数字，得到「{raw}」")
                    continue
                data[f.key] = val
            else:
                data[f.key] = raw          # JSON 导入直接给结构化值
        if row_errors:
            where = f"第 {line_no} 行" if line_no else "某行"
            errors.append({"row": line_no, "reason": "；".join(row_errors)})
            continue
        rec = EntityRecord(entity_type_id=type_id, data=data,
                           search_text=build_search_text(fields, data))
        db.add(rec)
        created += 1
    if created:
        await db.commit()

    return {
        "created": created,
        "failed": len(errors),
        "errors": errors[:50],           # 防大文件刷屏
        "warnings": warnings,
    }


async def get_record(db: AsyncSession, record_id: int) -> dict | None:
    rec = await db.get(EntityRecord, record_id)
    if not rec or rec.deleted_at:
        return None
    et = await db.get(EntityType, rec.entity_type_id)
    return {
        "id": rec.id,
        "entity_type_id": rec.entity_type_id,
        "entity_type_key": et.key if et else "",
        "entity_type_name": et.name if et else "",
        "entity_type_icon": et.icon if et else "📦",
        "data": rec.data or {},
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


async def list_records(
    db: AsyncSession,
    type_id: int,
    page: int = 1,
    page_size: int = 50,
    keyword: str | None = None,
    filters: dict | None = None,
) -> dict:
    """分页查询记录，支持 keyword + 字段过滤"""
    q = select(EntityRecord).where(
        EntityRecord.entity_type_id == type_id,
        EntityRecord.deleted_at.is_(None),
    )

    if keyword:
        like = f"%{keyword}%"
        q = q.where(EntityRecord.search_text.like(like))

    # 过滤
    if filters:
        # SQLite 的 JSON 过滤：data 是 JSON 字符串，可用 json_extract 或 LIKE
        # 为兼容 SQLite，简化用 LIKE 匹配
        for k, v in filters.items():
            if v is None or v == "":
                continue
            q = q.where(EntityRecord.data.like(f'%"{k}": "{v}"%'))

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    q = q.order_by(EntityRecord.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    records = result.scalars().all()

    et = await db.get(EntityType, type_id)
    items = []
    for r in records:
        items.append({
            "id": r.id,
            "entity_type_id": r.entity_type_id,
            "entity_type_key": et.key if et else "",
            "entity_type_name": et.name if et else "",
            "entity_type_icon": et.icon if et else "📦",
            "data": r.data or {},
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def search_all(
    db: AsyncSession, keyword: str, limit: int = 50
) -> list[dict]:
    """跨实体类型的全文检索"""
    if not keyword:
        return []
    like = f"%{keyword}%"
    q = (
        select(EntityRecord)
        .where(
            EntityRecord.search_text.like(like),
            EntityRecord.deleted_at.is_(None),
        )
        .order_by(EntityRecord.updated_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    records = result.scalars().all()

    out = []
    for r in records:
        et = await db.get(EntityType, r.entity_type_id)
        # 截取 snippet
        text = r.search_text or ""
        idx = text.lower().find(keyword.lower())
        if idx >= 0:
            start = max(0, idx - 30)
            end = min(len(text), idx + len(keyword) + 30)
            snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
        else:
            snippet = text[:80]

        out.append({
            "record_id": r.id,
            "entity_type_id": r.entity_type_id,
            "entity_type_key": et.key if et else "",
            "entity_type_name": et.name if et else "",
            "entity_type_icon": et.icon if et else "📦",
            "snippet": snippet,
            "data": r.data or {},
        })
    return out