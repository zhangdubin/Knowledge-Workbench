"""审计日志

只记「写操作 + 登录事件」。读操作量级大、且几乎没有追责价值，
全量记录会把真正重要的改动淹掉，也会让审计表迅速膨胀。

实现方式：ASGI 中间件在响应返回后落库。用独立 session 写 —— 请求自己的
session 此刻已经 commit/close，复用它只会引出难查的连接状态问题。
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..database import SessionLocal
from ..models import AuditLog

log = logging.getLogger("kb.audit")

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ACTION_BY_METHOD = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}

# 资源名归一：路径段 → 业务对象
RESOURCE_ALIAS = {
    "entity-types": "entity_type",
    "documents": "document",
    "attachments": "attachment",
    "records": "record",
    "relations": "relation",
    "apps": "app",
    "notes": "note",
    "knowledge": "knowledge",
    "dashboards": "dashboard",
    "users": "user",
    "roles": "role",
    "ai": "ai",
    "json": "json",
    "storage": "storage",
}


# 只是分组的路径前缀，不是资源本身。`/api/system/users/2` 的真实资源是
# users：不剥掉这层，用户/角色/审计三类写操作会全被记成资源 "system"，
# 审计页「按资源筛选」就失去意义。
GROUP_PREFIX = {"system"}


def _describe(request) -> tuple[str, str, str]:
    """路径 → (resource, resource_id, action)

    特例单独处理：上传、导入、链接这类语义从 HTTP 方法上看不出来。
    """
    segs = [p for p in request.url.path.split("/") if p]
    if segs and segs[0] == "api":
        segs = segs[1:]
    if len(segs) > 1 and segs[0] in GROUP_PREFIX:
        segs = segs[1:]

    resource = RESOURCE_ALIAS.get(segs[0], segs[0]) if segs else "api"

    # id 与子动作按「谁在前」判定：/api/documents/28/link → (28, link)
    rid, sub = "", ""
    for s in segs[1:]:
        if s.isdigit() and not rid:
            rid = s
        elif not sub:
            sub = s

    action = ACTION_BY_METHOD.get(request.method, request.method.lower())
    if sub in ("upload",):
        action = "upload"
    elif sub in ("import",):
        action = "import"
    elif sub == "export":
        action = "export"
    elif sub in ("restore",):
        action = "restore"
    elif sub in ("reindex",):
        action = "reindex"
    elif sub in ("link", "unlink"):
        action = sub
    elif sub == "ops" and len(segs) > 2:
        # /storage/ops/vacuum → maint_vacuum。维护动作不是「新建了一条 storage」，
        # 按 HTTP 方法记会完全看不出到底跑了什么。
        action = f"maint_{segs[2]}"
    elif sub == "backup":
        action = "backup"
    elif sub == "index" and "repair" in segs:
        action = "repair"
    return resource, rid, action


def mark_created(request, obj_id) -> None:
    """路由创建成功后回填对象 id，让审计能追到「建的是哪一条」

    创建类请求的路径里还没有 id（POST /api/records/type/3），不回填的话
    审计只答得出「谁在什么时候建了一条记录」，答不出「建的是哪一条」。
    这里一律吞异常：审计是旁路，绝不能因为它影响业务响应。
    """
    try:
        request.state.audit_resource_id = str(obj_id)
    except Exception:
        pass


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 还原期间挡掉所有业务请求（库正被整体替换，任何读写都可能与
        # 新旧状态混杂）。只放行健康探针 —— 不然监控会把整个服务误报为宕机。
        # 还原请求本身不受影响：标志是在它进入处理函数之后才置位的。
        from . import maintenance as _maint
        if _maint.restore_in_progress():
            p = request.url.path
            if p.startswith("/api") and not p.startswith("/api/health"):
                from starlette.responses import JSONResponse
                return JSONResponse(
                    status_code=503,
                    content={"detail": "系统正在从快照还原，请稍候重试"},
                    headers={"Retry-After": "30"},
                )

        response = await call_next(request)

        try:
            if not settings.audit_enabled:
                return response
            path = request.url.path
            if not path.startswith("/api") or request.method not in WRITE_METHODS:
                return response
            if path.startswith("/api/auth"):        # 登录事件由 auth 路由自己写
                return response
            if response.status_code >= 400:          # 失败的写请求由路由自己解释
                return response

            principal = getattr(request.state, "user", None)
            resource, rid, action = _describe(request)
            # 优先用路由回填的真实 id（POST 创建时路径里还没有 id）。
            # 必须 getattr 带默认值：Starlette 的 State 没这个属性时直接访问会抛
            # AttributeError，而异常正好被下面「审计失败不影响业务」的兜底吞掉 ——
            # 现象是审计表里只有登录事件、所有写操作静默丢失，极难发现。
            new_id = getattr(request.state, "audit_resource_id", None)
            if new_id is not None:
                rid = str(new_id)

            async with SessionLocal() as db:
                db.add(AuditLog(
                    user_id=principal.id if principal else None,
                    username=principal.username if principal else "",
                    action=action,
                    resource=resource,
                    resource_id=rid or "",
                    method=request.method,
                    path=path[:250],
                    status=response.status_code,
                    ip=(request.client.host if request.client else "") or "",
                    detail=getattr(request.state, "audit_detail", {}) or {},
                ))
                await db.commit()
        except Exception as e:      # 审计失败绝不能影响业务响应
            log.warning("审计写入失败：%s", e)

        return response


async def log_event(username: str, action: str, *, user_id: int | None = None,
                    ip: str = "", detail: dict | None = None, status: int = 200,
                    resource: str = "auth", method: str = "POST",
                    path: str = "/api/auth") -> None:
    """主动记事件（登录成功/失败、改密、AI 代执行等）

    resource / method / path 可覆盖：AI 写操作不在 HTTP 层面体现改了什么，
    必须自己把「哪条记录、改了哪些字段」写进 detail，审计才有用。
    """
    if not settings.audit_enabled:
        return
    try:
        async with SessionLocal() as db:
            db.add(AuditLog(
                user_id=user_id, username=username, action=action,
                resource=resource, method=method, path=path,
                status=status, ip=ip or "", detail=detail or {},
            ))
            await db.commit()
    except Exception as e:
        log.warning("审计写入失败：%s", e)


async def purge_old(db) -> int:
    """清理超过保留期的日志（启动时调用一次）"""
    if not settings.audit_keep_days:
        return 0
    from datetime import datetime, timedelta
    from sqlalchemy import delete

    cutoff = datetime.now() - timedelta(days=settings.audit_keep_days)
    res = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await db.commit()
    return res.rowcount or 0
