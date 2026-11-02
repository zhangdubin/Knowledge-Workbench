"""全局搜索：一次检索覆盖业务记录与文件

文件现在也存在数据库里并带正文，所以「全局搜索」如果不带上文件，
就名不副实了 —— 用户搜一个合同关键词，结果里应该有那份 PDF。

—— 检索效率上的两处改动（都是为了「数据变多也别变慢」）：

  1. **记录检索走倒排索引**（record_fts），不再全表 LIKE 扫描。
     索引不可用时自动退回原来的扫描路径 —— 索引是「增强」不是「前提」，
     建不起来时搜索必须还能用，只是慢一点。
  2. **返回里带上耗时、是否降级、是否截断**。
     前端要拿它说人话（「命中过多，已取前 N 条」「语义通道超时已跳过」），
     用户看到的是结论，而不是一直转圈。
"""
import logging
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityType
from ..services import access
from ..services import docindex
from ..services import document as doc_svc
from ..services import record as svc
from ..services.auth import Principal, current_principal

log = logging.getLogger("kb.search")

router = APIRouter(prefix="/api/search", tags=["search"])


async def _readable_type_ids(db: AsyncSession, principal: Principal) -> list[int] | None:
    """能读的模型 id 清单；None 表示「都能读」（不过滤）

    权限裁剪必须在**截断之前**做：先取 N 条再过滤，能留下的可能只剩几条，
    而用户明明还有更多命中。
    """
    keys = access.readable_model_keys(principal)
    if keys is None:
        return None
    if not keys:
        return []
    rows = (await db.execute(
        select(EntityType.id).where(EntityType.key.in_(list(keys)))
    )).scalars().all()
    return [int(i) for i in rows]


async def _search_records(
    db: AsyncSession, kw: str, limit: int, principal: Principal
) -> list[dict]:
    """记录检索：优先走倒排索引，不可用时退回 LIKE 扫描

    两条路返回的结果集**完全一致**（LIKE 条件仍然留在最终过滤里，
    索引只用来缩小候选），所以用户看不出差别。
    """
    try:
        allowed = await _readable_type_ids(db, principal)
        rows = await docindex.record_search(db, kw, limit, allowed)
        if rows is not None:
            return rows
    except Exception as e:
        log.warning("记录级索引检索失败，退回全表扫描：%s", e)
    return await svc.search_all(db, kw, limit, principal=principal)


@router.get("")
async def search(
    keyword: str = Query("", min_length=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    kw = (keyword or "").strip()
    if not kw:
        return {
            "records": [], "documents": [], "total": 0, "keyword": "",
            "elapsed_ms": 0, "degraded": False, "degraded_reason": "",
            "truncated": False, "truncated_reason": "",
        }

    t0 = time.perf_counter()

    records = await _search_records(db, kw, limit, principal)

    documents = []
    dmeta: dict = {}
    # 文件命中要跟着「数据中心」页面权限走：全局搜索能搜到文件是它的价值，
    # 但没给数据中心权限的人不该在结果里读到文件的正文片段。
    if principal.has_page("library"):
        try:
            res = await doc_svc.search_documents(
                db, kw, limit=min(limit, 30), mode="hybrid")
            documents = res.get("items") or []
            dmeta = {
                "degraded": bool(res.get("degraded")),
                "degraded_reason": res.get("degraded_reason") or "",
                "truncated": bool(res.get("truncated")),
                "truncated_reason": res.get("truncated_reason") or "",
            }
        except Exception as e:
            log.warning("全局搜索的文件通道失败：%s", e)

    # 记录这条通道命中数撞到了 limit，说明后面还有 —— 说清楚比让人猜好
    rec_truncated = len(records) >= limit
    truncated = bool(dmeta.get("truncated")) or rec_truncated
    reasons = []
    if rec_truncated:
        reasons.append(f"记录命中超过 {limit} 条，已取前 {limit} 条")
    if dmeta.get("truncated_reason"):
        reasons.append(dmeta["truncated_reason"])

    return {
        "records": records,
        "documents": documents,
        "total": len(records) + len(documents),
        "keyword": kw,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "degraded": bool(dmeta.get("degraded")),
        "degraded_reason": dmeta.get("degraded_reason") or "",
        "truncated": truncated,
        "truncated_reason": "；".join(reasons),
    }
