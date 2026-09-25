"""可视化驾驶舱路由

接口分三类：
  - CRUD：驾驶舱本体（含整份 layout）
  - /data：一次算完整舱所有卡片（首屏一个请求搞定）
  - /options、/templates、/preview：给编辑器用的元数据与单卡实时预览
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Dashboard, EntityType
from ..services import audit as audit_svc
from ..services import dashboard as svc
from ..services.auth import Principal, current_principal, require_feature, require_page

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


class DashboardIn(BaseModel):
    key: str
    name: str
    description: str = ""
    icon: str = "📊"
    app: str = "default"
    order: int = 0
    pinned: bool = False
    layout: list[dict] = []
    settings: dict = {}


class DashboardPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    app: str | None = None
    order: int | None = None
    pinned: bool | None = None
    layout: list[dict] | None = None
    settings: dict | None = None


class WidgetIn(BaseModel):
    widget: dict = {}


class FromTemplateIn(BaseModel):
    template_key: str
    name: str = ""


def _out(d: Dashboard, widget_count: int | None = None) -> dict:
    item = {
        "id": d.id, "key": d.key, "name": d.name, "description": d.description,
        "icon": d.icon, "app": d.app, "order": d.order, "pinned": d.pinned,
        "layout": d.layout or [],
        "settings": d.settings or {},
        "widget_count": widget_count if widget_count is not None else len(d.layout or []),
        "created_at": d.created_at, "updated_at": d.updated_at,
    }
    return item


# ---------- 静态路径（必须排在 /{dashboard_id} 之前） ----------

@router.get("/options")
async def options(db: AsyncSession = Depends(get_db),
                  principal: Principal = Depends(require_page("dashboards"))):
    """编辑器下拉：可选模型、字段、指标、时间字段…"""
    return await svc.source_options(db)


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(require_page("dashboards"))):
    types = (await db.execute(
        select(EntityType).order_by(EntityType.order, EntityType.id)
    )).scalars().all()
    return {"items": svc.templates([{"id": t.id, "key": t.key, "name": t.name} for t in types])}


@router.post("/templates")
async def create_from_template(payload: FromTemplateIn, request: Request,
                               db: AsyncSession = Depends(get_db),
                               principal: Principal = Depends(require_feature("dashboard_write"))):
    types = (await db.execute(
        select(EntityType).order_by(EntityType.order, EntityType.id)
    )).scalars().all()
    tpl = next((t for t in svc.templates(
        [{"id": t.id, "key": t.key, "name": t.name} for t in types]
    ) if t["key"] == payload.template_key), None)
    if not tpl:
        raise HTTPException(404, "模板不存在")

    # 标识冲突时自动加后缀，而不是直接报错 —— 用户点「从模板创建」
    # 的预期是「立刻拿到一个能用的驾驶舱」，不该先被标识占用挡住
    key = tpl["key"]
    serial = 1
    while (await db.execute(select(Dashboard).where(Dashboard.key == key))).scalar_one_or_none():
        serial += 1
        key = f"{tpl['key']}_{serial}"

    d = Dashboard(key=key, name=payload.name or tpl["name"], description=tpl["description"],
                  icon=tpl["icon"], app="default", layout=tpl["layout"],
                  settings=tpl.get("settings") or {})
    db.add(d)
    await db.commit()
    await db.refresh(d)
    audit_svc.mark_created(request, d.id)
    return _out(d)


@router.post("/preview")
async def preview(payload: WidgetIn, db: AsyncSession = Depends(get_db),
                  principal: Principal = Depends(require_page("dashboards"))):
    """编辑器里「试算」单张卡片，不落库"""
    return await svc.compute_widget(db, payload.widget or {})


@router.get("")
async def list_dashboards(db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(require_page("dashboards"))):
    rows = (await db.execute(
        select(Dashboard).order_by(Dashboard.order, Dashboard.id)
    )).scalars().all()
    return {"items": [_out(d) for d in rows]}


@router.post("")
async def create_dashboard(payload: DashboardIn, request: Request,
                           db: AsyncSession = Depends(get_db),
                           principal: Principal = Depends(require_feature("dashboard_write"))):
    key = (payload.key or "").strip()
    if not key or not payload.name.strip():
        raise HTTPException(400, "请填写标识与名称")
    if (await db.execute(select(Dashboard).where(Dashboard.key == key))).scalar_one_or_none():
        raise HTTPException(400, f"标识「{key}」已存在")

    d = Dashboard(key=key, name=payload.name, description=payload.description,
                  icon=payload.icon, app=payload.app, order=payload.order,
                  pinned=payload.pinned, layout=payload.layout,
                  settings=payload.settings or {})
    db.add(d)
    await db.commit()
    await db.refresh(d)
    audit_svc.mark_created(request, d.id)
    return _out(d)


# ---------- 单个驾驶舱 ----------

@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: int, db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(require_page("dashboards"))):
    d = await db.get(Dashboard, dashboard_id)
    if not d:
        raise HTTPException(404, "驾驶舱不存在")
    return _out(d)


@router.get("/{dashboard_id}/data")
async def dashboard_data(dashboard_id: int, db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(require_page("dashboards"))):
    d = await db.get(Dashboard, dashboard_id)
    if not d:
        raise HTTPException(404, "驾驶舱不存在")
    widgets = await svc.compute_layout(db, d.layout)
    return {"id": d.id, "name": d.name, "icon": d.icon,
            "description": d.description, "settings": d.settings or {},
            "widgets": widgets}


@router.put("/{dashboard_id}")
async def update_dashboard(dashboard_id: int, payload: DashboardPatch,
                           db: AsyncSession = Depends(get_db),
                           principal: Principal = Depends(require_feature("dashboard_write"))):
    d = await db.get(Dashboard, dashboard_id)
    if not d:
        raise HTTPException(404, "驾驶舱不存在")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(d, k, v)
    await db.commit()
    await db.refresh(d)
    return _out(d)


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: int, db: AsyncSession = Depends(get_db),
                           principal: Principal = Depends(require_feature("dashboard_write"))):
    d = await db.get(Dashboard, dashboard_id)
    if not d:
        raise HTTPException(404, "驾驶舱不存在")
    await db.delete(d)
    await db.commit()
    return {"ok": True}
