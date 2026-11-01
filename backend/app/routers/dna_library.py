"""DNA 养料库路由：吸收、检索、直答、离线开关、打包

接口：
    GET  /api/dna/library/overview     库的总览（基因数/种类/表达度/体检）
    GET  /api/dna/library/genes        基因列表（可按种类筛、可分页）
    GET  /api/dna/library/genes/{id}   单条基因
    GET  /api/dna/library/search       基因检索
    POST /api/dna/library/absorb       吸收（文档 / 文本 / 记录 / 源码）
    POST /api/dna/library/absorb/all   全库吸收
    POST /api/dna/library/offline      离线模式开关
    GET  /api/dna/library/offline      离线状态 + 断网可用性自检
    GET  /api/dna/library/answer       离线直答（不调模型）
    GET  /api/dna/library/bundle       导出养料库包
    POST /api/dna/library/bundle/inspect  检查一个包
    POST /api/dna/library/bundle/import   导入一个包

鉴权口径与 /api/dna 的其它接口一致：只挂 current_principal，
不硬拦 dna 页面位（原因见 routers/dna.py 顶部注释）。
写操作（吸收、离线开关、导入）会写审计日志。
"""
import asyncio
import logging
import shutil
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import DnaGap, DnaGene, DnaJob, Document, DocumentChunk
from ..services import audit as audit_svc
from ..services import dna_library as svc
from ..services import dna_ingest as ingest
from ..services.auth import Principal, current_principal

router = APIRouter(prefix="/api/dna/library", tags=["dna-library"])

log = logging.getLogger("kb.dna_library.router")

# 后台任务的 asyncio 句柄：用来取消还在跑的任务
_JOBS: dict[int, asyncio.Task] = {}


# ============ 请求体 ============

class AbsorbTextBody(BaseModel):
    text: str = Field(..., description="要吸收的正文（结构化/非结构化都行）")
    title: str = ""
    source_kind: str = "manual"
    source_ref: str = ""
    source_title: str = ""


class AbsorbCodeBody(BaseModel):
    code: str = Field("", description="源码原文；蒸馏后不留存")
    filename: str = "untitled"
    destroy: bool = Field(True, description="蒸馏完是否销毁原文（默认销毁）")
    path: str = Field("", description="文件库里的源码相对路径（给了就用它，不给用 code）")
    destroy_file: bool = Field(
        False, description="蒸馏后把磁盘上的源文件也删掉（默认不删）")


class AbsorbSourceBody(BaseModel):
    document_id: int = Field(..., description="文件库里那份源码的文档 id")
    destroy_file: bool = Field(
        False, description="蒸馏后把源文件从磁盘删掉（默认只清库留证）")
    destroy: bool = Field(True, description="蒸馏完是否写销毁证明（默认写）")


class OfflineBody(BaseModel):
    enabled: bool


class ImportBody(BaseModel):
    path: str = Field(..., description="包文件路径（服务器本地）")
    mode: str = Field("merge", description="merge 合并 / replace 覆盖")


# ============ 读接口 ============

@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db),
                   principal: Principal = Depends(current_principal)):
    """养料库总览：基因规模、种类分布、表达度、体检、离线状态"""
    health = await svc.gene_health(db)
    total = (await db.execute(
        select(func.count()).select_from(DnaGene))).scalar_one()
    by_kind = health["by_kind"]
    offline = await svc.is_offline(db)
    return {
        "total": total,
        "by_kind": by_kind,
        "health": health,
        "offline": offline,
        "offline_ready": await _offline_ready(db),
        "kinds": [
            {"key": "fact", "label": "事实", "count": by_kind.get("fact", 0),
             "desc": "是什么"},
            {"key": "method", "label": "方法", "count": by_kind.get("method", 0),
             "desc": "怎么做"},
            {"key": "experience", "label": "经验", "count": by_kind.get("experience", 0),
             "desc": "踩过什么坑"},
            {"key": "interface", "label": "接口", "count": by_kind.get("interface", 0),
             "desc": "怎么调"},
            {"key": "policy", "label": "约定", "count": by_kind.get("policy", 0),
             "desc": "必须怎么做"},
        ],
    }


