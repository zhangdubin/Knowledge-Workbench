"""知识关联路由：业务记录 ↔ 知识库笔记"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import knowledge as svc

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/note-type")
async def note_type(db: AsyncSession = Depends(get_db)):
    """返回笔记模型信息，供前端判断是否展示关联模块"""
    et = await svc.get_note_type(db)
    if not et:
        return {"exists": False}
    return {"exists": True, "id": et.id, "key": et.key,
            "name": et.name, "icon": et.icon}


@router.get("/for-record/{record_id}")
async def for_record(record_id: int, db: AsyncSession = Depends(get_db)):
    """某条记录关联的笔记"""
    return await svc.list_notes_for_record(db, record_id)


@router.get("/for-note/{note_id}")
async def for_note(note_id: int, db: AsyncSession = Depends(get_db)):
    """某条笔记被哪些业务记录引用"""
    return await svc.list_records_for_note(db, note_id)


@router.post("/link")
async def link(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    record_id = payload.get("record_id")
    note_id = payload.get("note_id")
    if not record_id or not note_id:
        raise HTTPException(400, "record_id 与 note_id 必填")
    try:
        return await svc.link(db, int(record_id), int(note_id))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/link")
async def unlink(
    record_id: int, note_id: int, db: AsyncSession = Depends(get_db)
):
    ok = await svc.unlink(db, record_id, note_id)
    if not ok:
        raise HTTPException(404, "关联不存在")
    return {"ok": True}


@router.post("/note-from-record")
async def note_from_record(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """把业务记录一键沉淀为笔记并自动关联"""
    record_id = payload.get("record_id")
    if not record_id:
        raise HTTPException(400, "record_id 必填")
    try:
        return await svc.note_from_record(db, int(record_id))
    except ValueError as e:
        raise HTTPException(400, str(e))
