"""实体类型（数据模型）管理服务"""
from datetime import datetime, timezone

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import EntityType, FieldDefinition
from ..schemas import EntityTypeIn


async def list_entity_types(db: AsyncSession, app: str | None = None) -> list[dict]:
    """列出所有实体类型，附带字段数 + 记录数（不含回收站中的）"""
    from ..models import EntityRecord
    q = (
        select(EntityType)
        .where(EntityType.deleted_at.is_(None))
        .order_by(EntityType.app, EntityType.order, EntityType.id)
    )
    if app:
        q = q.where(EntityType.app == app)
    result = await db.execute(q)
    types = result.scalars().all()

    # 统计字段数和记录数
    out = []
    for t in types:
        field_count_q = select(func.count(FieldDefinition.id)).where(
            FieldDefinition.entity_type_id == t.id
        )
        record_count_q = select(func.count(EntityRecord.id)).where(
            EntityRecord.entity_type_id == t.id,
            # 回收站里的记录不算数：否则删掉记录后列表数字不变，像没删掉
            EntityRecord.deleted_at.is_(None),
        )
        fc = (await db.execute(field_count_q)).scalar() or 0
        rc = (await db.execute(record_count_q)).scalar() or 0
        out.append({
            "id": t.id,
            "key": t.key,
            "name": t.name,
            "icon": t.icon,
            "description": t.description,
            "app": t.app,
            "order": t.order,
            "field_count": fc,
            "record_count": rc,
        })
    return out


async def get_entity_type(db: AsyncSession, type_id: int, include_deleted: bool = False) -> EntityType | None:
    q = (
        select(EntityType)
        .options(selectinload(EntityType.fields))
        .where(EntityType.id == type_id)
    )
    if not include_deleted:
        q = q.where(EntityType.deleted_at.is_(None))
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def get_entity_type_by_key(db: AsyncSession, key: str, include_deleted: bool = False) -> EntityType | None:
    q = (
        select(EntityType)
        .options(selectinload(EntityType.fields))
        .where(EntityType.key == key)
    )
    if not include_deleted:
        q = q.where(EntityType.deleted_at.is_(None))
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def create_entity_type(db: AsyncSession, payload: EntityTypeIn) -> EntityType:
    et = EntityType(
        key=payload.key,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        app=payload.app,
        order=payload.order,
    )
    db.add(et)
    await db.flush()  # 取 id

    for f in payload.fields:
        db.add(FieldDefinition(
            entity_type_id=et.id,
            key=f.key,
            name=f.name,
            type=f.type,
            required=f.required,
            options=f.options,
            order=f.order,
        ))
    await db.commit()
    await db.refresh(et)
    # 重新加载字段
    return await get_entity_type(db, et.id)


async def update_entity_type(
    db: AsyncSession, type_id: int, payload: EntityTypeIn
) -> EntityType | None:
    et = await get_entity_type(db, type_id)
    if not et:
        return None
    et.key = payload.key
    et.name = payload.name
    et.icon = payload.icon
    et.description = payload.description
    et.app = payload.app
    et.order = payload.order

    # 字段：删旧建新（简单粗暴，避免 diff 复杂度）
    await db.execute(delete(FieldDefinition).where(FieldDefinition.entity_type_id == et.id))
    for f in payload.fields:
        db.add(FieldDefinition(
            entity_type_id=et.id,
            key=f.key,
            name=f.name,
            type=f.type,
            required=f.required,
            options=f.options,
            order=f.order,
        ))
    await db.commit()
    return await get_entity_type(db, et.id)


async def delete_entity_type(db: AsyncSession, type_id: int) -> bool:
    """软删除：进回收站。字段/记录/关联全部保留，可随时恢复。"""
    et = await db.get(EntityType, type_id)
    if not et or et.deleted_at:
        return False
    et.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ============ 回收站 ============

async def list_deleted_types(db: AsyncSession) -> list[dict]:
    """回收站里的模型（附带记录数，评估要不要救）"""
    from ..models import EntityRecord
    q = (
        select(EntityType)
        .where(EntityType.deleted_at.is_not(None))
        .order_by(EntityType.deleted_at.desc())
    )
    types = (await db.execute(q)).scalars().all()
    out = []
    for t in types:
        rc = (
            await db.execute(
                select(func.count(EntityRecord.id)).where(
                    EntityRecord.entity_type_id == t.id,
                    EntityRecord.deleted_at.is_(None),
                )
            )
        ).scalar() or 0
        out.append({
            "id": t.id,
            "key": t.key,
            "name": t.name,
            "icon": t.icon,
            "app": t.app,
            "record_count": rc,
            "deleted_at": t.deleted_at,
        })
    return out


async def restore_entity_type(db: AsyncSession, type_id: int) -> dict | None:
    """从回收站恢复模型。Key 若被新模型占用则要求先处理。"""
    et = await db.get(EntityType, type_id)
    if not et or not et.deleted_at:
        return None
    alive = await get_entity_type_by_key(db, et.key)
    if alive:
        return {"conflict": True, "key": et.key}
    et.deleted_at = None
    await db.commit()
    return {"conflict": False, "key": et.key}


async def purge_entity_type(db: AsyncSession, type_id: int) -> bool:
    """彻底删除（物理级联：字段/记录/视图一起走，不可恢复）"""
    et = await db.get(EntityType, type_id)
    if not et or not et.deleted_at:
        return False
    await db.delete(et)
    await db.commit()
    return True