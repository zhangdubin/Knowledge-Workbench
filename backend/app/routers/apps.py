"""应用分组 + 全局统计 + 关联分析"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import App
from ..services import graph as graph_svc
from ..services import app as app_svc
from ..services import app_template as tpl_svc

router = APIRouter(prefix="/api/apps", tags=["apps"])


@router.get("")
async def list_apps(db: AsyncSession = Depends(get_db)):
    return await app_svc.list_apps(db)


@router.get("/templates")
async def list_templates():
    """内置应用模板（含模型与字段概要），用于「新建应用」一键生成"""
    return tpl_svc.list_templates()


@router.post("/from-template")
async def create_from_template(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """按模板创建应用：应用 + 数据模型 + 字段 + 关联定义 一次生成"""
    try:
        return await tpl_svc.create_app_from_template(db, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("")
async def create_app(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """新建应用分组"""
    if not payload.get("key") or not payload.get("name"):
        raise HTTPException(400, "key 和 name 必填")
    existing = (
        await db.execute(select(App).where(App.key == payload["key"]))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "key 已存在")
    return await app_svc.create_app(db, payload)


@router.put("/{app_id}")
async def update_app(
    app_id: int, payload: dict = Body(...), db: AsyncSession = Depends(get_db)
):
    a = await app_svc.update_app(db, app_id, payload)
    if not a:
        raise HTTPException(404, "App not found")
    return {"ok": True, "id": a.id}


@router.delete("/{app_id}")
async def delete_app(app_id: int, db: AsyncSession = Depends(get_db)):
    ok = await app_svc.delete_app(db, app_id)
    if not ok:
        raise HTTPException(404, "App not found")
    return {"ok": True}


# ============ 全局统计 + 图谱 ============
stats_router = APIRouter(prefix="/api", tags=["stats"])


@stats_router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    return await graph_svc.get_stats(db)


@stats_router.get("/graph/record/{record_id}")
async def graph_for_record(
    record_id: int, depth: int = Query(2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
):
    return await graph_svc.get_record_graph(db, record_id, depth)


@stats_router.get("/graph/type/{type_id}")
async def graph_for_type(
    type_id: int, limit: int = Query(200, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await graph_svc.get_type_graph(db, type_id, limit)


@stats_router.get("/graph/notes")
async def graph_for_notes(
    tag: str | None = Query(None),
    limit: int = Query(300, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """笔记全局图谱：所有笔记 + 双链关联"""
    return await graph_svc.get_notes_graph(db, tag, limit)


@stats_router.get("/graph/document/{document_id}")
async def graph_for_document(
    document_id: int, depth: int = Query(1, ge=1, le=3),
    db: AsyncSession = Depends(get_db),
):
    """以数据中心文件为中心：它关联的记录、以及这些记录挂着的其它文件"""
    return await graph_svc.get_document_graph(db, document_id, depth)


@stats_router.get("/graph/global")
async def graph_global(
    limit: int = Query(300, ge=20, le=2000),
    include_documents: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """全局关联网络：所有模型的记录 + 关系 + 参与关系的文件"""
    return await graph_svc.get_global_graph(db, limit, include_documents)


@stats_router.get("/graph/search")
async def graph_search(
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """图谱内搜索定位：返回节点 id，前端据此聚焦/高亮"""
    return await graph_svc.search_nodes(db, keyword, limit)