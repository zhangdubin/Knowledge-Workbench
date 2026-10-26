"""关系定义 / 关系实例路由

两端可以是业务记录或数据中心文件，详见 services/relation.py。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Document
from ..schemas import RelationDefIn, RelationRecordIn
from ..services import access
from ..services import audit as audit_svc
from ..services import document as document_svc
from ..services import relation as svc
from ..services.auth import Principal, current_principal, require_feature

router = APIRouter(prefix="/api/relations", tags=["relations"])


class RelationDefPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    cardinality: str | None = None


@router.get("/defs")
async def list_defs(db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    return await svc.list_relation_defs(db)


@router.post("/defs")
async def create_def(payload: RelationDefIn, request: Request,
                     db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(require_feature("relation_manage"))):
    rd = await svc.create_relation_def(db, payload.model_dump())
    audit_svc.mark_created(request, rd.id)
    return {"id": rd.id, "key": rd.key, "name": rd.name,
            "source_kind": rd.source_kind, "target_kind": rd.target_kind}


@router.patch("/defs/{def_id}")
async def update_def(def_id: int, payload: RelationDefPatch,
                     db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(require_feature("relation_manage"))):
    rd = await svc.update_relation_def(db, def_id, payload.model_dump(exclude_none=True))
    return {"id": rd.id, "key": rd.key, "name": rd.name}


@router.delete("/defs/{def_id}")
async def delete_def(def_id: int, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(require_feature("relation_manage"))):
    if not await svc.delete_relation_def(db, def_id):
        raise HTTPException(404, "关联定义不存在")
    return {"ok": True}


@router.get("/defs/{def_id}/pick")
async def pick_options(def_id: int, side: str = Query("target", pattern="^(source|target)$"),
                       keyword: str = "", limit: int = Query(30, ge=1, le=200),
                       db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """「添加关联」弹窗的候选：按该端的 kind 返回记录或文件"""
    return await svc.pickable(db, def_id=def_id, side=side, keyword=keyword,
                              limit=limit, principal=principal)


@router.post("/records")
async def create_record(payload: RelationRecordIn, request: Request,
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(require_feature("relation_manage"))):
    rr = await svc.create_relation_record(db, payload.model_dump())
    audit_svc.mark_created(request, rr.id)
    return {"id": rr.id}


@router.delete("/records/{record_id}")
async def delete_record(record_id: int, db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(require_feature("relation_manage"))):
    if not await svc.delete_relation_record(db, record_id):
        raise HTTPException(404, "关系不存在")
    return {"ok": True}


async def _need_record(db: AsyncSession, principal: Principal, record_id: int):
    """取记录的模型并校验读权限（读不到就 403）"""
    key = await access.record_type_key(db, record_id)
    if key is None:
        raise HTTPException(404, "记录不存在")
    if not access.can_read_record(principal, key):
        raise HTTPException(403, f"对模型「{key}」没有读权限")
    return key


@router.get("/for-record/{record_id}")
async def for_record(record_id: int, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    # 本体先过模型读权限：这条记录读不到，它的关系列表也没必要给
    await _need_record(db, principal, record_id)
    return await svc.get_related_records(db, record_id, principal=principal)


@router.get("/for-document/{document_id}")
async def for_document(document_id: int, db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    # 本体是文件：按文件自己的可读判定（独立文件归「数据中心」页面，
    # 记录附件归那条记录的模型权限）
    doc = await db.get(Document, document_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(404, "文档不存在")
    await document_svc.ensure_readable(db, principal, doc)
    return await svc.get_related_documents(db, document_id, principal=principal)


@router.get("/files-of-record/{record_id}")
async def files_of_record(record_id: int, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    """记录详情里的「挂载文件」：字段上传 + 附件两条通道合并展示"""
    await _need_record(db, principal, record_id)
    return {"items": await svc.documents_attached_to(db, record_id)}
