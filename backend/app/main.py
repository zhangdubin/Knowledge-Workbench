"""FastAPI 入口"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import SessionLocal, init_db
from .routers import (    entity_types, records, relations, attachments, apps, search, notes, jsontree, ai,
    knowledge, documents, auth, system, dashboards, recycle,
)
from .services.audit import AuditMiddleware
from .services.auth import current_principal

# 日志统一在入口配置一次：给每条日志打上时间戳与来源，
# 容器日志被 docker 收走之后，没有时间戳就没法跟事件对齐。
logging.basicConfig(
    level=getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kb-workbench")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initializing database...")
    await init_db()

    # 启动自检：库结构有问题要在启动时就喊出来，而不是等某个查询报错才发现
    from .services.scheduler import scheduler
    if settings.startup_quick_check:
        from .database import probe_health
        h = await probe_health()
        # 结果同时喂给健康缓存：这样 /api/health 从第一个请求起就有真实结论，
        # 而不是要等到第一次定时探测（最长 10 分钟）才不再报 unknown
        scheduler.prime_health(h)
        if h["ok"]:
            log.info("数据库自检通过：%.1f MB，空闲页 %s KB，向量扩展=%s",
                     h["bytes"] / 1048576, h["freelist_kb"], h["vec_available"])
        else:
            log.error("数据库自检异常：quick_check=%s —— 建议立即核对备份", h["quick_check"])

    # 审计日志按保留期清理（只做一次，避免每次请求都查）
    try:
        from .services.audit import purge_old
        async with SessionLocal() as s:
            n = await purge_old(s)
            if n:
                log.info("已清理 %s 条过期审计日志", n)
    except Exception as e:
        log.warning("审计日志清理跳过：%s", e)
    # 运行期设置（data/bootstrap.json）：备份目录、备份份数、初始口令。
    # 模块导入时已同步读过一次（建库要用口令），这里再刷新一次是为了
    # 在日志里留下「当前生效的是哪一份配置」，排障时一眼能看到。
    from .services import settings_store
    await settings_store.reload()

    log.info("KB Workbench ready (auth=%s).", settings.auth_enabled)

    # 后台定时维护：过期会话/审计清理、WAL 检查点、查询计划刷新、健康探测。
    # 放在 yield 之前启动，确保服务开始接请求时维护已经在跑。
    await scheduler.start()

    try:
        yield
    finally:
        # 顺序要紧：先停维护循环（否则它会持有连接、让 checkpoint 永远 busy），
        # 再释放连接池，最后才做关停维护
        await scheduler.stop()
        from .database import engine, shutdown_maintenance
        await engine.dispose()
        out = await shutdown_maintenance()
        log.info("关停维护：optimize=%s wal_checkpoint=%s",
                 out["optimized"], out.get("checkpoint"))


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# 中间件顺序：后 added 的先执行。CORS 必须在最外层，
# 否则鉴权失败返回的 401/403 不会带上 CORS 头，前端只看到网络错误。
app.add_middleware(AuditMiddleware)

# 通配来源与「携带 Cookie」在浏览器侧是互斥的：规范明确禁止
# `Access-Control-Allow-Origin: *` 与 `Allow-Credentials: true` 同时出现，
# 浏览器会直接拒掉响应。此前两个都开着，等于「配了跨域但登录态永远带不过去」，
# 且不会报任何服务端错误 —— 这里在启动时就把矛盾解开。
_cors_wildcard = "*" in (settings.cors_origins or [])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or [],
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _cors_wildcard:
    log.warning("CORS 允许来源为 *，已自动关闭凭证传递（Cookie 不会随跨域请求发送）。"
                "需要跨域登录请把具体前端域名写进 KB_CORS_ORIGINS。")
if not settings.cors_origins:
    log.info("CORS 未配置允许来源：只接受同源请求（前端由 nginx 反代 /api，属同源）")


def _http_exc_payload(code: int, detail) -> dict:
    return {"ok": False, "detail": detail, "code": code}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一错误体，前端拦截器只认 detail 字段

    401/403 额外带 hint，前端可据此直接弹出登录框或权限提示。
    """
    detail = exc.detail
    body = _http_exc_payload(exc.status_code, detail)
    if exc.status_code in (401, 403):
        body["hint"] = "unauthorized" if exc.status_code == 401 else "forbidden"
    return JSONResponse(status_code=exc.status_code, content=body,
                        headers=getattr(exc, "headers", None))


@app.get("/api/health")
async def health():
    """存活 + 就绪检查（Docker healthcheck 每 10 秒打一次，必须足够快）

    db.ok 取自后台定时探测的缓存，不在请求里查库 —— 每 10 秒跑一次
    quick_check 纯属浪费，而缓存值超过 3 个探测周期未更新会被标成 stale，
    这本身就是「后台维护停摆」的信号。
    """
    from .services.scheduler import health_snapshot
    h = health_snapshot()
    return {
        "ok": True,
        "app": settings.app_name,
        "version": settings.app_version,
        "auth_enabled": settings.auth_enabled,
        "db": {
            "ok": h["ok"],
            "quick_check": h["quick_check"],
            "stale": bool(h["at"] and not h["fresh"]),
            "age_seconds": h["age_seconds"],
            "vec_available": h["vec_available"],
        },
        "maintenance": h["maintenance_enabled"],
    }


@app.get("/api/health/deep")
async def health_deep():
    """深度自检：现跑一次库检查 + 文件目录余量 + 备份目录可写

    给上线前自检和排障用；不要挂到 Docker healthcheck 上（会定期跑全库检查）。
    """
    from .database import probe_health
    from .services import filestore
    from .services.maintenance import backup_dir

    probe = await probe_health()
    store = filestore.status()
    bdir = await backup_dir()
    writable = False
    try:
        os.makedirs(bdir, exist_ok=True)
        probe_file = os.path.join(bdir, ".write-test")
        with open(probe_file, "w") as f:
            f.write("ok")
        os.remove(probe_file)
        writable = True
    except Exception as e:
        log.warning("备份目录不可写 %s：%s", bdir, e)

    return {
        "ok": bool(probe.get("ok")) and writable,
        "app": settings.app_name,
        "version": settings.app_version,
        "database": probe,
        "file_store": store,
        "backup": {"dir": bdir, "writable": writable,
                   "keep": settings.backup_keep},
    }


# ---- 公开路由（无需登录）----
app.include_router(auth.router)

# ---- 需登录的路由 ----
PROTECTED = [
    entity_types, records, relations, attachments, documents,
    apps, search, notes, knowledge, jsontree, ai, dashboards, recycle,
]
for mod in PROTECTED:
    app.include_router(mod.router, dependencies=[Depends(current_principal)])

app.include_router(apps.stats_router, dependencies=[Depends(current_principal)])
app.include_router(system.router)   # 内部自带 require_feature 依赖


@app.get("/")
async def root():
    return {"app": settings.app_name, "docs": "/api/docs"}