@router.get("/genes")
async def genes(kind: str = Query("", description="按种类过滤"),
                q: str = Query("", description="标题/正文模糊过滤"),
                status: str = Query("active",
                                    description="active 当前 / superseded 已被取代 / all 全部"),
                sort: str = Query("id",
                                  description="id 默认 / usage 表达度 / updated 最近更新 / confidence 置信"),
                flag: str = Query("",
                                  description="体检筛选：cold 没人用 / used 用过 / no_source 没出处 / low_conf 置信低"),
                limit: int = Query(50, le=500),
                offset: int = Query(0),
                db: AsyncSession = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    """基因列表

    默认只给「当前」基因 —— 被取代的旧版本是历史，不是知识。
    要看历史就显式要 status=superseded 或 all。
    """
    stmt = select(DnaGene)
    if kind:
        stmt = stmt.where(DnaGene.kind == kind)
    if status and status != "all":
        stmt = stmt.where(DnaGene.status == status)
    if q:
        # 搜索要覆盖正文，不只是标题：
        # 很多基因的标题是「军队采购网」这种泛名，
        # 真正有信息量的是正文（「投标截止时间是多少」）。
        # 只搜标题 → 搜「投标截止」一条都搜不到。
        ids = await svc.search_gene_ids(db, q, limit=800)
        if ids:
            stmt = stmt.where(DnaGene.id.in_(ids))
        else:
            stmt = stmt.where(DnaGene.title.like(f"%{q}%"))
    # 体检筛选：让「冷基因 55」这种结论能点开看是哪 55 条，
    # 而不是只给一个数字让人猜
    if flag == "cold":
        stmt = stmt.where(DnaGene.usage_count == 0)
    elif flag == "used":
        stmt = stmt.where(DnaGene.usage_count > 0)
    elif flag == "no_source":
        stmt = stmt.where(DnaGene.source_ref == "")
    elif flag == "low_conf":
        stmt = stmt.where(DnaGene.confidence < 0.6)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {
        "usage": (DnaGene.usage_count.desc(), DnaGene.id),
        "updated": (DnaGene.updated_at.desc(), DnaGene.id),
        "confidence": (DnaGene.confidence.desc(), DnaGene.id),
    }.get(sort, (DnaGene.kind, DnaGene.id))
    rows = (await db.execute(
        stmt.order_by(*order)
        .offset(offset).limit(limit))).scalars().all()
    return {"items": [svc.serialize_gene(g) for g in rows],
            "total": total, "limit": limit, "offset": offset}


@router.get("/genes/{gene_id}")
async def gene_detail(gene_id: int, db: AsyncSession = Depends(get_db),
                       principal: Principal = Depends(current_principal)):
    """单条基因的详情"""
    g = (await db.execute(
        select(DnaGene).where(DnaGene.id == gene_id))).scalar_one_or_none()
    if g is None:
        raise HTTPException(404, "基因不存在")
    return svc.serialize_gene(g)


class CiteBody(BaseModel):
    gene_ids: list[int] = Field(default_factory=list)
    format: str = Field("markdown", description="markdown / plain")


@router.post("/cite")
async def cite(payload: CiteBody, db: AsyncSession = Depends(get_db),
               principal: Principal = Depends(current_principal)):
    """把基因变成一段可以贴到任何地方的引用

    「在系统任何地方直接可以引用」：
    这里给出的是**成品**（一段带出处的文字），
    不是「基因 id 12」这种需要自己再拼的东西。
    """
    genes = []
    for gid in payload.gene_ids[:20]:
        g = await svc.get_gene(db, gid)
        if g is None:
            continue
        # 已被取代的旧版本不拿去引用 ——
        # 引用出来的东西应该是当前有效的知识
        if g.status != "active":
            continue
        genes.append(svc.serialize_gene(g))
    if not genes:
        return {"text": "", "genes": []}
    if payload.format == "plain":
        text = "\n\n".join(
            f"【基因#{g['id']} · {g.get('kind_label') or g['kind']}】{g['title']}\n{g['content']}"
            for g in genes)
    else:
        blocks = []
        for g in genes:
            src = f"（出处：{g['source_title']}）" if g.get("source_title") else ""
            blocks.append(
                f"> **【基因#{g['id']} · {g.get('kind_label') or g['kind']}】{g['title']}**{src}\n"
                f">\n> " + (g.get("content") or "").replace("\n", "\n> "))
        text = "\n\n".join(blocks)
    return {"text": text, "genes": genes}


# ============ 后台吸收任务（源码树整体上传 / 进度 / 进化账本） ============

@router.post("/jobs/source-tree")
async def create_source_tree_job(
    files: list[UploadFile] = File(default=[]),
    zip_file: UploadFile | None = File(None, alias="zip"),
    title: str = Form(""),
    destroy: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """把一整棵源码树交给养料库学

    上传的是**目录**（浏览器一次选几百个文件）或者一个 zip，
    落盘到暂存区后立刻返回任务号，
    真正的解析在后台跑 —— 进度用 GET /api/dna/library/jobs/{id} 查。

    销毁顺序和单文件吸收一致：先蒸馏成基因、先写销毁证明，然后才删源码。
    """
    uploads = [f for f in (files or []) if f is not None and f.filename]
    if zip_file is not None and zip_file.filename:
        uploads.append(zip_file)
    if not uploads:
        raise HTTPException(status_code=400, detail="没有收到文件")

    job = await ingest.create_job(
        db, job_type="source_tree",
        title=title or f"源码树 {len(uploads)} 个文件",
        total=len(uploads),
        principal=str(getattr(principal, "username", "") or ""))

    staged = ingest.staging_root() / f"job-{job.id}"
    staged.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    written = 0
    try:
        for up in uploads:
            name = ingest._safe_name(up.filename)
            if not name:
                continue
            dest = staged / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = await up.read()
            total_bytes += len(data)
            if total_bytes > ingest.MAX_TOTAL_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"上传总量超过 {ingest.MAX_TOTAL_BYTES // 1024 // 1024} MB")
            dest.write_bytes(data)
            written += 1
            await up.close()
    except HTTPException:
        shutil.rmtree(staged, ignore_errors=True)
        await ingest._update_job(db, job.id, status="failed",
                                 error="上传中断", finished_at=ingest._now())
        raise
    except Exception as e:
        shutil.rmtree(staged, ignore_errors=True)
        await ingest._update_job(db, job.id, status="failed",
                                 error=str(e)[:300], finished_at=ingest._now())
        raise HTTPException(status_code=500, detail=f"保存上传文件失败：{e}")

    # zip 要解开（安全解压：拒绝越界路径）
    zips = [p for p in staged.rglob("*") if p.is_file() and p.suffix.lower() == ".zip"]
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                for member in zf.namelist():
                    # 目录条目要跳过：zip 里的目录项读出来是空的，
                    # 而 zf.open 对目录会直接抛异常 ——
                    # 一个目录项把整个解压循环带崩，整棵源码树就一个文件都没落地。
                    if member.endswith("/"):
                        continue
                    safe = ingest._safe_name(member)
                    if not safe or safe == "unnamed":
                        continue
                    try:
                        out = staged / safe
                        out.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, out.open("wb") as dst:
                            shutil.copyfileobj(src, dst, length=1024 * 256)
                    except Exception as e:
                        log.warning("解压条目失败 %s：%s", member, e)
        except Exception as e:
            log.warning("解压 zip 失败 %s：%s", zp.name, e)
        finally:
            try:
                zp.unlink()
            except OSError:
                pass

    # 真实的文件数（解压后才知道）
    real_files = [p for p in staged.rglob("*") if p.is_file()]
    await ingest._update_job(db, job.id, total=len(real_files),
                             title=title or f"源码树 {len(real_files)} 个文件")
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job.id))).scalar_one_or_none()

    # 后台跑：不等它
    task = asyncio.create_task(ingest.run_source_tree_job(job.id, staged))
    _JOBS[job.id] = task
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dna_source_tree_upload",
        user_id=getattr(principal, "id", None),
        resource="dna_library", method="POST",
        path="/api/dna/library/jobs/source-tree",
        detail={"job_id": job.id, "files": len(real_files),
                "title": job.title, "staged_bytes": written},
    )
    return {"job": ingest.job_to_dict(job), "staged_files": len(real_files)}


