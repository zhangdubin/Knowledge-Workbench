"""养料 DNA —— 体检报告 + 基因图谱（只读）

这个模块回答四个问题，正好对应 OpenKB 那边被吸收进来的四样东西：

    成分 —— 喂给模型的东西有多少、是什么（文档/笔记/块/字）
    骨架 —— 每篇文档的标题层级（PageIndex 的等价物）
    指纹 —— 全库的主题词分布（这批资料的「基因」）
    健康 —— 哪里有毛病（抽不出正文、没向量化、维度对不上、重复文件）

三条硬规矩，理由都比规矩本身重要：

1. **只读**。这个模块不写库、不调 LLM、不重算向量。
   OpenKB 把「二级」改写成「乙级」还持久化进索引 —— 那种「顺手改一改」
   在体检报告里绝对不能有：报告一旦会改被体检的对象，
   报告本身就不再可信，下一个人再也无法判断问题是不是被「修好了」。

2. **不碰检索链路**。分词思路照抄 docindex.keyword_terms，
   但代码自己写一份。docindex 是检索链路的命脉，
   为一个只读页面去动它，风险与收益完全不成比例；
   而且两边要的统计口径根本不同 —— 那边要「词表」，
   这边要「词频 + 文档频次」。

3. **不新增依赖**。中文没有 jieba，就用「汉字 2-gram + 拉丁整词」，
   再按 IDF 加权。2-gram 噪声大（"的配"、"配是"这种），
   但 IDF 会自动把它们压下去：到处都是的词 idf 趋近 0。
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime

from sqlalchemy import case, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..config import settings
from ..models import (
    Document,
    DocumentChunk,
    DocumentLink,
    EntityRecord,
    EntityType,
    FieldDefinition,
    RelationDef,
    RelationRecord,
    SysMeta,
)
from . import access
from . import docindex
from . import graph as graph_svc
from .auth import Principal, admin_perms

log = logging.getLogger("kb.dna")

# 体检分档：满分 100，error 扣得狠、warn 扣得轻
SCORE_ERROR_PENALTY = 8
SCORE_WARN_PENALTY = 3

# 指纹里保留多少个词条。太多则前端一屏放不下，
# 太少则「这批资料的主题」会被噪声词挤掉
FINGERPRINT_LIMIT = 24
DOC_TERM_LIMIT = 20


# ---------- 基础工具 ----------

_WS_RE = re.compile(r"\s+")


def _iso(value) -> str:
    """datetime → 无时区的 ISO 串

    库里存的是 naive datetime（服务器本地时间），直接 isoformat() 会带上
    微秒，前端显示成 "2026-09-24T03:23:28.000000" —— 秒级精度已经够用，
    多出来的微秒只会把字符串撑长。
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _count_words(text: str) -> int:
    """字数 = 去掉所有空白后的字符数

    为什么不用空格分词数词：中文正文里几乎没有空格，
    按空格数出来的「词数」约等于段落数，毫无信息量；
    去空白后的字符数既稳定又能反映真实体量，
    而且跟「字」这个中文语境天然对得上。
    """
    return len(_WS_RE.sub("", text or ""))


def _fmt_bytes(n: int) -> str:
    v = float(n or 0)
    if v >= 1048576:
        return f"{v / 1048576:.1f} MB"
    if v >= 1024:
        return f"{v / 1024:.1f} KB"
    return f"{int(v)} B"


# ---------- 中文分词：汉字 2-gram + 拉丁整词 ----------

_CJK_RUN = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")


def _terms_of(text: str) -> dict[str, int]:
    """把一段正文切成词条并统计词频

    与 docindex.keyword_terms 的**思路**一致（没有 jieba，
    汉字只能靠 2-gram 滑窗，拉丁词按整词保留），
    但这里做的是全库词频统计而不是「拿查询串去正文里匹配」，
    所以代码另写一份，不去动检索链路。

    2-gram 的噪声（"配是"、"的配"）交给 IDF 压制：
    到处都是的词 idf 趋近 0，只在少数文档里出现的词 idf 最高。
    """
    out: dict[str, int] = {}
    if not text:
        return out
    for run in _CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            out[g] = out.get(g, 0) + 1
    for w in _LATIN_RUN.findall(text):
        w = w.lower().strip("._-")
        if len(w) < 2:
            continue
        out[w] = out.get(w, 0) + 1
    return out


def _idf(n_docs: int, df: int) -> float:
    """BM25 式的 idf

    公式与 docindex.chunk_keyword_scan 一致：
    「越少见越值钱」，用同一套算法，
    DNA 的词权重与检索链路的关键词打分才讲得通，
    不会出现「体检说这个词很稀有、检索却当它很普通」的分裂。
    """
    if n_docs <= 0:
        return 0.0
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def _term_index(term_stats: list[dict[str, int]]) -> tuple[dict[str, int], dict[str, float]]:
    """算全库的「文档频次」与「权重」两张表

    权重 = Σ_文档 (1 + log(词频)) × idf(文档频次)

    为什么词频要取 log：长文档里同一个词出现几千次是常事，
    线性加权会让「谁更长谁词多」，指纹最后只反映文档长度；
    取 log 之后，「反复强调」与「提到一次」的差距被压到几倍以内，
    权重更多反映的是这个词在语料里的**分布**。
    """
    n = len(term_stats)
    df: dict[str, int] = {}
    for stats in term_stats:
        for term in stats:
            df[term] = df.get(term, 0) + 1

    weight: dict[str, float] = {}
    for stats in term_stats:
        for term, tf in stats.items():
            idf = _idf(n, df.get(term, 0))
            weight[term] = weight.get(term, 0.0) + (1.0 + math.log(tf)) * idf
    return df, weight


def _fingerprint(term_stats: list[dict[str, int]], limit: int) -> list[dict]:
    """把每篇文档的词频汇总成「主题指纹」"""
    df, weight = _term_index(term_stats)
    items = [{"term": t, "weight": round(w, 1), "docs": df.get(t, 0)}
             for t, w in weight.items()]
    items.sort(key=lambda x: (-x["weight"], -x["docs"], x["term"]))
    return items[:limit]


# ---------- 结构树：从 Markdown 正文抽标题层级 ----------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
# 结尾的闭合井号（`## 标题 ##`）
_TRAILING_HASH_RE = re.compile(r"\s+#+$")


def _parse_headings(text: str) -> list[tuple[int, str, int]]:
    """抽出正文里的标题（级别, 标题, 行号）

    坑一：**代码块里的 # 不是标题**。
    手册正文里大段 shell 命令带注释（`# 推荐用 bun(轻、快)`），
    不排除代码块的话，这些注释会变成一级标题，整棵树全是垃圾。
    坑二：结尾的闭合 #（`## 标题 ##`）要剥掉，
    否则标题里会多出一串井号，前端渲染成一级标题也看不出差别。
    行号是给「第一个标题之前的内容」定位用的 ——
    按标题文字去找位置不可靠：标题文字可能在正文更早的地方出现过。
    """
    out: list[tuple[int, str, int]] = []
    in_fence = False
    fence_char = ""
    for idx, line in enumerate((text or "").split("\n")):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
            continue
        if in_fence:
            continue
        h = _HEADING_RE.match(line.rstrip())
        if not h:
            continue
        title = _TRAILING_HASH_RE.sub("", h.group(2).strip())
        if title:
            out.append((len(h.group(1)), title, idx))
    return out


def _build_tree(headings: list[tuple[int, str, int]]) -> list[dict]:
    """把标题序列拼成树

    层级会跳跃：正文里 h1 后面直接跟 h3 是常事（作者删掉了中间层）。
    按「当前层 + 1」建树会凭空多出一层不存在的 h2。
    做法是维护一个栈：弹掉所有层级 ≥ 当前标题的节点，
    剩下的栈顶就是父节点 —— 没有父节点时它就是根节点。
    这样 h1 → h3 会挂在 h1 下面，h6 也不会越界。
    """
    root: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for level, title, _line in headings:
        while stack and stack[-1][0] >= level:
            stack.pop()
        node: dict = {"level": level, "title": title, "path": "", "children": []}
        if stack:
            parent = stack[-1][1]
            parent["children"].append(node)
            node["path"] = f"{parent['path']} / {title}"
        else:
            root.append(node)
            node["path"] = title
        stack.append((level, node))
    return root


