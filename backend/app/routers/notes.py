"""笔记相关的特殊路由：双链、反向链接"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import wikilink as svc
from ..services.auth import Principal, current_principal, ensure_model

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _need_note_write(principal: Principal) -> None:
    """双链同步属于写笔记，按 note 模型的写权限判断"""
    ensure_model(principal, "note", "write")


@router.post("/{record_id}/sync-links")
async def sync_links(
    record_id: int, payload: dict = Body(...), db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """保存笔记时调用：根据 content 同步双链"""
    _need_note_write(principal)
    content = payload.get("content", "")
    try:
        return await svc.sync_wikilinks(db, record_id, content)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/{record_id}/backlinks")
async def backlinks(record_id: int, db: AsyncSession = Depends(get_db)):
    """反向链接：哪些笔记引用了我"""
    return await svc.get_backlinks(db, record_id)


@router.get("/{record_id}/outgoing")
async def outgoing_links(record_id: int, db: AsyncSession = Depends(get_db)):
    """正向链接：我引用了哪些笔记"""
    return await svc.get_outgoing_links(db, record_id)


@router.get("/extract")
async def extract_links(content: str = ""):
    """仅解析文本中的 [[标题]]，不落库"""
    titles = await svc.extract_titles(content)
    return {"titles": titles}