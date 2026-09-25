"""回收站路由：软删除的模型与记录的统一管理

语义：
- 列表 / 恢复 → 需要 `model_manage`（结构性操作）；
  记录恢复也走这里，因为记录回收站常牵扯模型可见性。
- 彻底删除 → 同样 `model_manage`，且要求请求体带上模型 Key
  （前端弹 ElMessageBox.prompt 强制输入，与模型删除入口一致）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityType
from ..services import entity_type as et_svc
from ..services import record as rec_svc
from ..services.auth import require_feature

router = APIRouter(prefix="/api/recycle", tags=["recycle"])

_MANAGE = [Depends(require_feature("model_manage"))]


@router.get("", dependencies=_MANAGE)
async def list_recycle(db: AsyncSession = Depends(get_db)) -> dict:
    types = await et_svc.list_deleted_types(db)
    records = await rec_svc.list_deleted_records(db)
    return {
        "types": types,
        "records": records,
        "total": len(types) + len(records),
    }


class PurgeIn(BaseModel):
    key: str          # 模型 Key，二次确认用


@router.post("/types/{type_id}/restore", dependencies=_MANAGE)
async def restore_type(type_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await et_svc.restore_entity_type(db, type_id)
    if result is None:
        raise HTTPException(404, "回收站中没有这个模型")
    if result["conflict"]:
        raise HTTPException(
            409,
            f"Key「{result['key']}」已被现有模型占用，请先改掉占用方的 Key 再恢复",
        )
    return {"ok": True, "key": result["key"]}


@router.delete("/types/{type_id}", dependencies=_MANAGE)
async def purge_type(
    type_id: int, payload: PurgeIn, db: AsyncSession = Depends(get_db)
) -> dict:
    et = await db.get(EntityType, type_id)
    if not et or not et.deleted_at:
        raise HTTPException(404, "回收站中没有这个模型")
    if (payload.key or "").strip() != et.key:
        raise HTTPException(400, "模型 Key 不一致，已拒绝彻底删除")
    ok = await et_svc.purge_entity_type(db, type_id)
    return {"ok": ok}


@router.post("/records/{record_id}/restore", dependencies=_MANAGE)
async def restore_record(record_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await rec_svc.restore_record(db, record_id)
    if result is None:
        raise HTTPException(404, "回收站中没有这条记录")
    return {"ok": True, "model_restored": result["model_restored"]}


@router.delete("/records/{record_id}", dependencies=_MANAGE)
async def purge_record(record_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    ok = await rec_svc.purge_record(db, record_id)
    if not ok:
        raise HTTPException(404, "回收站中没有这条记录")
    return {"ok": True}