@router.get("/jobs")
async def list_jobs(limit: int = Query(20, le=100),
                    db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """后台任务列表（含进度）"""
    rows = (await db.execute(
        select(DnaJob).order_by(DnaJob.id.desc()).limit(limit))).scalars().all()
    return {"items": [ingest.job_to_dict(j) for j in rows]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int,
                  db: AsyncSession = Depends(get_db),
                  principal: Principal = Depends(current_principal)):
    """单个任务的进度 —— 前端轮询这个"""
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": ingest.job_to_dict(job)}


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: int,
                     db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    """取消一个还在跑的任务"""
    task = _JOBS.pop(job_id, None)
    if task is not None and not task.done():
        task.cancel()
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status in ("pending", "running"):
        job.status = "canceled"
        job.finished_at = ingest._now()
        await db.commit()
    return {"job": ingest.job_to_dict(job)}


@router.get("/gaps")
async def list_gaps(db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """系统还答不上来的问题 —— 下一轮该喂什么"""
    return await ingest.gap_summary(db)


@router.delete("/gaps/{gap_id}")
async def close_gap(gap_id: int, db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """手动关掉一条缺口（补过了）"""
    gap = (await db.execute(
        select(DnaGap).where(DnaGap.id == gap_id))).scalar_one_or_none()
    if gap is None:
        raise HTTPException(status_code=404, detail="缺口不存在")
    gap.status = "filled"
    gap.note = "手动关闭"
    await db.commit()
    return {"ok": True}


@router.get("/evolution")
async def evolution(db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """进化账本：吸收了多少 → 长出了多少 → 被用起来多少"""
    snap = await ingest.evolution_snapshot(db)
    snap["auto_feed"] = await ingest.get_auto_feed(db)
    gaps = await ingest.gap_summary(db)
    snap["gaps"] = {"open_count": gaps["open_count"],
                    "filled_count": gaps["filled_count"],
                    "total_count": gaps["total_count"]}
    return snap


class AutoFeedBody(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


@router.put("/auto-feed")
async def update_auto_feed(body: AutoFeedBody,
                            db: AsyncSession = Depends(get_db),
                            principal: Principal = Depends(current_principal)):
    """自动喂养开关：每隔一段时间自动吸收新资料"""
    cfg = await ingest.set_auto_feed(db, enabled=body.enabled,
                                     interval_minutes=body.interval_minutes)
    await audit_svc.log_event(
        getattr(principal, "username", "") or "-", "dna_auto_feed_update",
        user_id=getattr(principal, "id", None),
        resource="dna_library", method="PUT",
        path="/api/dna/library/auto-feed",
        detail={"enabled": cfg.get("enabled"),
                "interval_minutes": cfg.get("interval_minutes")},
    )
    return {"ok": True, "auto_feed": cfg}


@router.post("/auto-feed/run")
async def run_auto_feed_now(db: AsyncSession = Depends(get_db),
                             principal: Principal = Depends(current_principal)):
    """立刻跑一轮自动喂养（不等定时器）"""
    res = await ingest.auto_feed_once(db)
    return {"ok": True, "result": res}


@router.get("/search")
async def search(q: str = Query("", description="检索词"),
                 kind: str = Query(""),
                 limit: int = Query(12, le=100),
                 db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """基因检索（纯本地，不需要网络）"""
    kinds = [kind] if kind else None
    hits = await svc.search_genes(db, q, limit=limit, kinds=kinds)
    return {"query": q,
            "items": [{"gene": svc.serialize_gene(h["gene"]), "score": h["score"]}
                      for h in hits]}


@router.get("/answer")
async def answer(q: str = Query("", description="问题"),
                 kind: str = Query("", description="限定种类"),
                 limit: int = Query(5, le=20),
                 db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """离线直答：不调模型，把养料库里的基因与原文端出来

    断网时这条接口就是问答能力的下限 —— 给不出生成式答案，
    但给得出有出处的原文。
    """
    return await svc.answer_offline(db, q, limit=limit,
                                    kinds=[kind] if kind else None)


@router.get("/offline")
async def offline_status(db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(current_principal)):
    """离线状态与断网可用性自检"""
    return {"offline": await svc.is_offline(db),
            "ready": await _offline_ready(db)}


@router.get("/drill")
async def drill(db: AsyncSession = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    """断网演练：只用养料库跑一遍问答，证明离线还撑得住

    全程不调模型、不调 embedding —— 慢了就说明「离线」没做对。
    """
    return await svc.offline_drill(db)


# ============ 写接口 ============

@router.post("/absorb")
async def absorb(body: AbsorbTextBody, db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """吸收一段文本为基因"""
    if not body.text.strip():
        raise HTTPException(400, "内容为空")
    r = await svc.absorb_text(
        db, body.text, title=body.title, source_kind=body.source_kind,
        source_ref=body.source_ref, source_title=body.source_title)
    return r


@router.post("/absorb/code")
async def absorb_code(body: AbsorbCodeBody, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """吸收源码：蒸馏成方法与经验基因，原文不留

    给了 path 就从文件库取那个文件（可以再要求把源文件也删掉 ——
    「吸收方法经验后销毁源码」）；不给就用粘过来的 code。
    """
    try:
        if body.path.strip():
            return await svc.absorb_source_file(
                db, body.path.strip(), destroy=body.destroy,
                destroy_file=body.destroy_file)
        if not body.code.strip():
            raise HTTPException(400, "源码为空")
        return await svc.absorb_code(db, body.code, body.filename,
                                      destroy=body.destroy)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"源码蒸馏失败：{e}")


@router.post("/absorb/source")
async def absorb_source(body: AbsorbSourceBody, db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    """吸收文件库里的一份源码：蒸馏成基因，并可销毁源文件

    这是「吸收方法经验后销毁源码」的用户入口：
    先蒸馏成基因、写销毁证明，再删磁盘上的源文件、清掉库里的抽取正文。
    销毁证明没落库就不删 —— 文件没了证据也没了，等于什么都没留下。
    """
    doc = (await db.execute(
        select(Document).where(Document.id == body.document_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "文档不存在")
    if not (doc.path or "").strip():
        raise HTTPException(400, "这份文档没有外置文件（原文在库里），"
                                 "请改用「粘源码」的方式吸收")
    try:
        return await svc.absorb_source_file(
            db, doc.path, destroy=body.destroy,
            destroy_file=body.destroy_file, document_id=doc.id,
            display_name=doc.filename or doc.title or "")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"源码蒸馏失败：{e}")


@router.post("/absorb/all")
async def absorb_all(db: AsyncSession = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    """全库吸收：把文档与业务记录都抽成基因"""
    return await svc.absorb_all(db, principal)


@router.post("/offline")
async def set_offline(body: OfflineBody, db: AsyncSession = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """开关离线模式

    离线模式打开后：检索不走向量通道（要调 embedding 接口），
    问答走直答，写操作被挡住。系统因此可以只带一个养料库包上机运行。
    """
    on = await svc.set_offline(db, body.enabled)
    return {"offline": on, "ready": await _offline_ready(db)}


# ============ 打包 ============

@router.post("/bundle")
async def export_bundle(db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    """导出养料库包（tar.gz），供离线机器使用

    放哪儿：优先 DATA_DIR 下的 dna-bundles/，再退到 /tmp。
    放 DATA_DIR 是因为容器里的 /tmp 是临时的 ——
    养料库包是给人带走的东西，放到临时目录等于没导出。
    """
    try:
        from ..services import dna_bundle
    except Exception as e:
        raise HTTPException(500, f"打包模块不可用：{e}")
    import os
    from datetime import datetime
    from ..config import settings
    out_dir = os.environ.get("DNA_BUNDLE_DIR") or os.path.join(
        settings.data_dir, "dna-bundles")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = "/tmp/dna-bundles"
        os.makedirs(out_dir, exist_ok=True)
    name = f"养料库-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    path = os.path.join(out_dir, name)
    try:
        info = await dna_bundle.export_bundle(db, path)
    except Exception as e:
        raise HTTPException(500, f"导出失败：{e}")
    return {"path": path, "info": info}


@router.post("/bundle/inspect")
async def inspect_bundle(body: ImportBody, db: AsyncSession = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    """检查一个包（完整性、成员、统计）"""
    try:
        from ..services import dna_bundle
        return dna_bundle.inspect_bundle(body.path)
    except FileNotFoundError:
        raise HTTPException(404, "包文件不存在")
    except Exception as e:
        raise HTTPException(400, f"包不可读：{e}")


@router.post("/bundle/import")
async def import_bundle(body: ImportBody, db: AsyncSession = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    """导入一个包（merge 合并 / replace 覆盖）"""
    try:
        from ..services import dna_bundle
    except Exception as e:
        raise HTTPException(500, f"打包模块不可用：{e}")
    try:
        return await dna_bundle.import_bundle(db, body.path, mode=body.mode)
    except FileNotFoundError:
        raise HTTPException(404, "包文件不存在")
    except Exception as e:
        raise HTTPException(400, f"导入失败：{e}")


# ============ 内部 ============

async def _offline_ready(db: AsyncSession) -> dict:
    """断网可用性自检：哪些能力在断网时还在

    这不是「有没有网络」的检测，而是「把网络掐掉之后系统还剩什么」
    的清单 —— 每一项都能独立给出理由。
    """
    from ..services import docindex
    checks = []

    # FTS5：断网后唯一还能用的检索通道
    try:
        rows = (await db.execute(
            select(func.count()).select_from(DocumentChunk))).scalar_one()
        checks.append({"key": "knowledge", "ok": rows > 0,
                       "detail": f"库里有 {rows} 个知识块（原文在本地）"})
    except Exception as e:
        checks.append({"key": "knowledge", "ok": False, "detail": f"读不到知识块：{e}"})

    # 块级索引
    try:
        n = (await db.execute(
            text("select count(*) from chunk_fts"))).scalar_one()
        checks.append({"key": "fts", "ok": n > 0,
                       "detail": f"块级全文索引 {n} 行（断网可用的检索通道）"})
    except Exception as e:
        checks.append({"key": "fts", "ok": False, "detail": f"块级索引不可用：{e}"})

    # 基因库
    try:
        n = (await db.execute(
            select(func.count()).select_from(DnaGene))).scalar_one()
        checks.append({"key": "genes", "ok": n > 0,
                       "detail": f"基因库 {n} 条（可离线直答）"})
    except Exception as e:
        checks.append({"key": "genes", "ok": False, "detail": f"基因库不可用：{e}"})

    # 向量：断网后用不了（查询向量要调 embedding 接口）
    checks.append({"key": "vector", "ok": False,
                   "detail": "语义检索依赖 embedding 接口，断网时关闭（改用全文检索）"})

    # 生成：断网后用不了
    checks.append({"key": "llm", "ok": False,
                   "detail": "答案生成依赖大模型，断网时改为「直答」模式"})

    ok = any(c["ok"] for c in checks if c["key"] in ("fts", "genes"))
    return {"ok": ok, "checks": checks,
            "note": "断网后系统仍可：全文检索 + 结构定位 + 离线直答 + 全部资料原文"}