_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(\r?\n|\Z)", re.DOTALL)


def _strip_front_matter(text: str) -> str:
    """去掉开头的 YAML front-matter

    为什么：Obsidian 笔记开头常有

        ---
        title: ...
        tags: ...
        ---

    这段是元数据不是正文。不去掉的话，每篇带 front-matter 的 Markdown
    都会在结构树里多出一个空的「正文」节点，
    看起来像抽取出了内容，实际什么也没有 ——
    「结构树里多了一个节点」比「结构树少一个节点」更容易误导人。
    """
    return _FRONT_MATTER_RE.sub("", text or "", count=1)


def _outline_from(text: str, headings: list[tuple[int, str, int]]) -> list[dict]:
    """标题序列 + 正文 → 结构树"""
    if not headings:
        return [{"level": 1, "title": "正文", "path": "正文", "children": []}]

    # 第一个标题之前的内容（引言、摘要）单独挂一个「正文」节点，
    # 否则这部分内容在结构树里凭空消失。
    # 按**行号**切，不能按标题文字去找位置 ——
    # 标题文字很可能在正文更早的地方就出现过（比如摘要里提到了这一节），
    # 那样切出来的「前言」会是一段错位的文本。
    lines = (text or "").split("\n")
    preamble = "\n".join(lines[: headings[0][2]])
    tree = _build_tree(headings)
    if preamble.strip():
        tree.insert(0, {"level": 1, "title": "正文", "path": "正文", "children": []})
    return tree


def extract_outline(text: str) -> list[dict]:
    """从正文抽出结构树（OpenKB PageIndex 的等价物）

    PDF 抽不出标题是常态（PDF 里根本没有标题语义），
    这时候退化成单节点「正文」——
    总比给前端一个空数组强：空数组没法区分
    「这篇没有结构」和「解析出错了」。
    """
    body = _strip_front_matter(text or "")
    return _outline_from(body, _parse_headings(body))


def _outline_stats(text: str) -> tuple[list[dict], int]:
    """结构树 + 标题数（不含退化的「正文」节点）"""
    body = _strip_front_matter(text or "")
    headings = _parse_headings(body)
    return _outline_from(body, headings), len(headings)


# ---------- 记录标题 ----------

def _record_label(rec_id, data) -> str:
    """业务记录的可读标题

    记录的字段全是模型自定义的，标题可能叫 title / name / code，
    只能挨个试；都取不到就用 id 兜底 ——
    显示一个空字符串比显示「记录 #12」糟糕得多。
    """
    if isinstance(data, dict):
        for key in ("title", "name", "code", "label"):
            v = data.get(key)
            if v:
                return str(v)
    return f"记录 #{rec_id}"


# ---------- 数据快照 ----------

async def _load_links(db: AsyncSession, doc_ids: list[int]) -> dict[int, list[dict]]:
    """取每个文件挂着的「关联」

    关联有两条来路：document_link（文件挂在记录的某个字段上）
    与 relation_record（关联定义里以文件为一端的关系）。
    只算前者会漏掉后者，只算后者会漏掉前者 ——
    前端「这个文件连着谁」看到的不完整，就等于没有。
    """
    out: dict[int, list[dict]] = {d: [] for d in doc_ids}
    if not doc_ids:
        return out

    link_rows = (await db.execute(
        select(DocumentLink, EntityRecord)
        .join(EntityRecord, EntityRecord.id == DocumentLink.record_id, isouter=True)
        .where(DocumentLink.document_id.in_(doc_ids))
    )).all()
    for link, rec in link_rows:
        out.setdefault(link.document_id, []).append({
            "id": link.id,
            "title": _record_label(rec.id, rec.data) if rec is not None else "",
            "rel": link.field_key or "关联",
        })

    rel_rows = (await db.execute(
        select(RelationRecord, RelationDef)
        .join(RelationDef, RelationDef.id == RelationRecord.relation_def_id, isouter=True)
        .where(or_(
            RelationRecord.source_document_id.in_(doc_ids),
            RelationRecord.target_document_id.in_(doc_ids),
        ))
    )).all()

    peer_ids: set[int] = set()
    rel_meta = []
    for rel, rdef in rel_rows:
        peer_ids.update(r for r in (rel.source_record_id, rel.target_record_id) if r)
        rel_meta.append((rel, rdef))
        entry = {"id": rel.id, "title": "", "rel": rdef.name if rdef else "关联"}
        for did in (rel.source_document_id, rel.target_document_id):
            if did is not None and did in out:
                out[did].append(dict(entry))

    # 回填关系另一端的标题（关系的一端是文件时，另一端通常是一条记录）
    if peer_ids:
        rec_rows = (await db.execute(
            select(EntityRecord.id, EntityRecord.data)
            .where(EntityRecord.id.in_(list(peer_ids)))
        )).all()
        labels = {int(rid): _record_label(rid, data) for rid, data in rec_rows}
        for rel, _rdef in rel_meta:
            label = ""
            for rid in (rel.source_record_id, rel.target_record_id):
                if rid and int(rid) in labels:
                    label = labels[int(rid)]
                    break
            if not label:
                continue
            for did in (rel.source_document_id, rel.target_document_id):
                if did is None:
                    continue
                for item in out.get(did, []):
                    if item["id"] == rel.id and not item["title"]:
                        item["title"] = label

    return out


async def _count_notes(db: AsyncSession, principal: Principal) -> int:
    """知识库笔记条数

    笔记也是「养料」的一部分（spec 里 documents 与 notes 并列），
    所以要单独计数；但它属于 note 模型，
    读不到 note 模型的人不该知道库里有多少条笔记。
    """
    if not principal.can_model("note", "read"):
        return 0
    type_id = (await db.execute(
        select(EntityType.id).where(EntityType.key == "note")
    )).scalar()
    if not type_id:
        return 0
    return (await db.execute(
        select(func.count(EntityRecord.id))
        .where(EntityRecord.entity_type_id == type_id,
               EntityRecord.deleted_at.is_(None))
    )).scalar() or 0


async def _vec_stats(db: AsyncSession) -> tuple[int, bool, int]:
    """向量表：行数、是否可用、孤儿向量数

    孤儿向量 = 向量表里存在、但对应的块已经不在 document_chunk 里。
    这种向量会占着向量检索 top-k 的名额 ——
    检索命中它却找不到对应的块，那条命中就被白白消耗掉，
    真正该被召回的块反而被挤出候选集。
    """
    rows = 0
    ok = False
    try:
        rows = (await db.execute(
            text(f"select count(*) from {docindex.VEC_TABLE}")
        )).scalar() or 0
        ok = True
    except Exception as e:
        log.warning("向量表不可用（sqlite-vec 未加载或表不存在）：%s", e)
        return 0, False, 0

    orphan = 0
    try:
        orphan = (await db.execute(text(
            f"select count(*) from {docindex.VEC_TABLE} v where not exists "
            f"(select 1 from document_chunk c where c.id = v.rowid)"
        ))).scalar() or 0
    except Exception as e:
        log.warning("孤儿向量统计失败：%s", e)
    return int(rows), ok, int(orphan)


