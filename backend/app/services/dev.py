"""软件开发模块的核心服务

这个模块要做的事，一句话就是：把「喂养的源码知识」变成「真的能跑起来的代码」。

原来的养料库解决的是「知识存得下、查得到、答得出」，
但知识到代码之间还差三段：
    方案（想清楚要做成什么样） → 任务（拆成能一步步做的事） → 产出（真的写出来）
这三段过去靠人脑补，人一走开就断了。

所以这里的核心不是「调一次大模型」，而是一条**闭环**：
    检索喂养的知识 → 生成方案 → 拆任务 → 逐任务产出代码
    → 产出物入库（可检索、可引用）
    → 反哺知识库（把这次验证过的经验沉淀成新基因，置信度与表达度都往上走）
    → 下一轮开发直接用上

两条工作模式的边界（这一层是唯一发外网请求的业务层之一）：
    offline 离线闭环：检索只走本地知识库，模型只走本地端点，全程不出网
    online  在线协同：加上 GitHub 开源项目取材与网络知识检索

出网纪律见 dev_config.assert_outbound —— 所有外网调用都必须从那一个口子过。
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (DevArtifact, DevCitation, DevProject, DevSession, DevTask,
                      Document, DnaGene, DnaJob)
from . import ai_config, dev_config, dev_github, docindex, dna_distill, dna_library

# document 服务是「产出物入库」时才用到的，不在模块顶层导入：
# 它连带着向量化那一串依赖，谁在改那一层都会把开发模块一起拖下水，
# 而开发模块跟它八竿子打不着 —— 需要时再导入，耦合就断在这里。

log = logging.getLogger("kb.dev")


# ============ 状态与标签 ============

PROJECT_STATUS = {
    "draft": "草稿",
    "planning": "规划中",
    "building": "实现中",
    "produced": "已产出",
    "archived": "归档",
}

TASK_STATUS = {
    "todo": "待办",
    "doing": "实现中",
    "done": "已完成",
    "blocked": "被阻塞",
}

ARTIFACT_SOURCE = {
    "model": "模型生成",
    "knowledge": "知识库摘取",
    "manual": "人工上传",
}

CITATION_KIND = {
    "gene": "养料库基因",
    "doc": "文档知识",
    "github": "开源项目",
    "web": "网络知识",
}


class DevError(RuntimeError):
    """开发模块的业务错误。

    为什么要带 missing / how_to_fix：
        需求写得很明确 ——「没有配置 AI / GitHub / 网络时，接口要如实返回
        「缺什么、怎么配」，不能假成功」。
    所以这里不抛一个光秃秃的字符串，而是把「缺哪几项」和「怎么补」
    一起带上去，前端直接就能渲染成一张可执行的清单。
    """

    def __init__(self, message: str, *, missing: list | None = None,
                 how_to_fix: list | None = None, status: int = 400,
                 detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.missing = list(missing or [])
        self.how_to_fix = list(how_to_fix or [])
        self.status = status
        self.detail = dict(detail or {})

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "detail": self.message,
            "missing": self.missing,
            "how_to_fix": self.how_to_fix,
            "extra": self.detail,
        }


def _now() -> datetime:
    return datetime.now()


def _iso(obj, attr: str = "updated_at") -> str | None:
    """把时间列转成字符串；取不到就返回 None。

    为什么不能直接 obj.updated_at.isoformat()：
        带 onupdate 的列在写库之后会被标记为「过期」，
        异步会话里再读它会触发懒加载 → MissingGreenlet（greenlet_spawn has not been called）。
        这个错很隐蔽：报错点在序列化那一行，跟写库隔了好几层。

    注意取值也要放进 try 里 —— getattr 本身就可能抛，
    把整个属性访问包起来才拦得住。
    宁可少显示一个时间戳，也不要整条请求挂掉。
    """
    try:
        value = getattr(obj, attr, None)
        return value.isoformat() if value else None
    except Exception:
        return None


# ============ 序列化 ============

def serialize_project(p: DevProject) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "goal": p.goal or "",
        "tech_stack": list(p.tech_stack or []),
        "tech_notes": p.tech_notes or "",
        "status": p.status or "draft",
        "status_label": PROJECT_STATUS.get(p.status or "draft", p.status or "草稿"),
        "mode": p.mode or dev_config.MODE_OFFLINE,
        "mode_label": dev_config.MODE_LABEL.get(p.mode or "", p.mode or ""),
        "plan": p.plan or "",
        "plan_json": p.plan_json or {},
        "gene_refs": list(p.gene_refs or []),
        "library_refs": list(p.library_refs or []),
        "github_refs": list(p.github_refs or []),
        "feedback_round": p.feedback_round or 0,
        "principal": p.principal or "",
        "created_at": _iso(p, "created_at"),
        "updated_at": _iso(p, "updated_at"),
    }


def serialize_task(t: DevTask) -> dict:
    return {
        "id": t.id,
        "project_id": t.project_id,
        "title": t.title or "",
        "description": t.description or "",
        "acceptance": t.acceptance or "",
        "status": t.status or "todo",
        "status_label": TASK_STATUS.get(t.status or "todo", t.status or "待办"),
        "depends_on": list(t.depends_on or []),
        "order": t.order or 0,
        "created_at": _iso(t, "created_at"),
        "updated_at": _iso(t, "updated_at"),
    }


def serialize_artifact(a: DevArtifact, *, with_content: bool = False) -> dict:
    out = {
        "id": a.id,
        "project_id": a.project_id,
        "task_id": a.task_id,
        "filename": a.filename or "",
        "path": a.path or "",
        "language": a.language or "",
        "artifact_type": a.artifact_type or "code",
        "source": a.source or "model",
        "source_label": ARTIFACT_SOURCE.get(a.source or "model", a.source or ""),
        "size": a.size or 0,
        "warnings": list(a.warnings or []),
        "document_id": a.document_id,
        "accepted": bool(a.accepted),
        "created_at": _iso(a, "created_at"),
    }
    if with_content:
        out["content"] = a.content or ""
    return out


def serialize_session(s: DevSession, *, citations: list | None = None) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "task_id": s.task_id,
        "kind": s.kind or "plan",
        "prompt": s.prompt or "",
        "context": s.context or {},
        "reply": s.reply or "",
        "model": s.model or "",
        "mode": s.mode or "",
        "mode_label": dev_config.MODE_LABEL.get(s.mode or "", s.mode or ""),
        "status": s.status or "done",
        "notice": s.notice or "",
        "citations": citations or [],
        "created_at": _iso(s, "created_at"),
    }


def serialize_citation(c: DevCitation) -> dict:
    return {
        "id": c.id,
        "session_id": c.session_id,
        "artifact_id": c.artifact_id,
        "kind": c.kind or "gene",
        "kind_label": CITATION_KIND.get(c.kind or "gene", c.kind or ""),
        "ref": c.ref or "",
        "title": c.title or "",
        "snippet": c.snippet or "",
        "confidence": round(float(c.confidence or 0), 3),
        "created_at": _iso(c, "created_at"),
    }


# ============ 项目 ============

async def list_projects(db: AsyncSession, *, mode: str = "",
                        status: str = "", keyword: str = "") -> list[dict]:
    stmt = select(DevProject)
    if mode:
        stmt = stmt.where(DevProject.mode == mode)
    if status:
        stmt = stmt.where(DevProject.status == status)
    rows = (await db.execute(stmt.order_by(DevProject.updated_at.desc()))).scalars().all()
    out = []
    kw = (keyword or "").strip().lower()
    for p in rows:
        item = serialize_project(p)
        if kw:
            hay = " ".join([item["name"], item["goal"], item["tech_notes"],
                            " ".join(item["tech_stack"])]).lower()
            if kw not in hay:
                continue
        tasks = (await db.execute(
            select(DevTask).where(DevTask.project_id == p.id))).scalars().all()
        arts = (await db.execute(
            select(DevArtifact).where(DevArtifact.project_id == p.id))).scalars().all()
        item["task_count"] = len(tasks)
        item["task_done"] = sum(1 for t in tasks if t.status == "done")
        item["artifact_count"] = len(arts)
        out.append(item)
    return out


async def get_project(db: AsyncSession, project_id: int) -> DevProject | None:
    return (await db.execute(
        select(DevProject).where(DevProject.id == project_id))).scalar_one_or_none()


async def create_project(db: AsyncSession, payload: dict, *, principal: str = "") -> DevProject:
    name = (payload.get("name") or "").strip()
    if not name:
        raise DevError("项目名称不能为空", missing=["name"],
                       how_to_fix=["给项目起一个名字，例如「订单对账工具」"])
    mode = payload.get("mode") or dev_config.load_config().get("mode") or dev_config.MODE_OFFLINE
    if mode not in dev_config.MODES:
        mode = dev_config.MODE_OFFLINE
    stack = payload.get("tech_stack") or []
    if isinstance(stack, str):
        stack = [s.strip() for s in re.split(r"[,，\s]+", stack) if s.strip()]
    p = DevProject(
        name=name[:128],
        goal=(payload.get("goal") or "").strip(),
        tech_stack=[str(s)[:40] for s in stack][:20],
        tech_notes=(payload.get("tech_notes") or "").strip(),
        status=payload.get("status") or "draft",
        mode=mode,
        gene_refs=[int(g) for g in (payload.get("gene_refs") or [])][:100],
        library_refs=[int(d) for d in (payload.get("library_refs") or [])][:100],
        github_refs=[dev_config.normalize_repo(r) for r in (payload.get("github_refs") or [])][:10],
        plan="",
        plan_json={},
        feedback_round=0,
        principal=principal or "",
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def update_project(db: AsyncSession, project: DevProject, payload: dict) -> DevProject:
    for field in ("name", "goal", "tech_notes", "status", "plan"):
        if field in payload and payload[field] is not None:
            setattr(project, field, payload[field])
    if "mode" in payload and payload["mode"] in dev_config.MODES:
        project.mode = payload["mode"]
    if "tech_stack" in payload and payload["tech_stack"] is not None:
        stack = payload["tech_stack"]
        if isinstance(stack, str):
            stack = [s.strip() for s in re.split(r"[,，\s]+", stack) if s.strip()]
        project.tech_stack = [str(s)[:40] for s in stack][:20]
    if "gene_refs" in payload and payload["gene_refs"] is not None:
        project.gene_refs = [int(g) for g in payload["gene_refs"]][:100]
    if "library_refs" in payload and payload["library_refs"] is not None:
        project.library_refs = [int(d) for d in payload["library_refs"]][:100]
    if "github_refs" in payload and payload["github_refs"] is not None:
        project.github_refs = [dev_config.normalize_repo(r) for r in payload["github_refs"]][:10]
    project.updated_at = _now()
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project: DevProject) -> bool:
    await db.execute(update(DevSession).where(
        DevSession.project_id == project.id).values(task_id=None))
    await db.execute(update(DevArtifact).where(
        DevArtifact.project_id == project.id).values(task_id=None))
    await db.delete(project)
    await db.commit()
    return True


# ============ 任务 ============

async def list_tasks(db: AsyncSession, project_id: int) -> list[dict]:
    rows = (await db.execute(
        select(DevTask).where(DevTask.project_id == project_id)
        .order_by(DevTask.order, DevTask.id))).scalars().all()
    counts = {}
    for a in (await db.execute(
            select(DevArtifact).where(DevArtifact.project_id == project_id))).scalars().all():
        if a.task_id:
            counts[a.task_id] = counts.get(a.task_id, 0) + 1
    out = []
    for t in rows:
        item = serialize_task(t)
        item["artifact_count"] = counts.get(t.id, 0)
        out.append(item)
    return out


async def get_task(db: AsyncSession, task_id: int) -> DevTask | None:
    return (await db.execute(
        select(DevTask).where(DevTask.id == task_id))).scalar_one_or_none()


async def create_task(db: AsyncSession, project_id: int, payload: dict) -> DevTask:
    title = (payload.get("title") or "").strip()
    if not title:
        raise DevError("任务标题不能为空", missing=["title"],
                       how_to_fix=["写清楚这一步要做什么"])
    max_order = (await db.execute(
        select(DevTask).where(DevTask.project_id == project_id)
        .order_by(DevTask.order.desc()).limit(1))).scalars().first()
    t = DevTask(
        project_id=project_id,
        title=title[:200],
        description=(payload.get("description") or "").strip(),
        acceptance=(payload.get("acceptance") or "").strip(),
        status=payload.get("status") or "todo",
        depends_on=[int(x) for x in (payload.get("depends_on") or [])][:20],
        order=int(payload.get("order") or ((max_order.order + 1) if max_order else 0)),
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def update_task(db: AsyncSession, task: DevTask, payload: dict) -> DevTask:
    for field in ("title", "description", "acceptance", "status"):
        if field in payload and payload[field] is not None:
            setattr(task, field, payload[field])
    if "depends_on" in payload and payload["depends_on"] is not None:
        task.depends_on = [int(x) for x in payload["depends_on"]][:20]
    if "order" in payload and payload["order"] is not None:
        task.order = int(payload["order"])
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)
    return task


async def delete_task(db: AsyncSession, task: DevTask) -> bool:
    await db.execute(update(DevArtifact).where(
        DevArtifact.task_id == task.id).values(task_id=None))
    await db.execute(update(DevSession).where(
        DevSession.task_id == task.id).values(task_id=None))
    await db.delete(task)
    await db.commit()
    return True


# ============ 产出物 / 会话 / 引用 ============

async def list_artifacts(db: AsyncSession, project_id: int,
                         task_id: int | None = None) -> list[dict]:
    stmt = select(DevArtifact).where(DevArtifact.project_id == project_id)
    if task_id:
        stmt = stmt.where(DevArtifact.task_id == task_id)
    rows = (await db.execute(stmt.order_by(DevArtifact.id))).scalars().all()
    return [serialize_artifact(a) for a in rows]


async def get_artifact(db: AsyncSession, artifact_id: int) -> DevArtifact | None:
    return (await db.execute(
        select(DevArtifact).where(DevArtifact.id == artifact_id))).scalar_one_or_none()


async def create_artifact(db: AsyncSession, project_id: int, payload: dict,
                          *, task_id: int | None = None) -> DevArtifact:
    content = payload.get("content") or ""
    filename = (payload.get("filename") or "artifact.txt").strip()[:200]
    a = DevArtifact(
        project_id=project_id,
        task_id=task_id if task_id is not None else payload.get("task_id"),
        filename=filename,
        path=(payload.get("path") or filename)[:200],
        content=content,
        language=(payload.get("language") or "")[:32],
        artifact_type=payload.get("artifact_type") or "code",
        source=payload.get("source") or "manual",
        size=len(content.encode("utf-8", "replace")),
        warnings=list(payload.get("warnings") or []),
        document_id=None,
        accepted=bool(payload.get("accepted", False)),
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def update_artifact(db: AsyncSession, artifact: DevArtifact, payload: dict) -> DevArtifact:
    for field in ("filename", "path", "content", "language", "artifact_type",
                  "source", "accepted"):
        if field in payload and payload[field] is not None:
            setattr(artifact, field, payload[field])
    if "content" in payload and payload["content"] is not None:
        artifact.size = len((payload["content"] or "").encode("utf-8", "replace"))
    artifact.updated_at = _now()
    await db.commit()
    await db.refresh(artifact)
    return artifact


async def delete_artifact(db: AsyncSession, artifact: DevArtifact) -> bool:
    await db.execute(update(DevCitation).where(
        DevCitation.artifact_id == artifact.id).values(artifact_id=None))
    await db.delete(artifact)
    await db.commit()
    return True


async def list_sessions(db: AsyncSession, project_id: int,
                        limit: int = 50) -> list[dict]:
    rows = (await db.execute(
        select(DevSession).where(DevSession.project_id == project_id)
        .order_by(DevSession.id.desc()).limit(limit))).scalars().all()
    if not rows:
        return []
    ids = [s.id for s in rows]
    cites = (await db.execute(
        select(DevCitation).where(DevCitation.session_id.in_(ids)))).scalars().all()
    by_session: dict[int, list] = {}
    for c in cites:
        by_session.setdefault(c.session_id, []).append(serialize_citation(c))
    return [serialize_session(s, citations=by_session.get(s.id, [])) for s in rows]


async def list_citations(db: AsyncSession, project_id: int,
                         session_id: int | None = None) -> list[dict]:
    stmt = (select(DevCitation)
            .join(DevSession, DevCitation.session_id == DevSession.id)
            .where(DevSession.project_id == project_id))
    if session_id:
        stmt = stmt.where(DevCitation.session_id == session_id)
    rows = (await db.execute(stmt.order_by(DevCitation.id))).scalars().all()
    return [serialize_citation(c) for c in rows]


async def _save_citations(db: AsyncSession, session_id: int,
                          cites: list[dict], artifact_id: int | None = None) -> list[int]:
    ids = []
    for c in cites:
        row = DevCitation(
            session_id=session_id,
            artifact_id=artifact_id,
            kind=c.get("kind") or "gene",
            ref=str(c.get("ref") or "")[:128],
            title=str(c.get("title") or "")[:256],
            snippet=str(c.get("snippet") or "")[:2000],
            confidence=float(c.get("confidence") or 0.5),
            created_at=_now(),
        )
        db.add(row)
        await db.flush()
        ids.append(row.id)
    return ids


# ============ 知识检索（离线与在线的共同底座） ============

async def retrieve_knowledge(db: AsyncSession, query: str, *,
                             limit: int = 8) -> list[dict]:
    """检索可引用的本地知识：养料库基因 + 文档块。

    为什么两种模式都先走这一步：
        喂养的源码知识是「软件开发」这件事的地基 ——
        在线协同模式多出来的是 GitHub 与网络知识，不是替代品。
        没有本地知识垫底，模型写出来的东西就是通用教程，
        而不是「像这个系统该怎么写」。

    这里只查本地索引（FTS），不发任何外网请求 —— 离线模式下这是唯一的来源。
    """
    q = (query or "").strip()
    cites: list[dict] = []
    if not q:
        return cites

    genes = []
    try:
        genes = await dna_library.search_genes(db, q, limit=limit)
    except Exception as e:
        log.warning("基因检索失败：%s", type(e).__name__)
    for item in genes:
        gene = item["gene"]
        cites.append({
            "kind": "gene",
            "ref": "gene:%d" % gene.id,
            "gene_id": gene.id,
            "title": gene.title or (gene.summary or "")[:60],
            "snippet": (gene.content or "")[:800],
            "confidence": float(gene.confidence or 0.5),
            "score": float(item.get("score") or 0),
            "source_kind": gene.source_kind or "",
            "source_title": gene.source_title or "",
        })

    chunks = []
    try:
        chunks = await docindex.chunk_fts_search(db, q, limit=limit)
    except Exception as e:
        log.warning("文档块检索失败：%s", type(e).__name__)
    for c in chunks:
        text = c.get("text") or ""
        cites.append({
            "kind": "doc",
            "ref": "doc:%s" % (c.get("document_id") or ""),
            "document_id": c.get("document_id"),
            "title": c.get("heading") or ("文档 %s" % (c.get("document_id") or "")),
            "snippet": text[:800],
            "confidence": 0.55,
            "score": 0.0,
        })

    # 表达度：被开发流程真正引用到的基因，表达度 +1
    gene_ids = [c["gene_id"] for c in cites if c.get("gene_id")]
    if gene_ids:
        try:
            await dna_library.mark_gene_used(db, gene_ids)
        except Exception as e:
            log.warning("基因表达度更新失败：%s", type(e).__name__)
    return cites


async def _online_context(cfg: dict, mode: str, project: DevProject,
                           query: str) -> tuple[list[dict], list[str]]:
    """在线协同模式的外网取材：GitHub 仓库 + 网络知识。

    返回 (引用列表, 降级提示列表)。
    降级提示是必须给用户的：「没搜到」和「没搜」是两回事，
    混起来就是在骗人 —— 用户会以为模型参考过网络资料。
    """
    if mode != dev_config.MODE_ONLINE:
        return [], []
    cites: list[dict] = []
    notices: list[str] = []

    if not dev_config.outbound_enabled(cfg):
        notices.append("全局出网开关处于关闭状态，本次未访问任何外部服务")
        return cites, notices

    repos = list(project.github_refs or []) or list((cfg.get("github") or {}).get("repos") or [])
    for spec in repos[:3]:
        if not dev_config.is_repo_spec_ok(spec):
            notices.append("仓库标识不完整（需要 owner/repo），已跳过")
            continue
        label = dev_config.repo_label(spec)
        try:
            ctx = await dev_github.collect_repo_context(cfg, mode, spec, query)
        except dev_config.OutboundBlocked as e:
            notices.append(str(e))
            continue
        except Exception as e:
            notices.append("GitHub 取材失败（%s）：%s" % (label, type(e).__name__))
            continue
        for item in ctx.get("failed") or []:
            notices.append("GitHub %s：%s 未取到（%s）"
                           % (label, item.get("what"), item.get("reason")))
        data = ctx.get("data") or {}
        ov = data.get("overview") or {}
        if ov:
            cites.append({
                "kind": "github",
                "ref": "repo:%s" % label,
                "title": "%s —— %s" % (label, ov.get("description") or "开源项目"),
                "snippet": ("语言 %s · 星标 %s · 默认分支 %s · 许可证 %s"
                            % (ov.get("language") or "-", ov.get("stars") or 0,
                               ov.get("default_branch") or "-",
                               ov.get("license") or "-")),
                "confidence": 0.7,
            })
        readme = data.get("readme") or ""
        if readme:
            cites.append({
                "kind": "github",
                "ref": "repo:%s#readme" % label,
                "title": "%s 的 README" % label,
                "snippet": readme[:1200],
                "confidence": 0.7,
            })
        for it in (data.get("issues") or [])[:5]:
            cites.append({
                "kind": "github",
                "ref": "repo:%s#issue%s" % (label, it.get("number")),
                "title": "%s#%s %s" % (label, it.get("number"), it.get("title")),
                "snippet": (it.get("body") or "")[:600],
                "confidence": 0.6,
            })
        for f in (data.get("files") or [])[:20]:
            cites.append({
                "kind": "github",
                "ref": "repo:%s#%s" % (label, f.get("path")),
                "title": "%s 的目录项 %s" % (label, f.get("path")),
                "snippet": "%s · %s 字节" % (f.get("type") or "", f.get("size") or 0),
                "confidence": 0.5,
            })

    ws = cfg.get("web_search") or {}
    if not ws.get("enabled") or not (ws.get("endpoint") or "").strip():
        notices.append("未配置网络搜索服务，本次未使用网络知识（不是「没搜到」，是「没搜」）")
    else:
        try:
            results = await dev_github.web_search(cfg, mode, query, 5)
            for it in results:
                cites.append({
                    "kind": "web",
                    "ref": it.get("url") or "web",
                    "title": it.get("title") or "网络资料",
                    "snippet": (it.get("snippet") or "")[:600],
                    "confidence": 0.45,
                })
            if not results:
                notices.append("网络搜索没有返回结果")
        except dev_config.OutboundBlocked as e:
            notices.append(str(e))
        except dev_github.SearchUnavailable as e:
            notices.append(str(e))
        except Exception as e:
            notices.append("网络搜索失败：%s" % type(e).__name__)
    return cites, notices


def _context_block(cites: list[dict]) -> str:
    """把引用拼成给模型看的「参考资料」段落"""
    if not cites:
        return "（本次没有检索到可引用的知识，请明确说明依据不足）"
    lines = []
    for i, c in enumerate(cites[:16], start=1):
        lines.append("[%d] %s（%s｜置信度 %.2f）\n%s"
                     % (i, c.get("title") or "", c.get("kind") or "",
                        float(c.get("confidence") or 0),
                        (c.get("snippet") or "")[:600]))
    return "\n".join(lines)


# ============ 模型调用 ============

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def is_local_endpoint(url: str) -> bool:
    """判断一个 endpoint 是不是本机/内网地址。

    离线模式必须过这一关：
        「本地模型端点」这个字段名是人写的，人会把云端地址填进去。
    名字叫本地、地址是云端 —— 这时候说「离线运行」就是在骗人。
    """
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass
    # 局域网域名（如 my-nas.local）一律当外网处理：
    # 判定不了的东西宁可严一点，也不能在「离线」名下偷偷发出去
    return False


def local_model_ready(cfg: dict) -> bool:
    lm = cfg.get("local_model") or {}
    return bool((lm.get("base_url") or "").strip() and (lm.get("model") or "").strip())


def system_model_ready() -> bool:
    """系统级大模型（AI 设置里配的那个）是否可用"""
    try:
        ai = ai_config.get_full_config()
    except Exception:
        return False
    return bool(ai.get("enabled") and (ai.get("base_url") or "").strip()
                and (ai.get("model") or "").strip())


def describe_model(mode: str, cfg: dict | None = None) -> dict:
    """当前模式下「会用什么模型」—— 说不清就不叫「可用」"""
    cfg = cfg or dev_config.load_config()
    lm = cfg.get("local_model") or {}
    if mode == dev_config.MODE_OFFLINE:
        if local_model_ready(cfg):
            return {"ready": True, "kind": "local",
                    "model": lm.get("model"),
                    "endpoint": lm.get("base_url"),
                    "note": "离线模式：只用本地模型端点，不出网"}
        return {"ready": False, "kind": "local", "model": "",
                "endpoint": "",
                "note": "离线模式需要一个本地模型端点（OpenAI 兼容，如 Ollama / llama.cpp server）"}
    if system_model_ready():
        ai = ai_config.get_full_config()
        return {"ready": True, "kind": "system", "model": ai.get("model"),
                "endpoint": ai.get("base_url"),
                "note": "在线协同模式：优先用 AI 设置里配置的大模型"}
    if local_model_ready(cfg):
        return {"ready": True, "kind": "local", "model": lm.get("model"),
                "endpoint": lm.get("base_url"),
                "note": "在线协同模式：系统大模型未配置，改用本地模型端点"}
    return {"ready": False, "kind": "", "model": "", "endpoint": "",
            "note": "没有可用的大模型端点"}


def ensure_model_available(mode: str, cfg: dict | None = None) -> dict:
    """生成前先确认模型可用；不可用就如实说缺什么、怎么配"""
    cfg = cfg or dev_config.load_config()
    info = describe_model(mode, cfg)
    if info.get("ready"):
        return info
    missing = []
    how = []
    if mode == dev_config.MODE_OFFLINE:
        missing.append("local_model.base_url")
        missing.append("local_model.model")
        how.append("开发设置 → 本地模型端点：填 OpenAI 兼容的本地地址"
                   "（如 http://127.0.0.1:11434/v1/chat/completions）并填写模型名")
    else:
        missing.append("ai.base_url")
        missing.append("ai.model")
        how.append("AI 设置 → 填好大模型的 endpoint、模型名与密钥；"
                   "或开发设置 → 本地模型端点")
    how.append("也可以在开发设置里切换到离线模式，用本地模型端点")
    raise DevError("当前没有可用的模型端点，生成已停止", missing=missing,
                   how_to_fix=how, detail={"model": info})


async def _chat_openai_meta(base_url: str, api_key: str, model: str,
                               messages: list[dict], *, temperature: float = 0.3,
                               max_tokens: int = 8192, timeout: float = 600.0) -> dict:
    """一次 OpenAI 兼容调用，连同「是不是被截断了」一起返回。

    为什么多返回 finish_reason：
        模型输出撞到 max_tokens 上限时，OpenAI 兼容接口不会报错，
        它会把回答**戛然而止**地截断掉，返回 finish_reason="length"。
        对调用方来说这是「内容不完整」，跟「网络失败」完全不是一回事 ——
        前者可以抢救（补括号、让模型重写短的），后者只能重试。
        不看 finish_reason，两种情况都会退化成同一句「生成失败」，
        用户完全不知道自己该换模型还是该重试。
    """
    payload = {
        "model": model or "gpt-3.5-turbo",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = "Bearer %s" % api_key.strip()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.post(base_url, json=payload, headers=headers)
        if r.status_code >= 400:
            body = (r.text or "")[:200]
            # 不同的错要给出不同的出路：
            #   429 = 额度/频率限制（等一会儿或换个模型），
            #   401/403 = 密钥不对（去改密钥），
            #   5xx = 服务端抖动（重试）。
            # 一律说「检查模型地址、模型名与密钥」等于什么都没说 ——
            # 密钥明明是对的，是额度用完了。
            if r.status_code == 429:
                raise DevError(
                    "模型接口返回 429：%s" % body,
                    missing=["model_quota"],
                    how_to_fix=[
                        "模型额度用完了（429）：等额度恢复后再重跑，"
                        "或到 AI 设置里换一个额度充足的模型",
                        "如果同时跑多个开发任务，先停掉几个再重试",
                    ])
            if r.status_code in (401, 403):
                raise DevError("模型接口返回 %s：%s" % (r.status_code, body),
                               missing=["model_api_key"],
                               how_to_fix=["到 AI 设置里检查密钥是否正确、是否过期"])
            if r.status_code >= 500:
                raise DevError("模型接口返回 %s：%s" % (r.status_code, body),
                               missing=["model_endpoint"],
                               how_to_fix=["模型服务端出错了，稍后重试；"
                                           "反复失败就换一个模型端点"])
            raise DevError("模型接口返回 %s（%s）" % (r.status_code, body),
                           missing=["model_endpoint"],
                           how_to_fix=["检查模型地址、模型名与密钥是否正确"])
        data = r.json()
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except Exception as e:
        raise DevError("模型返回的结构不符合 OpenAI 兼容协议") from e
    content = msg.get("content") or ""
    # 推理模型会把思考链混在正文里，正文里不该出现它
    try:
        from .ai import scrub_reasoning
        content = scrub_reasoning(content)
    except Exception:
        pass
    return {
        "text": content,
        "finish_reason": choice.get("finish_reason") or "",
        "usage": data.get("usage") or {},
    }


async def _chat_openai(base_url: str, api_key: str, model: str,
                        messages: list[dict], *, temperature: float = 0.3,
                        max_tokens: int = 8192, timeout: float = 600.0) -> str:
    """一次 OpenAI 兼容调用，只要正文。

    为什么不复用 ai.chat_real：
        那个函数在调用失败时会静默降级到本地规则引擎（chat_mock），
    返回一段「看起来像答案」的规则拼装结果。
    开发流程里这等于假成功 —— 用户以为生成了方案，实际拿到的是模板。
    这里要的是：失败就明说失败。
    """
    out = await _chat_openai_meta(base_url, api_key, model, messages,
                                  temperature=temperature, max_tokens=max_tokens,
                                  timeout=timeout)
    return out["text"]


async def call_model(mode: str, messages: list[dict], *, cfg: dict | None = None,
                     temperature: float | None = None,
                     max_tokens: int | None = None) -> dict:
    """调模型，返回 {"text": ..., "model": ...}

    离线模式只用本地端点 —— 这是「离线闭环」的底线：
    系统里配着云端大模型也不许用（那等于偷偷出网）。
    """
    cfg = cfg or dev_config.load_config()
    info = ensure_model_available(mode, cfg)
    lm = cfg.get("local_model") or {}
    if temperature is not None:
        temp = temperature
    elif info["kind"] == "local":
        temp = float(lm.get("temperature") or 0.3)
    else:
        temp = float(ai_config.get_full_config().get("temperature") or 0.3)
    mx = max_tokens or _dev_max_tokens(cfg, info["kind"])
    ceiling = _max_tokens_ceiling(cfg, info["kind"])
    # 读超时：开发流程一次要出的东西比问答大得多，
    # 120 秒连「一份需求规格」都写不完 —— 实测 specify 阶段跑了几分钟，
    # 读超时先到了，作业被判失败。宁可多等，不要随机失败。
    timeout = float((cfg.get("model") or {}).get("timeout") or 600.0)

    async def _once(budget: int) -> dict:
        if info["kind"] == "local":
            base = (lm.get("base_url") or "").strip()
            if mode == dev_config.MODE_OFFLINE and not is_local_endpoint(base):
                raise DevError("离线模式的模型端点必须是本机或内网地址（当前填的是外部地址）",
                               missing=["local_model.base_url"],
                               how_to_fix=["把端点改成 http://127.0.0.1:11434/v1/chat/completions "
                                          "这类本机地址；确实要用云端模型请切到在线协同模式"])
            o = await _chat_openai_meta(base, lm.get("api_key") or "", lm.get("model") or "",
                                        messages, temperature=temp, max_tokens=budget,
                                        timeout=timeout)
            return {"text": o["text"], "model": lm.get("model") or "local",
                    "finish_reason": o.get("finish_reason") or "",
                    "usage": o.get("usage") or {}}

        ai = ai_config.get_full_config()
        base = (ai.get("base_url") or "").strip()
        # 云端端点属于出网：总开关关着时必须拦下
        if not is_local_endpoint(base):
            dev_config.assert_outbound(mode, "大模型调用", cfg=cfg)
        o = await _chat_openai_meta(base, ai.get("api_key") or "", ai.get("model") or "",
                                    messages, temperature=temp, max_tokens=budget,
                                    timeout=timeout)
        return {"text": o["text"], "model": ai.get("model") or "system",
                "finish_reason": o.get("finish_reason") or "",
                "usage": o.get("usage") or {}}

    # ---- 「没写完」就加预算重来 ----
    #
    # 推理模型有个坑：它会把 max_tokens 预算**全花在思考块上**，
    # 正文一个字都吐不出来。实测 MiniMax-M3.1-Flash：
    #   max_tokens=2048 → completion_tokens=2048，
    #   reasoning_tokens=2049，content 长度 **0**，
    #   finish_reason=length。
    # 这时候不是「内容写了一半」，是「根本没开始写」——
    # 加大预算才有意义，否则重试一万次也是空的。
    # AI 模块（services/ai.py）早就有这套逻辑，
    # 这里跟着它走一份，免得两个模块对同一件事有两套脾气。
    attempt = 0
    out = await _once(mx)
    while attempt < _MAX_LENGTH_RETRIES:
        empty = not (out.get("text") or "").strip()
        truncated = out.get("finish_reason") == "length"
        if not (empty or truncated):
            break
        if mx >= ceiling:
            break
        mx = min(mx * 2, ceiling)
        attempt += 1
        out = await _once(mx)
    out["retries"] = attempt
    out["max_tokens"] = mx
    return out


# 「没写完就加预算重来」最多重试几次
# 2048 → 4k → 8k → 16k → 32k：四次才够从最小的预算摸到天花板
_MAX_LENGTH_RETRIES = 4


def _max_tokens_ceiling(cfg: dict, kind: str = "") -> int:
    """输出预算的天花板 —— 加大也不能超过它。

    云端大模型的上限是用户在 AI 设置里自己定的（默认 32768），
    那是用户对「这次调用最多花多少钱」的表态，不能替他超。
    """
    if kind == "system":
        try:
            c = int(ai_config.get_full_config().get("max_tokens_ceiling") or 0)
        except Exception:
            c = 0
        if c:
            return c
    m = cfg.get("model") or {}
    return int(m.get("max_tokens_ceiling") or 32768)


def _dev_max_tokens(cfg: dict, kind: str = "") -> int:
    """开发流程该给模型多少输出预算。

    为什么不用 AI 设置里的 max_tokens：
        问答一次要的是一段话，4096 够用；
        开发流程一次要吐的是**一整份规格 + 一整套项目文件**，
        2048 会在半路被截断 —— 而截断的 JSON 解析不出来，
        用户只看到一句「生成失败」。
        实测就是这个：方案 JSON 在 2048 字符处戛然而止，
        finish_reason=length，于是「模型没有返回可解析的方案 JSON」。
    """
    m = cfg.get("model") or {}
    want = int(m.get("max_tokens") or 0)
    if not want:
        lm = cfg.get("local_model") or {}
        want = int(lm.get("max_tokens") or 0)
    if not want:
        want = 8192
    if kind == "system":
        # 系统大模型的上限是用户自己设的，不能越过去
        try:
            ceiling = int(ai_config.get_full_config().get("max_tokens_ceiling") or 0)
        except Exception:
            ceiling = 0
        if ceiling:
            want = min(want, ceiling)
    return max(1024, want)


async def call_model_json(mode: str, messages: list[dict], *, cfg: dict | None = None,
                          temperature: float | None = None,
                          max_tokens: int | None = None,
                          validator=None, retries: int = 1) -> dict:
    """调模型要一段 JSON，带**截断抢救**与**一次自动重试**。

    为什么要有这层：
        模型返回的 JSON 有两种「不完整」：
          1) 被 max_tokens 截断 —— 内容是对的，只是没写完；
          2) 字段结构不对 —— 内容在，但形状不对（比如 summary 给了对象）。
        第 1 种可以**抢救**（把断掉的括号补上、砍掉没写完的最后一个元素）；
        第 2 种抢救不了，只能**把问题告诉模型让它重写**。
        没有这层，两种情况的用户体感都是同一句「生成失败」。

    返回：{"text", "data", "model", "finish_reason", "attempts", "repaired"}
      data 是解析出来的 dict（失败为 None）
      repaired=True 表示原始输出是残的、这份 data 是抢救出来的
    """
    cfg = cfg or dev_config.load_config()
    last_text = ""
    last_reason = ""
    for attempt in range(max(1, retries + 1)):
        out = await call_model(mode, messages, cfg=cfg,
                               temperature=temperature, max_tokens=max_tokens)
        text = out.get("text") or ""
        last_text = text
        last_reason = out.get("finish_reason") or ""
        data = parse_json_block(text)
        repaired = False
        if data is None:
            data = parse_json_block(text, salvage=True)
            repaired = data is not None
        if data is not None and validator is not None:
            try:
                validator(data)
            except Exception as e:
                # 结构不对：告诉模型哪儿不对，让它重写
                if attempt >= max(1, retries + 1) - 1:
                    raise DevError(
                        "模型返回的结构不符合要求：%s" % (str(e)[:200]),
                        missing=["model_output"],
                        how_to_fix=["换个更听话的模型", "或在开发设置里调高输出预算"])
                messages = list(messages) + [
                    {"role": "assistant", "content": text[:4000]},
                    {"role": "user", "content":
                     "上一次输出不符合要求：%s\n请只输出一个 JSON 对象，"
                     "修正后重新输出，不要加任何解释文字。" % (str(e)[:300])},
                ]
                continue
        if data is not None:
            return {"text": text, "data": data, "model": out.get("model") or "",
                    "finish_reason": last_reason, "attempts": attempt + 1,
                    "repaired": repaired}
        # 解析不出来：告诉模型「刚才那次没写完/写坏了」
        if attempt >= max(1, retries + 1) - 1:
            break
        hint = ("上一次输出在写完之前就被截断了（输出预算 %s token）。"
                % (max_tokens or _dev_max_tokens(cfg)))
        if last_reason != "length":
            hint = "上一次输出的 JSON 解析不出来。"
        messages = list(messages) + [
            {"role": "assistant", "content": text[:4000]},
            {"role": "user", "content":
             hint + "请**重新输出一次**完整的 JSON，"
             "内容要精简（长数组只保留最关键的 3~5 项），"
             "每个字符串不要超过 200 字，只输出 JSON、不要任何解释。"},
        ]
    raise DevError("模型没有返回可解析的 JSON（重试 %d 次仍失败）" % (max(1, retries + 1)),
                   missing=["model_output"],
                   how_to_fix=["换个更听话的模型再试一次",
                               "在开发设置里调大「输出预算（max_tokens）」",
                               "或者把项目目标写得更具体些"],
                   detail={"finish_reason": last_reason, "text_head": last_text[:500]})


# ============ JSON 解析 ============

# 代码围栏用字符拼出来：源码里直接写三个反引号会让某些模板引擎提前收尾
_FENCE = chr(96) * 3
_FENCE_RE = re.compile(re.escape(_FENCE) + r"(?:json)?\s*(.*?)" + re.escape(_FENCE), re.S)


def _salvage_json(raw: str) -> dict | None:
    """抢救被截断的 JSON。

    模型输出撞到 token 上限时，JSON 会在半路断掉：
    数组的最后一个元素写了一半、对象的最后一个键没有值。
    这时候内容其实是对的，只是**没写完** —— 把它砍到最后一个完整的地方，
    再把没关上的括号补上，就能拿回大部分内容。

    为什么值得抢救：
        整份丢掉，用户看到的是「生成失败」，重试一次又是几分钟；
        抢救出来，用户看到的是「规格写了一半」，他知道该往哪补。
        前者像是系统坏了，后者像是活儿没干完 —— 后者才是真的。

    只在内容**不完整**时用；完整但结构不对的 JSON 不归它管。
    """
    start = raw.find("{")
    if start < 0:
        return None
    body = raw[start:]
    stack: list[str] = []
    in_str = False
    esc = False
    candidates: list[tuple[int, list[str]]] = []
    for i, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            continue
        if ch == "," and stack:
            # 逗号后面被截断了 → 这个逗号是多余的，切点在这里
            candidates.append((i, list(stack)))
    # 收尾时还停在字符串里：把这个字符串闭合掉
    body_fixed = body + '"' if in_str else body
    if not candidates:
        # 一个逗号都没有：整段就这么点内容，直接补齐括号试试
        closer = "".join(reversed(stack))
        for candidate in (body_fixed + closer, body_fixed + closer + "}",
                          body_fixed + closer + "]"):
            try:
                data = json.loads(candidate)
            except Exception:
                continue
            if isinstance(data, dict) and data:
                return data
        return None
    # 从最深的切点往回试：第一个能解析成功的就是内容最全的
    for cut, cut_stack in reversed(candidates):
        trimmed = body_fixed[:cut]
        closer = "".join(reversed(cut_stack))
        for candidate in (trimmed + closer, trimmed + closer + "}",
                          trimmed + closer + "]"):
            try:
                data = json.loads(candidate)
            except Exception:
                continue
            if isinstance(data, dict) and data:
                return data
    return None


def parse_json_block(text: str, salvage: bool = False) -> dict | None:
    """从模型回复里抠出 JSON 对象。

    模型爱把 JSON 包在代码块里，前后还带一句话。
    直接 json.loads 会失败 —— 那时候不该报「生成失败」，
    该做的是把 JSON 抠出来。

    salvage=True 时额外尝试抢救**被截断**的 JSON（见 _salvage_json）。
    """
    if not text:
        return None
    candidates = []
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text)
    for raw in candidates:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # 退而求其次：找最外层的 {...}
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            chunk = raw[start:end + 1]
            try:
                data = json.loads(chunk)
                if isinstance(data, dict):
                    return data
            except Exception:
                # 模型爱在最后一个元素后面多打一个逗号
                fixed = re.sub(r",\s*([}\]])", r"\1", chunk)
                try:
                    data = json.loads(fixed)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    continue
    if salvage:
        # 用原始正文抢救：上面循环里的 raw 是最后一个候选，
        # 拿它抢救等于只抢救「没有围栏的那份」，围栏版反而救不回来
        salvaged = _salvage_json(text)
        if salvaged is not None:
            return salvaged
    return None


# ============ 提示词 ============

PLAN_SYSTEM = """你是一位资深软件架构师，正在为一个知识库工作台里的「软件开发」模块生成项目方案。

