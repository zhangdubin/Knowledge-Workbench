"""认证与授权服务

三件事：
  1. 口令哈希（PBKDF2-HMAC-SHA256，标准库实现，不引第三方依赖）
  2. 会话（不透明 token + user_session 表，Cookie 为主、Bearer 为辅）
  3. 授权（角色 → 权限点；模型级读写单独判）

为什么不用 JWT：会话吊销是刚需（停用账号、改密、踢下线），
JWT 要做到同样效果还得再维护一张黑名单，不如直接查表。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import Role, User, UserSession
from .permissions import admin_perms

log = logging.getLogger("kb.auth")

COOKIE_NAME = "kb_session"
PBKDF2_ROUNDS = 120_000


# ---------- 口令 ----------

def hash_password(password: str) -> str:
    """返回 pbkdf2$<rounds>$<salt_hex>$<hash_hex>，格式自描述，便于将来换算法"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except Exception:
        return False
    # 定时安全比较：避免通过响应时间逐字节猜哈希
    return hmac.compare_digest(digest.hex(), hash_hex)


# ---------- 会话 ----------

def _now() -> datetime:
    return datetime.now()


async def create_session(db: AsyncSession, user: User, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        token=token,
        user_id=user.id,
        expires_at=_now() + timedelta(days=settings.session_days),
        last_seen_at=_now(),
        ip=(request.client.host if request and request.client else "") or "",
        user_agent=((request.headers.get("user-agent") if request else "") or "")[:250],
    ))
    user.last_login_at = _now()
    await db.commit()
    return token


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token == token))
    await db.commit()


async def revoke_user_sessions(db: AsyncSession, user_id: int) -> None:
    """改密 / 停用 / 删除角色后清掉该用户全部会话"""
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await db.commit()


def _token_from(request: Request) -> str:
    """Cookie 优先，其次 Authorization: Bearer

    Cookie 是主通道：文件预览走 <img>/<iframe>，那些请求带不了自定义头。
    """
    tok = request.cookies.get(COOKIE_NAME) or ""
    if tok:
        return tok
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


# ---------- 当前用户 ----------

class Principal:
    """当前请求的身份：用户 + 角色权限（鉴权期间只读一次）"""

    def __init__(self, user: User | None, perms: dict, *, auth_disabled: bool = False):
        self.user = user
        self.perms = perms
        self.auth_disabled = auth_disabled

    # --- 身份信息 ---
    @property
    def id(self) -> int | None:
        return self.user.id if self.user else None

    @property
    def username(self) -> str:
        if self.user:
            return self.user.username
        return "anonymous" if not self.auth_disabled else "local"

    @property
    def is_super(self) -> bool:
        return bool(self.perms.get("all"))

    @property
    def must_change_password(self) -> bool:
        return bool(self.user and self.user.must_change_password)

    # --- 权限判定 ---
    def has_page(self, page: str) -> bool:
        return self.is_super or page in (self.perms.get("pages") or [])

    def has_feature(self, feature: str) -> bool:
        return self.is_super or bool((self.perms.get("features") or {}).get(feature))

    def model_level(self, model_key: str) -> str:
        """返回 none / read / write；通配 * 作为兜底"""
        if self.is_super:
            return "write"
        models = self.perms.get("models") or {}
        level = models.get(model_key)
        if level is None:
            level = models.get("*")
        return level or "none"

    def can_model(self, model_key: str, need: str = "read") -> bool:
        order = {"none": 0, "read": 1, "write": 2}
        return order.get(self.model_level(model_key), 0) >= order.get(need, 1)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": (self.user.display_name or self.user.username) if self.user else "本机用户",
            "is_super": self.is_super,
            "must_change_password": self.must_change_password,
            "perms": self.perms,
        }


def _anonymous_principal() -> Principal:
    """关闭鉴权时用的等价管理员身份（本地单机调试场景）"""
    return Principal(None, admin_perms(), auth_disabled=True)


async def current_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal:
    """FastAPI 依赖：解析会话 → Principal

    鉴权关闭（settings.auth_enabled=False）时直接给管理员身份，
    这样本地跑验证脚本不必先登录。
    """
    if not settings.auth_enabled:
        principal = _anonymous_principal()
        request.state.user = principal
        return principal

    token = _token_from(request)
    if not token:
        raise HTTPException(401, "未登录")

    sess = await db.get(UserSession, token)
    if not sess:
        raise HTTPException(401, "会话无效，请重新登录")
    if sess.expires_at and sess.expires_at < _now():
        await db.delete(sess)
        await db.commit()
        raise HTTPException(401, "会话已过期，请重新登录")

    user = await db.get(User, sess.user_id)
    if not user or not user.is_active:
        await db.delete(sess)
        await db.commit()
        raise HTTPException(401, "账号不可用")

    role = await db.get(Role, user.role_id) if user.role_id else None
    # 角色被删掉时降级为「只读」而不是直接放行，避免越权
    perms = role.perms if role else {"all": False, "pages": [], "models": {}, "features": {}}

    # 每 5 分钟刷新一次在线时间，避免每个请求都写库
    if not sess.last_seen_at or (_now() - sess.last_seen_at) > timedelta(minutes=5):
        sess.last_seen_at = _now()
        await db.commit()

    principal = Principal(user, perms)

    # 初始口令是公开的默认值：没改密之前只放行 /api/auth/*，
    # 前端会强制弹改密框。否则「默认口令 + 默认开启鉴权」形同虚设。
    if user.must_change_password and not request.url.path.startswith("/api/auth"):
        request.state.user = principal
        raise HTTPException(403, "请先修改初始密码后再继续操作")

    request.state.user = principal
    return principal


def require_feature(feature: str):
    """生成一个功能位依赖：@router.post(..., dependencies=[Depends(require_feature('file_write'))])"""
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_feature(feature):
            raise HTTPException(403, f"没有「{feature}」权限，请联系管理员分配")
        return principal
    return _dep


def require_page(page: str):
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_page(page):
            raise HTTPException(403, "没有访问该页面的权限")
        return principal
    return _dep


def ensure_model(principal: Principal, model_key: str, need: str = "read") -> None:
    """模型级校验：records / entity_types 路由里调用"""
    if not principal.can_model(model_key, need):
        level = principal.model_level(model_key)
        raise HTTPException(
            403,
            f"对模型「{model_key}」没有{'写' if need == 'write' else '读'}权限（当前：{level}）",
        )


async def ensure_admin_user(db: AsyncSession) -> None:
    """首次启动：确保存在一个可登录的管理员

    口令来源优先级：运行期设置（data/bootstrap.json 里的哈希）> 环境变量
    `KB_ADMIN_PASSWORD` > 代码默认值。并置 must_change_password，
    登录后强制改密 —— 否则「默认口令 + 默认开启鉴权」等于没有鉴权。
    """
    existing = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if existing:
        return

    from . import settings_store

    role = (await db.execute(select(Role).where(Role.key == "admin"))).scalar_one_or_none()
    if not role:
        role = Role(key="admin", name="管理员", description="全部权限",
                    is_builtin=True, perms=admin_perms())
        db.add(role)
        await db.flush()

    db.add(User(
        username="admin",
        display_name="系统管理员",
        password_hash=settings_store.admin_password_hash(),
        role_id=role.id,
        is_active=True,
        must_change_password=True,
    ))
    await db.commit()
    log.warning("已创建初始管理员 admin（口令来自%s，登录后必须修改）",
                "系统设置" if settings_store.is_customized("admin_password")
                else "环境变量或默认值")