async def _fts_stats(db: AsyncSession) -> tuple[int, bool, set[int]]:
    """全文索引：行数、是否可用、已进索引的文档 id

    除了数行数，还要真跑一次 MATCH：
    「表在但索引坏了」是真实存在的情况，
    只查表是否存在会把这种情况漏过去。
    注意 MATCH 只用来「探活」，
    已入索引的文档 id 要整表取 ——
    用 MATCH 去取 id 的话，拿到的只是「命中这个词的文档」，
    差集会把没命中的文档全算成漏建索引。
    """
    rows = 0
    ok = False
    ids: set[int] = set()
    try:
        rows = (await db.execute(
            text(f"select count(*) from {docindex.FTS_TABLE}")
        )).scalar() or 0
        got = (await db.execute(
            text(f"select rowid from {docindex.FTS_TABLE}")
        )).all()
        ids = {int(r[0]) for r in got}
        await db.execute(
            text(f"select rowid from {docindex.FTS_TABLE} "
                 f"where {docindex.FTS_TABLE} match :q limit 1"),
            {"q": '"养料"'},
        )
        ok = True
    except Exception as e:
        log.warning("FTS 索引不可用：%s", e)
    return int(rows), ok, ids


async def _db_size(db: AsyncSession) -> tuple[int, int]:
    """库体积（字节）与页大小

    用 page_count × page_size 而不是 os.path.getsize：
    后者算的是文件当前大小，而 WAL 模式下还有没回写主库的数据在 -wal 里，
    文件大小会明显小于「数据实际占了多少页」。
    """
    try:
        page_size = (await db.execute(text("pragma page_size"))).scalar() or 4096
        page_count = (await db.execute(text("pragma page_count"))).scalar() or 0
        return int(page_size) * int(page_count), int(page_size)
    except Exception as e:
        log.warning("读取库体积失败：%s", e)
        return 0, 4096


async def _vector_bytes(db: AsyncSession, vec_rows: int, embed_dim: int) -> int:
    """向量表占用的字节数

    vec0 是虚拟表，真正的数据在它的影子表里，
    所以按 dbstat 把「document_vec*」这一族表加起来。
    dbstat 不是所有 SQLite 编译都带（SQLITE_ENABLE_DBSTAT_VTAB），
    拿不到时退化成「行数 × 维度 × 4 字节」的估算 ——
    宁可给个估算值，也不要让整个接口因为一个 pragma 缺失而失败。
    """
    try:
        rows = (await db.execute(
            text("select name, sum(pgsize) from dbstat group by name")
        )).all()
        total = sum(int(s or 0) for name, s in rows
                    if str(name or "").startswith(docindex.VEC_TABLE))
        if total:
            return total
    except Exception as e:
        log.warning("dbstat 不可用，向量体积改用估算：%s", e)
    return int(vec_rows) * int(embed_dim or 0) * 4