要求：
1. 只输出一个 JSON 对象，不要在 JSON 前后加解释性文字。
2. JSON 结构固定为：
{
  "summary": "一段话说清楚这个项目要解决什么问题",
  "architecture": "整体设计：分层、模块划分、数据流、关键取舍",
  "tech_stack": ["技术1", "技术2"],
  "risks": ["风险与对策"],
  "tasks": [
    {"title": "任务标题", "description": "这一步具体做什么",
     "acceptance": "可判定的验收标准（能拿它对照检查）", "depends_on": []}
  ]
}
3. summary 与 architecture 必须是**字符串**，不要写成对象或数组；
   tech_stack / risks 必须是**字符串数组**；tasks 必须是**对象数组**。
   结构错了调用方会直接判定生成失败。
4. **不要改动用户指定的技术栈**。用户给了技术栈就按它设计；
   只有当用户明确写「技术栈未指定」时才自己选，并在 tech_notes 里说明理由。
5. 任务粒度控制在半天到一天能做完，每条都要有可判定的验收标准；
   任务总数控制在 5~12 条 —— 太多会写不完，被截断的 JSON 一条都不算数。
6. 严格基于给定的参考资料。资料不足的地方要在 summary 里写明「依据不足」，
   不要用通用套路补齐 —— 那会让人以为这些经验来自这个系统。
