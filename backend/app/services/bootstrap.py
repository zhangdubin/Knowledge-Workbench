"""启动时确保基础结构存在：默认应用分组 + note 实体类型 + 内置角色与管理员

与 seed.py 的区别：seed 是"首次空库填充样例"，bootstrap 是"每次启动都补全缺失的基础项"
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import App, EntityType, FieldDefinition, Role
from .permissions import BUILTIN_ROLES


DEFAULT_APPS = [
    {"key": "knowledge", "name": "知识库", "icon": "📚",
     "description": "Obsidian 风格的笔记，双向链接", "order": 0},
    {"key": "project", "name": "项目管理", "icon": "📋",
     "description": "项目 / 任务 / 里程碑", "order": 1},
    {"key": "sales", "name": "销售管理", "icon": "💼",
     "description": "客户 / 商机 / 订单", "order": 2},
    {"key": "contract", "name": "合同管理", "icon": "📄",
     "description": "合同 / 付款计划", "order": 3},
    {"key": "default", "name": "通用", "icon": "📦",
     "description": "自定义数据", "order": 99},
]


NOTE_FIELDS = [
    {"key": "title", "name": "标题", "type": "text", "required": True, "order": 1},
    {"key": "content", "name": "内容（支持 [[双链]]）", "type": "textarea", "order": 2},
    {"key": "tags", "name": "标签", "type": "multiselect",
     "options": {"choices": []}, "order": 3},
    {"key": "parent", "name": "父笔记", "type": "reference",
     "options": {"target": "note"}, "order": 4},
]


async def ensure_default_apps(db: AsyncSession):
    """确保默认应用已注册（不覆盖用户自定义的）"""
    for spec in DEFAULT_APPS:
        existing = (
            await db.execute(select(App).where(App.key == spec["key"]))
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(App(**spec))
    await db.commit()


async def ensure_note_type(db: AsyncSession) -> EntityType | None:
    """确保 note 实体类型存在；返回实体类型（已存在或新建）"""
    et = (
        await db.execute(select(EntityType).where(EntityType.key == "note"))
    ).scalar_one_or_none()
    if et:
        return et

    et = EntityType(
        key="note",
        name="笔记",
        icon="📝",
        description="Obsidian 风格的笔记，支持 [[双向链接]] 和 #标签",
        app="knowledge",
        order=0,
    )
    db.add(et)
    await db.flush()

    for f in NOTE_FIELDS:
        db.add(FieldDefinition(
            entity_type_id=et.id,
            key=f["key"],
            name=f["name"],
            type=f["type"],
            required=f.get("required", False),
            options=f.get("options", {}),
            order=f.get("order", 0),
        ))
    await db.commit()
    await db.refresh(et)
    return et


async def ensure_builtin_roles(db: AsyncSession) -> None:
    """确保三个内置角色存在

    只在缺失时创建，不覆盖管理员改过的权限 —— 否则每次重启
    都会把被调过的权限点回滚。
    """
    for spec in BUILTIN_ROLES:
        role = (
            await db.execute(select(Role).where(Role.key == spec["key"]))
        ).scalar_one_or_none()
        if role:
            continue
        db.add(Role(
            key=spec["key"], name=spec["name"], description=spec["description"],
            is_builtin=True, perms=spec["perms"],
        ))
    await db.commit()


async def run_bootstrap(db: AsyncSession):
    """启动时执行的幂等补全"""
    await ensure_default_apps(db)
    await ensure_note_type(db)
    await ensure_builtin_roles(db)
    from .auth import ensure_admin_user
    await ensure_admin_user(db)