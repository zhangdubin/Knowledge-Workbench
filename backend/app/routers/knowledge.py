"""知识关联路由：业务记录 ↔ 知识库笔记"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import access
from ..services import knowledge as svc
from ..services.auth import Principal, current_principal, ensure_model

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _need_note(principal: Principal, need: str = "read") -> None:
    """笔记侧权限：知识库页面的实际数据权限由 note 模型的读写位决定"""
    ensure_model(principal, "note", need)


async def _need_source_record(db: AsyncSession, principal: Principal, record_id: int):
    """源记录侧的权限

    笔记侧有权限还不够：源记录读不到的话，
      - 「某条记录关联的笔记」会暴露记录存在性
      - 「一键沉淀为笔记」会把源记录的全部字段值抄进笔记正文
    两条都是绕过记录模型权限的路径，所以源记录也要过一遍。
    """
    key = await access.record_type_key(db, record_id)
    if key is None:
        raise HTTPException(404, "记录不存在")
    if not access.can_read_record(principal, key):
        raise HTTPException(403, f"对模型「{key}」没有读权限")
    return key


@router.get("/note-type")
async def note_type(db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """返回笔记模型信息，供前端判断是否展示关联模块"""
    _need_note(principal, "read")
    et = await svc.get_note_type(db)
    if not et:
        return {"exists": False}
    return {"exists": True, "id": et.id, "key": et.key,
            "name": et.name, "icon": et.icon}


@router.get("/for-record/{record_id}")
async def for_record(record_id: int, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    """某条记录关联的笔记"""
    _need_note(principal, "read")
    await _need_source_record(db, principal, record_id)
    return await svc.list_notes_for_record(db, record_id)


@router.get("/for-note/{note_id}")
async def for_note(note_id: int, db: AsyncSession = Depends(get_db),
                   principal: Principal = Depends(current_principal)):
    """某条笔记被哪些业务记录引用"""
    _need_note(principal, "read")
    out = await svc.list_records_for_note(db, note_id)
    # 反向引用里可能混着各种模型的记录，按各自的读权限过滤
    out["records"] = [
        r for r in out["records"]
        if principal.can_model(r.get("entity_type_key") or "", "read")
    ]
    out["total"] = len(out["records"])
    return out


@router.post("/link")
async def link(payload: dict = Body(...), db: AsyncSession = Depends(get_db),
               principal: Principal = Depends(current_principal)):
    _need_note(principal, "write")
    record_id = payload.get("record_id")
    note_id = payload.get("note_id")
    if not record_id or not note_id:
        raise HTTPException(400, "record_id 与 note_id 必填")
    await _need_source_record(db, principal, int(record_id))
    try:
        return await svc.link(db, int(record_id), int(note_id))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/link")
async def unlink(
    record_id: int, note_id: int, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    _need_note(principal, "write")
    await _need_source_record(db, principal, int(record_id))
    ok = await svc.unlink(db, record_id, note_id)
    if not ok:
        raise HTTPException(404, "关联不存在")
    return {"ok": True}


@router.post("/note-from-record")
async def note_from_record(payload: dict = Body(...), db: AsyncSession = Depends(get_db),
                            principal: Principal = Depends(current_principal)):
    """把业务记录一键沉淀为笔记并自动关联"""
    _need_note(principal, "write")
    record_id = payload.get("record_id")
    if not record_id:
        raise HTTPException(400, "record_id 必填")
    # 源记录必须读得到：否则等于把受限记录的整份内容抄进笔记
    await _need_source_record(db, principal, int(record_id))
    try:
        return await svc.note_from_record(db, int(record_id))
    except ValueError as e:
        raise HTTPException(400, str(e))
