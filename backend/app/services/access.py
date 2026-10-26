"""读权限裁剪的统一入口

为什么单独一个模块：全局搜索、关联图谱、关联列表这几条接口都会
「一次性把一批记录 / 一批文件整批返回」。每一处各写一遍过滤，
早晚有一处漏掉 —— 漏一处就是一次数据外流（早先搜索与图谱就漏过：
记录接口都老老实实校验了模型权限，唯独这两条聚合入口没校验，
合同金额、客户名直接摊在搜索结果里）。

所以规则只写在这里，各处调同一个函数。改规则也只改一处。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DocumentLink, EntityRecord, EntityType
from .auth import Principal


# ---------- 记录 ----------

async def record_type_key(db: AsyncSession, record_id: int) -> str | None:
    """这条记录属于哪个模型；记录不存在返回 None"""
    row = (await db.execute(
        select(EntityType.key)
        .join(EntityRecord, EntityRecord.entity_type_id == EntityType.id)
        .where(EntityRecord.id == record_id)
    )).first()
    return row[0] if row else None


def can_read_record(principal: Principal, type_key: str | None) -> bool:
    """能不能读这个模型的记录"""
    if principal.is_super:
        return True
    return principal.can_model(type_key or "", "read")


def readable_model_keys(principal: Principal) -> set[str] | None:
    """能读的模型 key 集合；None 表示「所有模型都能读」

    为什么要单独算一份清单：SQL 里没法直接问「这个人在这个模型上
    有没有读权限」（权限是 JSON），只能先把「哪些 key 能读」列出来，
    再拿它去筛 SQL。

    通配 `*: read/write` 表示全部可读 → 返回 None（调用方跳过过滤）。
    """
    if principal.is_super:
        return None
    models = principal.perms.get("models") or {}
    if models.get("*") in ("read", "write"):
        return None
    return {k for k, v in models.items() if k != "*" and v in ("read", "write")}


def filter_readable_records(principal: Principal, records: list[dict]) -> list[dict]:
    """按模型权限过滤一批记录结果

    入参里的每一项要带 entity_type_key（搜索与关联的返回体都有）。
    过滤放在截断之前 —— 否则先取 50 条再过滤，能留下的可能只剩几条，
    而用户明明还有更多命中。
    """
    return [r for r in records if can_read_record(principal, r.get("entity_type_key"))]


# ---------- 文件 ----------

async def linked_type_keys(db: AsyncSession, doc_id: int) -> list[str]:
    """这个文件挂着的所有记录分别属于哪些模型

    返回全部（去重、保序），而不是第一条：早先只取第一条，
    一个文件同时关联「能读的模型」和「不能读的模型」时，
    判定结果会随插入顺序漂移 —— 同样的人同样的文件，
    有时能读有时不能，这种不确定性最难排查。
    """
    rows = (await db.execute(
        select(EntityType.key)
        .join(EntityRecord, EntityRecord.entity_type_id == EntityType.id)
        .join(DocumentLink, DocumentLink.record_id == EntityRecord.id)
        .where(DocumentLink.document_id == doc_id)
    )).scalars().all()
    return list(dict.fromkeys(rows))


def can_read_document(principal: Principal, linked_keys: list[str]) -> bool:
    """文件可读判定（唯一口径，所有文件接口都走它）

    - 独立文件（没挂任何记录）→ 需要「数据中心」页面权限
    - 挂在记录上的文件 → 跟随那条记录的模型读权限
    - 一个文件挂多条记录时，**任一条可读即可**

    分两种是有原因的。文件读接口若一律按「数据中心」判，
    记录页里挂的附件预览就会 403（记录用户反而看不到自己的附件）；
    若一律放行，那「只给知识库」的角色换个 URL 就能把文件全读走 ——
    菜单挡住的是界面，不是数据。

    注意：这条规则是「文件从哪儿来就归谁管」，所以
    「数据中心」列表接口也必须用同一条规则过滤 ——
    否则列表里看得见、点进去 403，用户只会以为系统坏了。
    """
    if principal.is_super:
        return True
    if not linked_keys:
        return principal.has_page("library")
    return any(principal.can_model(k, "read") for k in linked_keys)


async def can_read_doc(db: AsyncSession, principal: Principal, doc_id: int) -> bool:
    """按文件 id 判可读（需要查它挂在哪些记录上）"""
    return can_read_document(principal, await linked_type_keys(db, doc_id))


async def filter_readable_documents(
    db: AsyncSession, principal: Principal, doc_ids: list[int]
) -> list[int]:
    """挑出其中可读的文件 id

    一次查清「这些文件各挂在哪些记录上」，避免逐个文件查（那会变成 N+1）。
    """
    if principal.is_super:
        return list(doc_ids)
    if not doc_ids:
        return []
    rows = (await db.execute(
        select(DocumentLink.document_id, EntityType.key)
        .join(EntityRecord, EntityRecord.id == DocumentLink.record_id)
        .join(EntityType, EntityType.id == EntityRecord.entity_type_id)
        .where(DocumentLink.document_id.in_(doc_ids))
    )).all()
    by_doc: dict[int, list[str]] = {}
    for did, key in rows:
        by_doc.setdefault(did, []).append(key)

    out: list[int] = []
    for did in doc_ids:
        keys = list(dict.fromkeys(by_doc.get(did, [])))
        if can_read_document(principal, keys):
            out.append(did)
    return out
