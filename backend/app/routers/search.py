"""全局搜索：一次检索覆盖业务记录与文件

文件现在也存在数据库里并带正文，所以「全局搜索」如果不带上文件，
就名不副实了 —— 用户搜一个合同关键词，结果里应该有那份 PDF。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import document as doc_svc
from ..services import record as svc

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search(
    keyword: str = Query("", min_length=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    kw = (keyword or "").strip()
    if not kw:
        return {"records": [], "documents": [], "total": 0, "keyword": ""}

    records = await svc.search_all(db, kw, limit)

    documents = []
    try:
        res = await doc_svc.search_documents(db, kw, limit=min(limit, 30), mode="hybrid")
        documents = res["items"]
    except Exception:
        documents = []

    return {
        "records": records,
        "documents": documents,
        "total": len(records) + len(documents),
        "keyword": kw,
    }