7. 任务之间的 depends_on 填前序任务在 tasks 数组中的下标（从 0 开始）。
8. 每个字符串控制在 200 字以内。宁可少写几句，也不要让 JSON 写不完 ——
   写到一半被截断，整份方案都作废。
"""

TASK_SYSTEM = """你是一位资深工程师，正在为一个项目里的某个任务写代码。

要求：
1. 只输出一个 JSON 对象：
{
  "files": [
    {"path": "src/xxx.py", "language": "python", "content": "完整文件内容"}
  ],
  "notes": "实现说明：关键取舍、与既有代码的衔接点、需要注意的地方"
}
2. content 必须是**完整的文件内容**，不要用「……此处省略」代替代码。
3. 严格基于给定的参考资料与该任务的验收标准。
4. 严禁在代码里硬编码密钥、口令、令牌；需要凭据的地方用环境变量或配置占位。
5. 严禁执行破坏性命令（rm -rf /、mkfs、dd 写裸设备等）。
6. 路径用相对路径，不要出现绝对路径。
"""

CHAT_SYSTEM = """你是这个项目的开发助手，回答要贴着这个项目与它的知识库。

要求：
1. 只输出一个 JSON 对象：
{"answer": "回答正文", "used_refs": [1, 2]}
2. used_refs 填你真正用到的参考资料编号（没有就填空数组）。
3. 回答里要写清楚「依据哪几条经验」，不要泛泛而谈。
4. 资料不足时直接说「知识库里没有这方面的经验」，不要编。
"""


def _flatten_to_text(value) -> str:
    """把模型随手给的任意结构压成一段能读的正文。

    为什么需要它：
        模型经常不照 schema 来 —— 明明要一个字符串的 summary，
        它给了一个对象（{"project": "...", "goal": "..."}）。
        这时候**内容是好的，只是形状不对**。
        把形状掰直，比让用户重跑一次划算得多。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten_to_text(v) for v in value]
        return "；".join([p for p in parts if p])
    if isinstance(value, dict):
        # 常见的两种形状：{"goal": "...", "scope": {...}} / {"description": "..."}
        for key in ("summary", "text", "description", "content", "goal",
                    "overview", "detail", "details"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        parts = []
        for k, v in value.items():
            t = _flatten_to_text(v)
            if t:
                parts.append("%s：%s" % (k, t) if isinstance(v, str) else "%s：%s" % (k, t))
        return "；".join(parts)
    return str(value)


def _normalize_plan_payload(data: dict) -> dict:
    """把模型的方案 JSON 掰成我们约定的形状。

    约定：
      summary     字符串
      architecture 字符串
      tech_stack  字符串数组
      risks       字符串数组
      tasks       对象数组（每项有 title/description/acceptance/depends_on）

    为什么「掰」而不是「拒」：
        模型给的内容往往是对的，只是把字符串写成了对象、
        把任务列表写成了对象。直接拒掉等于让用户重跑一次，
        而重跑一次要再等一分多钟。掰直之后内容还在，只是要读得懂。
    """
    out = dict(data or {})
    out["summary"] = _flatten_to_text(out.get("summary"))
    out["architecture"] = _flatten_to_text(out.get("architecture"))
    for key in ("tech_stack", "risks"):
        v = out.get(key)
        if isinstance(v, str):
            out[key] = [v] if v.strip() else []
        elif isinstance(v, list):
            out[key] = [_flatten_to_text(x)[:200] for x in v if _flatten_to_text(x)][:20]
        elif isinstance(v, dict):
            out[key] = [_flatten_to_text(x)[:200] for x in v.values()
                        if _flatten_to_text(x)][:20]
        else:
            out[key] = []
    tasks = out.get("tasks")
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not isinstance(tasks, list):
        tasks = []
    norm_tasks = []
    for t in tasks:
        if not isinstance(t, dict):
            text = _flatten_to_text(t)
            if text:
                norm_tasks.append({"title": text[:200], "description": "",
                                   "acceptance": "", "depends_on": []})
            continue
        deps = t.get("depends_on")
        if isinstance(deps, (int, float)):
            deps = [int(deps)]
        if not isinstance(deps, list):
            deps = []
        norm_tasks.append({
            "title": _flatten_to_text(t.get("title") or t.get("name"))[:200],
            "description": _flatten_to_text(
                t.get("description") or t.get("detail") or t.get("content"))[:2000],
            "acceptance": _flatten_to_text(
                t.get("acceptance") or t.get("criteria") or t.get("done_when"))[:2000],
            "depends_on": [int(d) for d in deps
                           if isinstance(d, (int, float)) and not isinstance(d, bool)],
        })
    out["tasks"] = [t for t in norm_tasks if t["title"]]
    return out


def _validate_plan_payload(data: dict) -> None:
    """校验方案 JSON —— 只在「实在没法用」时才报错。

    为什么不在这里掰形状：
        掰形状交给 _normalize_plan_payload（它不会失败）；
        这个函数只负责回答「有没有内容」。
        没有 summary 也没有任务，等于模型什么都没说 ——
        那时候重试一次是有意义的。
    """
    if not isinstance(data, dict) or not data:
        raise ValueError("输出不是一个 JSON 对象")
    has_summary = bool(_flatten_to_text(data.get("summary")))
    tasks = data.get("tasks")
    n_tasks = len(tasks) if isinstance(tasks, list) else 0
    if not has_summary and not n_tasks:
        raise ValueError("既没有 summary 也没有 tasks，等于什么都没说")


def build_plan_prompt(project: DevProject, cites: list[dict], extra: str = "") -> str:
    stack = "、".join(project.tech_stack or []) or "（未指定）"
    parts = [
        "项目名称：%s" % (project.name or ""),
        "项目目标：%s" % (project.goal or "（未填写）"),
        "技术栈：%s" % stack,
        "技术选型说明：%s" % (project.tech_notes or "（未填写）"),
    ]
    # 技术栈是用户拍板的事，不加这一句模型会「顺手」换成自己更喜欢的
    # （实测：用户选了 Python/FastAPI，模型给的是 Java/Spring Boot）
    if project.tech_stack:
        parts.append("注意：技术栈已经定死了，就用上面这些，不要换成别的。")
    parts.extend([
        "",
        "参考资料（只能基于这些内容推导）：",
        _context_block(cites),
    ])
    if extra:
        parts.extend(["", "补充要求：%s" % extra])
    return "\n".join(parts)


def build_task_prompt(project: DevProject, task: DevTask, cites: list[dict],
                      extra: str = "") -> str:
    parts = [
        "项目：%s（目标：%s）" % (project.name or "", project.goal or ""),
        "技术栈：%s" % ("、".join(project.tech_stack or []) or "（未指定）"),
        "",
        "当前任务：%s" % (task.title or ""),
        "任务说明：%s" % (task.description or "（未填写）"),
        "验收标准：%s" % (task.acceptance or "（未填写）"),
        "",
        "参考资料（只能基于这些内容推导）：",
        _context_block(cites),
    ]
    if extra:
        parts.extend(["", "补充要求：%s" % extra])
    return "\n".join(parts)


def build_chat_prompt(project: DevProject, question: str, cites: list[dict]) -> str:
    return "\n".join([
        "项目：%s（目标：%s）" % (project.name or "", project.goal or ""),
        "问题：%s" % (question or ""),
        "",
        "参考资料：",
        _context_block(cites),
    ])


# ============ 安全检查 ============

# 规则表：(正则, 严重级别, 规则名, 提示)
#
# 为什么分成 block 与 warn 两级：
#     block 是「这段代码不该进库」——硬编码真密钥、rm -rf / 这种；
#     warn 是「需要人看一眼」——eval、shell=True 这类。
# 全 block 会把正常代码也拦掉（模型爱写 subprocess），全 warn 又等于没拦。
_SCANNER_RULES = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "block", "private_key", "内嵌私钥"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "block", "openai_key", "疑似 OpenAI 风格密钥"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "block", "github_token", "疑似 GitHub 令牌"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "block", "aws_key", "疑似 AWS Access Key"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "block", "google_key", "疑似 Google API Key"),
    (re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?key|client[_-]?secret)"
                r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"), "block", "hardcoded_secret",
     "疑似硬编码密钥"),
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']"),
     "block", "hardcoded_password", "疑似硬编码口令"),
    (re.compile(r"rm\s+-rf\s+/(?:\s|$)"), "block", "rm_root", "rm -rf / 之类的破坏性命令"),
    (re.compile(r"\bmkfs(\.\w+)?\b"), "block", "mkfs", "格式化磁盘"),
    (re.compile(r"\bdd\s+if="), "block", "dd_raw", "写裸设备"),
    (re.compile(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh"), "block", "curl_pipe_sh",
     "下载后直接执行（curl | sh）"),
    (re.compile(r"chmod\s+-R\s+777\s+/"), "block", "chmod_777_root", "把根目录改成 777"),
    (re.compile(r"\bos\.system\s*\("), "warn", "os_system", "os.system 执行外部命令"),
    (re.compile(r"\bsubprocess\.[a-z_]+\([^)]*shell\s*=\s*True"), "warn",
     "shell_true", "subprocess 开了 shell=True"),
    (re.compile(r"(?<![A-Za-z0-9_.])eval\s*\("), "warn", "eval", "eval 动态执行"),
    (re.compile(r"(?<![A-Za-z0-9_.])exec\s*\("), "warn", "exec", "exec 动态执行"),
    (re.compile(r"pickle\.loads?\s*\("), "warn", "pickle", "反序列化不可信数据"),
    (re.compile(r"verify\s*=\s*False"), "warn", "no_tls_verify", "关闭了证书校验"),
]