async def _snapshot(db: AsyncSession, principal: Principal) -> dict:
    """把全库的「养料」读成一份快照，之后全是纯计算

    为什么一次性读完而不是各接口各查一次：
    成分、指纹、体检三处要用的是同一批数字，
    分开查会出现「体检说有 44 个块、成分表写 42 个块」这种自相矛盾。
    """
    docs = (await db.execute(
        select(Document)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.id)
        .options(defer(Document.data))
    )).scalars().all()

    # 权限：文件能不能读，规则只在 access.py 里写一份，这里只调用。
    # 不做这一步的话，「数据中心」权限被收回的人换个 URL
    # 就能在体检报告里看到全部文件标题与摘要。
    allowed = set(await access.filter_readable_documents(
        db, principal, [d.id for d in docs]))
    docs = [d for d in docs if d.id in allowed]
    doc_ids = [d.id for d in docs]

    # 块统计：按文档分组一次算完，别在 Python 里遍历所有块
    #
    # embedded 必须用 case 包一层再求和：直接 sum(embedded) 时，
    # SQLAlchemy 会按列的类型（Boolean）去处理结果，
    # 4 条已嵌入的块会变成 True（=1）而不是 4 —— 
    # 「已嵌入块数」于是永远等于「有多少篇文档有已嵌入的块」。
    chunk_rows = (await db.execute(
        select(
            DocumentChunk.document_id,
            func.count(DocumentChunk.id),
            func.coalesce(func.sum(case((
                DocumentChunk.embedded.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((
                or_(DocumentChunk.text.is_(None),
                    func.trim(DocumentChunk.text) == ""), 1), else_=0)), 0),
        ).group_by(DocumentChunk.document_id)
    )).all()
    chunk_stats = {int(r[0]): {"total": int(r[1] or 0),
                               "embedded": int(r[2] or 0),
                               "empty": int(r[3] or 0)}
                   for r in chunk_rows}

    # 孤儿块：块指向的文档在 document 表里根本不存在
    orphan_chunks = (await db.execute(
        select(func.count(DocumentChunk.id)).where(
            ~select(Document.id)
            .where(Document.id == DocumentChunk.document_id).exists()
        )
    )).scalar() or 0

    # 软删除文档留下的块：检索时按文档过滤掉了，等于白占空间
    deleted_chunks = (await db.execute(
        select(func.count(DocumentChunk.id)).where(
            select(Document.id).where(
                Document.id == DocumentChunk.document_id,
                Document.deleted_at.is_not(None),
            ).exists()
        )
    )).scalar() or 0

    meta_rows = (await db.execute(select(SysMeta.key, SysMeta.value))).all()
    meta = {str(k): str(v) for k, v in meta_rows}
    try:
        embed_dim = int(meta.get(docindex.META_EMBED_DIM) or 0)
    except (TypeError, ValueError):
        embed_dim = 0

    vec_rows, vec_ok, vec_orphan = await _vec_stats(db)
    fts_rows, fts_ok, fts_ids = await _fts_stats(db)
    db_bytes, page_size = await _db_size(db)
    vector_bytes = await _vector_bytes(db, vec_rows, embed_dim)

    links_by_doc = await _load_links(db, doc_ids)
    notes = await _count_notes(db, principal)

    return {
        "docs": docs,
        "doc_ids": doc_ids,
        "chunk_stats": chunk_stats,
        "orphan_chunks": int(orphan_chunks),
        "deleted_chunks": int(deleted_chunks),
        "meta": meta,
        "embed_dim": embed_dim,
        "vec_rows": vec_rows,
        "vec_ok": vec_ok,
        "vec_orphan": vec_orphan,
        "fts_rows": fts_rows,
        "fts_ok": fts_ok,
        "fts_ids": fts_ids,
        "db_bytes": db_bytes,
        "page_size": page_size,
        "vector_bytes": vector_bytes,
        "links_by_doc": links_by_doc,
        "notes": notes,
        "generated_at": _now_iso(),
    }


# ---------- 纯计算：成分 / 指纹 / 体检 ----------

_KIND_LABELS = {
    "doc": "文档", "image": "图片", "video": "视频",
    "audio": "音频", "other": "其他",
}


def _doc_label(d: Document) -> str:
    return d.title or d.filename or f"#{d.id}"


def _doc_list(docs: list[Document], limit: int = 5) -> str:
    """把一批文档压成一句能给人看的说明"""
    if not docs:
        return ""
    parts = [f"#{d.id} {_doc_label(d)}" for d in docs[:limit]]
    if len(docs) > limit:
        parts.append(f"等 {len(docs)} 篇")
    return "、".join(parts)


def _composition(docs: list[Document]) -> dict:
    """成分分布：按类型 / 扩展名 / 标签 / 来源 / 月份

    by_kind 带 label，其余几项只给 key+count ——
    前端要的是「点一下能筛」的列表，label 在这里没有信息量。
    """
    by_kind: dict[str, int] = {}
    by_ext: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for d in docs:
        by_kind[d.kind or "other"] = by_kind.get(d.kind or "other", 0) + 1
        ext = d.ext or ""
        by_ext[ext] = by_ext.get(ext, 0) + 1
        for t in (d.tags or []):
            t = str(t)
            by_tag[t] = by_tag.get(t, 0) + 1
        src = d.source or ""
        by_source[src] = by_source.get(src, 0) + 1
        if d.created_at:
            m = d.created_at.strftime("%Y-%m")
            by_month[m] = by_month.get(m, 0) + 1

    return {
        "by_kind": [{"key": k, "label": _KIND_LABELS.get(k, k), "count": v}
                    for k, v in sorted(by_kind.items(), key=lambda x: (-x[1], x[0]))],
        "by_ext": [{"key": k, "count": v}
                   for k, v in sorted(by_ext.items(), key=lambda x: (-x[1], x[0]))],
        "by_tag": [{"key": k, "count": v}
                   for k, v in sorted(by_tag.items(), key=lambda x: (-x[1], x[0]))],
        "by_source": [{"key": k, "count": v}
                      for k, v in sorted(by_source.items(), key=lambda x: (-x[1], x[0]))],
        "by_month": [{"month": k, "count": v}
                     for k, v in sorted(by_month.items())],
    }


def _checks(snap: dict, docs: list[Document]) -> list[dict]:
    """体检清单

    每条给：级别 + 标题 + 详情 + 建议（+ 可选的 action=reindex）。
    只列**有问题的**条目 —— 体检报告的价值在异常清单，
    把「一切正常」也塞进列表只会稀释注意力；
    全绿时单独给一条 ok 记录，前端才有绿色可画。
    """
    stats = snap["chunk_stats"]
    meta = snap["meta"]
    embed_dim = snap["embed_dim"]
    checks: list[dict] = []

    def add(key, level, title, detail, hint, *, action=None, count=0, doc_ids=None):
        item = {"key": key, "level": level, "title": title, "detail": detail,
                "hint": hint, "count": count}
        if action:
            item["action"] = action
        if doc_ids:
            item["doc_ids"] = doc_ids
        checks.append(item)

    # 1. 抽取失败
    failed = [d for d in docs if (d.extract_status or "") == "failed"]
    if failed:
        add("extract_failed", "error",
            f"{len(failed)} 篇文档抽取失败",
            f"{_doc_list(failed)} 的正文抽取报错，模型吃不到这些文件的内容",
            "在文档列表点「重建索引」重新抽取；若反复失败，检查文件是否损坏",
            action="reindex", count=len(failed),
            doc_ids=[d.id for d in failed])

    # 2. 抽取还没跑（通常是上传后尚未处理完）
    pending = [d for d in docs if (d.extract_status or "") == "pending"]
    if pending:
        add("extract_pending", "warn",
            f"{len(pending)} 篇文档还没抽取正文",
            f"{_doc_list(pending)} 处于 pending 状态",
            "上传后抽取是异步的，稍等片刻；长期停在这里就点「重建索引」",
            action="reindex", count=len(pending),
            doc_ids=[d.id for d in pending])

    # 3. 有正文却一块都没切出来 —— 切块失败等于没进检索
    no_chunk = [d for d in docs
                if (d.extracted_text or "").strip()
                and stats.get(d.id, {}).get("total", 0) == 0]
    if no_chunk:
        add("no_chunk", "warn",
            f"{len(no_chunk)} 篇文档有正文却没有任何块",
            f"{_doc_list(no_chunk)}：正文非空但 document_chunk 里没有它的块",
            "点「重建索引」重新分块", action="reindex", count=len(no_chunk),
            doc_ids=[d.id for d in no_chunk])

    # 4. 无正文（文档类）
    no_text = [d for d in docs
               if (d.kind or "") == "doc"
               and (d.extract_status or "") != "failed"
               and not (d.extracted_text or "").strip()]
    if no_text:
        add("no_text", "error",
            f"{len(no_text)} 篇文档没有正文",
            f"{_doc_list(no_text)}：抽取完成但正文为空，这类文件喂不进模型",
            "确认文件不是纯图片/扫描件；必要时重新抽取或换成文本副本",
            action="reindex", count=len(no_text),
            doc_ids=[d.id for d in no_text])

    # 5. 图片/音视频没有正文（不算错，但语义检索覆盖不到）
    media = [d for d in docs
             if (d.kind or "") in ("image", "video", "audio")
             and not (d.extracted_text or "").strip()]
    if media:
        add("media_no_text", "warn",
            f"{len(media)} 个图片/音视频没有正文",
            f"{_doc_list(media)}：这类文件不会被切块，语义检索覆盖不到它们",
            "如需纳入语义检索，先做 OCR / 转写，再把文本副本上传进来",
            count=len(media), doc_ids=[d.id for d in media])

    # 6. 未向量化
    not_embedded = [d for d in docs
                    if (d.extracted_text or "").strip()
                    and (d.embed_status or "") in ("pending", "partial", "skipped")]
    if not_embedded:
        add("not_embedded", "warn",
            f"{len(not_embedded)} 篇文档还没向量化",
            f"{_doc_list(not_embedded)}：语义检索会漏掉它们",
            "在文档列表点「重建索引」，或跑 scripts/reindex_all.py",
            action="reindex", count=len(not_embedded),
            doc_ids=[d.id for d in not_embedded])

    # 7. 向量化失败
    embed_failed = [d for d in docs if (d.embed_status or "") == "failed"]
    if embed_failed:
        add("embed_failed", "error",
            f"{len(embed_failed)} 篇文档向量化失败",
            f"{_doc_list(embed_failed)}：embedding 接口没返回结果或向量没写进库",
            "常见原因是额度不足 / 网络不通 / 模型不支持 embedding；"
            "恢复后点「重建索引」重试",
            action="reindex", count=len(embed_failed),
            doc_ids=[d.id for d in embed_failed])

    # 8. 维度与库里的记录不一致
    dim_mismatch = [d for d in docs
                    if (d.embed_dim or 0) > 0 and embed_dim > 0
                    and int(d.embed_dim) != embed_dim]
    if dim_mismatch:
        add("dim_mismatch", "error",
            f"{len(dim_mismatch)} 篇文档的向量维度与库不一致",
            f"{_doc_list(dim_mismatch)}：文档记录 "
            f"{dim_mismatch[0].embed_dim} 维，库里是 {embed_dim} 维，"
            f"这些文档的语义检索结果不可信",
            "切换 embedding 模型后旧向量必须重建；点「重建索引」按新维度重来",
            action="reindex", count=len(dim_mismatch),
            doc_ids=[d.id for d in dim_mismatch])
    elif embed_dim == 0 and any((d.embed_dim or 0) > 0 for d in docs):
        add("dim_missing", "warn",
            "库里没有记录向量维度",
            "文档上写着 embed_dim，但 sys_meta 里没有 embed_dim，"
            "无法判断向量表该是什么维度",
            "重建一次索引即可补上记录", action="reindex")

    # 9. 距离度量不是 cosine
    metric = (meta.get(docindex.META_VEC_METRIC) or "").strip()
    if snap["vec_rows"] > 0 and metric.lower() != docindex.VEC_METRIC:
        add("vec_metric", "error",
            "向量表的距离度量不是 cosine",
            f"当前记录是「{metric or '未记录（默认 L2）'}」，"
            f"而检索代码一律按余弦距离解释 distance，"
            f"两者对不上时排序会与语义相关性脱钩",
            "重建向量表即可（原始向量可以原样搬运，不必重新调用 embedding）",
            action="reindex")

    # 10. 重复文件
    by_sha: dict[str, list[Document]] = {}
    for d in docs:
        if d.sha256:
            by_sha.setdefault(d.sha256, []).append(d)
    dups = [g for g in by_sha.values() if len(g) > 1]
    if dups:
        flat = [d for g in dups for d in g]
        add("duplicate_sha", "warn",
            f"{len(dups)} 组文件内容完全重复",
            f"{_doc_list(flat)}：sha256 相同，同一份文件传了多次",
            "删掉多余的那份可以省下向量空间，也免得检索时同一段话命中好几次",
            count=len(dups), doc_ids=[d.id for d in flat])

    # 11. 空块
    empty_docs = [d for d in docs if stats.get(d.id, {}).get("empty", 0) > 0]
    empty_total = sum(stats.get(d.id, {}).get("empty", 0) for d in docs)
    if empty_total:
        add("empty_chunk", "warn",
            f"{empty_total} 个块是空的",
            f"涉及 {len(empty_docs)} 篇文档（{_doc_list(empty_docs)}）："
            f"空块会白白占用向量名额，还可能把检索结果顶掉",
            "点「重建索引」重新分块即可清掉",
            action="reindex", count=empty_total,
            doc_ids=[d.id for d in empty_docs])

    # 12. 孤儿块
    if snap["orphan_chunks"]:
        add("orphan_chunk", "error",
            f"{snap['orphan_chunks']} 个块指向了不存在的文档",
            "document_chunk 里有块的 document_id 在 document 表里找不到，"
            "这些块既没人认领也没法被检索命中",
            "清理 document_chunk 里的孤儿行（或重建相关文档的索引）",
            count=snap["orphan_chunks"])

    # 13. 已删文档留下的块
    if snap["deleted_chunks"]:
        add("deleted_doc_chunk", "warn",
            f"{snap['deleted_chunks']} 个块属于已删除的文档",
            "这些文档进了回收站，但块还留在库里占着空间，检索时又会被按文档过滤掉",
            "彻底删除回收站里的文件即可清掉",
            count=snap["deleted_chunks"])

    # 14. FTS 不可用
    #
    # 只有「库里有该被索引的东西」时才算问题：
    # 全新部署的库里 FTS/vec 表可能压根还没建，
    # 而库里也一份文件都没有 —— 那不是故障，只是还没开始用。
    has_content = [d for d in docs if (d.extracted_text or "").strip()]
    if not snap["fts_ok"]:
        if has_content:
            add("fts_unavailable", "error",
                "全文索引不可用",
                "FTS5 表不存在或索引损坏，全文检索会降级成 LIKE："
                "慢，而且不支持短语匹配",
                "检查 SQLite 是否编译了 FTS5，然后重建一次全文索引",
                action="reindex")
    else:
        missing = [d for d in docs if d.id not in snap["fts_ids"]]
        if missing:
            add("fts_lag", "warn",
                f"{len(missing)} 篇文档没进全文索引",
                f"{_doc_list(missing)}：FTS 里查不到它们，关键词检索覆盖不到",
                "点「重建索引」补建全文索引",
                action="reindex", count=len(missing),
                doc_ids=[d.id for d in missing])

    # 15. 向量不可用
    if not snap["vec_ok"] and has_content:
        add("vec_unavailable", "error",
            "向量索引不可用",
            "sqlite-vec 扩展没加载或向量表不存在，语义检索完全用不了，"
            "问答只能退化成纯关键词",
            "确认 sqlite-vec 能加载，然后重建一次索引",
            action="reindex")

    # 16. 块与向量对不上
    embedded_total = sum(stats.get(d.id, {}).get("embedded", 0) for d in docs)
    if snap["vec_ok"] and snap["vec_rows"] != embedded_total:
        add("vector_lag", "warn",
            "块数与向量行数对不上",
            f"已嵌入的块 {embedded_total} 个，向量表里 {snap['vec_rows']} 行，"
            f"差 {abs(snap['vec_rows'] - embedded_total)} 条",
            "重建索引，让块与向量重新对齐",
            action="reindex")

    # 17. 孤儿向量
    if snap["vec_orphan"]:
        add("vector_orphan", "warn",
            f"{snap['vec_orphan']} 条向量找不到对应的块",
            "向量表里存在、但 document_chunk 里已经没有的向量："
            "它们会占着向量检索 top-k 的名额，把真正该召回的块挤出去",
            "重建相关文档的索引即可清掉",
            action="reindex", count=snap["vec_orphan"])

    if not checks:
        checks.append({
            "key": "healthy", "level": "ok",
            "title": "体检通过，没有发现问题",
            "detail": f"{len(docs)} 篇文档、{embedded_total} 个块、"
                      f"{snap['vec_rows']} 条向量，索引与内容都对得上",
            "hint": "继续保持；新增资料后建议定期回来体检",
            "count": 0,
        })
    return checks


def _score(checks: list[dict]) -> int:
    """健康分：满分 100，error 扣 8、warn 扣 3，下限 0

    为什么 error 扣得比 warn 重那么多：
    warn 是「可能有影响」（比如一篇没向量化），
    error 是「已经确定有影响」（维度对不上、向量表不可用），
    两者对检索结果的影响不是一个量级。
    """
    score = 100
    for c in checks:
        if c.get("level") == "error":
            score -= SCORE_ERROR_PENALTY
        elif c.get("level") == "warn":
            score -= SCORE_WARN_PENALTY
    return max(0, score)


def _analyze(snap: dict) -> dict:
    """纯计算：把快照变成成分、结构树、指纹与体检结论"""
    docs: list[Document] = snap["docs"]
    stats = snap["chunk_stats"]

    term_stats = [_terms_of(d.extracted_text or "") for d in docs]
    fingerprint = _fingerprint(term_stats, FINGERPRINT_LIMIT)

    outlines: dict[int, list[dict]] = {}
    heading_count: dict[int, int] = {}
    items: list[dict] = []
    for d, tstats in zip(docs, term_stats):
        outline, hcount = _outline_stats(d.extracted_text or "")
        outlines[d.id] = outline
        heading_count[d.id] = hcount
        text_len = len(d.extracted_text or "")
        st = stats.get(d.id, {})
        items.append({
            "id": d.id,
            "title": _doc_label(d),
            "kind": d.kind or "other",
            "ext": d.ext or "",
            "tags": list(d.tags or []),
            "summary": d.summary or "",
            "words": _count_words(d.extracted_text or ""),
            "chars": text_len,
            "chunks": st.get("total", 0),
            "embedded": st.get("embedded", 0),
            "embed_status": d.embed_status or "pending",
            "extract_status": d.extract_status or "pending",
            "has_text": bool((d.extracted_text or "").strip()),
            "sha256": d.sha256 or "",
            "source": d.source or "",
            "storage": d.storage or "fs",
            "created_at": _iso(d.created_at),
            "updated_at": _iso(d.updated_at),
            "headings": hcount,
            "links": len(snap["links_by_doc"].get(d.id, [])),
        })

    checks = _checks(snap, docs)
    embedded_total = sum(i["embedded"] for i in items)
    chunks_total = sum(i["chunks"] for i in items)
    words_total = sum(i["words"] for i in items)

    totals = {
        "documents": len(docs),
        "notes": snap["notes"],
        "chunks": chunks_total,
        "words": words_total,
        "vector_rows": snap["vec_rows"],
        "embedded": embedded_total,
        "links": sum(len(v) for v in snap["links_by_doc"].values()),
        "db_bytes": snap["db_bytes"],
        "vector_bytes": snap["vector_bytes"],
    }

    engine = {
        "embed_model": snap["meta"].get(docindex.META_EMBED_MODEL) or "",
        "embed_dim": snap["embed_dim"],
        "vec_metric": snap["meta"].get(docindex.META_VEC_METRIC) or "",
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "fts_available": snap["fts_ok"],
        "vec_available": snap["vec_ok"],
    }

    return {
        "items": items,
        "outlines": outlines,
        "term_stats": term_stats,
        "fingerprint": fingerprint,
        "checks": checks,
        "checks_summary": {
            "ok": sum(1 for c in checks if c["level"] == "ok"),
            "warn": sum(1 for c in checks if c["level"] == "warn"),
            "error": sum(1 for c in checks if c["level"] == "error"),
        },
        "score": _score(checks),
        "totals": totals,
        "engine": engine,
        "composition": _composition(docs),
    }


# ---------- 对外接口 ----------

async def build_overview(db: AsyncSession, principal: Principal) -> dict:
    """总览：成分 + 指纹 + 体检 + 健康分"""
    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    return {
        "generated_at": snap["generated_at"],
        "totals": ana["totals"],
        "engine": ana["engine"],
        "composition": ana["composition"],
        "fingerprint": ana["fingerprint"],
        "checks": ana["checks"],
        "checks_summary": ana["checks_summary"],
        "score": ana["score"],
    }


async def build_documents(db: AsyncSession, principal: Principal) -> dict:
    """文档谱系列表"""
    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    return {"items": ana["items"]}


async def build_tree(db: AsyncSession, principal: Principal) -> dict:
    """全库结构索引（OpenKB index.md 的等价物）"""
    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    return {"items": [
        {"id": it["id"], "title": it["title"], "words": it["words"],
         "outline": ana["outlines"].get(it["id"], [])}
        for it in ana["items"]
    ]}


async def build_document_detail(db: AsyncSession, principal: Principal,
                                doc_id: int) -> dict | None:
    """单篇 DNA：结构树 + 块清单 + 主题词 + 关联 + 这篇的问题"""
    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    item = next((it for it in ana["items"] if it["id"] == doc_id), None)
    if item is None:
        return None

    doc = next((d for d in snap["docs"] if d.id == doc_id), None)
    document = dict(item)
    document["extracted_chars"] = len(doc.extracted_text or "") if doc else 0

    # 块清单：预览只给前 120 字，够看清这一块在讲什么
    chunk_rows = (await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.seq, DocumentChunk.id)
    )).scalars().all()
    chunks = []
    for c in chunk_rows:
        ctext = (c.text or "").strip()
        heading = ""
        first_line = ctext.split("\n", 1)[0].strip() if ctext else ""
        if _HEADING_RE.match(first_line):
            heading = first_line
        preview = ctext.replace("\n", " ")[:120]
        chunks.append({
            "id": c.id,
            "seq": c.seq or 0,
            "chars": c.char_len or len(ctext),
            "embedded": bool(c.embedded),
            "heading": heading,
            "preview": preview,
        })

    # 这篇的主题词：count 是本篇出现次数，docs 是全库出现在几篇里。
    # 排序用全库权重，而不是只看总榜前 24 ——
    # 一篇文档的主题词往往不在全库前列（它是「局部高信息量」的词），
    # 只按总榜排会把这些词挤掉，最后剩下的全是「谁长谁词多」。
    idx = next(i for i, it in enumerate(ana["items"]) if it["id"] == doc_id)
    tf = ana["term_stats"][idx]
    df_all, weight_all = _term_index(ana["term_stats"])
    terms = sorted(
        ({"term": t, "count": c, "docs": df_all.get(t, 1)} for t, c in tf.items()),
        key=lambda x: (-weight_all.get(x["term"], 0.0), -x["count"], x["term"]),
    )[:DOC_TERM_LIMIT]

    # 这篇的问题：从全局体检清单里挑出提到它的条目
    issues = [{"level": c["level"], "title": c["title"], "detail": c["detail"],
               "hint": c.get("hint", "")}
              for c in ana["checks"]
              if doc_id in (c.get("doc_ids") or [])]

    return {
        "document": document,
        "outline": ana["outlines"].get(doc_id, []),
        "chunks": chunks,
        "terms": terms,
        "links": snap["links_by_doc"].get(doc_id, []),
        "issues": issues,
    }


