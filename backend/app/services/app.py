"""应用分组管理服务"""
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import App, EntityType, EntityRecord

# 应用分组允许被修改的字段（白名单）
# 为什么要白名单：key 是结构标识符，一改模型路由的 ?app= 就失配了；
# 批量 setattr 还会把 id / created_at 一起写进去。
APP_UPDATABLE = ("name", "icon", "description", "order")

# 新建应用时允许写入的字段（其余键一律丢掉，免得 ORM 报未知字段）
APP_CREATABLE = ("key", "name", "icon", "description", "order")


async def list_apps(db: AsyncSession) -> list[dict]:
    """列出所有应用，含实体数与记录数"""
    q = select(App).order_by(App.order, App.id)
    res = await db.execute(q)
    apps = res.scalars().all()

    # 同时统计 default 桶（没有 App 记录但 EntityType.app 命中）的应用
    out = []
    seen_keys = set()
    for a in apps:
        # 该 app 下的实体类型
        ec_q = select(func.count(EntityType.id)).where(
            EntityType.app == a.key, EntityType.deleted_at.is_(None)
        )
        ec = (await db.execute(ec_q)).scalar() or 0
        # 该 app 下的记录数（通过 entity_type.app 关联）
        rc_q = (
            select(func.count(EntityRecord.id))
            .join(EntityType, EntityType.id == EntityRecord.entity_type_id)
            .where(
                EntityType.app == a.key,
                EntityType.deleted_at.is_(None),
                EntityRecord.deleted_at.is_(None),
            )
        )
        rc = (await db.execute(rc_q)).scalar() or 0
        out.append({
            "id": a.id,
            "key": a.key,
            "name": a.name,
            "icon": a.icon,
            "description": a.description,
            "order": a.order,
            "entity_count": ec,
            "record_count": rc,
        })
        seen_keys.add(a.key)

    # 兜底：EntityType.app 中出现但 App 表未注册的 key
    orphan_q = select(EntityType.app).distinct()
    orphan_res = await db.execute(orphan_q)
    for (app_key,) in orphan_res.all():
        if app_key in seen_keys:
            continue
        ec_q = select(func.count(EntityType.id)).where(
            EntityType.app == app_key, EntityType.deleted_at.is_(None)
        )
        ec = (await db.execute(ec_q)).scalar() or 0
        rc_q = (
            select(func.count(EntityRecord.id))
            .join(EntityType, EntityType.id == EntityRecord.entity_type_id)
            .where(
                EntityType.app == app_key,
                EntityType.deleted_at.is_(None),
                EntityRecord.deleted_at.is_(None),
            )
        )
        rc = (await db.execute(rc_q)).scalar() or 0
        out.append({
            "id": None,
            "key": app_key,
            "name": app_key,
            "icon": "📦",
            "description": "（未注册应用）",
            "order": 999,
            "entity_count": ec,
            "record_count": rc,
        })
    return out


async def create_app(db: AsyncSession, payload: dict) -> App:
    # 只取认识的字段：App(**payload) 遇到多余键会直接 TypeError → 500
    data = {k: payload[k] for k in APP_CREATABLE if k in payload}
    a = App(**data)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def update_app(db: AsyncSession, app_id: int, payload: dict) -> App | None:
    """改应用分组

    只认白名单里的字段：key 是结构标识符（模型路由按 ?app= 匹配），
    改了会让既有模型「找不到应用」；id / created_at 更不该被前端带进来。
    """
    a = await db.get(App, app_id)
    if not a:
        return None
    for k in APP_UPDATABLE:
        if k in payload and payload[k] is not None:
            setattr(a, k, payload[k])
    await db.commit()
    await db.refresh(a)
    return a


async def delete_app(db: AsyncSession, app_id: int) -> bool:
    a = await db.get(App, app_id)
    if not a:
        return False
    await db.delete(a)
    await db.commit()
    return True


async def ensure_default_apps(db: AsyncSession, specs: list[dict]):
    """确保默认应用存在（不覆盖用户已定义的）"""
    for s in specs:
        existing = (
            await db.execute(select(App).where(App.key == s["key"]))
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(App(
            key=s["key"],
            name=s["name"],
            icon=s.get("icon", "📦"),
            description=s.get("description", ""),
            order=s.get("order", 0),
        ))
    await db.commit()