def scan_code(text: str, filename: str = "") -> list[dict]:
    """给生成的代码做一次安全体检。

    为什么要查：
        模型有时会把示例里的密钥原样抄进来，也会顺手写一条
        「先清空目录」的 rm -rf。这类东西进了库、进了文档库，
        后面被人复制走就是真的泄密与误删。
    返回的告警要带回前端 —— 让人自己决定要不要留。
    """
    out: list[dict] = []
    if not text:
        return out
    lines = text.split("\n")
    for pattern, severity, rule, message in _SCANNER_RULES:
        for idx, line in enumerate(lines, start=1):
            m = pattern.search(line)
            if not m:
                continue
            out.append({
                "severity": severity,
                "rule": rule,
                "message": message,
                "file": filename,
                "line": idx,
                "snippet": line.strip()[:160],
            })
            break   # 每条规则只报一次，避免同一个问题刷屏
    return out


def has_blocking(warnings: list[dict]) -> bool:
    return any(w.get("severity") == "block" for w in (warnings or []))


# ============ 方案生成 ============

async def generate_plan(db: AsyncSession, project: DevProject, *,
                        principal: str = "", extra: str = "") -> dict:
    """生成项目方案：检索知识 → 问模型 → 拆任务 → 落库。

    每一步都留痕：检索到的引用、发给模型的原话、模型的原话，
    全部存进 dev_session —— 半年后回头看这个产出，
    才知道它凭什么这么写。
    """
    cfg = dev_config.load_config()
    mode = project.mode or dev_config.MODE_OFFLINE
    ensure_model_available(mode, cfg)

    query = " ".join([p for p in [
        project.goal or "", " ".join(project.tech_stack or []),
        project.tech_notes or ""] if p]).strip()
    cites = await retrieve_knowledge(db, query)
    extra_cites, notices = await _online_context(cfg, mode, project, query)
    cites = cites + extra_cites

    prompt = build_plan_prompt(project, cites, extra)
    # 走带重试与抢救的通道：模型输出被截断、结构不对，
    # 在这里当场修好或当场说清楚，不要把半成品丢给用户
    out = await call_model_json(mode, [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": prompt},
    ], cfg=cfg, validator=_validate_plan_payload)
    data = _normalize_plan_payload(out.get("data") or {})
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []

    session = DevSession(
        project_id=project.id,
        task_id=None,
        kind="plan",
        prompt=prompt,
        context={"citations": cites, "mode": mode, "notices": notices},
        reply=out.get("text") or "",
        model=out.get("model") or "",
        mode=mode,
        status="done",
        notice="\n".join(notices),
        created_at=_now(),
    )
    db.add(session)
    await db.flush()
    await _save_citations(db, session.id, cites)

    # 任务落到项目里（模型给的下标依赖先翻译成真实 id）
    base_order = len(await list_tasks(db, project.id))
    created_tasks = []
    id_map: dict[int, int] = {}
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        title = (t.get("title") or "").strip()
        if not title:
            continue
        row = DevTask(
            project_id=project.id,
            title=title[:200],
            description=(t.get("description") or "").strip(),
            acceptance=(t.get("acceptance") or "").strip(),
            status="todo",
            depends_on=[],
            order=base_order + i,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(row)
        await db.flush()
        id_map[i] = row.id
        created_tasks.append(row)
    for i, t in enumerate(tasks):
        if not isinstance(t, dict) or i not in id_map:
            continue
        deps = t.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        real = [id_map[int(d)] for d in deps
                if isinstance(d, int) and int(d) in id_map and int(d) != i]
        if real:
            created_tasks[i].depends_on = real

    project.plan = str(data.get("summary") or "")[:8000]
    project.plan_json = {
        "summary": data.get("summary") or "",
        "architecture": data.get("architecture") or "",
        "tech_stack": [str(x)[:40] for x in (data.get("tech_stack") or [])][:20]
        if isinstance(data.get("tech_stack"), list) else list(project.tech_stack or []),
        "risks": [str(x)[:200] for x in (data.get("risks") or [])][:20]
        if isinstance(data.get("risks"), list) else [],
        "session_id": session.id,
    }
    if project.status in ("draft", ""):
        project.status = "planning"
    project.gene_refs = sorted({int(c["gene_id"]) for c in cites if c.get("gene_id")})
    project.updated_at = _now()
    await db.commit()
    # 刷新一下：被改过的行（带 onupdate 的列）在写库后属性是过期的，
    # 直接序列化会触发异步懒加载报错
    for t in created_tasks:
        await db.refresh(t)
    await db.refresh(session)

    return {
        "session": serialize_session(session, citations=[
            serialize_citation(c) for c in await _citations_of(db, session.id)]),
        "plan": project.plan_json,
        "tasks": [serialize_task(t) for t in created_tasks],
        "citations": cites,
        "notices": notices,
        "model": out.get("model") or "",
    }


async def _citations_of(db: AsyncSession, session_id: int) -> list[DevCitation]:
    rows = (await db.execute(
        select(DevCitation).where(DevCitation.session_id == session_id))).scalars().all()
    return list(rows)


# ============ 任务产出生成 ============

async def generate_task_output(db: AsyncSession, project: DevProject, task: DevTask, *,
                               principal: str = "", extra: str = "",
                               force: bool = False) -> dict:
    """为单个任务生成产出物（代码 / 配置 / 文档）。

    生成完立刻做安全体检：
    block 级的告警（硬编码密钥、破坏性命令）默认不落库，
    除非调用方明确 force=True —— 但告警一定会带回来给人看。
    """
    cfg = dev_config.load_config()
    mode = project.mode or dev_config.MODE_OFFLINE
    ensure_model_available(mode, cfg)

    query = " ".join([p for p in [
        task.title or "", task.description or "", task.acceptance or "",
        project.goal or ""] if p]).strip()
    cites = await retrieve_knowledge(db, query)
    extra_cites, notices = await _online_context(cfg, mode, project, query)
    cites = cites + extra_cites

    prompt = build_task_prompt(project, task, cites, extra)
    out = await call_model(mode, [
        {"role": "system", "content": TASK_SYSTEM},
        {"role": "user", "content": prompt},
    ], cfg=cfg)

    data = parse_json_block(out.get("text") or "")
    if not data:
        raise DevError("模型没有返回可解析的产出 JSON，未生成任何文件",
                       missing=["model_output"],
                       how_to_fix=["换一个好一些的模型再试一次",
                                  "或者把任务说明与验收标准写得更具体"])
    files = data.get("files") or []
    if not isinstance(files, list):
        files = []

    session = DevSession(
        project_id=project.id,
        task_id=task.id,
        kind="task",
        prompt=prompt,
        context={"citations": cites, "mode": mode, "notices": notices,
                 "task": serialize_task(task)},
        reply=out.get("text") or "",
        model=out.get("model") or "",
        mode=mode,
        status="done",
        notice="\n".join(notices),
        created_at=_now(),
    )
    db.add(session)
    await db.flush()

    artifacts = []
    blocked = []
    all_warnings = []
    for f in files:
        if not isinstance(f, dict):
            continue
        path = (f.get("path") or f.get("filename") or "output.txt").strip()
        path = path.lstrip("/")[:200] or "output.txt"
        content = f.get("content") or ""
        if not content.strip():
            continue
        warnings = scan_code(content, path)
        all_warnings.extend(warnings)
        if has_blocking(warnings) and not force:
            blocked.append({"path": path, "warnings": warnings})
            continue
        row = DevArtifact(
            project_id=project.id,
            task_id=task.id,
            filename=path.rsplit("/", 1)[-1][:200],
            path=path,
            content=content,
            language=(f.get("language") or "")[:32],
            artifact_type=_guess_artifact_type(path),
            source="model",
            size=len(content.encode("utf-8", "replace")),
            warnings=warnings,
            document_id=None,
            accepted=False,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(row)
        await db.flush()
        await _save_citations(db, session.id, cites, artifact_id=row.id)
        artifacts.append(row)

    if task.status in ("todo", ""):
        task.status = "doing"
    if project.status in ("draft", "planning"):
        project.status = "building"
    project.gene_refs = sorted(set(list(project.gene_refs or [])
                                    + [int(c["gene_id"]) for c in cites if c.get("gene_id")]))
    project.updated_at = _now()
    await db.commit()
    for row in artifacts:
        await db.refresh(row)
    await db.refresh(session)
    await db.refresh(task)

    return {
        "session": serialize_session(session, citations=[
            serialize_citation(c) for c in await _citations_of(db, session.id)]),
        "artifacts": [serialize_artifact(a, with_content=True) for a in artifacts],
        "blocked": blocked,
        "warnings": all_warnings,
        "citations": cites,
        "notices": notices,
        "notes": str(data.get("notes") or "")[:4000],
        "model": out.get("model") or "",
    }


def _guess_artifact_type(path: str) -> str:
    p = (path or "").lower()
    if p.endswith((".md", ".rst", ".txt")):
        return "doc"
    if p.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".conf", ".xml")):
        return "config"
    return "code"