async def build_report_json(db: AsyncSession, principal: Principal) -> dict:
    """完整 JSON 报告（overview + documents + tree）"""
    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    return {
        "generated_at": snap["generated_at"],
        "overview": {
            "generated_at": snap["generated_at"],
            "totals": ana["totals"],
            "engine": ana["engine"],
            "composition": ana["composition"],
            "fingerprint": ana["fingerprint"],
            "checks": ana["checks"],
            "checks_summary": ana["checks_summary"],
            "score": ana["score"],
        },
        "documents": {"items": ana["items"]},
        "tree": {"items": [
            {"id": it["id"], "title": it["title"], "words": it["words"],
             "outline": ana["outlines"].get(it["id"], [])}
            for it in ana["items"]
        ]},
    }


# ---------- 关联脉络图 ----------

# 图规模上限。前端一次要画几百个节点、几千条边，vis-network 会开始卡；
# 而「这里被截断了」必须让前端知道 —— 静默丢边等于骗人：
# 「图上没连上」会被读成「这两份资料确实没关系」。
GRAPH_NODE_LIMIT = 200
GRAPH_EDGE_LIMIT = 400
# 每篇文件最多收多少小节。一篇长手册能有几十个标题，全收进来节点立刻爆炸，
# 而一屏里人只会盯着十几个标题看。
GRAPH_SECTIONS_PER_DOC = 12

