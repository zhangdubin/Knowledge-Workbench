"""实体记录 CRUD 路由

每个接口都做「模型级」读写校验：只读角色能看不能改，
被限制的模型连列表都拿不到（而不是拿到后由前端藏起来）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityRecord, EntityType
from ..schemas import RecordIn
from ..services import audit as audit_svc
from ..services import record as svc
from ..services.auth import Principal, current_principal, ensure_model

router = APIRouter(prefix="/api/records", tags=["records"])


async def _type_key(db: AsyncSession, type_id: int) -> str:
    et = await db.get(EntityType, type_id)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    return et.key


async def _record_type_key(db: AsyncSession, record_id: int) -> str:
    rec = await db.get(EntityRecord, record_id)
    if not rec:
        raise HTTPException(404, "记录不存在")
    et = await db.get(EntityType, rec.entity_type_id)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    return et.key


@router.get("/type/{type_id}")
async def list_records(
    type_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_model(principal, await _type_key(db, type_id), "read")
    return await svc.list_records(db, type_id, page, page_size, keyword)


@router.get("/{record_id}")
async def get_record(record_id: int, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    ensure_model(principal, await _record_type_key(db, record_id), "read")
    rec = await svc.get_record(db, record_id)
    if not rec:
        raise HTTPException(404, "记录不存在")
    return rec


@router.post("/type/{type_id}")
async def create_record(
    type_id: int, payload: RecordIn, request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_model(principal, await _type_key(db, type_id), "write")
    rec = await svc.create_record(db, type_id, payload.data)
    if not rec:
        raise HTTPException(404, "数据模型不存在")
    audit_svc.mark_created(request, rec.id)
    return await svc.get_record(db, rec.id)


@router.put("/{record_id}")
async def update_record(
    record_id: int, payload: RecordIn, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_model(principal, await _record_type_key(db, record_id), "write")
    rec = await svc.update_record(db, record_id, payload.data)
    if not rec:
        raise HTTPException(404, "记录不存在")
    return await svc.get_record(db, rec.id)


@router.delete("/{record_id}")
async def delete_record(record_id: int, db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    ensure_model(principal, await _record_type_key(db, record_id), "write")
    if not await svc.delete_record(db, record_id):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


# ============ 批量导入 / 导出 ============

class ImportIn(BaseModel):
    content: str
    format: str = "csv"          # csv | json


@router.get("/type/{type_id}/export")
async def export_records(
    type_id: int, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_model(principal, await _type_key(db, type_id), "read")
    result = await svc.export_records_csv(db, type_id)
    if not result:
        raise HTTPException(404, "数据模型不存在")
    fname, text = result
    # 带 BOM：Excel 双击打开中文不乱码；导入端会剥掉
    return Response(
        content="\ufeff" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/type/{type_id}/import")
async def import_records(
    type_id: int, payload: ImportIn, request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_model(principal, await _type_key(db, type_id), "write")
    if not payload.content.strip():
        raise HTTPException(400, "内容为空")
    result = await svc.import_records(db, type_id, payload.content, payload.format)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    if result["created"]:
        audit_svc.mark_created(request, 0)     # 批量导入记为一次创建事件
    return result
