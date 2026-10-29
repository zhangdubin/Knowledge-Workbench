"""左侧导航的自定义项

内置导航写死在前端（Layout.vue 的 NAV 常量），这里管的是**用户自己加的**：
想把某个应用、某个文档目录挂到侧栏，或者把常用的页面顶到前面，都行。

为什么单独一张表、而不是让前端存 localStorage：
localStorage 只在这台机器上，换台电脑就没了；而且多用户部署时
「每个人的侧栏不一样」没法在服务端统一管理。

权限：跟系统配置一个档次（system_config 功能位），也就是只有管理员能改。
自定义项只是导航入口，不承载数据权限 ——
点进去还是走各页面自己的权限判定，接口层照样拦。
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import NavItem
from ..services.auth import Principal, current_principal, require_feature

router = APIRouter(prefix="/api/nav-items", tags=["nav-items"])

# 改导航 = 改系统配置那一档
_MANAGE = [Depends(require_feature("system_config"))]

MAX_LABEL = 32
MAX_PATH = 256


def _clean_label(raw) -> str:
    label = str(raw or "").strip()
    if not label:
        raise HTTPException(400, "名称不能为空")
    if len(label) > MAX_LABEL:
        raise HTTPException(400, f"名称不能超过 {MAX_LABEL} 个字")
    return label


def _clean_path(raw) -> str:
    """站内路径校验

    只允许站内相对路径：必须以 / 开头，不能是 //（那会被当成外站），
    不能带协议（http:// 之类）。拒绝外站地址是刻意的 ——
    导航项会渲染成 <a>，放个外站地址等于开了个钓鱼入口。
    """
    path = str(raw or "").strip()
    if not path:
        raise HTTPException(400, "路径不能为空")
    if len(path) > MAX_PATH:
        raise HTTPException(400, f"路径不能超过 {MAX_PATH} 个字符")
    if not path.startswith("/"):
        raise HTTPException(400, "路径要以 / 开头")
    if path.startswith("//") or "://" in path:
        raise HTTPException(400, "只能填站内路径，不能是外部网址")
    if "#" in path or "?" in path:
        raise HTTPException(400, "路径里不能带 # 或 ?")
    return path


def _clean_group(raw) -> str:
    group = str(raw or "").strip() or "自定义"
    return group[:32]


def _payload(raw) -> dict:
    """归一化一个导航项的字段"""
    out = {
        "label": _clean_label(raw.get("label")),
        "path": _clean_path(raw.get("path")),
        "icon": str(raw.get("icon") or "").strip()[:32],
        "group_name": _clean_group(raw.get("group_name") or raw.get("group")),
        "description": str(raw.get("description") or "").strip()[:256],
    }
    order = raw.get("sort_order")
    out["sort_order"] = int(order) if isinstance(order, (int, float)) else 0
    return out


def _to_dict(item: NavItem) -> dict:
    return {
        "id": item.id,
        "label": item.label,
        "path": item.path,
        "icon": item.icon or "",
        "group_name": item.group_name or "自定义",
        "description": item.description or "",
        "sort_order": item.sort_order or 0,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
async def list_nav_items(db: AsyncSession = Depends(get_db)):
    """列出自定义导航项（登录就能读 —— 侧栏要用）"""
    rows = (await db.execute(
        select(NavItem).order_by(NavItem.sort_order, NavItem.id)
    )).scalars().all()
    return [_to_dict(r) for r in rows]


@router.post("", dependencies=_MANAGE)
async def create_nav_item(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    data = _payload(payload)
    item = NavItem(**data)
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "创建失败：同名同路径的导航项已存在")
    await db.refresh(item)
    return _to_dict(item)


@router.patch("/{item_id}", dependencies=_MANAGE)
async def update_nav_item(item_id: int, payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    item = await db.get(NavItem, item_id)
    if not item:
        raise HTTPException(404, "导航项不存在")
    data = _payload(payload)
    for k, v in data.items():
        setattr(item, k, v)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "保存失败：同名同路径的导航项已存在")
    await db.refresh(item)
    return _to_dict(item)


@router.delete("/{item_id}", dependencies=_MANAGE)
async def delete_nav_item(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(NavItem, item_id)
    if not item:
        raise HTTPException(404, "导航项不存在")
    await db.delete(item)
    await db.commit()
    return {"ok": True}
