"""系统管理：用户 / 角色 / 审计日志

三个路由共用前缀 /api/system，前端「系统管理」页一组内切换。
（放在一起是因为它们共享同一份权限点，路由文件拆开反而要重复依赖。）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AuditLog, Role, User, UserSession
from ..services import audit as audit_svc
from ..services.auth import (
    Principal,
    current_principal,
    hash_password,
    require_feature,
    revoke_user_sessions,
)
from ..services.permissions import BUILTIN_ROLES

router = APIRouter(prefix="/api/system", tags=["system"])


# ==================== 用户 ====================

class UserIn(BaseModel):
    username: str
    password: str = ""
    display_name: str = ""
    role_id: int | None = None
    is_active: bool = True


class UserPatch(BaseModel):
    display_name: str | None = None
    role_id: int | None = None
    is_active: bool | None = None
    password: str | None = None


def _user_out(u: User, role: Role | None) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "role_id": u.role_id,
        "role_name": role.name if role else "",
        "role_key": role.key if role else "",
        "is_active": u.is_active,
        "must_change_password": u.must_change_password,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
    }


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(require_feature("user_manage"))):
    rows = (await db.execute(select(User).order_by(User.id))).scalars().all()
    roles = {r.id: r for r in (await db.execute(select(Role))).scalars().all()}
    return {"items": [_user_out(u, roles.get(u.role_id)) for u in rows]}


@router.post("/users")
async def create_user(payload: UserIn, request: Request,
                      db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("user_manage"))):
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(400, "请填写用户名")
    if len(payload.password or "") < 8:
        raise HTTPException(400, "密码至少 8 位")
    exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"用户名「{username}」已存在")
    if payload.role_id and not await db.get(Role, payload.role_id):
        raise HTTPException(400, "角色不存在")

    u = User(username=username, display_name=payload.display_name or username,
             password_hash=hash_password(payload.password),
             role_id=payload.role_id, is_active=payload.is_active)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    audit_svc.mark_created(request, u.id)
    return _user_out(u, await db.get(Role, u.role_id) if u.role_id else None)


@router.patch("/users/{user_id}")
async def update_user(user_id: int, payload: UserPatch, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("user_manage"))):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")

    changing_own_role = principal.id == u.id
    if payload.role_id is not None and payload.role_id != u.role_id:
        if payload.role_id and not await db.get(Role, payload.role_id):
            raise HTTPException(400, "角色不存在")
        if changing_own_role:
            raise HTTPException(400, "不能修改自己的角色，请让其他管理员操作")
        u.role_id = payload.role_id
        await revoke_user_sessions(db, u.id)     # 权限变了，旧会话立即失效

    if payload.is_active is not None and payload.is_active != u.is_active:
        if changing_own_role and not payload.is_active:
            raise HTTPException(400, "不能停用当前登录的账号")
        u.is_active = payload.is_active
        if not payload.is_active:
            await revoke_user_sessions(db, u.id)

    if payload.display_name is not None:
        u.display_name = payload.display_name

    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(400, "密码至少 8 位")
        u.password_hash = hash_password(payload.password)
        u.must_change_password = True            # 管理员重置的口令，要求本人再改一次
        await revoke_user_sessions(db, u.id)

    await db.commit()
    await db.refresh(u)
    return _user_out(u, await db.get(Role, u.role_id) if u.role_id else None)


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("user_manage"))):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    if principal.id == u.id:
        raise HTTPException(400, "不能删除当前登录的账号")
    total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    if total <= 1:
        raise HTTPException(400, "至少保留一个用户")

    await revoke_user_sessions(db, u.id)
    await db.delete(u)
    await db.commit()
    return {"ok": True}


# ==================== 角色 ====================

class RoleIn(BaseModel):
    key: str
    name: str
    description: str = ""
    perms: dict = {}


class RolePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    perms: dict | None = None


def _clean_perms(perms: dict) -> dict:
    """白名单化：只接受已知权限点，避免前端传进来一堆垃圾键"""
    from ..services.permissions import FEATURES, MODEL_LEVELS, PAGES

    perms = perms or {}
    pages = [p for p in (perms.get("pages") or []) if p in PAGES]
    features = {k: bool(v) for k, v in (perms.get("features") or {}).items() if k in FEATURES}
    models = {}
    for k, v in (perms.get("models") or {}).items():
        if v in MODEL_LEVELS:
            models[str(k)[:64]] = v
    return {"all": bool(perms.get("all")), "pages": pages, "models": models, "features": features}


def _role_out(r: Role) -> dict:
    return {"id": r.id, "key": r.key, "name": r.name, "description": r.description,
            "is_builtin": r.is_builtin, "perms": r.perms or {},
            "user_count": getattr(r, "_user_count", 0)}


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(require_feature("role_manage"))):
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    counts = dict((await db.execute(
        select(User.role_id, func.count(User.id)).group_by(User.role_id)
    )).all())
    out = []
    for r in roles:
        item = _role_out(r)
        item["user_count"] = counts.get(r.id, 0)
        out.append(item)
    return {"items": out}


@router.post("/roles")
async def create_role(payload: RoleIn, request: Request,
                      db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("role_manage"))):
    key = (payload.key or "").strip()
    if not key or not payload.name:
        raise HTTPException(400, "请填写角色标识与名称")
    if (await db.execute(select(Role).where(Role.key == key))).scalar_one_or_none():
        raise HTTPException(400, f"角色标识「{key}」已存在")

    perms = _clean_perms(payload.perms)
    if perms["all"] and not principal.is_super:
        raise HTTPException(403, "只有超级管理员能创建超级管理员角色")

    r = Role(key=key, name=payload.name, description=payload.description,
             is_builtin=False, perms=perms)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    audit_svc.mark_created(request, r.id)
    return _role_out(r)


@router.patch("/roles/{role_id}")
async def update_role(role_id: int, payload: RolePatch, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("role_manage"))):
    r = await db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "角色不存在")

    if payload.perms is not None:
        perms = _clean_perms(payload.perms)
        if r.key == "admin" and not perms.get("all"):
            raise HTTPException(400, "管理员角色必须保留全部权限，否则会把自己锁在外面")
        if perms.get("all") and not principal.is_super:
            raise HTTPException(403, "只有超级管理员能授予全部权限")
        r.perms = perms
        # 权限变更后，属于该角色的用户需要重新登录才会拿到新权限点；
        # 这里主动清会话，避免「改了权限但对方还能用旧权限操作」。
        uids = (await db.execute(select(User.id).where(User.role_id == r.id))).scalars().all()
        for uid in uids:
            await revoke_user_sessions(db, uid)

    if payload.name is not None:
        r.name = payload.name
    if payload.description is not None:
        r.description = payload.description

    await db.commit()
    await db.refresh(r)
    return _role_out(r)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("role_manage"))):
    r = await db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    if r.is_builtin:
        raise HTTPException(400, "内置角色不可删除")
    used = (await db.execute(
        select(func.count(User.id)).where(User.role_id == r.id)
    )).scalar() or 0
    if used:
        raise HTTPException(400, f"还有 {used} 个用户在使用该角色，请先改派")

    await db.delete(r)
    await db.commit()
    return {"ok": True}


# ==================== 审计日志 ====================

@router.get("/audit")
async def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    keyword: str = "",
    username: str = "",
    resource: str = "",
    action: str = "",
    days: int = Query(0, ge=0, le=3650),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_feature("audit_view")),
):
    conds = []
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        conds.append(AuditLog.path.like(kw) | AuditLog.resource.like(kw)
                     | AuditLog.username.like(kw) | AuditLog.resource_id.like(kw))
    if username:
        conds.append(AuditLog.username == username)
    if resource:
        conds.append(AuditLog.resource == resource)
    if action:
        conds.append(AuditLog.action == action)
    if days:
        conds.append(AuditLog.created_at >= datetime.now() - timedelta(days=days))

    base = select(AuditLog)
    for c in conds:
        base = base.where(c)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return {
        "items": [{
            "id": r.id, "username": r.username, "action": r.action,
            "resource": r.resource, "resource_id": r.resource_id,
            "method": r.method, "path": r.path, "status": r.status,
            "ip": r.ip, "detail": r.detail or {}, "created_at": r.created_at,
        } for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "facets": await _audit_facets(db),
    }


async def _audit_facets(db: AsyncSession) -> dict:
    """筛选下拉的可选值：从现有日志里取，避免前端硬编码"""
    users = [u for (u,) in (await db.execute(
        select(AuditLog.username).group_by(AuditLog.username).order_by(AuditLog.username)
    )).all() if u]
    resources = sorted({r for (r,) in (await db.execute(
        select(AuditLog.resource).group_by(AuditLog.resource)
    )).all() if r})
    actions = sorted({a for (a,) in (await db.execute(
        select(AuditLog.action).group_by(AuditLog.action)
    )).all() if a})
    return {"users": users, "resources": resources, "actions": actions}


@router.get("/audit/stats")
async def audit_stats(days: int = Query(7, ge=1, le=90),
                      db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(require_feature("audit_view"))):
    """近 N 天：写入量趋势 + 按用户/资源分布（审计页顶部图表）"""
    since = datetime.now() - timedelta(days=days)
    rows = (await db.execute(
        select(AuditLog.created_at, AuditLog.username, AuditLog.resource, AuditLog.action)
        .where(AuditLog.created_at >= since)
    )).all()

    by_day: dict[str, int] = {}
    by_user: dict[str, int] = {}
    by_resource: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for created, user, res, act in rows:
        if created:
            day = created.strftime("%m-%d")
            by_day[day] = by_day.get(day, 0) + 1
        by_user[user or "-"] = by_user.get(user or "-", 0) + 1
        by_resource[res or "-"] = by_resource.get(res or "-", 0) + 1
        by_action[act or "-"] = by_action.get(act or "-", 0) + 1

    days_list = [(datetime.now() - timedelta(days=days - 1 - i)).strftime("%m-%d")
                 for i in range(days)]
    return {
        "trend": [{"day": d, "count": by_day.get(d, 0)} for d in days_list],
        "by_user": sorted(({"name": k, "value": v} for k, v in by_user.items()),
                          key=lambda x: -x["value"])[:10],
        "by_resource": sorted(({"name": k, "value": v} for k, v in by_resource.items()),
                              key=lambda x: -x["value"])[:10],
        "by_action": sorted(({"name": k, "value": v} for k, v in by_action.items()),
                            key=lambda x: -x["value"])[:10],
        "total": len(rows),
    }


# ==================== 存储与备份 ====================
#
# 单列一段而不是并进「审计」：存储诊断看的是基础设施，跟谁改了什么是两件事，
# 权限点也分开（storage_manage / audit_view），免得"能看日志"就等于"能重整数据库"。

@router.get("/storage")
async def storage(principal: Principal = Depends(require_feature("storage_manage"))):
    """存储体检：体积构成、容量余量、索引占比、增长趋势"""
    from ..services import maintenance as maint
    return await maint.storage_report()


@router.get("/storage/index")
async def storage_index(db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(require_feature("storage_manage"))):
    """索引一致性体检：全文/向量索引与业务表是否还对得上"""
    from ..services import maintenance as maint
    return await maint.index_report(db)


@router.post("/storage/index/repair")
async def storage_index_repair(request: Request,
                               db: AsyncSession = Depends(get_db),
                               principal: Principal = Depends(require_feature("storage_manage"))):
    """修复索引漂移（幂等；只校准状态与补全文索引，不重算向量）"""
    from ..services import maintenance as maint
    out = await maint.repair_index(db)
    request.state.audit_detail = {"fixed": out}
    return {"ok": True, **out}


@router.get("/storage/ops")
async def storage_ops(principal: Principal = Depends(require_feature("storage_manage"))):
    """可执行的维护动作清单（含「是否阻塞」说明，供界面提示风险）"""
    from ..services import maintenance as maint
    return {"items": [{"key": k, **v} for k, v in maint.OPS.items()]}


@router.post("/storage/ops/{op}")
async def storage_run_op(op: str, request: Request, batch: int = 50,
                         principal: Principal = Depends(require_feature("storage_manage"))):
    """执行维护动作：optimize / checkpoint / analyze / incremental_vacuum /
    vacuum / integrity_check / externalize_blobs / verify_files

    batch 只对 externalize_blobs 生效：一次请求搬多少个文件。
    界面上的按钮会循环调用直到 remaining=0，这样单个请求不会长到被网关掐断。
    """
    from ..services import maintenance as maint
    if op not in maint.OPS:
        raise HTTPException(400, f"不支持的动作：{op}")
    out = await maint.run_op(op, batch=max(1, min(batch, 500)))
    request.state.audit_detail = {"op": op, "result": str(out.get("result"))[:200],
                                  "elapsed_ms": out.get("elapsed_ms")}
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("result")))
    return out


@router.post("/storage/backup")
async def storage_backup(request: Request,
                         principal: Principal = Depends(require_feature("storage_manage"))):
    """立即做一次在线一致性备份（VACUUM INTO），产出落在备份目录"""
    from ..services import maintenance as maint
    out = await maint.make_backup()
    request.state.audit_detail = {"path": out.get("path"), "bytes": out.get("bytes")}
    if not out.get("ok"):
        raise HTTPException(500, str(out.get("error") or "备份失败"))
    return out


@router.get("/storage/backups")
async def storage_backups(principal: Principal = Depends(require_feature("storage_manage"))):
    """列出已有备份文件"""
    from ..services import maintenance as maint
    return {"items": await maint.list_backups(),
            "dir": await maint.backup_dir()}


class RestoreIn(BaseModel):
    name: str        # 快照目录名（snap-...）
    confirm: str = ""  # 前端要求输入快照名确认，这里再核一遍


@router.post("/storage/restore")
async def storage_restore(body: RestoreIn, request: Request,
                          principal: Principal = Depends(require_feature("storage_manage"))):
    """在线还原到指定快照（不停服务）

    流程与安全设计见 services/maintenance.py 的 restore_snapshot：
    先校验快照 → 给当前状态留退路 → 阻塞其他请求 → 同步文件 →
    在线换库 → 自检（不过则自动回滚）。
    还原成功后当前会话随旧库失效，需要用备份时刻的账号口令重新登录。
    """
    from ..services import maintenance as maint
    if body.confirm != body.name:
        raise HTTPException(400, "确认文本与快照名不一致")
    out = await maint.restore_snapshot(body.name, who=principal.username)
    request.state.audit_detail = {"snapshot": body.name, "ok": out.get("ok"),
                                  "elapsed_ms": out.get("elapsed_ms"),
                                  "safety": out.get("safety_snapshot")}
    if not out.get("ok"):
        # 400 而不是 500：失败都发生在动手前或已自动回滚，属于可解释的拒绝
        raise HTTPException(400, str(out.get("error") or "还原失败"))
    return out


# ==================== 运行期设置（改完立即生效，无需重启） ====================
#
# 为什么要有这一组接口，而不是让人去改 .env：见 services/settings_store.py
# 顶部说明 —— 核心是「容器里环境变量被 compose 写死」和「备份目录不能存在
# 数据库里（恢复时才有鸡生蛋问题）」。

class SettingsIn(BaseModel):
    items: dict[str, Any]


class PathIn(BaseModel):
    path: str


@router.get("/settings")
async def get_settings(principal: Principal = Depends(require_feature("system_config"))):
    """当前生效的运行期配置（含来源标注与校验规则）"""
    from ..services import settings_store as ss
    return {
        "items": ss.describe(),
        "file": str(ss.BOOTSTRAP_FILE),
        "precedence": [
            {"source": "file", "label": "系统设置", "note": "在本页修改的值，立即生效"},
            {"source": "env", "label": "环境变量", "note": "来自 .env / compose，需重启容器"},
            {"source": "default", "label": "代码默认值", "note": "未做任何设置时使用"},
        ],
    }


@router.put("/settings")
async def update_settings(payload: SettingsIn, request: Request,
                          principal: Principal = Depends(require_feature("system_config"))):
    """保存运行期配置。任一项校验失败则整体不落盘。

    校验不是走形式：备份目录会做一次真实的「建目录 → 写 → 读回 → 删」探针，
    并且拒绝落在容器可写层上的路径 —— 那种路径写备份，容器一重建就全没了，
    而当事人会一直以为自己在正常备份。
    """
    from ..services import settings_store as ss
    out = await ss.set_many(payload.items, who=principal.username)
    request.state.audit_detail = {"changed": out.get("changed")}
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error")))
    return {"ok": True, **out, "items": ss.describe()}


@router.delete("/settings/{key}")
async def reset_setting(key: str, request: Request,
                        principal: Principal = Depends(require_feature("system_config"))):
    """把某项恢复成环境变量/默认值（删掉本页的覆盖）"""
    from ..services import settings_store as ss
    out = await ss.reset(key, who=principal.username)
    request.state.audit_detail = {"reset": key}
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error")))
    return {"ok": True, **out, "items": ss.describe()}


@router.get("/settings/backup-targets")
async def backup_targets(principal: Principal = Depends(require_feature("system_config"))):
    """可作为备份目录的容器内路径（带探针结果）

    只列**持久挂载点**及其子目录。列表里没有别的盘，就说明 compose 还没把
    宿主机的盘挂进容器 —— 界面会据此给出可复制的挂载片段。
    """
    from ..services import settings_store as ss
    return ss.backup_targets()


@router.post("/settings/probe")
async def probe_path(payload: PathIn,
                     principal: Principal = Depends(require_feature("system_config"))):
    """保存前先试一下：目录能不能建、能不能写、是不是持久盘"""
    from ..services import settings_store as ss
    info = ss.probe_dir(payload.path)
    if info["ok"] and not info["persistent"]:
        info["error"] = ("该路径不在任何持久挂载点上（属于容器可写层），"
                         "容器重建后备份会全部丢失")
        info["ok"] = False
    return info


# ==================== 升级更新（GitHub Releases）====================
#
# 只做「检查」：有没有新版、改了什么、怎么升。升级本身（git fetch →
# checkout tag → 重建镜像）只能发生在宿主机（容器里没有 docker），
# 由 scripts/upgrade.sh 执行 —— 接口不越权代执行，见 services/update.py。

@router.get("/update/check")
async def update_check(refresh: int = 0,
                       principal: Principal = Depends(require_feature("system_config"))):
    """对比 GitHub 最新 Release 与当前版本

    refresh=1 跳过服务端缓存（界面上「重新检查」按钮用）。
    网络失败也返回 200 + ok=false + 人话错误，前端按字段渲染而不是吃报错弹窗。
    """
    from ..services import update as upd
    return await upd.check_update(refresh=bool(refresh))

