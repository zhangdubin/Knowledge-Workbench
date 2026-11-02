"""软件开发模块路由：项目、任务、产出物、会话、引用、闭环

接口分组：
    配置与自检   /api/dev/config、/api/dev/mode、/api/dev/doctor、/api/dev/github/probe
    项目         /api/dev/projects ...
    任务         /api/dev/projects/{id}/tasks ...、/api/dev/tasks/{id}
    生成         /api/dev/projects/{id}/plan、/tasks/{task_id}/output、/chat
    产出物       /api/dev/artifacts ...、/api/dev/artifacts/{id}/import
    闭环         /api/dev/projects/{id}/feedback
    作业进度     /api/dev/jobs/{id}

鉴权口径与养料库一致：只挂 current_principal，不硬拦页面位 ——
页面可见性由前端路由 meta.perm 与 permissions.PAGES 决定。
写操作会写审计日志。

错误口径：所有「缺什么、怎么配」的错误都返回同一个结构
    {ok: false, detail: "…", missing: [...], how_to_fix: [...]}
前端拿 missing / how_to_fix 直接渲染成一张可执行的清单。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import DevCitation, Role, SysMeta
from ..services import audit as audit_svc
from ..services import dev_config
from ..services import dev as svc
from ..services.auth import Principal, current_principal

router = APIRouter(prefix="/api/dev", tags=["dev"])

log = logging.getLogger("kb.dev.router")

# 后台作业句柄：用来取消还在跑的任务（进程重启后由启动清理兜底）
_JOBS: dict[int, asyncio.Task] = {}


# ============ 请求体 ============

class ProjectBody(BaseModel):
    name: str = ""
    goal: str = ""
    tech_stack: list = Field(default_factory=list)
    tech_notes: str = ""
    status: str = ""
    mode: str = ""
    gene_refs: list = Field(default_factory=list)
    library_refs: list = Field(default_factory=list)
    github_refs: list = Field(default_factory=list)


class TaskBody(BaseModel):
    title: str = ""
    description: str = ""
    acceptance: str = ""
    status: str = ""
    depends_on: list = Field(default_factory=list)
    order: int = -1


class ArtifactBody(BaseModel):
    project_id: int = 0
    task_id: int = 0
    filename: str = ""
    path: str = ""
    content: str = ""
    language: str = ""
    artifact_type: str = "code"
    source: str = "manual"
    accepted: bool = False


class ChatBody(BaseModel):
    question: str = ""


class FeedbackBody(BaseModel):
    artifact_ids: list = Field(default_factory=list)
    lessons: str = ""


class GenerateBody(BaseModel):
    extra: str = ""
    force: bool = False


class ConfigBody(BaseModel):
    mode: str = ""
    outbound_enabled: bool = None
    github: dict = Field(default_factory=dict)
    local_model: dict = Field(default_factory=dict)
    web_search: dict = Field(default_factory=dict)
    clear_secrets: Any = None


class ModeBody(BaseModel):
    mode: str


class RepoBody(BaseModel):
    repo: str = ""
    branch: str = ""


# ============ 工具 ============

def _fail(e: svc.DevError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content=e.to_dict())


async def _project_or_404(db: AsyncSession, project_id: int):
    p = await svc.get_project(db, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


async def _task_or_404(db: AsyncSession, task_id: int):
    t = await svc.get_task(db, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


DEV_PERM_META_KEY = "migrated_dev_perm_v1"


async def ensure_dev_page_perm(db: AsyncSession) -> bool:
    """把「软件开发」页面权限补进内置角色（只做一次）

    为什么要在运行时补，而不是只改 permissions.PAGES：
        PAGES 只对**新建**的内置角色生效 ——
        已经跑起来的库里，管理员/编辑/只读三个角色的 pages 列表里
        都没有 "dev"。而左侧导航是按页面权限过滤的，
        「软件开发」这一项会对所有人隐形，页面成了摆设。

    只做一次（sys_meta 记一笔），管理员后来手动调过的权限不会被覆盖回去。
    """
    row = (await db.execute(
        select(SysMeta).where(SysMeta.key == DEV_PERM_META_KEY))).scalar_one_or_none()
    if row is not None:
        return False
    touched = 0
    roles = (await db.execute(
        select(Role).where(Role.is_builtin.is_(True)))).scalars().all()
    for r in roles:
        perms = dict(r.perms or {})
        pages = list(perms.get("pages") or [])
        if "dev" in pages:
            continue
        pages.append("dev")
        perms["pages"] = pages
        r.perms = perms
        touched += 1
    db.add(SysMeta(key=DEV_PERM_META_KEY, value="done:%d" % touched))
    await db.commit()
    if touched:
        log.info("已给 %d 个内置角色补上「软件开发」页面权限", touched)
    return True


async def _guard_perm(db: AsyncSession) -> None:
    """首个请求时补一次权限（放在这里而不是启动流程里：
    启动流程在 database.py，那边正被别人改，不去碰）"""
    try:
        await ensure_dev_page_perm(db)
    except Exception as e:
        log.warning("补页面权限失败：%s", type(e).__name__)


# ============ 配置与自检 ============

@router.get("/config")
async def read_config(db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """开发模块配置（密钥掩码）"""
    await _guard_perm(db)
    cfg = dev_config.public_config()
    cfg["model"] = svc.describe_model(cfg.get("mode") or dev_config.MODE_OFFLINE)
    return cfg


@router.put("/config")
async def write_config(payload: ConfigBody, db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """保存开发模块配置

    注意：前端回传的密钥是掩码时会被当成「不修改」，
    保留磁盘上的真值（与 AI 设置同一套口径）。
    """
    await _guard_perm(db)
    body = payload.model_dump(exclude_none=True)
    # 空串不等于「要设成空」：前端没填模式时不能把当前模式冲掉
    if not body.get("mode"):
        body.pop("mode", None)
    if body.get("mode") and body["mode"] not in dev_config.MODES:
        raise HTTPException(status_code=400, detail="模式只能是 offline 或 online")
    cfg = dev_config.save_config(body)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_config_update",
        user_id=getattr(principal, "id", None),
        resource="dev", method="PUT", path="/api/dev/config",
        detail={"mode": cfg.get("mode"),
                "outbound_enabled": cfg.get("outbound_enabled"),
                "repos": len((cfg.get("github") or {}).get("repos") or [])})
    out = dev_config.public_config()
    out["model"] = svc.describe_model(out.get("mode") or dev_config.MODE_OFFLINE)
    return out


@router.post("/mode")
async def switch_mode(payload: ModeBody, db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """切换全局在线/离线模式

    切到离线模式时，如果本地模型端点没配，如实返回「缺什么」，
    而不是切完了让人一头撞上去。
    """
    await _guard_perm(db)
    if payload.mode not in dev_config.MODES:
        raise HTTPException(status_code=400, detail="模式只能是 offline 或 online")
    cfg = dev_config.load_config()
    cfg["mode"] = payload.mode
    dev_config.save_config(cfg)
    info = svc.describe_model(payload.mode)
    missing = []
    how = []
    if not info.get("ready"):
        missing.append("local_model.base_url" if payload.mode == dev_config.MODE_OFFLINE
                       else "ai.base_url")
        how.append("离线模式需要本地模型端点（OpenAI 兼容，如 Ollama / llama.cpp server）"
                   if payload.mode == dev_config.MODE_OFFLINE
                   else "在线模式需要 AI 设置里的大模型，或开发设置里的本地模型端点")
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_mode_switch",
        user_id=getattr(principal, "id", None),
        resource="dev", method="POST", path="/api/dev/mode",
        detail={"mode": payload.mode})
    return {"mode": payload.mode,
            "mode_label": dev_config.MODE_LABEL.get(payload.mode, payload.mode),
            "model": info,
            "missing": missing,
            "how_to_fix": how}


@router.get("/doctor")
async def doctor(mode: str = "", db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """外部依赖体检：现在缺什么、怎么配

    离线模式下不发任何外网请求（连探测都不做）。
    """
    await _guard_perm(db)
    return await svc.doctor(db, mode=mode)


@router.post("/github/probe")
async def probe_repo(payload: RepoBody, db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    """探测 GitHub 仓库是否可达（仅在线模式）

    离线模式下这里返回「已按离线策略跳过」，不会发请求。
    """
    await _guard_perm(db)
    cfg = dev_config.load_config()
    mode = cfg.get("mode") or dev_config.MODE_OFFLINE
    if mode != dev_config.MODE_ONLINE:
        return {"ok": True, "skipped": True,
                "detail": "当前是离线模式，按策略不访问外网"}
    spec = dev_config.normalize_repo(payload.repo)
    if payload.branch:
        spec["branch"] = payload.branch
    if not dev_config.is_repo_spec_ok(spec):
        raise HTTPException(status_code=400, detail="仓库标识不完整，需要 owner/repo")
    try:
        ov = await svc.dev_github.repo_overview(cfg, mode, spec)
        return {"ok": True, "skipped": False, "repo": ov}
    except dev_config.OutboundBlocked as e:
        return {"ok": False, "skipped": True, "detail": str(e)}
    except Exception as e:
        return {"ok": False, "skipped": False, "detail": str(e)}


# ============ 项目 ============

@router.get("/projects")
async def list_projects(mode: str = "", status: str = "", keyword: str = "",
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    rows = await svc.list_projects(db, mode=mode, status=status, keyword=keyword)
    return {"projects": rows}


@router.post("/projects")
async def create_project(payload: ProjectBody, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    try:
        p = await svc.create_project(db, payload.model_dump(),
                                     principal=getattr(principal, "username", "") or "")
    except svc.DevError as e:
        return _fail(e)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_project_create",
        user_id=getattr(principal, "id", None),
        resource="dev", method="POST", path="/api/dev/projects",
        detail={"project_id": p.id, "name": p.name, "mode": p.mode})
    return {"project": svc.serialize_project(p)}


@router.get("/projects/{project_id}")
async def get_project(project_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """项目详情：方案 + 任务 + 产出物 + 会话 + 引用（一次给全，前端不用拼五个请求）"""
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    return {
        "project": svc.serialize_project(p),
        "tasks": await svc.list_tasks(db, project_id),
        "artifacts": await svc.list_artifacts(db, project_id),
        "sessions": await svc.list_sessions(db, project_id, limit=30),
        "citations": await svc.list_citations(db, project_id),
    }


@router.patch("/projects/{project_id}")
async def patch_project(project_id: int, payload: ProjectBody,
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    p = await svc.update_project(db, p, payload.model_dump(exclude_none=True))
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_project_update",
        user_id=getattr(principal, "id", None),
        resource="dev", method="PATCH", path="/api/dev/projects/%d" % project_id,
        detail={"project_id": project_id})
    return {"project": svc.serialize_project(p)}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    await svc.delete_project(db, p)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_project_delete",
        user_id=getattr(principal, "id", None),
        resource="dev", method="DELETE", path="/api/dev/projects/%d" % project_id,
        detail={"project_id": project_id, "name": p.name})
    return {"ok": True}


@router.post("/projects/{project_id}/plan")
async def generate_plan(project_id: int, payload: GenerateBody = GenerateBody(),
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    """生成项目方案（后台作业，前端轮询 /api/dev/jobs/{id} 看进度）"""
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    # 先做一次「能不能生成」的检查，别让用户等一个注定失败的作业
    try:
        svc.ensure_model_available(p.mode or dev_config.MODE_OFFLINE)
    except svc.DevError as e:
        return _fail(e)
    from ..services import dna_ingest
    job = await dna_ingest.create_job(
        db, job_type="dev_plan",
        title="生成方案：%s" % (p.name or ""), total=1,
        principal=getattr(principal, "username", "") or "")
    task = asyncio.create_task(svc.run_plan_job(job.id, project_id))
    _JOBS[job.id] = task
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_plan_generate",
        user_id=getattr(principal, "id", None),
        resource="dev", method="POST", path="/api/dev/projects/%d/plan" % project_id,
        detail={"project_id": project_id, "job_id": job.id})
    return {"job": dna_ingest.job_to_dict(job)}


@router.post("/projects/{project_id}/tasks/generate-all")
async def generate_all(project_id: int, payload: GenerateBody = GenerateBody(),
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    """逐任务生成产出物（后台作业，进度可见）"""
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    try:
        svc.ensure_model_available(p.mode or dev_config.MODE_OFFLINE)
    except svc.DevError as e:
        return _fail(e)
    from ..services import dna_ingest
    job = await dna_ingest.create_job(
        db, job_type="dev_tasks",
        title="生成任务产出：%s" % (p.name or ""), total=0,
        principal=getattr(principal, "username", "") or "")
    task = asyncio.create_task(svc.run_tasks_job(job.id, project_id))
    _JOBS[job.id] = task
    return {"job": dna_ingest.job_to_dict(job)}


@router.post("/projects/{project_id}/chat")
async def chat(project_id: int, payload: ChatBody,
               db: AsyncSession = Depends(get_db),
               principal: Principal = Depends(current_principal)):
    """工作台里的对话：基于项目与知识库回答，并留下引用"""
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    if not (payload.question or "").strip():
        raise HTTPException(status_code=400, detail="请先输入问题")
    try:
        return await svc.chat(db, p, payload.question,
                              principal=getattr(principal, "username", "") or "")
    except svc.DevError as e:
        return _fail(e)


@router.post("/projects/{project_id}/feedback")
async def feedback(project_id: int, payload: FeedbackBody,
                    db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """反哺知识库：把这次开发的产出沉淀成新的基因经验

    这一步是闭环的收口 —— 产出物 → 基因 → 下一轮开发直接用上。
    """
    await _guard_perm(db)
    p = await _project_or_404(db, project_id)
    try:
        report = await svc.feedback_to_library(
            db, p, principal=getattr(principal, "username", "") or "",
            artifact_ids=payload.artifact_ids or None,
            lessons=payload.lessons or "")
    except svc.DevError as e:
        return _fail(e)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_feedback",
        user_id=getattr(principal, "id", None),
        resource="dev", method="POST",
        path="/api/dev/projects/%d/feedback" % project_id,
        detail={"project_id": project_id, "round": report.get("round"),
                "created": report.get("genes_created")})
    return {"report": report}


# ============ 任务 ============

@router.post("/projects/{project_id}/tasks")
async def create_task(project_id: int, payload: TaskBody,
                      db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    await _project_or_404(db, project_id)
    try:
        t = await svc.create_task(db, project_id, payload.model_dump(exclude_none=True))
    except svc.DevError as e:
        return _fail(e)
    return {"task": svc.serialize_task(t)}


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: int, payload: TaskBody,
                     db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    t = await _task_or_404(db, task_id)
    t = await svc.update_task(db, t, payload.model_dump(exclude_none=True))
    return {"task": svc.serialize_task(t)}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    t = await _task_or_404(db, task_id)
    await svc.delete_task(db, t)
    return {"ok": True}


@router.post("/tasks/{task_id}/output")
async def generate_output(task_id: int, payload: GenerateBody = GenerateBody(),
                          db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    """为单个任务生成产出物"""
    await _guard_perm(db)
    t = await _task_or_404(db, task_id)
    p = await _project_or_404(db, t.project_id)
    try:
        res = await svc.generate_task_output(
            db, p, t, principal=getattr(principal, "username", "") or "",
            extra=payload.extra or "", force=payload.force)
    except svc.DevError as e:
        return _fail(e)
    return res


# ============ 产出物 ============

@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: int, db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    a = await svc.get_artifact(db, artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="产出物不存在")
    cites = (await db.execute(
        select(DevCitation).where(DevCitation.artifact_id == a.id))).scalars().all()
    return {"artifact": svc.serialize_artifact(a, with_content=True),
            "citations": [svc.serialize_citation(c) for c in cites]}


@router.post("/artifacts")
async def create_artifact(payload: ArtifactBody,
                          db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    """人工上传产出物（模型之外的第三条来源）"""
    await _guard_perm(db)
    await _project_or_404(db, payload.project_id)
    a = await svc.create_artifact(db, payload.project_id, payload.model_dump(),
                                  task_id=payload.task_id or None)
    return {"artifact": svc.serialize_artifact(a, with_content=True)}


@router.patch("/artifacts/{artifact_id}")
async def patch_artifact(artifact_id: int, payload: ArtifactBody,
                         db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(current_principal)):
    """更新产出物（改内容、标记已验收）"""
    await _guard_perm(db)
    a = await svc.get_artifact(db, artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="产出物不存在")
    a = await svc.update_artifact(db, a, payload.model_dump(exclude_none=True))
    return {"artifact": svc.serialize_artifact(a, with_content=True)}


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: int, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    a = await svc.get_artifact(db, artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="产出物不存在")
    await svc.delete_artifact(db, a)
    return {"ok": True}


@router.post("/artifacts/{artifact_id}/import")
async def import_artifact(artifact_id: int, db: AsyncSession = Depends(get_db),
                           principal: Principal = Depends(current_principal)):
    """把产出物导入数据中心（文件库），让它可检索、可引用"""
    await _guard_perm(db)
    a = await svc.get_artifact(db, artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="产出物不存在")
    p = await _project_or_404(db, a.project_id)
    try:
        res = await svc.import_artifact_to_library(
            db, a, principal=getattr(principal, "username", "") or "",
            mode=p.mode or dev_config.MODE_OFFLINE)
    except svc.DevError as e:
        return _fail(e)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dev_artifact_import",
        user_id=getattr(principal, "id", None),
        resource="dev", method="POST",
        path="/api/dev/artifacts/%d/import" % artifact_id,
        detail={"artifact_id": artifact_id, "document_id": res.get("id")})
    return {"document": res, "artifact": svc.serialize_artifact(a)}


# ============ 会话与引用 ============

@router.get("/projects/{project_id}/sessions")
async def list_sessions(project_id: int, limit: int = Query(50, le=200),
                        db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    await _project_or_404(db, project_id)
    return {"sessions": await svc.list_sessions(db, project_id, limit=limit)}


@router.get("/projects/{project_id}/citations")
async def list_citations(project_id: int, session_id: int = 0,
                         db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(current_principal)):
    await _guard_perm(db)
    await _project_or_404(db, project_id)
    return {"citations": await svc.list_citations(db, project_id,
                                                  session_id=session_id or None)}


# ============ 作业进度 ============

@router.get("/jobs/{job_id}")
async def job_status(job_id: int, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """作业进度（沿用养料库那套 dna_job 表）"""
    await _guard_perm(db)
    from ..services import dna_ingest
    from ..models import DnaJob
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    return {"job": dna_ingest.job_to_dict(job)}
