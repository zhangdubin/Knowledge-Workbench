"""DNA 养料库 —— 把资料变成可复用的「基因」，并让它在断网时撑得住系统

上一版的 DNA 模块是「体检报告」：看的是这批资料**长什么样**（成分、结构、
指纹、健康度）。这一层往下再挖一层，问的是另一个问题：

    这批资料**能做什么**？

「能做什么」的部分被拆成一条条**基因**：
  fact        事实（是什么）
  method      方法（怎么做）
  experience  经验（踩过什么坑、为什么）
  interface   接口（怎么调、字段是什么）
  policy      约定（必须怎么做、不许怎么做）

为什么要有基因这一层，四个理由，都不是「设计上好看」：

1. **跨文档复用**。同一个坑在五份文档里各写一遍，人读要读五遍，
   模型检索要命中五次的概率。基因把它合成一条。
2. **能单独检索**。结构层（文档/章节/块）回答「在哪儿」，基因层回答「是什么」。
   「端口是多少」这种问题，答案在文档里往往只是其中一行。
3. **断网时能直答**。模型调用要网络，基因库不要。
   断网时把命中的基因原样端出来（带出处），系统照样能用。
4. **用得上的知识才留得下**。基因带表达度（被引用过多少次），
   冷基因提示复核 —— 这是「知识库越用越准」的抓手。

**源码的吸收**是这个库最特别的一条：源码进来，蒸馏成方法与经验基因，
**原文不留**，只留销毁证明（指纹、时间、文件名）。理由是源码体积大、
泄密风险高、过期快，但里面的方法与经验值钱。蒸馏在 `dna_distill.py`，
本模块只负责编排（吸收 → 蒸馏 → 落库 → 销毁）。

**离线模式**（`META_OFFLINE`）是这个库的存在理由：
断网时，检索只走 FTS5 与结构通道（不需要网络），问答走「直答」
（原样给出基因与证据，不做生成），写操作被挡住。系统因此可以只带一个
养料库包就上机运行。
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DnaGene, Document, DocumentChunk, EntityRecord
from . import docindex

log = logging.getLogger("kb.dna_library")

# 基因级全文索引：与 chunk_fts 同构（同样的 bigram 分词、同样的 FTS5 表）
GENE_FTS_TABLE = "dna_gene_fts"
# 离线模式开关（sys_meta 里的键）
META_OFFLINE = "dna_offline_mode"

KIND_FACT = "fact"
KIND_METHOD = "method"
KIND_EXPERIENCE = "experience"
KIND_INTERFACE = "interface"
KIND_POLICY = "policy"
KINDS = (KIND_FACT, KIND_METHOD, KIND_EXPERIENCE, KIND_INTERFACE, KIND_POLICY)

# 标题里的关键词 → 基因种类。
# 经验类词最靠前：一个标题写着「踩坑」「注意事项」的段落，
# 它的价值在「教训」而不在「陈述」，先判成经验。
_KIND_HINTS = [
    (KIND_EXPERIENCE, ("踩坑", "坑", "教训", "注意事项", "注意", "避免", "别", "不要",
                       "禁止", "风险", "警告", "陷阱", "问题", "失败", "异常",
                       "todo", "fixme", "hack", "bug", "经验", "最佳实践", "best practice")),
    (KIND_POLICY, ("规范", "约定", "规则", "必须", "要求", "策略", "标准", "红线", "禁止")),
    (KIND_INTERFACE, ("接口", "api", "端点", "字段", "参数", "配置", "端点", "endpoint",
                      "schema", "表结构", "命令", "cli", "环境变量", "变量")),
    (KIND_METHOD, ("方法", "步骤", "流程", "教程", "指南", "做法", "怎么", "如何",
                   "步骤", "how to", "recipe", "方案", "操作")),
]

_CODE_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.S)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


# ============ 基础工具 ============

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def gene_uid(kind: str, fingerprint: str) -> str:
    """基因的跨库稳定身份：种类 + 内容指纹

    为什么 uid 不直接用指纹：同一条内容既是「方法」又是「经验」时，
    两个种类是不同的基因，合并掉就丢了一类语义。
    """
    return hashlib.sha1(f"{kind}:{fingerprint}".encode("utf-8")).hexdigest()


def _fingerprint(title: str, content: str) -> str:
    """内容指纹：**只算正文**，不算标题

    为什么标题不进指纹：标题是会变的（同一段内容，抽出来的标题可能
    因为规则调整而不同）。标题进了指纹，改一次标题就多一条基因 ——
    同一件事在库里躺着两条，检索时两条都出来，看起来像「有两份知识」。
    只算正文，身份就跟着内容走；标题变了就地更新，不新增。
    """
    norm = re.sub(r"\s+", " ", (content or "")).strip()
    return _sha256(norm)


def _norm_tags(tags) -> list[str]:
    out: list[str] = []
    for t in (tags or [])[:12]:
        s = str(t).strip()
        if s and s not in out:
            out.append(s)
    return out


def _kind_of(title: str, text_body: str = "") -> str:
    """按标题（辅以正文）猜基因种类

    猜不准不算错：种类只是标签，检索靠的是正文与标题的词面。
    真正影响检索的只有「经验类优先」这一条 ——
    一段讲教训的文字，写成 fact 也能被搜到，只是统计上不归类。
    """
    hay = f"{title} {text_body[:200]}".lower()
    for kind, words in _KIND_HINTS:
        for w in words:
            if w in hay:
                return kind
    return KIND_FACT


# ============ 索引（与 chunk_fts 同构） ============

async def ensure_gene_fts(conn) -> bool:
    """建基因级 FTS 表

    与 chunk_fts 用同一套分词（seg_bigram）：两边不一致的话，
    基因检索会静默失灵（查得到但排序全乱，或者干脆查不到）。
    """
    try:
        await conn.execute(text(
            f"create virtual table if not exists {GENE_FTS_TABLE} using fts5("
            "title, content, tags, tokenize='unicode61 remove_diacritics 2')"
        ))
        return True
    except Exception as e:
        log.warning("基因全文索引表创建失败，基因检索将退回 Python 扫描：%s", e)
        return False


async def index_gene(db: AsyncSession, gene: DnaGene) -> None:
    """把一条基因写进索引（幂等：先删同 uid 的旧行）"""
    try:
        await db.execute(
            text(f"delete from {GENE_FTS_TABLE} where rowid = :r"), {"r": gene.id})
        await db.execute(
            text(f"insert into {GENE_FTS_TABLE}(rowid, title, content, tags) "
                 "values (:r, :t, :c, :g)"),
            {"r": gene.id,
             "t": docindex.seg_bigram(gene.title or ""),
             "c": docindex.seg_bigram((gene.content or "")[:4000]),
             "g": docindex.seg_bigram(" ".join(gene.tags or []))})
    except Exception as e:
        log.warning("基因索引写入失败 gene=%s：%s", gene.uid, e)


async def remove_gene_index(db: AsyncSession, gene_ids: list[int]) -> None:
    if not gene_ids:
        return
    try:
        qmarks = ",".join(f":g{i}" for i in range(len(gene_ids)))
        params = {f"g{i}": gid for i, gid in enumerate(gene_ids)}
        await db.execute(
            text(f"delete from {GENE_FTS_TABLE} where rowid in ({qmarks})"), params)
    except Exception as e:
        log.warning("基因索引清理失败：%s", e)


async def _gene_fts_rows(db: AsyncSession, query: str, limit: int,
                         kinds: list[str] | None = None) -> list[tuple[int, float]]:
    expr = docindex.chunk_fts_query(query)
    if not expr:
        return []
    try:
        rows = (await db.execute(
            text(f"select rowid, bm25({GENE_FTS_TABLE}) as r from {GENE_FTS_TABLE} "
                 f"where {GENE_FTS_TABLE} match :q order by rank limit :lim"),
            {"q": expr, "lim": limit * 3 if kinds else limit})).all()
    except Exception as e:
        log.warning("基因 FTS 检索失败：%s", e)
        return []
    return [(r[0], -float(r[1] or 0.0)) for r in rows]


def _python_scan_genes(genes: list[DnaGene], query: str, limit: int) -> list[dict]:
    """兜底扫描：索引表为空或不可用时，在 Python 端按词面打分

    与旧 keyword 扫描同一套思路，但基因条数通常远少于文档块，
    全量扫是可以接受的。
    """
    terms = docindex.chunk_fts_terms(query)
    if not terms:
        return []
    out = []
    for g in genes:
        hay = f"{g.title} {g.content} {' '.join(g.tags or [])}".lower()
        hits = sum(1 for t in terms if t in hay)
        if hits:
            out.append({"gene": g, "score": float(hits), "hits": hits})
    out.sort(key=lambda x: (-x["score"], x["gene"].id))
    return out[:limit]


# ============ 基因的读写 ============

async def _supersede_old(db: AsyncSession, gene: DnaGene) -> None:
    """同一处知识变了 → 旧基因标记为「已被取代」（突变）

    判定「同一处」：
      - 文档来源：同一篇文档 + 同一种类 + 同一个标题
        （标题就是这一节的位置；同文档不同节是不同基因，不能互相取代）
      - 源码来源：同一个文件名 + 同一种类
        （源码每次蒸馏的指纹都不同，但「这个文件的那条方法」是同一处）

    取代而不是删除：旧知识仍然可能被人引用过，
    删掉它等于让引用它的地方变成悬空指针。
    """
    if not gene.source_ref and not gene.source_title:
        return
    try:
        if gene.source_kind == "code":
            stmt = select(DnaGene).where(
                DnaGene.source_kind == "code",
                DnaGene.source_title == gene.source_title,
                DnaGene.kind == gene.kind,
                DnaGene.status == "active",
                DnaGene.id != gene.id)
        else:
            stmt = select(DnaGene).where(
                DnaGene.source_ref == gene.source_ref,
                DnaGene.kind == gene.kind,
                DnaGene.title == gene.title,
                DnaGene.status == "active",
                DnaGene.id != gene.id)
        olds = (await db.execute(stmt.limit(5))).scalars().all()
        for old in olds:
            old.status = "superseded"
            old.superseded_by = gene.id   # 指向新基因的 id（列是 Integer）
            old.updated_at = _now()
            await db.flush()
            # 旧的也要从检索索引里摘掉：它已经不是当前结论了，
            # 留着就是在答案里混进过期知识。
            await remove_gene_index(db, [old.id])
    except Exception as e:
        log.warning("标记基因取代关系失败：%s", e)


async def upsert_gene(db: AsyncSession, *, kind: str, title: str, content: str,
                      summary: str = "", tags: list[str] | None = None,
                      source_kind: str = "", source_ref: str = "",
                      source_title: str = "", confidence: float = 0.7,
                      meta: dict | None = None) -> tuple[DnaGene, bool]:
    """写入一条基因（按 uid 幂等）

    返回 (基因, 是否新建)。已存在时更新内容与表达度计数 ——
    同一条知识被重新吸收，说明它更值得留在库里。
    """
    title = (title or "").strip()[:250]
    content = (content or "").strip()
    if not title or not content:
        raise ValueError("基因必须有标题和正文")
    fp = _fingerprint(title, content)
    uid = gene_uid(kind, fp)
    existing = (await db.execute(
        select(DnaGene).where(DnaGene.uid == uid))).scalar_one_or_none()
    if existing is not None:
        existing.content = content
        # 标题跟着正文走：抽取规则改了标题（比如原来拿文件名当标题，
        # 后来改成取正文第一句），这里就地把标题换掉，
        # 而不是留下一条旧标题的同内容基因。
        if title and (existing.title or "") != title:
            existing.title = title
        existing.summary = summary or existing.summary
        existing.tags = _norm_tags(tags) or existing.tags
        existing.confidence = max(existing.confidence, confidence)
        existing.source_kind = source_kind or existing.source_kind
        existing.source_ref = source_ref or existing.source_ref
        existing.source_title = source_title or existing.source_title
        if meta:
            old = dict(existing.meta or {})
            old.update(meta)
            existing.meta = old
        existing.updated_at = _now()
        await db.flush()
        await index_gene(db, existing)
        return existing, False

    gene = DnaGene(
        uid=uid, kind=kind, title=title, content=content,
        summary=(summary or content[:120]).strip()[:500],
        tags=_norm_tags(tags), source_kind=source_kind, source_ref=source_ref,
        source_title=source_title, fingerprint=fp, confidence=confidence,
        status="active", meta=meta or {}, created_at=_now(), updated_at=_now())
    db.add(gene)
    await db.flush()
    # 取代关系要等新基因拿到 id 之后才能写 ——
    # superseded_by 指向的是新基因，id 还没有的时候写进去是空。
    await _supersede_old(db, gene)
    await index_gene(db, gene)
    return gene, True


def serialize_gene(g: DnaGene) -> dict:
    return {
        "id": g.id, "uid": g.uid, "kind": g.kind, "title": g.title,
        "content": g.content, "summary": g.summary, "tags": g.tags or [],
        "source_kind": g.source_kind, "source_ref": g.source_ref,
        "source_title": g.source_title, "confidence": g.confidence,
        "status": g.status, "usage_count": g.usage_count,
        "last_used_at": g.last_used_at.isoformat() if g.last_used_at else None,
        "meta": g.meta or {},
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


# ============ 吸收：从资料到基因 ============

def extract_genes_from_markdown(text: str, *, title: str = "") -> list[dict]:
    """从 Markdown 正文里抽候选基因（纯函数，可单测）

    规则按「这段话的价值在哪」来定，而不是按格式：
      - 有代码块 → 代码块蒸馏成方法/经验基因；散文部分留成事实基因
      - 标题里带「坑/注意/避免」→ 经验基因（教训比陈述值钱）
      - 标题里带「接口/字段/参数」→ 接口基因
      - 有表格 → 接口基因（表结构就是接口）
      - 其余有实质内容的段落 → 事实基因

    短段落（<40 字）不抽：那是标题的注脚，不是知识。
    """
    if not text:
        return []
    lines = (text or "").splitlines()
    # 按标题切段
    sections: list[dict] = []
    cur = {"title": title or "", "level": 0, "body": []}
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            if cur["body"] or cur["title"]:
                sections.append(cur)
            cur = {"title": m.group(2).strip(), "level": len(m.group(1)), "body": []}
        else:
            cur["body"].append(ln)
    if cur["body"] or cur["title"]:
        sections.append(cur)

    out: list[dict] = []
    for sec in sections:
        body = "\n".join(sec["body"]).strip()
        if not body:
            continue
        # 代码块：单独拿出来蒸馏，正文里不留代码原文
        codes = _CODE_FENCE.findall(body)
        prose = _CODE_FENCE.sub("", body).strip()
        if codes:
            from . import dna_distill
            for lang, code in codes:
                try:
                    res = dna_distill.distill_code(code, f"{sec['title'] or title}.{lang or 'txt'}")
                except Exception as e:      # 蒸馏器不该拖垮整篇吸收
                    log.warning("代码块蒸馏失败：%s", e)
                    continue
                for g in res.genes:
                    g["meta"] = {**(g.get("meta") or {}),
                                 "section": sec["title"], "origin": "markdown_code_block"}
                    out.append(g)
        # 表格 → 接口基因
        table_lines = [ln for ln in body.splitlines() if _TABLE_ROW.match(ln)]
        if len(table_lines) >= 2:
            out.append({
                "kind": KIND_INTERFACE,
                "title": f"{sec['title'] or title}：表格结构",
                "content": "\n".join(table_lines[:40]),
                "tags": ["表格", "结构"],
                "confidence": 0.7,
                "meta": {"section": sec["title"], "origin": "table"},
            })
        if len(prose) < 40:
            continue
        kind = _kind_of(sec["title"], prose)
        # 标题：段落有自己的标题就用它；没有（首段常常没有，
        # 或者标题就是文件名）就用正文第一句顶上 ——
        # 基因的标题是它在检索结果里的唯一一行字，
        # 拿文件名当标题等于这条基因在库里没有名字。
        gtitle = (sec["title"] or "").strip()
        if not gtitle or (title and gtitle.strip() == title.strip()):
            gtitle = _first_sentence(prose)
        out.append({
            "kind": kind,
            "title": gtitle or title or "未命名片段",
            "content": prose[:4000],
            "tags": _auto_tags(gtitle or sec["title"], prose),
            "confidence": 0.6 if kind == KIND_FACT else 0.75,
            "meta": {"section": sec["title"], "origin": "section",
                     "doc_title": title},
        })
    return out


def _first_sentence(text: str, limit: int = 42) -> str:
    """取正文第一句当标题用（去掉 markdown 记号）"""
    t = (text or "").strip().splitlines()
    line = ""
    for ln in t:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith(("```", "|", "- ", "* ", "#")):
            continue
        line = ln
        break
    if not line:
        return ""
    # PDF 抽出来的正文常有 "[标题] xxx" "[第 1 页]" 这类前缀，
    # 直接当标题会得到「标题 军队采购网」这种带噪声的一行。
    line = re.sub(r"^\[[^\]]{0,10}\]\s*", "", line)
    line = re.sub(r"[*_`>#\-\[\]()]", "", line).strip()
    for sep in ("。", "；", ";", "，", ","):
        if sep in line and line.index(sep) > 6:
            line = line[:line.index(sep)]
            break
    return line[:limit].strip()


def _auto_tags(title: str, body: str) -> list[str]:
    """自动打标签：标题里的词 + 正文里的高频二字词

    只取二字词（CJK 2-gram）和拉丁词，跟 DNA 指纹那套口径一致 ——
    标签的用途是聚类与筛选，口径统一才不会到处对不上。
    """
    tags: list[str] = []
    for t in re.findall(r"[一-鿿]{2}", title or "")[:4]:
        if t not in tags:
            tags.append(t)
    for t in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", body or "")[:6]:
        tl = t.lower()
        if tl not in tags:
            tags.append(tl)
    return tags[:8]


async def absorb_document(db: AsyncSession, doc: Document) -> dict:
    """吸收一篇文档 → 若干基因

    文档本身留在库里（它是证据）；基因是从它里抽出来的可复用单元。
    """
    genes = extract_genes_from_markdown(doc.extracted_text or "", title=doc.title or "")
    created = updated = 0
    for g in genes:
        try:
            _, is_new = await upsert_gene(
                db, kind=g["kind"], title=g["title"], content=g["content"],
                tags=g.get("tags"), source_kind="document",
                source_ref=f"doc-{doc.id}", source_title=doc.title or "",
                confidence=g.get("confidence", 0.7), meta=g.get("meta") or {})
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
        except ValueError:
            continue
    await db.commit()
    return {"document_id": doc.id, "genes": created + updated,
            "created": created, "updated": updated}


async def absorb_text(db: AsyncSession, text_body: str, *, title: str = "",
                      source_kind: str = "manual", source_ref: str = "",
                      source_title: str = "") -> dict:
    """吸收一段手贴的文本（结构化或非结构化都行）"""
    genes = extract_genes_from_markdown(text_body, title=title)
    if not genes and len((text_body or "").strip()) >= 20:
        genes = [{
            "kind": _kind_of(title, text_body),
            "title": title or (text_body or "")[:60],
            "content": (text_body or "")[:4000],
            "tags": _auto_tags(title, text_body),
            "confidence": 0.6,
            "meta": {"origin": "manual"},
        }]
    created = updated = 0
    for g in genes:
        try:
            _, is_new = await upsert_gene(
                db, kind=g["kind"], title=g["title"], content=g["content"],
                tags=g.get("tags"), source_kind=source_kind, source_ref=source_ref,
                source_title=source_title or title,
                confidence=g.get("confidence", 0.7), meta=g.get("meta") or {})
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
        except ValueError:
            continue
    await db.commit()
    return {"genes": created + updated, "created": created, "updated": updated}


async def absorb_code(db: AsyncSession, code: str, filename: str, *,
                      destroy: bool = True) -> dict:
    """吸收程序源码：蒸馏成方法与经验基因，**原文不留**

    「销毁原文」在这里落地：蒸馏完成后，本函数不把源码写进任何表，
    只留一份销毁证明（meta.destroyed：指纹、时间、文件名、蒸馏出的条数）。
    以后想核验「原文确实没留下」，看这条证明就行。

    destroy=False 只用于预览（前端想先看看会抽出什么）。

    注意：本函数只管「库里不留原文」。
    要把**磁盘上的源文件**也删掉，用 `absorb_source_file`
    （那边有越界校验与二次确认）。
    """
    from . import dna_distill
    res = dna_distill.distill_code(code, filename)
    created = updated = 0
    for g in res.genes:
        try:
            _, is_new = await upsert_gene(
                db, kind=g["kind"], title=g["title"], content=g["content"],
                tags=g.get("tags"), source_kind="code",
                source_ref=f"code:{res.sha256[:16]}",
                source_title=filename,
                confidence=g.get("confidence", 0.7),
                meta={**(g.get("meta") or {}),
                      "language": res.language, "file": filename})
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
        except ValueError:
            continue
    await db.commit()
    result = {
        "language": res.language, "summary": res.summary, "sha256": res.sha256,
        "lines": res.lines, "stats": res.stats, "warnings": res.warnings,
        "genes": created + updated, "created": created, "updated": updated,
        "destroyed": False, "skeleton_preview": res.skeleton[:2000],
    }
    if destroy and (created + updated) > 0:
        # 销毁证明：留证据不留原文
        await upsert_gene(
            db, kind=KIND_POLICY,
            title=f"源码已销毁：{filename}",
            content=(f"来源文件 {filename}（{res.lines} 行，{res.language}）已被蒸馏吸收，"
                     f"原文不保留。蒸馏出 {created + updated} 条基因"
                     f"（方法 {sum(1 for g in res.genes if g['kind'] == KIND_METHOD)}、"
                     f"经验 {sum(1 for g in res.genes if g['kind'] == KIND_EXPERIENCE)}）。"
                     f"原始内容指纹 sha256={res.sha256}，"
                     f"蒸馏时间 {_now().isoformat()}。"),
            tags=["源码", "销毁证明", "吸收"],
            source_kind="code", source_ref=f"code:{res.sha256[:16]}",
            source_title=filename, confidence=0.9,
            meta={"destroyed": True, "sha256": res.sha256, "file": filename,
                  "destroyed_at": _now().isoformat(), "language": res.language})
        await db.commit()
        result["destroyed"] = True
        result["attestation"] = {"sha256": res.sha256, "file": filename,
                                 "destroyed_at": _now().isoformat()}
    return result


async def absorb_source_file(db: AsyncSession, rel_path: str, *,
                             destroy: bool = True,
                             destroy_file: bool = False,
                             document_id: int | None = None,
                             display_name: str = "") -> dict:
    """从文件库里取一个源码文件，蒸馏成基因，并（可选）销毁源文件

    「吸收方法经验后销毁源码」落地在这里：蒸馏完、销毁证明写进库之后，
    源文件从磁盘上删掉。

    三道保险，缺一不可：
    1. 路径必须在文件库根目录内（越界直接拒绝，不做任何写入）
    2. 先写销毁证明，再删文件 —— 证明没落库就不删，
       否则文件没了、证据也没了，等于什么都没留下
    3. 只删文件本身，不碰数据库里的文档记录（那是另一件事，
       要删文档走文档删除接口）

    destroy_file=False 时只蒸馏不删文件（预览与可逆操作）。
    """
    from . import filestore
    try:
        path = filestore.abs_path(rel_path)
    except ValueError as e:
        raise ValueError(f"非法路径：{rel_path}") from e
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{rel_path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise OSError(f"读取失败：{e}") from e
    # 文件库里存的是内容寻址的名字（一串 sha256），
    # 销毁证明里要写**用户认识的那个名字**（demo_ingest.py）——
    # 以后核验「这个文件确实没了」时，得能对上人认识的名字。
    name = display_name or path.name
    result = await absorb_code(db, text, name, destroy=destroy)
    result["source_path"] = rel_path
    result["file_deleted"] = False
    result["document_cleared"] = False
    if destroy_file and result.get("destroyed"):
        # 证明已经写进库了（absorb_code 里 commit 过），这才敢删
        if filestore.remove(rel_path):
            result["file_deleted"] = True
            # 证明里补一句「文件已从磁盘删除」，方便以后核验
            gene = (await db.execute(
                select(DnaGene).where(
                    DnaGene.source_ref == f"code:{result['sha256'][:16]}",
                    DnaGene.kind == KIND_POLICY).order_by(DnaGene.id.desc())
            )).scalars().first()
            if gene is not None:
                meta = dict(gene.meta or {})
                meta["file_deleted"] = True
                meta["file_deleted_at"] = _now().isoformat()
                gene.meta = meta
                await db.commit()
        # 文档表里的抽取正文也是原文（.py 文件抽出来就是代码本身）——
        # 只删文件不清正文，等于源码还在库里躺着。
        doc = None
        if document_id is not None:
            doc = (await db.execute(
                select(Document).where(Document.id == document_id))).scalar_one_or_none()
        else:
            doc = (await db.execute(
                select(Document).where(Document.path == rel_path))).scalars().first()
        if doc is not None:
            doc.extracted_text = ""
            doc.summary = "（源码已销毁，只留蒸馏出的基因）"
            doc.extract_status = "destroyed"
            doc.extract_error = ""
            doc.deleted_at = _now()
            await db.commit()
            result["document_cleared"] = True
            result["document_id"] = doc.id
    return result


async def absorb_all(db: AsyncSession, principal=None) -> dict:
    """全库吸收：把每篇文档、每条业务记录都抽成基因"""
    docs = (await db.execute(
        select(Document).where(Document.deleted_at.is_(None)))).scalars().all()
    total = created = 0
    for d in docs:
        try:
            r = await absorb_document(db, d)
            total += r["genes"]
            created += r["created"]
        except Exception as e:
            log.warning("吸收文档失败 doc=%s：%s", d.id, e)
    recs = (await db.execute(
        select(EntityRecord).where(EntityRecord.deleted_at.is_(None))
        .limit(500))).scalars().all()
    for rec in recs:
        try:
            body = rec.search_text or ""
            if len(body.strip()) < 20:
                continue
            r = await absorb_text(db, body, title=_record_title(rec),
                                  source_kind="record", source_ref=f"record-{rec.id}",
                                  source_title=_record_title(rec))
            total += r["genes"]
            created += r["created"]
        except Exception as e:
            log.warning("吸收记录失败 rec=%s：%s", rec.id, e)
    return {"documents": len(docs), "records": len(recs),
            "genes": total, "created": created}


def _record_title(rec: EntityRecord) -> str:
    try:
        data = rec.data or {}
        if isinstance(data, dict):
            for k in ("title", "name", "名称", "标题", "subject"):
                if data.get(k):
                    return str(data[k])[:120]
    except Exception:
        pass
    return f"记录 #{rec.id}"


# ============ 检索与直答 ============

# 查询里点名要哪一类知识时，给那一类的基因加分。
# 注意是「加分」不是「过滤」：过滤会让「经验类的问题」丢掉那些
# 混在别类里的经验（一条 fact 里写着踩坑），答不全；
# 加分只是把对的那类排到前面。
_QUERY_KIND_WORDS = {
    KIND_EXPERIENCE: ("经验", "教训", "坑", "踩过", "失败", "异常", "风险", "避坑"),
    KIND_METHOD: ("方法", "步骤", "怎么做", "如何", "流程", "教程", "照着做", "用法"),
    KIND_INTERFACE: ("接口", "字段", "参数", "端点", "api", "配置项", "表结构"),
    KIND_POLICY: ("约定", "规范", "规则", "必须", "要求", "红线", "禁止"),
    KIND_FACT: ("事实", "是什么", "有哪些事实", "记录"),
}


def _query_kind_bias(query: str) -> str:
    """从问句里认出它要的是哪一类知识（认不出就返回空）"""
    hay = (query or "").lower()
    best = ""
    best_len = 0
    for kind, words in _QUERY_KIND_WORDS.items():
        for w in words:
            if w in hay and len(w) > best_len:
                best, best_len = kind, len(w)
    return best


async def search_genes(db: AsyncSession, query: str, limit: int = 12,
                       kinds: list[str] | None = None) -> list[dict]:
    """基因检索：先查 FTS 表，查不动再退回 Python 扫描"""
    q = (query or "").strip()
    if not q:
        return []
    rows = await _gene_fts_rows(db, q, limit * 4, kinds)
    out: list[dict] = []
    if rows:
        ids = [r[0] for r in rows]
        score = {rid: sc for rid, sc in rows}
        qmarks = ",".join(f":g{i}" for i in range(len(ids)))
        params = {f"g{i}": gid for i, gid in enumerate(ids)}
        genes = (await db.execute(
            select(DnaGene).where(DnaGene.id.in_(ids)), params)).scalars().all()
        by_id = {g.id: g for g in genes}
        for gid in ids:
            g = by_id.get(gid)
            if g is None:
                continue
            if kinds and g.kind not in kinds:
                continue
            out.append({"gene": g, "score": score.get(gid, 0.0), "hits": 0})
    if not out:
        stmt = select(DnaGene).where(DnaGene.status == "active")
        if kinds:
            stmt = stmt.where(DnaGene.kind.in_(kinds))
        genes = (await db.execute(stmt.limit(800))).scalars().all()
        out = _python_scan_genes(genes, q, limit)
    # 问句点名了类别就把那一类顶上来（加分，不是过滤）
    bias = _query_kind_bias(q)
    if bias:
        for item in out:
            if item["gene"].kind == bias:
                # 绝对加分而不是比例加分：bm25 的绝对值很小（个位数），
                # 比例加权（×1.8）根本压不过一条词面命中的别类基因，
                # 「问经验」还是答成事实。
                item["score"] = item["score"] + 10.0
                item["kind_boost"] = True
        # 一条都没命中那一类，就直接补几条那一类的基因进来。
        # 「有哪些经验」这种问法，词面命中的是「正文里恰好提到经验的段落」，
        # 而不是「经验类的知识」—— 不补的话，问经验却答出一堆事实，
        # 答非所问比答不出来更糟。
        if not any(item["gene"].kind == bias for item in out):
            extra = (await db.execute(
                select(DnaGene).where(DnaGene.status == "active",
                                       DnaGene.kind == bias)
                .order_by(DnaGene.usage_count.desc(), DnaGene.confidence.desc())
                .limit(limit))).scalars().all()
            for g in extra:
                # 补进来的要排在前面：分数低就会被 limit 砍掉，
                # 补了等于没补
                out.append({"gene": g, "score": 11.0, "hits": 0, "kind_boost": True})
    out.sort(key=lambda x: (-x["score"], x["gene"].id))
    return out[:limit]


async def mark_gene_used(db: AsyncSession, gene_ids: list[int]) -> None:
    """基因被引用 → 表达度 +1

    表达度是「知识在用」的度量：一直没人用的基因要么该归档，
    要么该换个说法重新写一遍。
    """
    if not gene_ids:
        return
    try:
        # 用 ORM 的 update 语句，不用裸 SQL：
        # text() 不会把元组展开成 IN 子句（那是 bindparam(expanding=True) 才有的事），
        # 写出来是 `id in :ids` 绑一个元组 —— SQLite 不认，
        # 报错被吞掉之后，表达度就永远是 0（一个很安静的坏掉的功能）。
        # synchronize_session=False 是必须的：
        # ORM 的批量 update 默认会「同步会话」，同步不了表达式值时就退化成
        # 把命中对象的属性标成过期 —— 之后访问那些属性会触发懒加载，
        # 而异步会话里懒加载会抛 MissingGreenlet（greenlet_spawn has not been called）。
        # 这个错很隐蔽：报错点在「序列化基因」那一行，跟 update 隔了好几层。
        await db.execute(
            update(DnaGene).where(DnaGene.id.in_(gene_ids)).values(
                usage_count=DnaGene.usage_count + 1,
                last_used_at=_now()),
            execution_options(synchronize_session=False))
        await db.commit()
    except Exception as e:
        log.warning("基因表达度更新失败：%s", e)


async def answer_offline(db: AsyncSession, query: str, limit: int = 5) -> dict:
    """离线直答：不调模型，把命中的基因与证据原样端出来

    断网时这就是问答能力的下限：给不出「生成」的答案，
    但能给「有出处的原文」—— 对一个知识工作台来说这已经能用：
    人能直接读，模型（如果本地有）也能直接吃。
    """
    q = (query or "").strip()
    genes = await search_genes(db, q, limit=limit)
    chunks = await docindex.chunk_fts_search(db, q, limit=limit) if q else []
    # 回表取章节标题，答案里要指得出「在哪」
    cites = []
    for c in chunks[:limit]:
        doc = (await db.execute(
            select(Document).where(Document.id == c["document_id"]))).scalar_one_or_none()
        cites.append({
            "document_id": c["document_id"],
            "title": doc.title if doc else "",
            "seq": c.get("seq"),
            "text": (c.get("text") or "")[:600],
            "heading": c.get("heading") or "",
        })
    # 先序列化再标记表达度：标记会写库，
    # 而写库之后对象属性可能变成「过期」，那时候再读属性会炸。
    payload = [{"gene": serialize_gene(g["gene"]), "score": g["score"]}
               for g in genes]
    if genes:
        await mark_gene_used(db, [g["gene"].id for g in genes])
    return {
        "query": q,
        "offline": True,
        "genes": payload,
        "citations": cites,
        "text": _render_offline_answer(q, genes, cites),
    }


def _render_offline_answer(query: str, genes: list[dict], cites: list[dict]) -> str:
    """离线直答的正文：基因优先（它们是可复用的结论），证据跟在后面"""
    lines: list[str] = []
    if genes:
        lines.append(f"关于「{query}」，养料库里已有这些结论：")
        for i, g in enumerate(genes, 1):
            gene = g["gene"]
            src = gene.source_title or gene.source_kind or "养料库"
            lines.append(f"\n{i}. **{gene.title}**（{gene.kind}｜来源：{src}）")
            lines.append(f"   {gene.content[:600]}")
    if cites:
        lines.append("\n相关原文：")
        for i, c in enumerate(cites, 1):
            head = f"【{c['heading']}】" if c.get("heading") else ""
            lines.append(f"[{i}] {c['title']} {head}\n   {c['text'][:300]}")
    if not lines:
        lines.append(f"养料库里没有关于「{query}」的基因或原文。")
    else:
        lines.append("\n（离线直答：未调用模型，以上均为养料库中的原始记录。）")
    return "\n".join(lines)


# ============ 离线模式 ============

async def is_offline(db: AsyncSession) -> bool:
    from ..models import SysMeta
    row = (await db.execute(
        select(SysMeta).where(SysMeta.key == META_OFFLINE))).scalar_one_or_none()
    return bool(row and row.value == "1")


async def set_offline(db: AsyncSession, on: bool) -> bool:
    from ..models import SysMeta
    row = (await db.execute(
        select(SysMeta).where(SysMeta.key == META_OFFLINE))).scalar_one_or_none()
    if row is None:
        row = SysMeta(key=META_OFFLINE, value="")
        db.add(row)
    row.value = "1" if on else "0"
    row.updated_at = _now()
    await db.commit()
    return bool(on)


# ============ 断网演练 ============

# 演练题库刻意不写死语料内容：换一台机器、换一个库，
# 写死的问题就答非所问。这里问的都是「库对自己的结构」，
# 任何一份养料库都答得上来 —— 演练要证明的是
# 「断网时这套机制还转得起来」，不是「这个库答对了某道业务题」。
DRILL_QUESTIONS = [
    {"q": "养料库里有哪些经验类的知识？", "expect_kind": "experience",
     "why": "经验是养料库最容易丢的一层（原文里往往只是一句话）"},
    {"q": "有哪些接口或字段的说明？", "expect_kind": "interface",
     "why": "接口类知识直接决定能不能把系统接起来"},
    {"q": "有什么方法可以直接照着做？", "expect_kind": "method",
     "why": "方法基因是「拿来就用」的那部分"},
    {"q": "有哪些必须遵守的约定和规则？", "expect_kind": "policy",
     "why": "约定类知识漏了最容易出事"},
    {"q": "库里关于事实的记录有哪些？", "expect_kind": "fact",
     "why": "事实基因是引用与核对的基础"},
]


async def offline_drill(db: AsyncSession) -> dict:
    """断网演练：只用养料库（不调模型、不调向量）跑一遍问答

    这是「断网时系统还撑得住」的**证明**，不是承诺：
    每一题都真的走一次离线直答，然后检查答没答上来。

    演练要快：全部题目加起来应该在百毫秒级 ——
    因为它只用本地 FTS 与基因索引，任何一次外部调用都会让它变慢，
    那就说明「离线」这件事没做对。
    """
    import time
    results = []
    t0 = time.time()
    for item in DRILL_QUESTIONS:
        started = time.time()
        try:
            ans = await answer_offline(db, item["q"], limit=6)
            genes = ans["genes"]
            kinds = {g["gene"]["kind"] for g in genes}
            hit = item["expect_kind"] in kinds
            results.append({
                "question": item["q"], "expect_kind": item["expect_kind"],
                "ok": hit, "kinds": sorted(kinds),
                "genes": len(genes), "citations": len(ans["citations"]),
                "ms": round((time.time() - started) * 1000, 1),
                "why": item["why"],
            })
        except Exception as e:
            results.append({"question": item["q"], "expect_kind": item["expect_kind"],
                            "ok": False, "error": str(e),
                            "ms": round((time.time() - started) * 1000, 1),
                            "why": item["why"]})
    # 拒答测试：库里没有的东西，必须明说没有，不能编
    refuse_ok = True
    refuse_ms = 0
    started = time.time()
    try:
        ans = await answer_offline(db, "请介绍一下拓扑量子比特的制备工艺与良率", limit=6)
        refuse_ms = round((time.time() - started) * 1000, 1)
        text = ans["text"] or ""
        refuse_ok = ("没有" in text) or ("未提及" in text) or len(ans["genes"]) == 0
    except Exception:
        refuse_ok = False
    results.append({
        "question": "库里没有的东西会编吗？（应回答没有）",
        "expect_kind": "refusal", "ok": refuse_ok, "ms": refuse_ms,
        "why": "离线直答最大的风险是「没有也硬答」，这道题专门盯这个",
    })
    passed = sum(1 for r in results if r["ok"])
    return {
        "passed": passed, "total": len(results),
        "ok": passed == len(results),
        "ms": round((time.time() - t0) * 1000, 1),
        "results": results,
        "note": "演练全程不调模型、不调 embedding，只用养料库的本地索引",
    }


# ============ 体检 ============

async def gene_health(db: AsyncSession) -> dict:
    """基因库体检：哪些知识不可信、该复核、该归档

    检出的四类问题：
      无源基因   —— 说不出从哪来的知识，模型会用，人不敢用
      冷基因     —— 一直没人用的知识，可能已经过时
      低置信     —— 抽取时就不确定的
      重复基因   —— 同一件事写了两遍（指纹不同但标题高度相似）
    """
    genes = (await db.execute(
        select(DnaGene).where(DnaGene.status == "active"))).scalars().all()
    no_source = [g for g in genes if not g.source_ref]
    cold = [g for g in genes if (g.usage_count or 0) == 0]
    low_conf = [g for g in genes if (g.confidence or 0) < 0.6]
    by_title: dict[str, list[DnaGene]] = {}
    for g in genes:
        key = re.sub(r"\s+", "", g.title or "")[:24]
        if key:
            by_title.setdefault(key, []).append(g)
    dup = [v[0] for v in by_title.values() if len(v) > 1]
    destroyed = [g for g in genes if (g.meta or {}).get("destroyed")]
    by_kind: dict[str, int] = {}
    for g in genes:
        by_kind[g.kind] = by_kind.get(g.kind, 0) + 1
    return {
        "total": len(genes),
        "by_kind": by_kind,
        "used": sum(1 for g in genes if (g.usage_count or 0) > 0),
        "usage_total": sum((g.usage_count or 0) for g in genes),
        "no_source": len(no_source),
        "cold": len(cold),
        "low_confidence": len(low_conf),
        "duplicated": len(dup),
        "destroyed_sources": len(destroyed),
        "samples": {
            "no_source": [{"id": g.id, "title": g.title} for g in no_source[:8]],
            "cold": [{"id": g.id, "title": g.title, "kind": g.kind}
                     for g in sorted(cold, key=lambda x: x.id)[:8]],
            "duplicated": [{"id": g.id, "title": g.title} for g in dup[:8]],
        },
    }
