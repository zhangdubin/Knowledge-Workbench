"""应用分组 + 全局统计 + 关联分析"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import App, Document, EntityType
from ..services import access
from ..services import graph as graph_svc
from ..services import app as app_svc
from ..services import app_ai as ai_app_svc
from ..services import app_template as tpl_svc
from ..services import document as doc_svc
from ..services.auth import Principal, current_principal, ensure_model, require_feature

router = APIRouter(prefix="/api/apps", tags=["apps"])

# AI 生成要消耗 token、会把用户描述发给外部服务，所以单独要「ai」功能位
_AI = [Depends(require_feature("ai"))]

# 建应用就是批量建模（应用 + 数据模型 + 字段 + 关联），
# 门禁必须跟 entity_types 的 model_manage 对齐，不能绕过去
_MANAGE = [Depends(require_feature("model_manage"))]


@router.get("")
async def list_apps(db: AsyncSession = Depends(get_db)):
    return await app_svc.list_apps(db)


@router.get("/templates")
async def list_templates():
    """内置应用模板（含模型与字段概要），用于「新建应用」一键生成"""
    return tpl_svc.list_templates()


@router.post("/from-prompt", dependencies=_AI)
async def create_from_prompt(payload: dict = Body(...)):
    """自然语言 → 应用规格草稿（只返回草稿，不落库）

    用户在弹窗里审阅、删改之后再调 from-spec 创建 ——
    AI 不该绕过用户确认直接写库。
    """
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "请先描述你要的应用")
    try:
        return await ai_app_svc.generate_app_spec(prompt)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/from-template", dependencies=_MANAGE)
async def create_from_template(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """按模板或直接按规格草稿创建应用：应用 + 数据模型 + 字段 + 关联 一次生成

    两种入参：
    - {"template": "project", "key": "...", "name": "..."}：按内置模板（原有调用方式，保持兼容）
    - {"spec": {...}, "key": "...", "name": "..."}：按 AI 草稿 / 用户改过的规格
    """
    try:
        if isinstance(payload.get("spec"), dict):
            return await tpl_svc.create_app_from_draft(db, payload)
        return await tpl_svc.create_app_from_template(db, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IntegrityError:
        # 并发建同名应用时「先查后插」会撞 unique 约束，这里给 409 而不是 500
        await db.rollback()
        raise HTTPException(409, "key 已存在")


@router.post("/from-spec", dependencies=_MANAGE)
async def create_from_spec(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """按规格草稿创建应用（AI 生成 → 用户确认 → 创建）

    与 /from-template 共用同一段落库逻辑，区别只是规格的来源。
    """
    try:
        return await tpl_svc.create_app_from_draft(db, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "key 已存在")


@router.post("", dependencies=_MANAGE)
async def create_app(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """新建应用分组"""
    if not payload.get("key") or not payload.get("name"):
        raise HTTPException(400, "key 和 name 必填")
    existing = (
        await db.execute(select(App).where(App.key == payload["key"]))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "key 已存在")
    try:
        return await app_svc.create_app(db, payload)
    except IntegrityError:
        # 先查后插有竞态窗口：并发建同名应用时靠 unique 约束兜底
        await db.rollback()
        raise HTTPException(409, "key 已存在")


@router.put("/{app_id}", dependencies=_MANAGE)
async def update_app(
    app_id: int, payload: dict = Body(...), db: AsyncSession = Depends(get_db)
):
    a = await app_svc.update_app(db, app_id, payload)
    if not a:
        raise HTTPException(404, "App not found")
    return {"ok": True, "id": a.id}


@router.delete("/{app_id}", dependencies=_MANAGE)
async def delete_app(app_id: int, db: AsyncSession = Depends(get_db)):
    ok = await app_svc.delete_app(db, app_id)
    if not ok:
        raise HTTPException(404, "App not found")
    return {"ok": True}


# ============ 全局统计 + 图谱 ============
stats_router = APIRouter(prefix="/api", tags=["stats"])


@stats_router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    # 「最近更新」是具体记录的完整内容，按模型权限裁剪
    return await graph_svc.get_stats(db, principal=principal)


@stats_router.get("/graph/record/{record_id}")
async def graph_for_record(
    record_id: int, depth: int = Query(2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    # 本体先过模型读权限：读不到这条记录，图谱就不该展开
    key = await access.record_type_key(db, record_id)
    if key is None:
        raise HTTPException(404, "记录不存在")
    if not access.can_read_record(principal, key):
        raise HTTPException(403, f"对模型「{key}」没有读权限")
    return await graph_svc.get_record_graph(db, record_id, depth, principal=principal)


@stats_router.get("/graph/type/{type_id}")
async def graph_for_type(
    type_id: int, limit: int = Query(200, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    # 整个模型读不到 → 不给图（早先这里连 principal 都不取，登录即可看全库）
    et = await db.get(EntityType, type_id)
    if not et:
        raise HTTPException(404, "模型不存在")
    if not access.can_read_record(principal, et.key):
        raise HTTPException(403, f"对模型「{et.key}」没有读权限")
    return await graph_svc.get_type_graph(db, type_id, limit, principal=principal)


@stats_router.get("/graph/notes")
async def graph_for_notes(
    tag: str | None = Query(None),
    limit: int = Query(300, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """笔记全局图谱：所有笔记 + 双链关联"""
    ensure_model(principal, "note", "read")
    return await graph_svc.get_notes_graph(db, tag, limit)


@stats_router.get("/graph/document/{document_id}")
async def graph_for_document(
    document_id: int, depth: int = Query(1, ge=1, le=3),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """以数据中心文件为中心：它关联的记录、以及这些记录挂着的其它文件"""
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "文件不存在")
    await doc_svc.ensure_readable(db, principal, doc)
    return await graph_svc.get_document_graph(db, document_id, depth)


@stats_router.get("/graph/global")
async def graph_global(
    limit: int = Query(300, ge=20, le=2000),
    include_documents: bool = True,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """全局关联网络：所有模型的记录 + 关系 + 参与关系的文件"""
    # 节点按读权限裁剪：记录看模型权限，文件看文件自己的判定
    # （独立文件归「数据中心」页面，记录附件归那条记录的模型权限）。
    # 早先只按 has_page("library") 挡了文件节点，记录节点从来没管过。
    return await graph_svc.get_global_graph(db, limit, include_documents, principal=principal)


@stats_router.get("/graph/search")
async def graph_search(
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """图谱内搜索定位：返回节点 id，前端据此聚焦/高亮"""
    return await graph_svc.search_nodes(db, keyword, limit, principal=principal)