# 节点 id 前缀：看一眼就知道点它会跳到哪儿
DOC_PREFIX = "doc-"
SECTION_PREFIX = "sec-"
RECORD_PREFIX = "rec-"


def _doc_node_id(doc_id: int) -> str:
    return f"{DOC_PREFIX}{doc_id}"


def _section_node_id(doc_id: int, index: int) -> str:
    return f"{SECTION_PREFIX}{doc_id}-{index}"


def _record_node_id(rec_id: int) -> str:
    return f"{RECORD_PREFIX}{rec_id}"


def _normalize_node_id(node_id: str) -> str:
    """graph.py 的节点 id（r-12 / d-3）→ 本契约的 id（rec-12 / doc-3）

    为什么要转：两套前缀各说各话，前端就得为同一张图维护两张对照表。
    而节点 id 的用途只有一个 —— 点节点跳到对应的东西 ——
    统一成「前缀 + 数字」之后，看一眼 id 就知道跳哪儿。
    """
    for prefix, maker in (("r-", _record_node_id), ("d-", _doc_node_id)):
        if node_id.startswith(prefix):
            try:
                return maker(int(node_id[len(prefix):]))
            except ValueError:
                return node_id
    return node_id


def _id_sort_key(node_id: str) -> tuple[str, int, int]:
    """id 的自然序：doc-2 在 doc-10 前面，sec-3-2 在 sec-3-10 前面

    直接按字符串排会得到 doc-10 排在 doc-2 前面 ——
    数字 id 按字典序排是人看的顺序，不是人预期的顺序。
    而且同一份库两次请求必须给出同一个顺序，
    否则前端的图每次刷新都在跳。
    """
    m = re.match(r"^(doc|rec|sec)-(\d+)(?:-(\d+))?$", node_id or "")
    if not m:
        return (node_id or "", 0, 0)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 0))


def _flatten_outline(nodes: list[dict]) -> list[dict]:
    """结构树 → 扁平列表（保持正文里出现的先后顺序）"""
    out: list[dict] = []
    stack = list(reversed(nodes or []))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(node.get("children") or []))
    return out


def _rel_endpoint(rec_id, doc_id) -> str:
    """关系的一端 → 节点 id（记录优先，其次文件，都没有就空）"""
    if rec_id:
        return graph_svc.rid_node_id(rec_id)
    if doc_id:
        return graph_svc.did_node_id(doc_id)
    return ""


def _title_matches(heading: str, doc_label: str) -> bool:
    """这个标题是不是就是文件自己的标题

    为什么要比对：Markdown 正文里的 h1 通常就是文件标题本身
    （「V-MAX Agent 协同记录手册.md」的第一行是
    「# V-MAX Agent 协同记录手册」）。文件节点上已经写着这个标题，
    再画一个小节节点等于同一个东西在图上出现两次。
    比对时忽略扩展名 —— 文件名带 .md，正文里的标题不带。
    """
    h = (heading or "").strip()
    if not h:
        return False
    label = (doc_label or "").strip()
    candidates = {label}
    if "." in label:
        base, _, ext = label.rpartition(".")
        if base and ext.isascii() and ext.isalnum() and len(ext) <= 5:
            candidates.add(base)
    return h in candidates


async def _alive_note_ids(db: AsyncSession) -> set[int] | None:
    """还活着的笔记 id；库里没有笔记模型时返回 None（没东西要过滤）"""
    type_id = (await db.execute(
        select(EntityType.id).where(EntityType.key == "note")
    )).scalar()
    if not type_id:
        return None
    rows = (await db.execute(
        select(EntityRecord.id).where(
            EntityRecord.entity_type_id == type_id,
            EntityRecord.deleted_at.is_(None),
        )
    )).all()
    return {int(r[0]) for r in rows}