# ============ 自由问答 ============

async def chat(db: AsyncSession, project: DevProject, question: str, *,
               principal: str = "") -> dict:
    """工作台中间的对话：基于项目 + 知识库回答，并留下引用"""
    cfg = dev_config.load_config()
    mode = project.mode or dev_config.MODE_OFFLINE
    ensure_model_available(mode, cfg)
    query = " ".join([p for p in [question or "", project.goal or ""] if p]).strip()
    cites = await retrieve_knowledge(db, query)
    extra_cites, notices = await _online_context(cfg, mode, project, query)
    cites = cites + extra_cites
    prompt = build_chat_prompt(project, question, cites)
    out = await call_model(mode, [
        {"role": "system", "content": CHAT_SYSTEM},
        {"role": "user", "content": prompt},
    ], cfg=cfg)
    data = parse_json_block(out.get("text") or "") or {}
    answer = str(data.get("answer") or out.get("text") or "")

    session = DevSession(
        project_id=project.id,
        task_id=None,
        kind="chat",
        prompt=prompt,
        context={"citations": cites, "notices": notices, "question": question},
        reply=out.get("text") or "",
        model=out.get("model") or "",
        mode=mode,
        status="done",
        notice="\n".join(notices),
        created_at=_now(),
    )
    db.add(session)
    await db.flush()
    await _save_citations(db, session.id, cites)
    await db.commit()
    return {
        "session": serialize_session(session, citations=[
            serialize_citation(c) for c in await _citations_of(db, session.id)]),
        "answer": answer,
        "citations": cites,
        "notices": notices,
    }


