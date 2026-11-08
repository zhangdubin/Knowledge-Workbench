"""笔记相关的特殊路由：双链、反向链接、按规范排版

**排版为什么放在这里，而不是 /api/ai/**

《笔记 UI 排版规范》是一套**确定性规则**（见 services/note_format.py）：
标题要配 emoji、表格表头要加粗、凭证要遮盖、front-matter 要合规。
这些不需要模型，也不该消耗 token。

之前只有一个 `/api/ai/beautify-layout`，挂在 AI 授权后面 ——
没配 AI Key（或没给这个用户 AI 权限）的部署里，「排版」整条路是断的。
可是「把笔记排整齐」是笔记的基础能力，不是 AI 功能。
所以这里给纯规则版的接口，AI 只做增强（写摘要、判断语义），不做前置条件。
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import EntityRecord, EntityType
from ..services import ai as ai_svc
from ..services import note_format as fmt_svc
from ..services import note_profile as profile_svc
from ..services import record as record_svc
from ..services import wikilink as svc
from ..services.auth import Principal, current_principal, ensure_model

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _need_note_write(principal: Principal) -> None:
    """双链同步属于写笔记，按 note 模型的写权限判断"""
    ensure_model(principal, "note", "write")


# ---------------------------------------------------------------------------
# 按规范排版（纯规则，不依赖 AI）
# ---------------------------------------------------------------------------

class FormatIn(BaseModel):
    content: str = ""
    title: str = ""
    tags: list[str] = []
    scope: str | None = None
    status: str | None = None
    source: str = "human"
    # AI 结构化（TL;DR / 风险表 / 目标表 / 时间线）；没配 AI 时自动退回规则
    use_ai: bool = False
    # 笔记类型：只影响模板骨架与默认敏感度，不影响已有内容的排版
    profile: str = ""
    # None = 自动：原文已有 front-matter 或给了标题时才写
    frontmatter: bool | None = None
    add_summary: bool = True
    mask_secrets: bool = True
    toc: bool | None = None
    meta_card: bool = True
    fence_commands: bool = True


class TemplateIn(BaseModel):
    title: str = ""
    tags: list[str] = []
    # 类型：pentest-record / troubleshoot / tutorial / generic（见 note_profile）
    profile: str = "generic"
    scope: str = "concept"
    status: str = "draft"
    source: str = "human"
    summary: str = ""
    related: list[str] = []
    sensitivity: str = ""


async def _related_candidates(
    db: AsyncSession, *, exclude_id: int | None = None, limit: int = 200,
) -> list[dict]:
    """候选笔记（给「相关」链接用）

    只取最近 200 篇的标题/标签/正文前 400 字 —— 全量扫在几百篇时还行，
    上千篇就该上向量检索了（这里先不做，避免给排版加一个重依赖）。
    """
    tid = (await db.execute(
        select(EntityType.id).where(EntityType.key == "note")
    )).scalar_one_or_none()
    if not tid:
        return []
    q = (select(EntityRecord)
         .where(EntityRecord.entity_type_id == tid, EntityRecord.deleted_at.is_(None))
         .order_by(EntityRecord.updated_at.desc())
         .limit(limit))
    rows = (await db.execute(q)).scalars().all()
    out = []
    for r in rows:
        if exclude_id and r.id == exclude_id:
            continue
        data = r.data or {}
        out.append({
            "id": r.id,
            "title": str(data.get("title") or ""),
            "tags": [str(t) for t in (data.get("tags") or [])],
            "text": str(data.get("content") or "")[:400],
        })
    return out


def _pick_related(title: str, content: str, tags: list[str], candidates: list[dict]) -> list[str]:
    """按「标签重合 → 标题词重合 → 正文词重合」打分，取前 5

    没有模型也能做出「相关笔记」：同一批笔记里标签和关键词重的，
    大概率就是同一系列。分数太低（几乎不相关）的不硬塞 —— 相关区里
    塞一篇无关的笔记，比空着更糟。
    """
    import re as _re

    blob = f"{title}\n{content}".lower()
    words = {w for w in _re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,6}", blob)}
    tagset = {t.lower() for t in tags}
    scored: list[tuple[float, str]] = []
    for c in candidates:
        if not c["title"] or c["title"].strip() == title.strip():
            continue
        score = 0.0
        score += 3 * len(tagset & {t.lower() for t in c["tags"]})
        ctitle = c["title"].lower()
        score += 2 * len([w for w in words if len(w) >= 2 and w in ctitle])
        cbody = c["text"].lower()
        score += 1 * len([w for w in words if len(w) >= 3 and w in cbody])
        if score >= 4:
            scored.append((score, c["title"]))
    scored.sort(key=lambda x: -x[0])
    return [t for _s, t in scored[:5]]


def _stats(text: str) -> dict:
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]
    return {
        "chars": len(text or ""),
        "lines": len(lines),
        "h2": sum(1 for ln in lines if ln.startswith("## ")),
        "tables": sum(1 for ln in lines if ln.startswith("|")),
        "code_blocks": (text or "").count("```") // 2,
        "secrets": (text or "").count("secret-toggle"),
    }


@router.post("/format")
async def format_content(
    payload: FormatIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """按《笔记 UI 排版规范》排一段正文（不落库）

    返回排版后的正文 + 「改了哪几处」的报告：
    前端拿它做**预览**，用户看过再决定要不要用。
    自动排版最怕的就是「偷偷改了还改坏了」，所以默认给看。
    """
    _need_note_write(principal)
    if not (payload.content or "").strip():
        return {"text": "", "changes": [], "report": {}, "stats": _stats("")}

    # AI 结构化：TL;DR / 风险表 / 目标表 / 时间线（没配 AI 时自动为空）
    structure: dict = {}
    ai_used = False
    if payload.use_ai:
        try:
            structure = await ai_svc.structure_note(payload.content)
            ai_used = bool(structure.get("tldr") or structure.get("risks")
                           or structure.get("targets") or structure.get("timeline"))
        except Exception:
            structure = {}

    # 相关笔记：拿现有笔记打一次分
    related: list[str] = []
    try:
        candidates = await _related_candidates(db)
        related = _pick_related(
            payload.title, fmt_svc.core_text(payload.content), payload.tags, candidates,
        )
    except Exception:
        related = []

    text, report = fmt_svc.format_note_with_report(
        payload.content,
        title=payload.title,
        tags=payload.tags,
        scope=payload.scope,
        status=payload.status,
        source=payload.source,
        frontmatter=payload.frontmatter,
        add_summary=payload.add_summary,
        mask_secrets=payload.mask_secrets,
        toc=payload.toc,
        meta_card=payload.meta_card,
        fence_commands=payload.fence_commands,
        related=related,
        structure=structure,
    )
    return {
        "text": text,
        "report": report,
        "changes": _describe_changes(report),
        "elements": fmt_svc.element_audit(text),
        "stats": _stats(text),
        "ai": ai_used,
        "structure": structure if ai_used else {},
        "related": related,
    }


def _describe_changes(report: dict) -> list[dict]:
    """把计数翻译成人话（前端直接列出来给用户看）"""
    by_key = {r["report_key"]: r for r in fmt_svc.rule_catalog()}
    out = []
    for key, n in sorted(report.items()):
        meta = by_key.get(key)
        if not meta:
            continue
        title = meta["title"]
        if key == "secrets_masked":
            title = f"遮盖了 {n} 处凭证"
        elif key in ("table_header_bold", "table_cells_normalized"):
            title = f"表格处理 {n} 处"
        elif key == "h2_emoji":
            title = f"{n} 个章节标题补了 emoji"
        elif key == "code_lang":
            title = f"{n} 个代码块补了语言标识"
        elif key == "commands_fenced":
            title = f"{n} 段命令行包成代码块"
        elif key == "bare_heading":
            title = f"{n} 个裸标题提升成二级标题"
        elif key == "frontmatter_normalized":
            title = "front-matter 规范化（顺序 / 引号 / 日期）"
        elif key == "frontmatter_added":
            title = "补上了 front-matter"
        elif key == "abstract_added":
            title = "补了顶部摘要卡"
        elif key == "meta_card":
            title = "补了元信息卡"
        elif key == "toc_added":
            title = "生成了目录"
        elif key == "quote_to_callout":
            title = f"{n} 处引用转成 callout"
        elif key == "hr_spacing":
            title = f"{n} 处分割线补齐留白"
        elif key == "paragraphs_merged":
            title = f"合并了 {n} 组零散短段落"
        elif key == "empty_sections_dropped":
            title = f"删掉 {n} 个空章节"
        elif key == "code_block_restored":
            title = f"还原了 {n} 段被复制弄丢的代码块"
        elif key == "cn_heading":
            title = f"{n} 个「一、二、」标题提升成章节"
        elif key == "tsv_table":
            title = f"{n} 处制表符表格还原成表格"
        elif key == "risk_callout":
            title = f"{n} 条发现变成风险卡片"
        elif key == "fix_checklist":
            title = "修复建议整理成待办清单"
        elif key == "banner_added":
            title = "加了敏感度横幅"
        elif key == "structure_sections":
            title = "生成了目标 / 风险 / 时间线速览表"
        elif key == "dates_resolved":
            title = f"{n} 个日期从表达式落成实际值"
        out.append({"key": key, "count": n, "section": meta["section"], "title": title})
    return out


@router.get("/profiles")
async def note_profiles(principal: Principal = Depends(current_principal)):
    """笔记类型清单（新建时选类型 → 出一份要素齐全的骨架）"""
    ensure_model(principal, "note", "read")
    return {"profiles": profile_svc.list_profiles()}


@router.get("/format/rules")
async def format_rules(principal: Principal = Depends(current_principal)):
    """排版规则清单 —— 规范条目 ↔ 我们实际做了没有

    前端把这张表当「排版说明」展示：用户看得见规则，
    才不会觉得「自动排版」是个黑箱。
    """
    ensure_model(principal, "note", "read")
    return {"version": fmt_svc.SPEC_VERSION, "rules": fmt_svc.rule_catalog()}


@router.post("/template")
async def note_template(
    payload: TemplateIn,
    principal: Principal = Depends(current_principal),
):
    """新建笔记的模板（纯规则，不再要求 AI 授权）

    和 Obsidian 里「从模板新建」是一回事：一建出来就是规范形态。
    """
    _need_note_write(principal)
    profile = payload.profile or payload.scope or "generic"
    text = profile_svc.skeleton(
        profile,
        title=payload.title,
        tags=payload.tags,
        sensitivity=payload.sensitivity,
        related=payload.related,
    )
    return {
        "text": text,
        "profile": profile,
        "elements": fmt_svc.element_audit(text),
        "stats": _stats(text),
    }


async def _note_record(db: AsyncSession, record_id: int) -> EntityRecord:
    rec = await db.get(EntityRecord, record_id)
    if not rec or rec.deleted_at:
        raise HTTPException(404, "笔记不存在")
    et = await db.get(EntityType, rec.entity_type_id)
    if not et or et.key != "note":
        raise HTTPException(400, "这条记录不是笔记")
    return rec


@router.post("/{record_id}/format")
async def format_record(
    record_id: int,
    payload: dict | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """把已存在的一篇笔记按规范重排，并落库

    只动 content（正文里含 front-matter），不动分组/父笔记这些结构字段 ——
    排版是「整容」，不是「搬家」。
    """
    _need_note_write(principal)
    rec = await _note_record(db, record_id)
    data = dict(rec.data or {})
    content = str(data.get("content") or "")
    if not content.strip():
        raise HTTPException(400, "这篇笔记没有正文，没什么可排的")

    opts = payload or {}
    before = content

    structure: dict = {}
    ai_used = False
    if opts.get("use_ai"):
        try:
            structure = await ai_svc.structure_note(content)
            ai_used = bool(structure.get("tldr") or structure.get("risks")
                           or structure.get("targets") or structure.get("timeline"))
        except Exception:
            structure = {}

    related: list[str] = []
    try:
        candidates = await _related_candidates(db, exclude_id=record_id)
        related = _pick_related(
            str(data.get("title") or ""), fmt_svc.core_text(content),
            list(data.get("tags") or []), candidates,
        )
    except Exception:
        related = []

    text, report = fmt_svc.format_note_with_report(
        content,
        title=str(data.get("title") or ""),
        tags=list(data.get("tags") or []),
        scope=opts.get("scope"),
        status=opts.get("status"),
        source=opts.get("source") or "human",
        mask_secrets=bool(opts.get("mask_secrets", True)),
        fence_commands=bool(opts.get("fence_commands", True)),
        meta_card=bool(opts.get("meta_card", True)),
        add_summary=bool(opts.get("add_summary", True)),
        related=related,
        structure=structure,
    )
    if not report:
        return {
            "ok": True, "changed": False, "text": text,
            "report": {}, "changes": [], "stats": _stats(text),
        }

    data["content"] = text
    # 标题空着而正文有 H1 → 顺手补上（Obsidian 里文件名就是首行）
    if not str(data.get("title") or "").strip():
        first_h1 = next((ln.lstrip("# ").strip() for ln in text.split("\n")
                         if ln.startswith("# ")), "")
        if first_h1:
            data["title"] = fmt_svc._strip_emoji(first_h1)

    await record_svc.update_record(db, record_id, data)
    # 正文变了 → 双链要重算（否则反链指向老标题）
    try:
        await svc.sync_wikilinks(db, record_id, text)
    except Exception:  # 双链同步失败不该让排版结果丢掉
        pass
    return {
        "ok": True,
        "changed": True,
        "text": text,
        "report": report,
        "changes": _describe_changes(report),
        "elements": fmt_svc.element_audit(text),
        "stats": _stats(text),
        "ai": ai_used,
        "structure": structure if ai_used else {},
        "related": related,
        "before_chars": len(before),
    }


# ---------------------------------------------------------------------------
# 双链
# ---------------------------------------------------------------------------

@router.post("/{record_id}/sync-links")
async def sync_links(
    record_id: int, payload: dict = Body(...), db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """保存笔记时调用：根据 content 同步双链"""
    _need_note_write(principal)
    content = payload.get("content", "")
    try:
        return await svc.sync_wikilinks(db, record_id, content)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/{record_id}/backlinks")
async def backlinks(record_id: int, db: AsyncSession = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    """反向链接：哪些笔记引用了我"""
    ensure_model(principal, "note", "read")
    return await svc.get_backlinks(db, record_id)


@router.get("/{record_id}/outgoing")
async def outgoing_links(record_id: int, db: AsyncSession = Depends(get_db),
                         principal: Principal = Depends(current_principal)):
    """正向链接：我引用了哪些笔记"""
    ensure_model(principal, "note", "read")
    return await svc.get_outgoing_links(db, record_id)


@router.get("/extract")
async def extract_links(content: str = ""):
    """仅解析文本中的 [[标题]]，不落库"""
    titles = await svc.extract_titles(content)
    return {"titles": titles}