async def build_graph(db: AsyncSession, principal: Principal) -> dict:
    """关联脉络图：文件的骨架 + 文件的挂载 + 记录之间的关联

    三层放在同一张图上，因为它们回答的是同一个问题 ——
    「这批资料是怎么长成现在这样的」：
      骨架（文件 → 小节）说结构，挂载（文件 → 记录）说归属，
      关联（记录 → 记录）说流转。
    只画其中一层，另外两层就成了「凭空冒出来的节点」。

    权限：文件与记录各走 access 的统一规则（services/access.py），
    节点过滤交给 graph.filter_graph_by_access ——
    不在这里另写一套；另写一套就意味着迟早有一处漏掉，
    而漏掉的那一处就是一次泄露。

    只读：这个函数只查不写，和本模块其它接口一样。
    """
    if principal is None:
        # 没有身份按本机管理员算（与关闭鉴权时 current_principal 的口径一致）
        principal = Principal(None, admin_perms(), auth_disabled=True)

    snap = await _snapshot(db, principal)
    ana = _analyze(snap)
    doc_items = {it["id"]: it for it in ana["items"]}

    # 记录侧脉络：业务关联（记录 ↔ 记录 / 文件）与笔记双链
    biz = await graph_svc.get_global_graph(
        db, limit=GRAPH_NODE_LIMIT, principal=principal)
    notes = await graph_svc.get_notes_graph(db, limit=GRAPH_NODE_LIMIT)

    nodes_by_id: dict[str, dict] = {}
    edges_by_id: dict[str, dict] = {}
    for part in (biz, notes):
        for n in part.get("nodes") or []:
            nodes_by_id[n["id"]] = n
        for e in part.get("edges") or []:
            edges_by_id[e["id"]] = e

    # 全部文件都要进图。
    #
    # 为什么不能只留「被关系/挂载提到」的那些：养料图谱讲的是
    # 「这批资料长什么样」，一份没跟任何记录沾边的文件同样在养料里 ——
    # 它只是还没被人挂到记录上，不代表它不重要。
    # 漏掉它们，这些文件连同它们的结构骨架就整段消失了。
    for doc_id in doc_items:
        nid = graph_svc.did_node_id(doc_id)
        nodes_by_id.setdefault(nid, {
            "id": nid, "kind": "document", "ref_id": doc_id,
        })

    # 回收站里的笔记不进图。
    # graph.get_notes_graph 没有排除软删除的记录（老问题）：
    # 「已经删掉」的东西还带着标题站在图上，等于删除没生效。
    alive_notes = await _alive_note_ids(db)
    if alive_notes is not None:
        for nid in [nid for nid, n in nodes_by_id.items()
                    if n.get("kind") == "record" and n.get("type") == "note"
                    and int(n.get("ref_id") or 0) not in alive_notes]:
            nodes_by_id.pop(nid, None)

    # 挂载边：文件 → 挂在它上面的记录
    #
    # 为什么自己查 document_link 而不是直接用 graph.py 那条：
    # 那边只给业务记录补挂载的文件，笔记挂着附件时那条边根本不会出现 ——
    # 而「这条笔记是看着这份 PDF 写的」恰恰是脉络图最该说的话。
    # 方向也要反过来：契约里挂载边是「文件 → 记录」。
    mount_rows = (await db.execute(
        select(DocumentLink, Document, EntityRecord)
        .join(Document, Document.id == DocumentLink.document_id)
        .join(EntityRecord, EntityRecord.id == DocumentLink.record_id)
        .where(Document.deleted_at.is_(None),
               EntityRecord.deleted_at.is_(None))
    )).all()
    # 字段名要人看得懂的那一份（files → 附件），不是字段 key。
    # 图上一条边写「字段：files」谁也看不懂它挂的是什么。
    field_names: dict[tuple[int, str], str] = {}
    for fd in (await db.execute(
        select(FieldDefinition).where(
            FieldDefinition.type.in_(("file", "image")))
    )).scalars().all():
        field_names[(fd.entity_type_id, fd.key)] = fd.name
    for link, doc, rec in mount_rows:
        rec_nid = graph_svc.rid_node_id(rec.id)
        if rec_nid not in nodes_by_id:
            continue                      # 记录不在图里，挂载也就无从说起
        if doc.id not in doc_items:
            continue                      # 读不到的文件不进图
        doc_nid = graph_svc.did_node_id(doc.id)
        nodes_by_id.setdefault(doc_nid, {
            "id": doc_nid, "kind": "document", "ref_id": doc.id,
        })
        field_label = (field_names.get((rec.entity_type_id, link.field_key or ""))
                       or link.field_key or "附件")
        edges_by_id[f"dl-{link.id}"] = {
            "id": f"dl-{link.id}",
            "source": doc_nid, "target": rec_nid,
            "relation": f"字段：{field_label}",
            "via": "field",
        }

    # 补齐被 get_global_graph 丢掉的关联边
    #
    # 丢在哪：get_global_graph 明确把笔记排除在业务图之外
    # （那是「关联图谱」的分工 —— 笔记归「知识图谱」），
    # 于是「业务记录 ↔ 笔记」这类关系的另一端没有节点，边被丢掉了。
    # 脉络图里笔记和记录同处一张图，这种边不补，图就是断的。
    rec_ids = [int(n["ref_id"]) for n in nodes_by_id.values()
               if n.get("kind") == "record"]
    if rec_ids:
        rel_rows = (await db.execute(
            select(RelationRecord, RelationDef)
            .join(RelationDef, RelationDef.id == RelationRecord.relation_def_id,
                  isouter=True)
            .where(or_(
                RelationRecord.source_record_id.in_(rec_ids),
                RelationRecord.target_record_id.in_(rec_ids),
            ))
        )).all()
        for rel, rdef in rel_rows:
            eid = f"rr-{rel.id}"
            if eid in edges_by_id:
                continue
            src = _rel_endpoint(rel.source_record_id, rel.source_document_id)
            tgt = _rel_endpoint(rel.target_record_id, rel.target_document_id)
            if src not in nodes_by_id or tgt not in nodes_by_id:
                continue
            edges_by_id[eid] = {
                "id": eid, "source": src, "target": tgt,
                "relation": rdef.name if rdef else "关联",
                "via": "relation",
            }

    # 权限过滤统一走 graph 那条路（文件按 access 的文件规则，
    # 记录按模型读权限），摘掉读不到的节点与指向它们的边
    merged = await graph_svc.filter_graph_by_access(
        db, principal,
        {"nodes": list(nodes_by_id.values()),
         "edges": list(edges_by_id.values())})

    # ---------- 换成契约里的节点/边形状 ----------

    nodes: list[dict] = []
    edges: list[dict] = []
    doc_of_node: dict[str, int] = {}

    for n in merged["nodes"]:
        kind = n.get("kind")
        nid = _normalize_node_id(n["id"])
        if kind == "document":
            item = doc_items.get(n.get("ref_id"))
            if item is None:
                continue          # 读不到的文件不进图
            doc_of_node[nid] = int(n["ref_id"])
            nodes.append({
                "id": nid,
                "kind": "document",
                "ref_id": int(n["ref_id"]),
                "label": item["title"],
                "meta": {
                    "type": item["kind"],
                    "words": item["words"],
                    "chunks": item["chunks"],
                },
            })
        elif kind == "record":
            nodes.append({
                "id": nid,
                "kind": "record",
                "ref_id": int(n["ref_id"]),
                "label": n.get("label") or f"记录 #{n['ref_id']}",
                "meta": {
                    "type": n.get("type") or "",
                    "entity_type": n.get("type_name") or "",
                },
            })

    # 骨架：文件 → 它的小节
    for nid, doc_id in doc_of_node.items():
        doc_label = (doc_items.get(doc_id) or {}).get("title") or ""
        picked: list[dict] = []
        for sec in _flatten_outline(ana["outlines"].get(doc_id) or []):
            title = sec.get("title") or ""
            if not picked and _title_matches(title, doc_label):
                # 与文件标题重复的那个标题不单独成节：
                # 文件节点上已经写着这个标题了，
                # 再画一个小节节点等于同一个东西在图上出现两次。
                continue
            picked.append(sec)
            if len(picked) >= GRAPH_SECTIONS_PER_DOC:
                break
        for index, sec in enumerate(picked):
            sid = _section_node_id(doc_id, index)
            nodes.append({
                "id": sid,
                "kind": "section",
                "label": sec.get("title") or "正文",
                "meta": {
                    "document_id": doc_id,
                    "level": int(sec.get("level") or 1),
                },
            })
            edges.append({
                "source": nid, "target": sid,
                "kind": "structure", "label": "章节",
            })

    for e in merged["edges"]:
        src = _normalize_node_id(e.get("source") or "")
        tgt = _normalize_node_id(e.get("target") or "")
        if not src or not tgt or src == tgt:
            continue
        label = e.get("relation") or "关联"
        if e.get("via") == "field":
            # 挂载边：方向统一成「文件 → 记录」
            if src.startswith(RECORD_PREFIX) and tgt.startswith(DOC_PREFIX):
                src, tgt = tgt, src
            kind = "attach"
        elif src.startswith(DOC_PREFIX) or tgt.startswith(DOC_PREFIX):
            # 文件为端点的关系（文件归属项目之类）也归挂载：
            # 契约里只有三类边，没有「文件关系」这一类，
            # 而它讲的同样是「这个文件挂在那条记录上」。
            if src.startswith(RECORD_PREFIX):
                src, tgt = tgt, src
            kind = "attach"
        else:
            kind = "relation"
        edges.append({"source": src, "target": tgt,
                      "kind": kind, "label": label})

    # 去重：同一对节点之间、同一种边、同一种说法只留一条
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for e in edges:
        key = (e["source"], e["target"], e["kind"], e["label"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    edges = uniq

    # ---------- 规模控制与稳定排序 ----------

    nodes.sort(key=lambda n: (n["kind"], _id_sort_key(n["id"])))
    truncated = False
    if len(nodes) > GRAPH_NODE_LIMIT:
        nodes = nodes[:GRAPH_NODE_LIMIT]
        truncated = True
    kept = {n["id"] for n in nodes}

    # 节点被截掉之后，指向它的边就成了悬空的线 —— 一并摘掉
    edges = [e for e in edges
             if e["source"] in kept and e["target"] in kept]
    edges.sort(key=lambda e: (e["kind"], _id_sort_key(e["source"]),
                               _id_sort_key(e["target"]), e["label"]))
    if len(edges) > GRAPH_EDGE_LIMIT:
        edges = edges[:GRAPH_EDGE_LIMIT]
        truncated = True
    # 边 id 最后统一编号：前端只要认 e1/e2/... 就行
    for i, e in enumerate(edges, 1):
        e["id"] = f"e{i}"

    stats = {
        "documents": sum(1 for n in nodes if n["kind"] == "document"),
        "sections": sum(1 for n in nodes if n["kind"] == "section"),
        "records": sum(1 for n in nodes if n["kind"] == "record"),
        "edges": len(edges),
        "truncated": truncated,
    }
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
        # 截断必须说清楚：不说就等于骗人 ——
        # 「图上没有」会被读成「确实没关系」。
        "meta": {
            "truncated": truncated,
            "node_limit": GRAPH_NODE_LIMIT,
            "edge_limit": GRAPH_EDGE_LIMIT,
            "sections_per_doc": GRAPH_SECTIONS_PER_DOC,
            "note": ("节点或边超出上限，已按稳定序截断；"
                     "被截掉的内容不在图里") if truncated else "",
        },
    }


# ---------- Markdown 报告 ----------

def _md_outline(nodes: list[dict], depth: int = 0) -> list[str]:
    """结构树 → Markdown 列表

    缩进用 2 空格：4 空格在 Markdown 里会被当成代码块，
    6 级标题缩进到第 4 层就会踩这个坑。
    """
    lines: list[str] = []
    for n in nodes:
        lines.append(f"{'  ' * depth}- {n['title']}（h{n['level']}）")
        lines.extend(_md_outline(n.get("children") or [], depth + 1))
    return lines


def render_report_markdown(report: dict) -> str:
    """把 JSON 报告渲染成一份可以直接贴给 agent 的 Markdown

    这份 Markdown 就是 OpenKB 的 AGENTS.md 的等价物：
    人和模型都靠它快速搞清「这批资料里有什么、能不能用」。
    """
    ov = report["overview"]
    totals = ov["totals"]
    engine = ov["engine"]
    lines: list[str] = []

    lines.append("# 养料 DNA 体检报告")
    lines.append("")
    lines.append(f"> 生成时间：{ov['generated_at']}　|　"
                 f"健康分 **{ov['score']} / 100**")
    lines.append("")

    # 一、体检结论
    lines.append("## 一、体检结论")
    lines.append("")
    if ov["checks_summary"]["error"] or ov["checks_summary"]["warn"]:
        lines.append("| 级别 | 问题 | 详情 | 建议 |")
        lines.append("|---|---|---|---|")
        for c in ov["checks"]:
            mark = {"error": "🔴 错误", "warn": "🟡 警告", "ok": "🟢 正常"}.get(c["level"], c["level"])
            lines.append(f"| {mark} | {c['title']} | {c['detail']} | {c.get('hint', '')} |")
    else:
        lines.append("🟢 体检通过，没有发现问题。")
    lines.append("")

    # 二、成分
    lines.append("## 二、成分")
    lines.append("")
    lines.append(f"- 文档 **{totals['documents']}**　笔记 **{totals['notes']}**　"
                 f"块 **{totals['chunks']}**　字数 **{totals['words']}**")
    lines.append(f"- 向量行 **{totals['vector_rows']}**　已嵌入 **{totals['embedded']}**　"
                 f"链接 **{totals['links']}**")
    lines.append(f"- 库体积 **{_fmt_bytes(totals['db_bytes'])}**　"
                 f"向量体积 **{_fmt_bytes(totals['vector_bytes'])}**")
    lines.append(f"- 引擎：{engine.get('embed_model') or '未配置'} / "
                 f"{engine.get('embed_dim') or '?'} 维 / "
                 f"{engine.get('vec_metric') or '?'} / "
                 f"分块 {engine.get('chunk_size')} + {engine.get('chunk_overlap')}　"
                 f"FTS {'可用' if engine.get('fts_available') else '不可用'}　"
                 f"向量 {'可用' if engine.get('vec_available') else '不可用'}")
    lines.append("")

    comp = ov["composition"]
    if comp["by_kind"]:
        lines.append("### 按类型")
        lines.append("")
        for it in comp["by_kind"]:
            lines.append(f"- {it['label']}：{it['count']}")
        lines.append("")
    if comp["by_tag"]:
        lines.append("### 按标签")
        lines.append("")
        for it in comp["by_tag"]:
            lines.append(f"- {it['key']}：{it['count']}")
        lines.append("")
    if comp["by_source"]:
        lines.append("### 按来源")
        lines.append("")
        for it in comp["by_source"]:
            lines.append(f"- {it['key']}：{it['count']}")
        lines.append("")
    if comp["by_month"]:
        lines.append("### 按月份")
        lines.append("")
        for it in comp["by_month"]:
            lines.append(f"- {it['month']}：{it['count']}")
        lines.append("")

    # 三、结构树
    lines.append("## 三、结构树")
    lines.append("")
    for item in report["tree"]["items"]:
        lines.append(f"### {item['title']}（{item['words']} 字）")
        lines.append("")
        outline = item["outline"] or []
        if outline:
            lines.extend(_md_outline(outline))
        else:
            lines.append("- （无结构）")
        lines.append("")

    # 四、主题指纹
    lines.append("## 四、主题指纹")
    lines.append("")
    if ov["fingerprint"]:
        lines.append("| 词条 | 权重 | 出现文档数 |")
        lines.append("|---|---|---|")
        for f in ov["fingerprint"]:
            lines.append(f"| {f['term']} | {f['weight']} | {f['docs']} |")
    else:
        lines.append("（没有可提取的主题词）")
    lines.append("")

    return "\n".join(lines)