# ============ 产出物入库（数据中心） ============

async def import_artifact_to_library(db: AsyncSession, artifact: DevArtifact, *,
                                     principal: str = "",
                                     mode: str = dev_config.MODE_OFFLINE) -> dict:
    """把产出物存进数据中心（文件库）。

    为什么要多这一步：
        产出物只在开发模块里躺着的话，它既搜不到、也引用不了、
        更不会成为下一轮开发的输入。进了文件库之后，
        它就是「这个系统的一部分」，能被全局检索、被别的模块引用。
    """
    from . import document as doc_svc

    content = artifact.content or ""
    if not content.strip():
        raise DevError("这个产出物是空的，入库没有意义")
    data = content.encode("utf-8")
    # 离线模式下不做向量化：向量化要调嵌入接口，那是外网调用
    do_embed = mode != dev_config.MODE_OFFLINE
    res = await doc_svc.create_document(
        db,
        data=data,
        filename=artifact.filename or "artifact.txt",
        title="%s · %s" % ((artifact.path or artifact.filename or "产出物"),
                           "开发产出"),
        tags=["开发产出"],
        source="dev",
        app="default",
        description="由软件开发模块产出（项目 #%s）" % artifact.project_id,
        do_embed=do_embed,
    )
    artifact.document_id = res.get("id")
    artifact.updated_at = _now()
    await db.commit()
    return res


