"""认证路由：登录 / 登出 / 当前身份 / 改密

注意：/status 必须免鉴权（登录页要靠它判断是否需要引导初始化），
其余接口都要求已登录。
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import Role, User
from ..services import audit as audit_svc
from ..services.auth import (
    COOKIE_NAME,
    Principal,
    create_session,
    current_principal,
    hash_password,
    revoke_session,
    revoke_user_sessions,
    verify_password,
)
from ..services.permissions import FEATURE_LABELS, MODEL_LEVEL_LABELS, PAGE_LABELS, PAGES, FEATURES

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 登录失败节流：内存计数足够（单进程部署），
# 目的是挡住暴力猜口令，而不是做分布式风控。
_FAILS: dict[str, list[float]] = defaultdict(list)
_WINDOW = 600.0
_MAX_FAILS = 8


def _throttle_key(username: str, request: Request) -> str:
    ip = request.client.host if request.client else "?"
    return f"{username.lower()}@{ip}"


def _check_throttle(key: str) -> None:
    now = time.time()
    hits = [t for t in _FAILS[key] if now - t < _WINDOW]
    _FAILS[key] = hits
    if len(hits) >= _MAX_FAILS:
        wait = int(_WINDOW - (now - hits[0]))
        raise HTTPException(429, f"登录失败次数过多，请 {max(wait, 1)} 秒后再试")


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str = ""
    new_password: str


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,          # 前端 JS 读不到，降低 XSS 窃取会话的风险
        samesite="lax",         # 兼顾跨站请求防护与正常跳转
        # 走 HTTPS 时必须开（KB_COOKIE_SECURE=true），否则会话 Cookie 会在
        # 链路上明文可见；纯 HTTP 内网部署保持关闭，否则浏览器直接不保存。
        secure=settings.cookie_secure,
        path="/",
    )


@router.get("/status")
async def status(request: Request, db: AsyncSession = Depends(get_db)):
    """公开接口：登录页用它决定「显示登录框」还是「直接进系统」"""
    info = {
        "auth_enabled": settings.auth_enabled,
        # 系统版本标识：登录页在鉴权之前就要展示，所以搭 /status 的便车带上，
        # 前端不用为它单独再打一次 /api/health。
        "version": settings.app_version,
        "authenticated": False,
        "needs_setup": False,
        # 初始口令是否仍未修改。登录页据此决定要不要提示「首次使用」，不能由
        # 前端写死默认口令字样：部署时用 KB_ADMIN_PASSWORD 覆盖过、或口令已被
        # 改过之后，那句「默认 admin12345」就是误导。
        "initial_password": False,
        "user": None,
    }
    if not settings.auth_enabled:
        # 关闭鉴权时直接给管理员身份，前端无需登录
        return {**info, "authenticated": True, "user": {
            "id": None, "username": "local", "display_name": "本机用户",
            "is_super": True, "must_change_password": False,
            "perms": {"all": True, "pages": PAGES, "models": {"*": "write"},
                      "features": {k: True for k in FEATURES}},
        }}

    has_user = (await db.execute(select(User.id).limit(1))).first()
    info["needs_setup"] = not has_user

    if has_user:
        admin = (await db.execute(
            select(User).where(User.username == "admin")
        )).scalar_one_or_none()
        info["initial_password"] = bool(admin and admin.must_change_password)

    token = request.cookies.get(COOKIE_NAME) or ""
    if token:
        try:
            principal = await current_principal(request, db)
            info["authenticated"] = True
            info["user"] = principal.summary()
        except HTTPException:
            info["authenticated"] = False
    return info


@router.get("/meta")
async def meta():
    """权限点的中文标签，供角色编辑界面渲染矩阵（免登录也可读，不敏感）"""
    return {
        "pages": [{"key": k, "label": PAGE_LABELS.get(k, k)} for k in PAGES],
        "features": [{"key": k, "label": FEATURE_LABELS.get(k, k)} for k in FEATURES],
        "levels": [{"key": k, "label": v} for k, v in MODEL_LEVEL_LABELS.items()],
    }


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)):
    username = (payload.username or "").strip()
    key = _throttle_key(username, request)
    _check_throttle(key)

    user = (await db.execute(
        select(User).where(User.username == username)
    )).scalar_one_or_none()

    ok = bool(user) and user.is_active and verify_password(payload.password, user.password_hash)
    if not ok:
        _FAILS[key].append(time.time())
        await audit_svc.log_event(
            username or "-", "login_failed", status=401,
            ip=(request.client.host if request.client else ""),
            detail={"reason": "账号或口令不正确"},
        )
        # 不区分「用户不存在」与「口令错」，避免账号枚举
        raise HTTPException(401, "账号或密码不正确")
    if not user.is_active:
        raise HTTPException(403, "账号已停用")

    _FAILS.pop(key, None)
    token = await create_session(db, user, request)
    _set_cookie(response, token)

    role = await db.get(Role, user.role_id) if user.role_id else None
    perms = role.perms if role else {"all": False, "pages": [], "models": {}, "features": {}}
    principal = Principal(user, perms)

    await audit_svc.log_event(
        user.username, "login", user_id=user.id,
        ip=(request.client.host if request.client else ""),
        detail={"role": role.name if role else "（无角色）"},
    )
    return {"ok": True, "user": principal.summary()}


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME) or ""
    if token:
        await revoke_session(db, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(principal: Principal = Depends(current_principal)):
    return principal.summary()


@router.post("/password")
async def change_password(payload: PasswordIn, request: Request,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_db)):
    """改自己的密码。初始管理员被强制改密，所以这里必须允许在
    must_change_password 状态下调用（见 current_principal 的白名单）。"""
    if principal.auth_disabled or not principal.user:
        raise HTTPException(400, "当前未启用登录，无需改密")

    user = await db.get(User, principal.user.id)
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "原密码不正确")

    new_pw = payload.new_password or ""
    if len(new_pw) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    if new_pw == payload.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")

    user.password_hash = hash_password(new_pw)
    user.must_change_password = False
    await db.commit()

    # 改密后清掉所有旧会话（含当前这条），强制重新登录
    await revoke_user_sessions(db, user.id)
    await audit_svc.log_event(
        user.username, "change_password", user_id=user.id,
        ip=(request.client.host if request.client else ""),
    )
    return {"ok": True, "relogin": True}
