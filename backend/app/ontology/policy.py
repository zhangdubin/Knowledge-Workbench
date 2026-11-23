from fastapi import HTTPException
from sqlalchemy import select
from .models import Projection


def require_workspace(principal):
    if not principal.has_page("types"):
        raise HTTPException(403, "缺少数据模型页面权限")


def require_schema(principal, schema, *, write=False):
    require_workspace(principal)
    if write and schema["relations"] and not principal.has_feature("relation_manage"):
        raise HTTPException(403, "缺少关联管理权限")
    if write and not principal.has_feature("model_manage"):
        raise HTTPException(403, "需要模型管理权限")
    if any(
        not principal.can_model(t["key"], "write" if write else "read")
        for t in schema["types"]
    ):
        raise HTTPException(403, "缺少模型权限")


async def legacy_projection(db, kind, row_id):
    return await db.scalar(
        select(Projection).where(
            Projection.kind == kind, Projection.legacy_id == row_id
        )
    )


async def protect_projection(db, kind, row_id):
    if await legacy_projection(db, kind, row_id):
        raise HTTPException(409, "该模型或关系由本体管理，请在本体工作室修改并发布修订")