# ============ 反哺知识库（闭环的最后一段） ============

async def _raise_confidence(db: AsyncSession, gene_ids: list[int], *,
                            delta: float = 0.05, cap: float = 0.95) -> dict:
    """被真实产出验证过的知识，置信度上调。

    为什么要有这一步：
        基因入库时的置信度是「蒸馏出来的置信度」—— 看着像那么回事，
        但没人验证过。真正跑过一次开发、产出了能用的代码之后，
        这条知识的可信度才配往上调。
        不上调的话，库里的知识永远停在「0.7 差不多」，用得越多也不长进。
    """
    if not gene_ids:
        return {}
    rows = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(gene_ids)))).scalars().all()
    before = {}
    for g in rows:
        before[g.id] = float(g.confidence or 0.0)
        g.confidence = min(cap, round(float(g.confidence or 0.0) + delta, 3))
        g.updated_at = _now()
    await db.commit()
    return before


async def _validate_genes(db: AsyncSession, gene_ids: list[int], *,
                          project: DevProject, round_no: int) -> dict:
    """把「被这次真实产出验证过」的基因标成已验证，并让评分跟着涨

    走的是养料库自己的评分模型（dna_score）：
      - meta.verified = True —— 「人工确认过」的来源权威度加分；
      - record_use(success=True) —— 复用成功率与表达度跟着涨。

    为什么不用手改 confidence 列：
        那一列是评分结果的**镜像**，下一次重算就被冲掉了。
    手改的数等于没改 —— 闭环要的是真的长进，不是看着像长进。
    评分模型不可用时（升级过程中的短暂状态）才退回直接加分。
    """
    empty = {"confidence_raised": [], "expression_raised": [], "mechanism": "none"}
    if not gene_ids:
        return empty
    rows = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(gene_ids)))).scalars().all()
    before = {}
    for g in rows:
        before[g.id] = {
            "confidence": float(getattr(g, "confidence", 0) or 0),
            "expressiveness": float(getattr(g, "expressiveness", 0) or 0),
            "title": g.title or "",
        }
    for g in rows:
        meta = dict(g.meta or {})
        meta["verified"] = True
        meta["dev_validated"] = {
            "project_id": project.id,
            "project": project.name,
            "round": round_no,
            "at": _now().isoformat(),
        }
        g.meta = meta
    await db.commit()

    mechanism = "fallback"
    try:
        from . import dna_score
        # 引用计数先加：表达度里的「被复用度」要看到最新的次数
        await dna_library.mark_gene_used(db, gene_ids)
        # mark_gene_used 走的是 ORM update，不刷新会话里的对象；
        # 不刷新的话，重算时读到的还是旧次数 —— 表达度就涨不上去
        for g in rows:
            await db.refresh(g)
        if hasattr(dna_score, "record_use"):
            await dna_score.record_use(db, gene_ids, success=True)
        if hasattr(dna_score, "rescore_genes"):
            await dna_score.rescore_genes(db, gene_ids)
        mechanism = "dna_score"
    except Exception as e:
        log.warning("基因评分重算失败，退回直接加分：%s", type(e).__name__)
        await _raise_confidence(db, gene_ids, delta=0.05)
        await dna_library.mark_gene_used(db, gene_ids)

    after_rows = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(gene_ids)))).scalars().all()
    confidence_raised = []
    expression_raised = []
    for g in after_rows:
        b = before.get(g.id) or {}
        now_c = float(getattr(g, "confidence", 0) or 0)
        now_e = float(getattr(g, "expressiveness", 0) or 0)
        if now_c > float(b.get("confidence") or 0) + 1e-6:
            confidence_raised.append({
                "gene_id": g.id, "title": g.title or b.get("title", ""),
                "before": round(float(b.get("confidence") or 0), 3),
                "after": round(now_c, 3)})
        if now_e > float(b.get("expressiveness") or 0) + 1e-6:
            expression_raised.append({
                "gene_id": g.id, "title": g.title or b.get("title", ""),
                "before": round(float(b.get("expressiveness") or 0), 3),
                "after": round(now_e, 3)})
    return {
        "confidence_raised": confidence_raised,
        "expression_raised": expression_raised,
        "mechanism": mechanism,
    }


async def feedback_to_library(db: AsyncSession, project: DevProject, *,
                              principal: str = "", artifact_ids: list | None = None,
                              lessons: str = "") -> dict:
    """把这次开发沉淀回养料库 —— 闭环的最后一段。

    落库路径（复用的是 DNA 的蒸馏能力，不是另起一套）：
        产出物（代码） → dna_distill.distill_code 抽出方法与经验
                       → dna_library.upsert_gene 写入基因（带开发来源）
        产出物（文档） → dna_library.extract_genes_from_markdown 抽段落
                       → 同上

    两条「长进」的体现，都落在这张表上，不是嘴上说说：
        置信度：被这次成功产出验证过的引用基因，confidence 上调；
        表达度：同一批基因的 usage_count +1（被真正用起来过）。
    """
    round_no = int(project.feedback_round or 0) + 1
    stmt = select(DevArtifact).where(DevArtifact.project_id == project.id)
    if artifact_ids:
        stmt = stmt.where(DevArtifact.id.in_([int(a) for a in artifact_ids]))
    else:
        # 默认只反哺「已验收」的产出物：
        # 没验收的代码沉淀进知识库，等于把错的做法也变成经验
        stmt = stmt.where(DevArtifact.accepted.is_(True))
    artifacts = (await db.execute(stmt.order_by(DevArtifact.id))).scalars().all()
    if not artifacts:
        raise DevError("没有可反哺的产出物",
                       missing=["accepted_artifacts"],
                       how_to_fix=["先在项目里把产出物标记为「已验收」，再执行反哺"])

    created = 0
    updated = 0
    touched: list[int] = []
    detail_rows = []
    for a in artifacts:
        text = a.content or ""
        if not text.strip():
            continue
        if a.artifact_type == "doc":
            genes = dna_library.extract_genes_from_markdown(text, title=a.filename or a.path or "")
        else:
            res = dna_distill.distill_code(text, a.filename or a.path or "artifact.txt")
            genes = res.genes
        for g in genes:
            title = (g.get("title") or "").strip()[:250]
            content = (g.get("content") or "").strip()
            if not title or not content:
                continue
            before_row = (await db.execute(
                select(DnaGene).where(
                    DnaGene.kind == (g.get("kind") or "method"),
                    DnaGene.title == title,
                    DnaGene.content == content))).scalars().first()
            before_conf = float(before_row.confidence or 0.0) if before_row else None
            gene, is_new = await dna_library.upsert_gene(
                db,
                kind=g.get("kind") or "method",
                title=title,
                content=content,
                summary=dna_library.short_summary(content),
                tags=list(g.get("tags") or []) + ["开发沉淀", "项目#%s" % project.id],
                source_kind="derived",
                source_ref="dev:%d" % project.id,
                source_title=a.filename or a.path or "",
                # 0.86：比新蒸馏出来的经验（0.7）高 —— 因为它被一次真实开发验证过
                confidence=0.86,
                meta={
                    "origin": "dev_feedback",
                    "dev_project": project.id,
                    "dev_project_name": project.name,
                    "dev_artifact": a.id,
                    "feedback_round": round_no,
                    "validated": True,
                },
            )
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
            touched.append(gene.id)
            detail_rows.append({
                "gene_id": gene.id,
                "title": gene.title,
                "kind": gene.kind,
                "created": is_new,
                "confidence_before": before_conf,
                "confidence_after": round(float(gene.confidence or 0.0), 3),
            })

    # 项目级经验：方案 + 验收 + 踩坑，合起来才是「可复用的做法」
    plan = project.plan_json or {}
    summary_lines = [
        "项目「%s」的目标：%s" % (project.name or "", project.goal or "（未填写）"),
        "整体设计：%s" % (plan.get("architecture") or "（未生成方案）"),
        "技术栈：%s" % ("、".join(project.tech_stack or []) or "（未指定）"),
    ]
    if lessons:
        summary_lines.append("这次的经验与踩坑：%s" % lessons)
    summary_lines.append("产出文件：%s" % "、".join(a.path or a.filename for a in artifacts[:20]))
    summary_title = "开发项目「%s」的做法与经验" % (project.name or "")
    gene, is_new = await dna_library.upsert_gene(
        db,
        kind="experience" if lessons else "method",
        title=summary_title[:250],
        content="\n".join(summary_lines)[:4000],
        summary=dna_library.short_summary("\n".join(summary_lines)),
        tags=["开发沉淀", "项目#%s" % project.id],
        source_kind="derived",
        source_ref="dev:%d" % project.id,
        source_title=project.name or "",
        confidence=0.82,
        meta={"origin": "dev_feedback", "dev_project": project.id,
              "dev_project_name": project.name, "feedback_round": round_no,
              "validated": True},
    )
    created += 1 if is_new else 0
    updated += 0 if is_new else 1
    touched.append(gene.id)
    await db.commit()

    # ---- 表达度与置信度的「长进」：这次开发真正用过的那些基因 ----
    cited_rows = (await db.execute(
        select(DevCitation.ref)
        .join(DevSession, DevCitation.session_id == DevSession.id)
        .where(DevSession.project_id == project.id,
               DevCitation.kind == "gene"))).scalars().all()
    cited_gene_ids = []
    for ref in cited_rows:
        raw = str(ref or "")
        if raw.startswith("gene:"):
            try:
                cited_gene_ids.append(int(raw.split(":", 1)[1]))
            except ValueError:
                continue
    cited_gene_ids = sorted(set(cited_gene_ids))

    growth = await _validate_genes(db, cited_gene_ids,
                                      project=project, round_no=round_no)
    confidence_raised = growth["confidence_raised"]
    expression_raised = growth["expression_raised"]

    project.feedback_round = round_no
    project.status = "produced"
    project.updated_at = _now()
    await db.commit()

    return {
        "round": round_no,
        "artifacts_absorbed": len(artifacts),
        "genes_created": created,
        "genes_updated": updated,
        "gene_ids": sorted(set(touched)),
        "detail": detail_rows[:100],
        "confidence_raised": confidence_raised,
        "expression_raised": expression_raised,
        "cited_gene_count": len(cited_gene_ids),
    }


