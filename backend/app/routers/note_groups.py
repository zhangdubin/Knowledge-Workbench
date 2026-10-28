"""知识库自定义分组路由

分组是「知识库」的一等公民：一张 note_group 表 + 笔记记录里的一个归属键。

**笔记挂在哪儿**

知识库里的「笔记」是「笔记」模型（entity_type key='note'）的 entity_record，
不是 document 表里的行（那一列 source='note' 实际上一条都没有）。
所以分组归属存在记录的 data JSON 里 —— 和「父笔记」的 data.parent 同一套路子：
分组号是 data.group_id，缺这个键（或值为 0）就是「未分组」。

分组表本身只存名字与外观，不存笔记内容。

**边界上的几个决定**

  - 名字去重按「去空白 + 忽略大小写」：用户在「工作」和「工作 」之间
    纠结的收益是零，但分组栏里出现两个几乎一样的名字时，谁都分不清
    哪个才是自己刚建的那个 —— 判重宽松一点，栏里就干净一点。
  - 删分组**不删笔记**，只把归属清空：分组是标签，不是容器。
    用户删一个分组，期待的是「这批笔记回到未分组」，而不是「这批笔记没了」。
  - 置空与删分组在**同一个事务**里：中途失败若只完成了一半，
    就会出现「分组还在但笔记已经置空」或「分组没了但笔记还指着它」，
    两种都是脏数据，而且用户不会知道是哪一步出的问题。
  - 置空时把 data.group_id **整个键删掉**（不是留 null）：
    前端判「这条笔记有没有分组信息」靠的是值不为 null，
    留个 null 会被当成「没有分组信息」。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityRecord, EntityType, NoteGroup
from ..services import audit as audit_svc
from ..services.auth import Principal, current_principal, ensure_model, require_page

router = APIRouter(prefix="/api/note-groups", tags=["note-groups"])

# 分组是知识库的概念，权限跟着知识库走：
#   - 页面位：能进「知识库」页（notes）才谈得上管理它的分组
#   - 模型位：分组管的正是笔记，读分组要能读笔记，写分组要能写笔记
# 两道都过才放行 —— 分组权限不该比笔记本身更宽
# （GET /api/records 要求的就是 note 模型的读权限）。
_READ_PAGE = [Depends(require_page("notes"))]
_WRITE_PAGE = [Depends(require_page("notes"))]


def _need_note(principal: Principal, need: str = "read") -> None:
    """模型级校验：分组管的是笔记，按 note 模型的权限判断"""
    ensure_model(principal, "note", need)


# 名字长度上限（与列宽一致）
NAME_MAX = 40
# 颜色：#rgb / #rrggbb，或前端自己的语义色名（red、primary…）
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class GroupIn(BaseModel):
    name: str
    color: str = ""
    description: str = ""
    sort_order: int = 0


class GroupPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None
    sort_order: int | None = None


def _clean_name(raw: str | None) -> str:
    """校验并规整分组名

    空白名 / 超长名一律 400：分组名会直接显示在侧栏里，
    空名字会渲染出一个点，空格名看起来像没填。
    """
    name = (raw or "").strip()
    if not name:
        raise HTTPException(400, "分组名不能为空")
    if len(name) > NAME_MAX:
        raise HTTPException(400, f"分组名不能超过 {NAME_MAX} 个字")
    return name


def _clean_color(raw: str | None) -> str:
    """校验颜色：空串表示「不指定颜色」"""
    color = (raw or "").strip()
    if not color:
        return ""
    if len(color) > 16:
        raise HTTPException(400, "颜色值过长")
    # 十六进制色必须合法；其他短字符串当作语义色名放行
    if color.startswith("#") and not _COLOR_RE.match(color):
        raise HTTPException(400, "颜色值格式不对（#rgb 或 #rrggbb）")
    return color


async def _name_taken(db: AsyncSession, name: str, exclude_id: int = 0) -> bool:
    """分组名是否已被占用（去空白 + 忽略大小写）

    不能靠数据库的 UNIQUE：SQLite 的唯一约束大小写敏感，
    「Work」与「work」在它眼里是两个不同的名字。
    """
    target = name.strip().casefold()
    rows = (await db.execute(select(NoteGroup.id, NoteGroup.name))).all()
    for gid, other in rows:
        if gid == exclude_id:
            continue
        if (other or "").strip().casefold() == target:
            return True
    return False


def _out(g: NoteGroup, count: int = 0) -> dict:
    """分组对象（对外契约）

    count = 该分组下的笔记数：note 模型的记录里 data.group_id 命中、
    且未软删的条数。
    """
    return {
        "id": g.id,
        "name": g.name,
        "color": g.color or "",
        "count": count,
        "sort_order": g.sort_order or 0,
        "description": g.description or "",
        "created_at": g.created_at,
        "updated_at": g.updated_at,
    }


# 记录里的分组号：data.group_id
# 用 SQLAlchemy 的 JSON 索引（底层是 SQLite 的 json_extract）：
# 直接在库里筛，不把上千条记录捞进内存再数。
_REC_GROUP_ID = EntityRecord.data["group_id"].as_integer()


async def _note_type_id(db: AsyncSession) -> int | None:
    """note 模型的 id（没有这个模型时返回 None）"""
    return (await db.execute(
        select(EntityType.id).where(EntityType.key == "note")
    )).scalar_one_or_none()


async def _note_counts(db: AsyncSession) -> dict[int, int]:
    """各分组下的笔记数（一次查询算完，别在循环里查库）"""
    tid = await _note_type_id(db)
    if not tid:
        return {}
    rows = (await db.execute(
        select(_REC_GROUP_ID, func.count(EntityRecord.id))
        .where(EntityRecord.entity_type_id == tid,
               EntityRecord.deleted_at.is_(None))
        .group_by(_REC_GROUP_ID)
    )).all()
    return {gid: n for gid, n in rows if gid is not None}


async def _move_records(db: AsyncSession, from_gid: int, to_gid: int | None) -> int:
    """把笔记记录从 from_gid 挪到 to_gid（to_gid=None = 移出分组）

    走「读出来改 JSON 再写回」而不是 SQL 里的 json_set：
    data 里除了 group_id 还有别的字段（title/content/tags…），
    整份读回来改一个键再写回去，比拼 JSON 字符串稳妥。
    """
    tid = await _note_type_id(db)
    if not tid:
        return 0
    rows = (await db.execute(
        select(EntityRecord).where(
            EntityRecord.entity_type_id == tid,
            _REC_GROUP_ID == from_gid,
        )
    )).scalars().all()
    for r in rows:
        data = r.data if isinstance(r.data, dict) else {}
        data = dict(data)
        if to_gid is None:
            # 整个键删掉，而不是留一个 null：
            # 前端判「这条笔记有没有分组字段」靠的是值不为 null，
            # 留个 null 会被当成「没有分组信息」。
            data.pop("group_id", None)
        else:
            data["group_id"] = to_gid
        r.data = data
    return len(rows)


# ---------- 列表 ----------

@router.get("", dependencies=_READ_PAGE)
async def list_groups(db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """分组列表（按 sort_order、id 升序）"""
    _need_note(principal, "read")
    rows = (await db.execute(
        select(NoteGroup).order_by(NoteGroup.sort_order, NoteGroup.id)
    )).scalars().all()
    counts = await _note_counts(db)
    return [_out(g, counts.get(g.id, 0)) for g in rows]


# ---------- 新建 ----------

@router.post("", status_code=201, dependencies=_WRITE_PAGE)
async def create_group(payload: GroupIn, request: Request,
                       db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """新建分组；重名 → 409"""
    _need_note(principal, "write")
    name = _clean_name(payload.name)
    color = _clean_color(payload.color)
    if await _name_taken(db, name):
        raise HTTPException(409, "分组名已存在")

    g = NoteGroup(
        name=name, color=color,
        description=(payload.description or "").strip(),
        sort_order=payload.sort_order or 0,
    )
    db.add(g)
    try:
        await db.commit()
    except IntegrityError:
        # 并发建同名分组时，数据库的唯一约束兜住了（应用层判重是并行的）
        await db.rollback()
        raise HTTPException(409, "分组名已存在") from None
    await db.refresh(g)
    audit_svc.mark_created(request, g.id)
    return _out(g)


# ---------- 改 ----------

@router.patch("/{group_id}", dependencies=_WRITE_PAGE)
async def update_group(group_id: int, payload: GroupPatch,
                       db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """改名 / 改颜色 / 改排序；分组不存在 → 404"""
    _need_note(principal, "write")
    g = await db.get(NoteGroup, group_id)
    if not g:
        raise HTTPException(404, "分组不存在")

    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        name = _clean_name(fields["name"])
        if await _name_taken(db, name, exclude_id=group_id):
            raise HTTPException(409, "分组名已存在")
        g.name = name
    if "color" in fields:
        g.color = _clean_color(fields["color"])
    if "description" in fields:
        g.description = (fields["description"] or "").strip()
    if "sort_order" in fields and fields["sort_order"] is not None:
        g.sort_order = fields["sort_order"]

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "分组名已存在") from None
    await db.refresh(g)
    counts = await _note_counts(db)
    return _out(g, counts.get(g.id, 0))


# ---------- 删 ----------

@router.delete("/{group_id}", dependencies=_WRITE_PAGE)
async def delete_group(group_id: int, move_to: int | None = Query(None),
                       db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """删分组：组里的笔记**不删**，只是移出分组（或整体转移到另一个分组）

    ?move_to=<另一分组id> —— 笔记整体转移过去（常用于「把 A 组的活儿并进 B 组」）。
    目标分组不存在 → 400（不静默当成「置空」，那会丢用户想保留的归属）。
    """
    _need_note(principal, "write")
    g = await db.get(NoteGroup, group_id)
    if not g:
        raise HTTPException(404, "分组不存在")

    if move_to is not None:
        if move_to == group_id:
            raise HTTPException(400, "目标分组与当前分组相同")
        target = await db.get(NoteGroup, move_to)
        if not target:
            raise HTTPException(400, f"目标分组 {move_to} 不存在")
        await _move_records(db, group_id, move_to)
    else:
        await _move_records(db, group_id, None)

    # 置空/转移与删分组在同一个事务里：中途失败只完成一半的话，
    # 就会留下「分组没了但笔记还指着它」的脏数据。
    await db.delete(g)
    await db.commit()
    return {"ok": True}
