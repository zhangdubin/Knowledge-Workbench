"""实体记录 CRUD + 全文检索"""
import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EntityType, FieldDefinition, EntityRecord, NoteGroup
from . import access


# 记录里的分组号：data.group_id
# 用 SQLAlchemy 的 JSON 索引（底层是 SQLite 的 json_extract）：
# 分组筛选在库里做，不把上千条记录捞进内存再筛。
_REC_GROUP_ID = EntityRecord.data["group_id"].as_integer()


async def ensure_group_exists(db: AsyncSession, data: dict) -> None:
    """记录里的 group_id 必须指向真实存在的分组

    校验放在服务层而不是路由层：写记录的入口不止一个
    （记录接口、AI 代执行、CSV 导入），从服务层统一把关，
    才不会出现「换个入口就能写进一个不存在的分组」。

    0 与缺省都表示「未分组」，不校验。
    """
    gid = (data or {}).get("group_id")
    if gid is None or gid == "":
        return
    try:
        gid = int(gid)
    except (TypeError, ValueError):
        raise ValueError("分组编号不合法") from None
    if gid <= 0:
        return
    if not await db.get(NoteGroup, gid):
        raise ValueError(f"分组 {gid} 不存在")


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
    data = dict(data or {})
    # 分组号要先验存在：指向已删分组的 id 不该被写进记录里，
    # 否则它会变成一个谁也选不到、也删不掉的幽灵归属。
    await ensure_group_exists(db, data)
    if "group_id" in data and data["group_id"] is None:
        # 显式 null = 未分组：整个键删掉（留 null 会被前端当成「没有分组信息」）
        data.pop("group_id", None)
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
    new_data = dict(data or {})
    if "group_id" in new_data:
        if new_data["group_id"] is None:
            # 显式 null = 移出分组：整个键删掉，别留个 null
            new_data.pop("group_id", None)
        else:
            await ensure_group_exists(db, new_data)
    else:
        # 没传 group_id = 不变：记录的数据是整份替换的，
        # 不把原来的分组带过去的话，别的字段一改分组就掉了。
        old_gid = (rec.data or {}).get("group_id")
        if old_gid is not None:
            new_data["group_id"] = old_gid
    rec.data = new_data
    # 重建 search_text
    f_q = select(FieldDefinition).where(FieldDefinition.entity_type_id == rec.entity_type_id)
    fields = (await db.execute(f_q)).scalars().all()
    rec.search_text = build_search_text(fields, new_data)
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
    group_id: int | None = None,
) -> dict:
    """分页查询记录，支持 keyword + 字段过滤 + 分组过滤"""
    q = select(EntityRecord).where(
        EntityRecord.entity_type_id == type_id,
        EntityRecord.deleted_at.is_(None),
    )

    if keyword:
        like = f"%{keyword}%"
        q = q.where(EntityRecord.search_text.like(like))

    if group_id is not None:
        # group_id 存在 data JSON 里（知识库的分组就是靠它归属的）
        if group_id:
            q = q.where(_REC_GROUP_ID == group_id)
        else:
            # 0 = 未分组：键不存在（取值 NULL）与值为 0 都算未分组。
            # 只判 NULL 的话，前端新建的「未分组」笔记（存的是 0）就漏了。
            q = q.where(or_(_REC_GROUP_ID.is_(None), _REC_GROUP_ID == 0))

    # 字段过滤
    if filters:
        # 按**字段类型**生成条件，而不是一律 LIKE 匹配 JSON 文本。
        #
        # 为什么不一律 LIKE：
        #   记录里的 data 是 JSON 字符串，LIKE 只能匹配文本形态的值。
        #   数字 13800138000 存的是 `"phone": 13800138000`（不带引号），
        #   布尔 true 存的是 `"active": true`（不是 "true"），
        #   多选存的是 `"tags": ["a","b"]`（不是 "a"）。
        #   一律按 `"k": "v"` 去 LIKE，这三种全都匹配不上 ——
        #   筛选面板看着能选，选完一条都不剩，用户只会觉得「筛选坏了」。
        #
        # 所以这里查一次字段定义，拿到每个筛选字段的类型，
        # 再按类型选比较方式（数字比数字、布尔比 1/0、文本比文本）。
        f_q = select(FieldDefinition).where(FieldDefinition.entity_type_id == type_id)
        defs = {d.key: d for d in (await db.execute(f_q)).scalars().all()}
        for k, v in filters.items():
            vals = v if isinstance(v, (list, tuple)) else [v]
            vals = [x for x in vals if x is not None and x != ""]
            if not vals:
                continue
            ftype = defs[k].type if k in defs else "text"
            if ftype == "number":
                nums = []
                for x in vals:
                    try:
                        nums.append(int(x))
                    except (TypeError, ValueError):
                        pass
                if not nums:
                    continue
                q = q.where(EntityRecord.data[k].as_integer().in_(nums))
            elif ftype == "boolean":
                # SQLite 的 json_extract 把 true/false 取成 1/0
                ints = [1 if x in (True, 1, "1", "true", "True") else 0 for x in vals]
                q = q.where(EntityRecord.data[k].as_integer().in_(ints))
            elif ftype == "multiselect":
                # 多选的值在 JSON 里是数组，json_extract 取出的是整个数组文本。
                # 要判「数组里含某一项」，只能退回 LIKE。
                #
                # 但有个坑：data 存的是 **ensure_ascii 的 JSON** ——
                # 中文被转义成 \uXXXX，LIKE 拿中文原文去匹配是匹配不上的
                # （「示例」在库里长成 "\u793a\u4f8b"）。
                # 所以两种形态都试一遍：转义形态 + 原文形态。
                cond = None
                for x in vals:
                    raw = str(x)
                    esc = json.dumps(raw, ensure_ascii=True)[1:-1]
                    c = or_(EntityRecord.data.like(f'%"{raw}"%'),
                            EntityRecord.data.like(f'%"{esc}"%'))
                    cond = c if cond is None else (cond & c)
                if cond is not None:
                    q = q.where(cond)
            else:
                # 文本 / 下拉 / 日期 / 外键：值都是字符串形态
                q = q.where(EntityRecord.data[k].as_string().in_([str(x) for x in vals]))

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
    db: AsyncSession, keyword: str, limit: int = 50, principal=None
) -> list[dict]:
    """跨实体类型的全文检索

    principal 传进来是为了按模型权限裁剪：全局搜索是唯一一条
    「一次把各模型的记录整批返回」的聚合入口。早先它不带权限，
    于是只有笔记读权限的人搜「合同」也能把合同金额、客户名翻出来 ——
    而记录接口本身是拦得住的。这个聚合入口反而成了绕过口。

    过滤在截断之前做：先取 50 条再过滤，能留下的可能只剩几条，
    而用户明明还有更多命中。
    """
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
    )
    if principal is not None:
        # 先把「读不到的模型」在 SQL 层剔掉，再取 limit 条
        read_keys = access.readable_model_keys(principal)
        if read_keys is not None:
            q = q.where(
                EntityRecord.entity_type_id.in_(
                    select(EntityType.id).where(EntityType.key.in_(read_keys))
                )
            )
    q = q.limit(limit)
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