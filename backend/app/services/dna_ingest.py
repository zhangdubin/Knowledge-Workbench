"""DNA 养料库：后台吸收任务（源码树整体上传 → 解析学习 → 进度可见）

这一版要解决的事：
  以前「吸收源码」只支持单文件：一段粘过来的代码，或者文件库里的一份文件。
  真实场景是**把一整个系统的源码交给它学** —— 几十上百个文件，
  每个都要静态分析、蒸馏成基因、写销毁证明。

  这种活儿放不进一个 HTTP 请求里（几分钟起步，一定超时），
  所以拆成三段：
    1. 上传 → 落到暂存区 → 建一个任务 → **立刻返回任务号**
    2. 后台任务逐文件蒸馏，进度写回数据库（前端轮询就能看到「现在在解析哪个文件」）
    3. 每个文件蒸馏完、写完销毁证明之后，才删暂存区的源码

「一生二，二生三，三生万物」落到代码上是三件事：
  一生二 —— 一份资料（一份代码文件）→ 若干条基因
  二生三 —— 新基因与既有基因建立关联（谁印证谁、谁派生自谁）
  三生万物 —— 基因进入检索/问答/引用，被真正用起来（表达度）
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DnaGap, DnaGene, DnaJob, Document, EntityRecord
from . import dna_distill
from .dna_library import KIND_EXPERIENCE, KIND_INTERFACE, KIND_METHOD, KIND_POLICY

log = logging.getLogger("kb.dna_ingest")

# 一次上传最多收多少文件 / 多少字节
MAX_FILES = 2000
MAX_TOTAL_BYTES = 256 * 1024 * 1024      # 256 MB
MAX_FILE_BYTES = 8 * 1024 * 1024        # 单文件 8 MB
# 明细最多留多少条（数据库里也别堆成日志）
MAX_DETAIL = 200

# 这些目录/文件不学：不是知识，是噪声
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".idea", ".vscode", ".pytest_cache",
    ".mypy_cache", ".next", ".nuxt", "coverage", ".tox", "site-packages",
    ".gradle", "vendor", ".cache", ".DS_Store",
}
SKIP_FILE_SUFFIX = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".pdf", ".docx", ".xlsx", ".pptx", ".db", ".sqlite", ".sqlite3",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".lock", ".map",
}
# 二进制嗅探：前 8 KB 里有 NUL 字节就当二进制
BINARY_SNIFF_BYTES = 8192
BINARY_NUL_RATIO = 0.02


# ============ 小工具 ============

def _now() -> datetime:
    return datetime.now()


def _safe_name(name: str) -> str:
    """把上传里的路径压成安全的相对路径

    上传的 filename 可能带 `../../etc/passwd` 这种路径，
    也可能是 Windows 的 `C:\\Users\\...`。落到磁盘前必须洗一遍。
    """
    name = (name or "").replace("\\", "/")
    parts = []
    for seg in name.split("/"):
        seg = seg.strip()
        if not seg or seg in (".", ".."):
            continue
        seg = re.sub(r"[:*?\"<>|]", "_", seg)
        if seg:
            parts.append(seg)
    return "/".join(parts[-12:]) or "unnamed"


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    if not chunk:
        return False
    return chunk.count(b"\x00") / len(chunk) > BINARY_NUL_RATIO


def _should_skip(rel: str, path: Path) -> str:
    """返回非空字符串表示「要跳过」，空串表示要学"""
    parts = rel.split("/")
    for p in parts[:-1]:
        if p in SKIP_DIRS:
            return f"目录 {p}/ 跳过"
    name = parts[-1] if parts else ""
    if not name:
        return "空文件名"
    if name in SKIP_DIRS:
        return f"{name} 跳过"
    suffix = Path(name).suffix.lower()
    if suffix in SKIP_FILE_SUFFIX:
        return f"{suffix} 类型跳过"
    if name.startswith(".") and name.count(".") == 1 and suffix == "":
        return "隐藏文件跳过"
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return "超过单文件上限"
    except OSError:
        return "读不到文件"
    if _looks_binary(path):
        return "二进制跳过"
    return ""


# ============ 任务序列化 ============

def job_to_dict(job: DnaJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "title": job.title,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "current": job.current,
        "created": job.created,
        "updated": job.updated,
        "skipped": job.skipped,
        "failed": job.failed,
        "bytes_read": job.bytes_read,
        "error": job.error,
        "detail": (job.detail or {}).get("items") or [],
        "percent": (round(job.processed * 100 / job.total, 1)
                    if job.total else (100.0 if job.status == "done" else 0.0)),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


async def _update_job(db: AsyncSession, job_id: int, **fields) -> None:
    job = (await db.execute(
        select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
    if job is None:
        return
    for k, v in fields.items():
        setattr(job, k, v)
    await db.commit()


# ============ 暂存区 ============

def staging_root() -> Path:
    """暂存源码的目录

    放在 data 目录而不是文件库里：
    文件库目录将来可能被整体备份或者被某个预览路由扫到，
    而暂存区里的东西是**还没销毁的源码** ——
    不该出现在任何会被复制、被访问的地方。
    """
    from ..config import settings
    root = Path(settings.data_dir) / "_ingest_staging"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cleanup_staging(older_than_hours: int = 24) -> int:
    """清理陈旧的暂存目录（进程崩了留下的）"""
    root = staging_root()
    n = 0
    cutoff = time.time() - older_than_hours * 3600
    for d in root.iterdir() if root.exists() else []:
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            continue
    return n


# ============ 建任务 ============

async def create_job(db: AsyncSession, *, job_type: str, title: str,
                     total: int, principal: str = "") -> DnaJob:
    job = DnaJob(job_type=job_type, title=title, status="pending",
                 total=total, principal=principal)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


# ============ 后台执行：源码树 ============

async def run_source_tree_job(job_id: int, staged: Path) -> None:
    """后台把一棵源码树蒸馏成基因

    进度写回数据库，前端轮询任务号就能看到「现在在解析哪个文件」。
    """
    from ..database import SessionLocal
    from .dna_library import absorb_code

    async with SessionLocal() as db:
        job = (await db.execute(
            select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
        if job is None:
            return
        job.status = "running"
        job.started_at = _now()
        await db.commit()

    files: list[str] = []
    for p in sorted(staged.rglob("*")):
        if p.is_file():
            files.append(str(p.relative_to(staged)))
    total = len(files)

    langs: dict[str, int] = {}
    per_file: list[dict] = []
    new_gene_ids: list[int] = []
    created = updated = skipped = failed = 0
    bytes_read = 0
    started = time.time()

    try:
        async with SessionLocal() as db:
            for idx, rel in enumerate(files, start=1):
                path = staged / rel
                await _update_job(db, job_id, current=rel, processed=idx - 1,
                                  total=total, created=created, updated=updated,
                                  skipped=skipped, failed=failed,
                                  bytes_read=bytes_read,
                                  detail={"items": per_file[-MAX_DETAIL:]})
                reason = _should_skip(rel, path)
                if reason:
                    skipped += 1
                    per_file.append({"file": rel, "status": "skipped",
                                     "note": reason})
                    continue
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    failed += 1
                    per_file.append({"file": rel, "status": "failed",
                                     "note": f"读失败：{e}"})
                    continue
                bytes_read += len(raw.encode("utf-8", "replace"))
                try:
                    res = await absorb_code(db, raw, rel, destroy=True)
                except Exception as e:      # 单个文件失败不能拖垮整棵树
                    failed += 1
                    log.warning("源码树解析失败 %s：%s", rel, e)
                    per_file.append({"file": rel, "status": "failed",
                                     "note": str(e)[:120]})
                    continue
                # 销毁证明已经落库（absorb_code 内部 commit 了），
                # 现在才可以删这个文件的暂存源码 ——
                # 顺序不能反：文件先没了、证据没写上，等于什么都没留下。
                if res.get("destroyed"):
                    try:
                        path.unlink()
                    except OSError:
                        pass
                lang = res.get("language") or "unknown"
                langs[lang] = langs.get(lang, 0) + 1
                created += int(res.get("created") or 0)
                updated += int(res.get("updated") or 0)
                new_gene_ids.extend(res.get("gene_ids") or [])
                per_file.append({
                    "file": rel,
                    "status": "ok",
                    "language": lang,
                    "lines": res.get("lines"),
                    "genes": res.get("genes"),
                    "created": res.get("created"),
                    "updated": res.get("updated"),
                    "destroyed": bool(res.get("destroyed")),
                })
                # 每 5 个文件落一次盘：进度刷新要看得见，又不能每个文件都写库
                if idx % 5 == 0 or idx == total:
                    await _update_job(db, job_id, current=rel, processed=idx,
                                      total=total, created=created, updated=updated,
                                      skipped=skipped, failed=failed,
                                      bytes_read=bytes_read,
                                      detail={"items": per_file[-MAX_DETAIL:]})

            # ---- 二生三：新基因跟既有基因建立关联 ----
            # 一条基因刚入库时是孤立的；跟老知识挂上关系之后，
            # 它才能被「顺着关系」找到，也才算长进了库里。
            linked = 0
            try:
                linked = await link_similar_genes(db, new_gene_ids)
            except Exception as e:
                log.warning("基因关联失败：%s", e)

            # ---- 树级合成：这套系统整体长什么样 ----
            profile_created = 0
            try:
                jrow = (await db.execute(
                    select(DnaJob).where(DnaJob.id == job_id))).scalar_one_or_none()
                tree_title = (jrow.title if jrow else "") or staged.name
                profile_created = await _absorb_tree_profile(
                    db, staged, files, langs, created, updated, tree_title)
            except Exception as e:
                log.warning("源码树画像合成失败：%s", e)

            # 收尾：把没留下基因的文件也一并销毁，
            # 然后把明细里的「是否已销毁」标准 ——
            # 界面上写「未销毁」而文件其实已经删了，是在骗人。
            shutil.rmtree(staged, ignore_errors=True)
            for item in per_file:
                if item.get("status") == "ok" and not item.get("destroyed"):
                    item["destroyed"] = True
                    item["note"] = item.get("note") or "未蒸馏出基因，已随暂存目录清除"

            await _update_job(
                db, job_id, status="done", processed=total, total=total,
                current="", created=created + profile_created, updated=updated,
                skipped=skipped, failed=failed, bytes_read=bytes_read,
                finished_at=_now(),
                detail={"items": per_file[-MAX_DETAIL:], "links": linked})
    except Exception as e:
        log.exception("源码树任务失败 job=%s：%s", job_id, e)
        async with SessionLocal() as db:
            await _update_job(db, job_id, status="failed", error=str(e)[:500],
                              finished_at=_now(),
                              detail={"items": per_file[-MAX_DETAIL:]})
    finally:
        # 暂存的源码不留：销毁证明已经落库，原文就该走
        shutil.rmtree(staged, ignore_errors=True)
        log.info("源码树任务结束 job=%s 用时 %.1fs 库=%s", job_id,
                 time.time() - started, staged)


async def _absorb_tree_profile(db: AsyncSession, staged: Path, files: list[str],
                                langs: dict[str, int], created: int,
                                updated: int, tree_title: str = "") -> int:
    """把「这套系统整体长什么样」也变成一条基因

    单文件蒸馏得到的是「这个函数怎么做」，
    但真正值钱的是「这套系统由什么组成、入口在哪、依赖哪些模块」——
    这条知识在任何单文件里都看不出来，只能从整棵树上看。
    """
    from .dna_library import upsert_gene

    # 目录结构（两层）
    tops: dict[str, int] = {}
    for rel in files:
        seg = rel.split("/")[0]
        tops[seg] = tops.get(seg, 0) + 1
    tree = "\n".join(f"  {k}/（{v} 个文件）" for k, v in
                     sorted(tops.items(), key=lambda kv: -kv[1])[:12])
    lang_line = "、".join(f"{k} {v} 个" for k, v in
                          sorted(langs.items(), key=lambda kv: -kv[1])[:8]) or "未识别"

    # 入口候选：名字像入口的文件
    entries = [f for f in files
               if Path(f).name.lower() in ("main.py", "app.py", "index.js",
                                          "server.py", "manage.py", "__main__.py",
                                          "cli.py", "run.py", "start.py")]
    entry_line = "、".join(entries[:8]) or "未识别"

    # 清单文件：说明依赖
    manifests = [f for f in files if Path(f).name.lower() in (
        "requirements.txt", "pyproject.toml", "package.json", "go.mod",
        "cargo.toml", "pom.xml", "build.gradle", "composer.json")]
    manifest_line = "、".join(manifests[:8]) or "无"

    content = (
        f"一套系统的源码被整体吸收：{len(files)} 个文件，语言分布 {lang_line}。\n"
        f"顶层目录：\n{tree}\n"
        f"入口候选：{entry_line}\n"
        f"依赖清单：{manifest_line}\n"
        f"本次蒸馏出 {created} 条新基因、{updated} 条更新。\n"
        f"（源码原文已销毁，这里只留结构与统计。）"
    )
    name = tree_title or staged.name
    try:
        _, is_new = await upsert_gene(
            db, kind=KIND_POLICY,
            title=f"源码树画像：{name}",
            content=content,
            tags=["源码树", "系统画像", "吸收"],
            source_kind="code",
            source_ref=f"tree:{hashlib.sha256(name.encode()).hexdigest()[:16]}",
            source_title=name,
            confidence=0.85,
            meta={"tree": True, "files": len(files), "languages": langs,
                  "entries": entries[:8], "manifests": manifests[:8]},
        )
        return 1 if is_new else 0
    except Exception as e:
        log.warning("写入源码树画像失败：%s", e)
        return 0


# ============ 进化账本 ============

async def evolution_snapshot(db: AsyncSession) -> dict:
    """这个系统吸收了多少、自己长出了多少

    「一生二，二生三，三生万物」拆成能看懂的三个数：
      一生二 —— 吸收了多少批资料，生成了多少条基因
      二生三 —— 新基因和既有基因之间建立了多少条关联
      三生万物 —— 知识被真正用起来多少次（被检索、被引用、被直答）
    """
    total = (await db.execute(
        select(func.count()).select_from(DnaGene))).scalar_one() or 0
    active = (await db.execute(
        select(func.count()).select_from(DnaGene)
        .where(DnaGene.status == "active"))).scalar_one() or 0
    by_kind = dict((await db.execute(
        select(DnaGene.kind, func.count()).select_from(DnaGene)
        .where(DnaGene.status == "active").group_by(DnaGene.kind))).all())
    usage = await db.execute(
        select(func.sum(DnaGene.usage_count)).select_from(DnaGene))
    usage = int(usage.scalar_one() or 0)
    # 「二生三」要数的是**真正建立了关联**的基因，
    # 不是「meta 不是空的」—— 几乎每条基因都有 meta，
    # 拿那个当指标，数字会一直虚高。
    linked_rows = (await db.execute(
        select(DnaGene.meta).select_from(DnaGene)
        .where(DnaGene.status == "active"))).scalars().all()
    linked = 0
    for m in linked_rows:
        if isinstance(m, dict) and (m.get("links") or []):
            linked += 1

    docs = await db.execute(
        select(func.count()).select_from(Document)
        .where(Document.deleted_at.is_(None)))
    docs = int(docs.scalar_one() or 0)
    recs = await db.execute(
        select(func.count()).select_from(EntityRecord)
        .where(EntityRecord.deleted_at.is_(None)))
    recs = int(recs.scalar_one() or 0)

    jobs = await db.execute(
        select(func.count()).select_from(DnaJob)
        .where(DnaJob.status == "done"))
    jobs = int(jobs.scalar_one() or 0)

    # 成长曲线：按天统计新建的基因
    since = _now() - timedelta(days=30)
    rows = (await db.execute(
        select(func.date(DnaGene.created_at), func.count())
        .select_from(DnaGene)
        .where(DnaGene.created_at >= since)
        .group_by(func.date(DnaGene.created_at))
        .order_by(func.date(DnaGene.created_at)))).all()
    timeline = [{"day": str(d), "genes": int(n)} for d, n in rows]

    return {
        "totals": {
            "genes_total": total,
            "genes_active": active,
            "by_kind": by_kind,
            "usage_total": int(usage),
            "linked_genes": int(linked),
            "documents": int(docs),
            "records": int(recs),
            "absorb_rounds": int(jobs),
        },
        "generations": [
            {"stage": "一生二", "label": "资料 → 基因",
             "value": int(active),
             "note": f"已吸收 {jobs} 轮，当前在用的基因 {active} 条"},
            {"stage": "二生三", "label": "基因 → 关联",
             "value": int(linked),
             "note": "带关联/出处线索的基因数（图谱能连起来的那些）"},
            {"stage": "三生万物", "label": "基因 → 被使用",
             "value": int(usage),
             "note": "被检索/引用/直答的总次数 —— 知识真的被用起来多少次"},
        ],
        "timeline": timeline,
    }


async def link_similar_genes(db: AsyncSession, gene_ids: list[int],
                              threshold: float = 0.55) -> int:
    """新基因入库后，和既有基因建立关联（二生三）

    判定用「字符集合的 Jaccard 相似度」——
    不用向量：这里是几十条新基因跟几千条老基因比，
    字面重合度够用，而且不用等 embedding。
    """
    if not gene_ids:
        return 0
    new_genes = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(gene_ids)))).scalars().all()
    if not new_genes:
        return 0
    others = (await db.execute(
        select(DnaGene).where(DnaGene.status == "active",
                               DnaGene.id.notin_(gene_ids))
        .limit(2000))).scalars().all()
    linked = 0
    for g in new_genes:
        meta = dict(g.meta or {})
        links = list(meta.get("links") or [])
        a = set(g.content or "")
        if len(a) < 8:
            continue
        for o in others:
            b = set(o.content or "")
            if len(b) < 8:
                continue
            inter = len(a & b)
            if not inter:
                continue
            sim = inter / len(a | b)
            if sim >= threshold:
                links.append({"id": o.id, "title": o.title[:60],
                              "kind": o.kind, "sim": round(sim, 3)})
        if links:
            links = sorted(links, key=lambda x: -x["sim"])[:12]
            meta["links"] = links
            g.meta = meta
            linked += len(links)
    await db.commit()
    return linked


# ============ 知识缺口：系统答不上来的问题 ============

# 模型说「没有」时的几种说法（中文模型最常见的就是这几类）
_NO_ANSWER_MARKERS = (
    "资料里没有", "资料中没有", "上下文中没有", "上下文没有",
    "语料里没有", "没有提到", "没有相关信息", "没有记载",
    "无法从资料中", "找不到相关",
)


def looks_like_no_answer(answer: str) -> bool:
    """答案是不是「资料里没有」

    只认「明确说没有」的说法，不认「答案里没有某个词」——
    后者会把正常答案也判成缺口，缺口列表就废了。
    """
    t = (answer or "").strip()
    if not t:
        return True
    return any(m in t for m in _NO_ANSWER_MARKERS)


async def record_gap(db: AsyncSession, question: str,
                     answer: str = "") -> DnaGap | None:
    """记一条缺口（同一个问题问多次只算一条，asked +1）"""
    import hashlib
    q = (question or "").strip()
    if not q:
        return None
    fp = hashlib.sha256(q.encode("utf-8", "replace")).hexdigest()
    row = (await db.execute(
        select(DnaGap).where(DnaGap.fingerprint == fp))).scalar_one_or_none()
    if row is not None:
        row.asked = (row.asked or 0) + 1
        row.last_asked_at = _now()
        if row.status == "filled":
            # 又问不出来了 → 缺口重新打开
            row.status = "open"
        await db.commit()
        return row
    row = DnaGap(question=q[:512], fingerprint=fp, asked=1, status="open")
    db.add(row)
    await db.commit()
    return row


async def close_matching_gaps(db: AsyncSession, question: str,
                              filled_by: str = "") -> int:
    """这个问题现在答得出来了 → 关掉对应的缺口

    这就是「进化闭环」的那一下：补上的知识让一个老缺口消失。
    """
    import hashlib
    q = (question or "").strip()
    if not q:
        return 0
    fp = hashlib.sha256(q.encode("utf-8", "replace")).hexdigest()
    row = (await db.execute(
        select(DnaGap).where(DnaGap.fingerprint == fp))).scalar_one_or_none()
    if row is None or row.status == "filled":
        return 0
    row.status = "filled"
    row.filled_by = filled_by
    row.note = "补上知识后已能回答"
    row.updated_at = _now()
    await db.commit()
    return 1


async def gap_summary(db: AsyncSession) -> dict:
    """缺口概况：还缺什么、补了多少"""
    open_rows = (await db.execute(
        select(DnaGap).where(DnaGap.status == "open")
        .order_by(DnaGap.asked.desc(), DnaGap.last_asked_at.desc())
        .limit(50))).scalars().all()
    filled = await db.execute(
        select(func.count()).select_from(DnaGap).where(DnaGap.status == "filled"))
    total = await db.execute(select(func.count()).select_from(DnaGap))
    return {
        "open": [
            {"id": g.id, "question": g.question, "asked": g.asked,
             "last_asked_at": g.last_asked_at.isoformat() if g.last_asked_at else None}
            for g in open_rows
        ],
        "open_count": len(open_rows),
        "filled_count": int(filled.scalar_one() or 0),
        "total_count": int(total.scalar_one() or 0),
    }


# ============ 自动喂养 ============

AUTO_FEED_KEY = "dna.auto_feed"


async def get_auto_feed(db: AsyncSession) -> dict:
    import json
    from ..models import SysMeta
    raw = (await db.execute(
        select(SysMeta).where(SysMeta.key == AUTO_FEED_KEY))).scalar_one_or_none()
    cfg = {}
    if raw is not None and raw.value:
        try:
            cfg = dict(json.loads(raw.value))
        except Exception:
            cfg = {}
    cfg.setdefault("enabled", False)
    cfg.setdefault("interval_minutes", 60)
    cfg.setdefault("last_run_at", None)
    cfg.setdefault("last_result", None)
    return cfg


async def set_auto_feed(db: AsyncSession, *, enabled: bool | None = None,
                        interval_minutes: int | None = None) -> dict:
    import json
    from ..models import SysMeta
    cfg = await get_auto_feed(db)
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if interval_minutes is not None:
        cfg["interval_minutes"] = max(5, min(int(interval_minutes), 24 * 60))
    row = (await db.execute(
        select(SysMeta).where(SysMeta.key == AUTO_FEED_KEY))).scalar_one_or_none()
    if row is None:
        row = SysMeta(key=AUTO_FEED_KEY, value="")
        db.add(row)
    row.value = json.dumps(cfg, ensure_ascii=False)
    await db.commit()
    return cfg


async def save_auto_feed(db: AsyncSession, cfg: dict) -> dict:
    """把整份配置写回去（不是只改一两个字段）

    set_auto_feed 是「改字段」的语义；
    但自动喂养跑完要把 last_run_at / last_result 一起写回去 ——
    如果改字段的接口每次都重新从库里读一遍再写，
    这两个字段就会被自己的修改冲掉（改了等于没改）。
    """
    import json
    from ..models import SysMeta
    row = (await db.execute(
        select(SysMeta).where(SysMeta.key == AUTO_FEED_KEY))).scalar_one_or_none()
    if row is None:
        row = SysMeta(key=AUTO_FEED_KEY, value="")
        db.add(row)
    row.value = json.dumps(cfg, ensure_ascii=False)
    await db.commit()
    return cfg


async def auto_feed_once(db: AsyncSession) -> dict:
    """一轮自动喂养：把新出现/有变化的资料吸收成基因

    「不断喂养、不断自主进化」落到代码上就是这个：
    每隔一段时间扫一遍资料，有新的就吸收，
    系统里的可复用知识就自己长出来一点。
    """
    from .dna_library import absorb_all
    cfg = await get_auto_feed(db)
    # 定时器每 5 分钟问一次，但用户设的间隔可能更长 ——
    # 没到点就直接跳过，别把「每 5 分钟吸一次」当成用户的选择。
    if cfg.get("last_run_at"):
        try:
            last = datetime.fromisoformat(cfg["last_run_at"])
            gap = (_now() - last).total_seconds() / 60
            if gap < float(cfg.get("interval_minutes") or 60):
                return {"skipped": True, "reason": "还没到间隔"}
        except Exception:
            pass
    try:
        res = await absorb_all(db)
        cfg = await get_auto_feed(db)
        cfg["last_run_at"] = _now().isoformat()
        # 只留摘要：last_result 整个塞进元数据表，
        # 里面可能有几十个文档的明细，越滚越大
        cfg["last_result"] = {
            "documents": res.get("documents"),
            "records": res.get("records"),
            "genes": res.get("genes"),
            "created": res.get("created"),
        }
        await save_auto_feed(db, cfg)
        return res
    except Exception as e:
        log.warning("自动喂养失败：%s", e)
        return {"error": str(e)[:200]}
