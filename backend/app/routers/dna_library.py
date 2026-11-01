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
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import DnaGene, Document, DocumentChunk
from ..services import dna_library as svc
from ..services.auth import Principal, current_principal

router = APIRouter(prefix="/api/dna/library", tags=["dna-library"])


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
        stmt = stmt.where(DnaGene.title.like(f"%{q}%"))
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(DnaGene.kind, DnaGene.id)
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
                 limit: int = Query(5, le=20),
                 db: AsyncSession = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    """离线直答：不调模型，把养料库里的基因与原文端出来

    断网时这条接口就是问答能力的下限 —— 给不出生成式答案，
    但给得出有出处的原文。
    """
    return await svc.answer_offline(db, q, limit=limit)


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