# ============ 自检：现在缺什么、怎么配 ============

async def doctor(db: AsyncSession, mode: str = "") -> dict:
    """外部依赖体检。

    离线模式下这里不发任何外网请求 —— 连「探测一下能不能连上」都不做，
    因为那本身就是一次出网。

    返回里的两段语义**不许混**：
      missing / how_to_fix —— 阻断项：缺了就完全没法开工。
        目前只有 model_endpoint（没模型端点）与 knowledge（本地知识库为空）。
      optional            —— 增强项：配了更好，不配照样能开工。
        目前只有 github.repos 与 web_search.endpoint（仅在线模式探测）。

    为什么必须分开：前端把 missing 渲染成「还差这些才能开发」的红条。
    以前把增强项也算进 missing，用户看到的永远是「差一堆东西」，
    于是以为整个软件开发模块不可用 —— 实际上模型一就绪就能开工。
    """
    cfg = dev_config.load_config()
    mode = mode or cfg.get("mode") or dev_config.MODE_OFFLINE
    caps = []

    gene_count = (await db.execute(select(func.count()).select_from(DnaGene))).scalar_one() or 0
    doc_count = (await db.execute(
        select(func.count()).select_from(Document))).scalar_one() or 0
    caps.append({
        "key": "knowledge",
        "ok": bool(gene_count or doc_count),
        "label": "本地知识库",
        "detail": "基因 %s 条 · 文档 %s 篇" % (gene_count, doc_count),
    })

    info = describe_model(mode, cfg)
    caps.append({
        "key": "model",
        "ok": bool(info.get("ready")),
        "label": "模型端点",
        "detail": info.get("note") or "",
        "model": info.get("model") or "",
        "endpoint": info.get("endpoint") or "",
    })

    gh = cfg.get("github") or {}
    gh_ready = bool(gh.get("token")) or bool(gh.get("repos"))
    if mode != dev_config.MODE_ONLINE:
        caps.append({"key": "github", "ok": True, "label": "GitHub 开源项目",
                     "detail": "离线模式不访问外网（本项未探测）"})
        caps.append({"key": "web_search", "ok": True, "label": "网络知识检索",
                     "detail": "离线模式不访问外网（本项未探测）"})
    else:
        caps.append({
            "key": "github",
            "ok": gh_ready,
            "label": "GitHub 开源项目",
            "detail": ("已配置 %s 个仓库、令牌%s"
                       % (len(gh.get("repos") or []),
                          "已配置" if (gh.get("token") or "").strip() else "未配置（匿名额度有限）")),
        })
        ws = cfg.get("web_search") or {}
        caps.append({
            "key": "web_search",
            "ok": bool(ws.get("enabled") and (ws.get("endpoint") or "").strip()),
            "label": "网络知识检索",
            "detail": ("已配置搜索服务" if ws.get("enabled") and (ws.get("endpoint") or "").strip()
                       else "未配置搜索服务：在线模式将不使用网络知识"),
        })

    missing = []
    how = []
    # 「缺了就完全没法开工」与「只是少个增强」必须分开：
    #   阻断项只有两个 —— 没有模型端点就一个字也生成不出来，
    #     没有本地知识就只剩通用套路。
    #   GitHub 仓库、网络检索都是**增强**：不配照样能开工。
    optional: list[dict] = []
    # 「一键切到在线协同」的出口：
    #   离线模式不认云端模型是刻意的（不偷偷出网），但现实里大多数机器
    #   没有本地模型端点 —— 于是整个开发模块直接罢工，用户被卡在门口。
    #   这里明确告诉前端「系统大模型已经配好了，切一下就能用」，
    #   让前端能给出**一键切换**而不是一句「请自行配置」。
    switch_hint = None
    if not info.get("ready"):
        missing.extend(["model_endpoint"])
        how.append("配置模型端点：离线模式用「开发设置 → 本地模型端点」，"
                   "在线模式用「AI 设置」里的大模型")
        if mode == dev_config.MODE_OFFLINE and system_model_ready():
            switch_hint = {
                "action": "switch_mode",
                "mode": dev_config.MODE_ONLINE,
                "label": "切到在线协同模式（用系统大模型 %s）"
                         % (ai_config.get_full_config().get("model") or ""),
                "why": "当前是离线闭环模式，它只认本机模型端点；"
                       "而系统里已经配好了一个可用的大模型。",
            }
    if mode == dev_config.MODE_ONLINE:
        # 这两项是**增强**，不是阻断：
        #   配了 → 方案能参考 GitHub 上的现成实现、能查最新资料；
        #   没配 → 照样开工，只是少这两路参考来源。
        # 放在 missing 里的话，前端会一直提示「还差这些才能开发」，
        # 用户就以为整个模块不可用 —— 实际第一份方案照样出得来。
        if not gh_ready:
            optional.append({
                "key": "github.repos",
                "label": "增强：参考 GitHub 上现成的开源实现",
                "how_to_fix": "开发设置 → GitHub 仓库：填 owner/repo，并配置令牌（可选但强烈建议）；不配也能开工，只是少了这一路现成方案的来源",
            })
        ws = cfg.get("web_search") or {}
        if not (ws.get("enabled") and (ws.get("endpoint") or "").strip()):
            optional.append({
                "key": "web_search.endpoint",
                "label": "增强：联网检索最新的技术资料与用法",
                "how_to_fix": "开发设置 → 网络搜索：填搜索服务地址；不配也能开工，只是不会去网上找资料",
            })
    if not (gene_count or doc_count):
        missing.append("knowledge")
        how.append("先到「养料库」吸收源码或文档：没有知识可引用，生成只能是通用套路")

    return {
        "mode": mode,
        "mode_label": dev_config.MODE_LABEL.get(mode, mode),
        "outbound_enabled": dev_config.outbound_enabled(cfg),
        "capabilities": caps,
        # missing 只放阻断项（与 how_to_fix 一一对应）：
        #   前端拿它渲染「还差这些才能开工」的红条。
        # optional 放增强项：配了更好，不配照样能开工，
        #   绝不能混进 missing —— 混进去就等于说「模块不可用」。
        "missing": missing,
        "how_to_fix": how,
        "optional": optional,
        "model": info,
        "switch_hint": switch_hint,
    }


# ============ 后台作业（进度条沿用养料库那套） ============

async def _update_job(db: AsyncSession, job_id: int, **fields) -> None:
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        return
    for k, v in fields.items():
        setattr(job, k, v)
    await db.commit()


async def run_plan_job(job_id: int, project_id: int) -> None:
    """后台生成方案：进度写回 dna_job，前端轮询就能看到状态"""
    from ..database import SessionLocal
    async with SessionLocal() as db:
        job = (await db.execute(
            select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
        if job is None:
            return
        job.status = "running"
        job.started_at = _now()
        await db.commit()
    try:
        async with SessionLocal() as db:
            project = await get_project(db, project_id)
            if project is None:
                await _update_job(db, job_id, status="failed", error="项目不存在")
                return
            res = await generate_plan(db, project)
            await _update_job(db, job_id, status="done", processed=1, total=1,
                              current="",
                              created=len(res.get("tasks") or []),
                              finished_at=_now(),
                              detail={"session_id": (res.get("session") or {}).get("id"),
                                      "tasks": len(res.get("tasks") or []),
                                      "citations": len(res.get("citations") or [])})
    except DevError as e:
        async with SessionLocal() as db:
            await _update_job(db, job_id, status="failed", error=e.message[:500],
                              finished_at=_now(),
                              detail={"missing": e.missing, "how_to_fix": e.how_to_fix})
    except Exception as e:
        log.exception("方案生成任务失败 job=%s", job_id)
        async with SessionLocal() as db:
            await _update_job(db, job_id, status="failed",
                              error=("%s: %s" % (type(e).__name__, e))[:500],
                              finished_at=_now())


async def run_tasks_job(job_id: int, project_id: int) -> None:
    """后台逐任务生成：每个任务生成完就更新一次进度"""
    from ..database import SessionLocal
    async with SessionLocal() as db:
        job = (await db.execute(
            select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
        if job is None:
            return
        job.status = "running"
        job.started_at = _now()
        await db.commit()
    try:
        async with SessionLocal() as db:
            project = await get_project(db, project_id)
            if project is None:
                await _update_job(db, job_id, status="failed", error="项目不存在")
                return
            tasks = [t for t in (await list_tasks(db, project_id))
                     if t.get("status") in ("todo", "doing")]
            total = len(tasks)
            await _update_job(db, job_id, total=total)
            done = 0
            failed = 0
            for t in tasks:
                await _update_job(db, job_id, current=t.get("title") or "",
                                  processed=done)
                task = await get_task(db, t["id"])
                if task is None:
                    failed += 1
                    continue
                try:
                    await generate_task_output(db, project, task)
                    done += 1
                except DevError as e:
                    failed += 1
                    log.warning("任务生成失败 #%s：%s", task.id, e.message)
                except Exception as e:
                    failed += 1
                    log.warning("任务生成异常 #%s：%s", task.id, type(e).__name__)
                await _update_job(db, job_id, processed=done, failed=failed)
            await _update_job(db, job_id, status="done", processed=done, total=total,
                              current="", created=done, failed=failed,
                              finished_at=_now())
    except Exception as e:
        log.exception("任务生成作业失败 job=%s", job_id)
        async with SessionLocal() as db:
            await _update_job(db, job_id, status="failed",
                              error=("%s: %s" % (type(e).__name__, e))[:500],
                              finished_at=_now())
