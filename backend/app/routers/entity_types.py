"""实体类型（数据模型）管理路由

除了常规 CRUD，另提供 JSON 通道：
- `GET  /api/entity-types/{id}/export` 导出模型为 JSON（可直接编辑）
- `POST /api/entity-types/import`      粘贴/回写 JSON → 新建或覆盖模型
  `dry_run=true` 只做校验并把 warnings 返回，前端可当「校验」按钮用
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas import EntityTypeIn, EntityTypeOut, EntityTypeListOut, FieldDefIn
from ..services import audit as audit_svc
from ..services import entity_type as svc
from ..services import model_json as mj
from ..services.auth import Principal, current_principal, ensure_model, require_feature

router = APIRouter(prefix="/api/entity-types", tags=["entity-types"])

# 写模型是「结构性」操作，统一用 model_manage 功能位把关；
# 读模型则走模型级权限，被限制的模型连定义都拿不到。
_MANAGE = [Depends(require_feature("model_manage"))]


@router.get("", response_model=list[EntityTypeListOut])
async def list_types(app: str | None = None, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    items = await svc.list_entity_types(db, app)
    # 只列出「至少可读」的模型：不可读的模型连出现在下拉里都是信息泄漏。
    # 注意 list_entity_types 返回的是 dict（额外带了字段数/记录数），不是 ORM 对象。
    return [t for t in items if principal.can_model(t.get("key") or "", "read")]


@router.post("", response_model=EntityTypeOut, dependencies=_MANAGE)
async def create_type(payload: EntityTypeIn, request: Request,
                      db: AsyncSession = Depends(get_db)):
    if await svc.get_entity_type_by_key(db, payload.key):
        raise HTTPException(400, f"标识「{payload.key}」已被占用，请换一个")
    # Key 全局唯一（数据库约束），回收站里躺着的模型同样占着坑：
    # 提前拦下来并告诉用户去哪处理，别让 IntegrityError 变成 500。
    deleted_holder = await svc.get_entity_type_by_key(db, payload.key, include_deleted=True)
    if deleted_holder and deleted_holder.deleted_at:
        raise HTTPException(
            400,
            f"标识「{payload.key}」被回收站中的模型「{deleted_holder.name}」占用，"
            "请先到 回收站 恢复或彻底删除它",
        )
    et = await svc.create_entity_type(db, payload)
    audit_svc.mark_created(request, et.id)
    return et


# ============ JSON 通道 ============
# 注意：必须声明在 `/{type_id}` 之前，否则 "import" 会被当成 id 解析

class ImportIn(BaseModel):
    text: str | None = None
    model: dict | None = None
    target_id: int | None = None
    dry_run: bool = True
    overwrite: bool = False


def _et_to_json(et) -> dict:
    """模型定义 → 干净的可编辑 JSON（字段按 order 排序）

    字段不再输出 order：数组顺序本身就是顺序，
    导入时会按数组下标补 1..n，来回转换不丢信息。
    """
    fields = sorted(et.fields or [], key=lambda f: (f.order or 0, f.id))
    return {
        "key": et.key,
        "name": et.name,
        "icon": et.icon or "Document",
        "description": et.description or "",
        "app": et.app or "default",
        "order": et.order or 0,
        "fields": [
            {
                "key": f.key,
                "name": f.name,
                "type": f.type,
                "required": bool(f.required),
                "options": f.options or {},
            }
            for f in fields
        ],
    }


@router.post("/import", dependencies=_MANAGE)
async def import_type(payload: ImportIn, request: Request,
                      db: AsyncSession = Depends(get_db)):
    """JSON → 模型。dry_run 时只校验，返回 model + warnings 供前端预览"""
    source = payload.model if payload.model is not None else payload.text
    if source is None:
        return {"ok": False, "errors": ["没有收到 JSON 内容"], "warnings": [],
                "model": None, "entity_type": None, "action": "none"}

    try:
        model, warnings = mj.normalize_model(source)
    except ValueError as e:
        return {"ok": False, "errors": [str(e)], "warnings": [],
                "model": None, "entity_type": None, "action": "none"}

    # 目标模型的确定：显式 id > 同 key 覆盖 > 新建
    target = None
    if payload.target_id:
        target = await svc.get_entity_type(db, payload.target_id)
        if not target:
            return {"ok": False, "errors": [f"要回写的模型 #{payload.target_id} 不存在"],
                    "warnings": warnings, "model": model, "entity_type": None,
                    "action": "none"}
    else:
        same_key = await svc.get_entity_type_by_key(db, model["key"])
        if same_key:
            if payload.overwrite:
                target = same_key
            else:
                return {
                    "ok": False,
                    "errors": [f"已存在标识为「{model['key']}」的模型；"
                               f"如需覆盖请勾选「覆盖同标识模型」，或改一个 key"],
                    "warnings": warnings, "model": model,
                    "entity_type": None, "action": "none",
                }

    # 改 key 时防止撞车
    if target is not None and target.key != model["key"]:
        other = await svc.get_entity_type_by_key(db, model["key"])
        if other and other.id != target.id:
            return {"ok": False,
                    "errors": [f"标识「{model['key']}」已被模型 #{other.id} 占用"],
                    "warnings": warnings, "model": model,
                    "entity_type": None, "action": "none"}

    if payload.dry_run:
        return {"ok": True, "errors": [], "warnings": warnings, "model": model,
                "entity_type": None,
                "action": "update" if target else "create"}

    payload_in = EntityTypeIn(
        key=model["key"],
        name=model["name"],
        icon=model["icon"],
        description=model["description"],
        app=model["app"],
        order=model["order"],
        fields=[FieldDefIn(**f) for f in model["fields"]],
    )
    try:
        if target:
            et = await svc.update_entity_type(db, target.id, payload_in)
            action = "updated"
        else:
            et = await svc.create_entity_type(db, payload_in)
            action = "created"
    except Exception as e:                       # 唯一约束等数据库层报错
        return {"ok": False, "errors": [f"写入失败：{e}"], "warnings": warnings,
                "model": model, "entity_type": None, "action": "none"}

    audit_svc.mark_created(request, et.id)
    return {"ok": True, "errors": [], "warnings": warnings, "model": model,
            "entity_type": EntityTypeOut.model_validate(et).model_dump(),
            "action": action}


@router.get("/example")
def example_json():
    """JSON 建模型的样例模板（前端「填入示例」用）"""
    return {"json": mj.example_json()}


@router.get("/{type_id}/export")
async def export_type(type_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    et = await svc.get_entity_type(db, type_id)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    ensure_model(principal, et.key, "read")
    model = _et_to_json(et)
    return {"model": model, "json": mj.model_to_json(model)}


@router.get("/{type_id}", response_model=EntityTypeOut)
async def get_type(type_id: int, db: AsyncSession = Depends(get_db),
                   principal: Principal = Depends(current_principal)):
    et = await svc.get_entity_type(db, type_id)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    ensure_model(principal, et.key, "read")
    return et


@router.get("/by-key/{key}", response_model=EntityTypeOut)
async def get_type_by_key(key: str, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    et = await svc.get_entity_type_by_key(db, key)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    ensure_model(principal, et.key, "read")
    return et


@router.put("/{type_id}", response_model=EntityTypeOut, dependencies=_MANAGE)
async def update_type(
    type_id: int, payload: EntityTypeIn, db: AsyncSession = Depends(get_db)
):
    conflict = await svc.get_entity_type_by_key(db, payload.key)
    if conflict and conflict.id != type_id:
        raise HTTPException(400, f"标识「{payload.key}」已被模型 #{conflict.id} 占用")
    et = await svc.update_entity_type(db, type_id, payload)
    if not et:
        raise HTTPException(404, "数据模型不存在")
    return et


@router.delete("/{type_id}", dependencies=_MANAGE)
async def delete_type(type_id: int, db: AsyncSession = Depends(get_db)):
    if not await svc.delete_entity_type(db, type_id):
        raise HTTPException(404, "数据模型不存在")
    return {"ok": True}
