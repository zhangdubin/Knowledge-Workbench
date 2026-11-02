"""学以致用：把高分基因落成**能直接拿走的产出**，并用「用过」反过来校准分数

知识库最容易停在「存得下」：文档进了库、基因抽出来了、检索也能命中，
但没有任何一条知识**变成过代码、变成过方案、变成过任务**。
存了一万条却一条没用上，等于没学。

这一层补的就是最后一段：

    基因（知道什么）
      ↓ extract_asset        抽取可执行部分
    资产（能直接拿走用什么）
      ↓ use_asset            记录：哪个项目、什么任务、成没成功
    使用事件（证据链）
      ↓ 反馈
    评分（表达度 ↑ 置信度 ↑ 或 ↓）

闭环里最要紧的一条：**「用过」必须真的改变分数**。
否则「学 → 用 → 更准」只是一句口号。这里的做法是：
    - 复用成功 → 置信度的「复用成功率」上升、表达度的「被复用度」上升
    - 复用失败 → 置信度按次扣分（负反馈真的扣）
    - 人工纠正 → 置信度按次扣分

而且这些不是「口头反馈」，是**落库的事件**（dna_asset_use），
谁在哪个项目用了哪条知识、结果如何，都查得到。
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DnaAsset, DnaAssetUse, DnaGene

log = logging.getLogger("kb.dna_asset")

# 资产种类
ASSET_CODE = "code_snippet"
ASSET_CONTRACT = "api_contract"
ASSET_CHECKLIST = "checklist"
ASSET_NOTE = "note"
ASSET_KINDS = (ASSET_CODE, ASSET_CONTRACT, ASSET_CHECKLIST, ASSET_NOTE)

ASSET_KIND_LABEL = {
    ASSET_CODE: "代码片段",
    ASSET_CONTRACT: "接口契约",
    ASSET_CHECKLIST: "操作步骤",
    ASSET_NOTE: "要点",
}

# 一次抽取最多产出多少条资产：一条基因里可能塞了十几段代码，
# 全抽出来资产表就变成垃圾场
MAX_ASSETS_PER_GENE = 3


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _asset_uid(gene_id: int, kind: str, content: str) -> str:
    """资产的稳定身份：来源基因 + 种类 + 内容指纹

    为什么要带 gene_id：同一段代码在两条基因里各出现一次，
    它们是两次不同的「学习成果」，不该合成一条。
    """
    fp = hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:24]
    return hashlib.sha1(f"{gene_id}:{kind}:{fp}".encode("utf-8")).hexdigest()


# ============ 从基因里抽资产（纯函数，可单测） ============

# 围栏代码块：\x60\x60\x60lang ... \x60\x60\x60
# 用 \x60 而不是直接写反引号，是为了让正则本身在源码里一目了然。
_FENCE_RE = re.compile(r"\x60\x60\x60([A-Za-z0-9_+-]*)\n(.*?)\x60\x60\x60", re.S)
# 表格行：| 名称 | 说明 |
_TABLE_ROW_RE = re.compile(r"^\s*\|?\s*([^|\n]+?)\s*\|\s*([^|\n]*?)\s*\|", re.M)
# 「字段：说明」「字段 = 说明」「--field 说明」
_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\x60)?([A-Za-z_][\w.\-]{1,40})(?:\x60)?\s*[:：=]\s*(.{1,120})$", re.M)
# 步骤行：1. xxx / 第一步 / - xxx
_STEP_RE = re.compile(
    r"^\s*(?:(\d+)[.、)]\s*|第[一二三四五六七八九十]+步[：:、]?\s*|[-*]\s+)(.{4,200})$", re.M)


def extract_code_snippet(content: str, language: str = "") -> dict | None:
    """从基因正文里抽一段可复制的代码

    优先取围栏代码块；没有围栏时，看正文本身是不是代码
    （含 def/class/function/import 之类）。
    """
    text = content or ""
    m = _FENCE_RE.search(text)
    if m:
        code = m.group(2).strip()
        lang = (m.group(1) or language or "").strip()
        if len(code) >= 20:
            return {"kind": ASSET_CODE, "content": code[:4000], "language": lang}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    code_like = sum(1 for ln in lines
                    if re.match(r"^\s*(def |class |function |import |from |return |"
                                r"public |private |func |const |let |var )", ln))
    if code_like >= 2 and code_like / len(lines) >= 0.4:
        return {"kind": ASSET_CODE, "content": text[:4000],
                "language": language or ""}
    return None


def extract_api_contract(content: str) -> dict | None:
    """从基因正文里抽接口契约：有哪些字段、字段是什么

    抽不出来就返回 None —— 接口契约宁缺毋滥：
    猜出来的字段名比没有字段更害人。
    """
    text = content or ""
    fields: list[dict] = []
    seen: set[str] = set()
    for m in _TABLE_ROW_RE.finditer(text):
        name = (m.group(1) or "").strip()
        desc = (m.group(2) or "").strip()
        name = re.sub(r"^[\s|:-]+|[\s|:-]+$", "", name)
        if not name or len(name) > 40 or name in seen:
            continue
        if name in ("字段", "参数", "名称", "Name", "Field", "参数名"):
            continue
        seen.add(name)
        fields.append({"name": name, "desc": desc[:120],
                       "required": bool(re.search(r"必填|required|必须", desc, re.I))})
    if len(fields) < 2:
        fields = []
        for m in _FIELD_RE.finditer(text):
            name = (m.group(1) or "").strip()
            desc = (m.group(2) or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            fields.append({"name": name, "desc": desc[:120],
                           "required": bool(re.search(r"必填|required|必须", desc, re.I))})
    if len(fields) < 2:
        return None
    body = "\n".join(
        f"- {f['name']}：{f['desc'] or '（无说明）'}"
        + ("（必填）" if f["required"] else "")
        for f in fields[:40])
    return {"kind": ASSET_CONTRACT, "content": body, "language": "",
            "fields": fields[:40]}


def extract_checklist(content: str) -> dict | None:
    """从基因正文里抽操作步骤：照着做的那几步

    只认「有序的短句」：一行讲一件事，超过 200 字的是散文不是步骤。
    """
    text = content or ""
    steps: list[str] = []
    for m in _STEP_RE.finditer(text):
        step = (m.group(2) or "").strip()
        if not step or len(step) > 200:
            continue
        if step not in steps:
            steps.append(step)
    if len(steps) < 2:
        return None
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps[:30], start=1))
    return {"kind": ASSET_CHECKLIST, "content": body, "language": "",
            "steps": steps[:30]}


def extract_note(content: str, summary: str = "") -> dict | None:
    """兜底：实在抽不出结构，就留一段要点"""
    text = (content or "").strip()
    if len(text) < 20:
        return None
    return {"kind": ASSET_NOTE, "content": text[:2000], "language": ""}


def extract_assets(gene: DnaGene, summary: str = "") -> list[dict]:
    """从一条基因里抽出候选资产（纯函数）

    顺序有讲究：先抽最「可执行」的（代码、契约、步骤），
    抽不出来才退到要点 —— 一条方法基因既含代码又含解释时，
    代码才是那个能直接拿走用的东西。
    """
    content = gene.content or ""
    meta = gene.meta or {}
    out: list[dict] = []
    seen_kinds: set[str] = set()
    for fn, kwargs in (
        (extract_code_snippet, {"language": str(meta.get("language") or "")}),
        (extract_api_contract, {}),
        (extract_checklist, {}),
    ):
        try:
            item = fn(content, **kwargs)
        except Exception as e:      # 抽取器不该拖垮整条流水线
            log.warning("资产抽取失败 gene=%s：%s", gene.uid, e)
            item = None
        if item and item["kind"] not in seen_kinds:
            out.append(item)
            seen_kinds.add(item["kind"])
        if len(out) >= MAX_ASSETS_PER_GENE:
            return out
    if not out:
        note = extract_note(content, summary)
        if note:
            out.append(note)
    return out


# ============ 落库 ============

async def create_assets_from_gene(db: AsyncSession, gene: DnaGene, *,
                                 commit: bool = True) -> list[DnaAsset]:
    """把一条基因落成资产（幂等：同一基因同一份内容只落一条）"""
    created: list[DnaAsset] = []
    for item in extract_assets(gene):
        uid = _asset_uid(gene.id, item["kind"], item["content"])
        row = (await db.execute(
            select(DnaAsset).where(DnaAsset.uid == uid))).scalar_one_or_none()
        if row is None:
            row = DnaAsset(
                uid=uid, kind=item["kind"],
                title=(gene.title or "（无标题）")[:200],
                content=item["content"],
                language=item.get("language") or "",
                gene_id=gene.id,
                source_kind=gene.source_kind or "",
                source_title=gene.source_title or "",
                meta={"fields": item.get("fields") or [],
                      "steps": item.get("steps") or [],
                      "gene_uid": gene.uid,
                      "gene_title": gene.title},
                created_at=_now(), updated_at=_now())
            db.add(row)
            created.append(row)
        else:
            # 内容变了就更新（基因被重新吸收的情况）
            if row.content != item["content"]:
                row.content = item["content"]
                row.updated_at = _now()
    if commit:
        await db.commit()
    return created


async def create_assets_from_genes(db: AsyncSession, gene_ids: list[int], *,
                                   commit: bool = True) -> list[DnaAsset]:
    """批量落资产（从一批高分基因里挑可执行的那些）"""
    ids = [int(i) for i in (gene_ids or []) if i]
    if not ids:
        return []
    genes = (await db.execute(
        select(DnaGene).where(DnaGene.id.in_(ids)))).scalars().all()
    out: list[DnaAsset] = []
    for g in genes:
        out.extend(await create_assets_from_gene(db, g, commit=False))
    if commit:
        await db.commit()
    return out


async def list_assets(db: AsyncSession, *, gene_id: int | None = None,
                      kind: str = "", limit: int = 50,
                      offset: int = 0) -> dict:
    """资产清单"""
    stmt = select(DnaAsset)
    if gene_id:
        stmt = stmt.where(DnaAsset.gene_id == gene_id)
    if kind:
        stmt = stmt.where(DnaAsset.kind == kind)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(DnaAsset.use_count.desc(), DnaAsset.id.desc())
        .offset(offset).limit(limit))).scalars().all()
    return {"items": [serialize_asset(a) for a in rows],
            "total": int(total or 0), "limit": limit, "offset": offset}


def serialize_asset(a: DnaAsset) -> dict:
    return {
        "id": a.id, "uid": a.uid, "kind": a.kind,
        "kind_label": ASSET_KIND_LABEL.get(a.kind, a.kind),
        "title": a.title, "content": a.content,
        "language": a.language or "",
        "gene_id": a.gene_id,
        "source_kind": a.source_kind or "",
        "source_title": a.source_title or "",
        "use_count": a.use_count or 0,
        "use_success": a.use_success or 0,
        "use_fail": a.use_fail or 0,
        "last_project": a.last_project or "",
        "last_used_at": a.last_used_at.isoformat() if a.last_used_at else None,
        "meta": a.meta or {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


async def use_asset(db: AsyncSession, asset_id: int, *, project: str = "",
                    task: str = "", outcome: str = "unknown",
                    note: str = "", actor: str = "",
                    commit: bool = True) -> dict:
    """记录一次「资产被用了」，并让源基因的分数跟着变

    这是整个闭环的关键一步：
      - 写一条使用事件（证据链：谁、在哪个项目、什么任务、结果如何）
      - 资产的计数 +1
      - 源基因的使用计数与成功/失败计数跟着变
      - 源基因重算评分 —— **成功加分、失败扣分**

    outcome 只认三种：success / fail / unknown。
    unknown 表示「用了但还没结果」，它只增加被复用度，不动成功率。
    """
    asset = (await db.execute(
        select(DnaAsset).where(DnaAsset.id == asset_id))).scalar_one_or_none()
    if asset is None:
        raise ValueError("资产不存在")
    outcome = (outcome or "unknown").strip().lower()
    if outcome not in ("success", "fail", "unknown"):
        outcome = "unknown"
    now = _now()
    ev = DnaAssetUse(
        asset_id=asset.id, gene_id=asset.gene_id,
        project=(project or "")[:128], task=(task or "")[:256],
        outcome=outcome, note=(note or "")[:2000], actor=(actor or "")[:64],
        used_at=now, created_at=now)
    db.add(ev)
    asset.use_count = (asset.use_count or 0) + 1
    if outcome == "success":
        asset.use_success = (asset.use_success or 0) + 1
    elif outcome == "fail":
        asset.use_fail = (asset.use_fail or 0) + 1
    asset.last_project = (project or "")[:128]
    asset.last_used_at = now
    asset.updated_at = now
    if commit:
        await db.commit()
    # 反馈到源基因：这一步让「学 → 用 → 更准」成立
    score_change = None
    if asset.gene_id:
        from . import dna_library, dna_score
        try:
            # 被复用度也要涨：资产被用 = 这条基因被用
            await dna_library.mark_gene_used(db, [asset.gene_id])
            success = True if outcome == "success" else (
                False if outcome == "fail" else None)
            score_change = await dna_score.record_use(
                db, [asset.gene_id], success=success, commit=True)
        except Exception as e:
            log.warning("资产使用反馈到基因失败 asset=%s：%s", asset.uid, e)
    return {
        "asset": serialize_asset(asset),
        "event": {"id": ev.id, "asset_id": ev.asset_id, "gene_id": ev.gene_id,
                  "project": ev.project, "task": ev.task,
                  "outcome": ev.outcome, "note": ev.note,
                  "actor": ev.actor,
                  "used_at": ev.used_at.isoformat() if ev.used_at else None},
        "score": score_change,
    }


async def list_uses(db: AsyncSession, *, asset_id: int | None = None,
                    gene_id: int | None = None, limit: int = 50) -> dict:
    """使用事件流水（证据链）"""
    stmt = select(DnaAssetUse)
    if asset_id:
        stmt = stmt.where(DnaAssetUse.asset_id == asset_id)
    if gene_id:
        stmt = stmt.where(DnaAssetUse.gene_id == gene_id)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(DnaAssetUse.id.desc()).limit(limit))).scalars().all()
    return {
        "items": [{
            "id": r.id, "asset_id": r.asset_id, "gene_id": r.gene_id,
            "project": r.project, "task": r.task, "outcome": r.outcome,
            "note": r.note, "actor": r.actor,
            "used_at": r.used_at.isoformat() if r.used_at else None,
        } for r in rows],
        "total": int(total or 0),
    }


async def asset_stats(db: AsyncSession) -> dict:
    """产出层的统计：学以致用到底发生了没有"""
    total = (await db.execute(
        select(func.count()).select_from(DnaAsset))).scalar_one() or 0
    used = (await db.execute(
        select(func.count()).select_from(DnaAsset)
        .where(DnaAsset.use_count > 0))).scalar_one() or 0
    events = (await db.execute(
        select(func.count()).select_from(DnaAssetUse))).scalar_one() or 0
    ok = (await db.execute(
        select(func.count()).select_from(DnaAssetUse)
        .where(DnaAssetUse.outcome == "success"))).scalar_one() or 0
    bad = (await db.execute(
        select(func.count()).select_from(DnaAssetUse)
        .where(DnaAssetUse.outcome == "fail"))).scalar_one() or 0
    by_kind = dict((await db.execute(
        select(DnaAsset.kind, func.count()).select_from(DnaAsset)
        .group_by(DnaAsset.kind))).all())
    return {
        "assets": int(total), "used": int(used), "events": int(events),
        "success": int(ok), "fail": int(bad),
        "by_kind": by_kind,
        # 「学以致用率」：有多少知识真的变成了产出
        "reuse_rate": round(int(used) / int(total), 3) if total else 0.0,
        "success_rate": round(int(ok) / int(events), 3) if events else 0.0,
    }
