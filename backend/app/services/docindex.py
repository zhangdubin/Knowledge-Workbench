"""文档索引层：FTS5 全文索引 + sqlite-vec 向量索引

三个不那么显然但很关键的取舍：

1. **中文必须逐字切分再入 FTS5**
   SQLite 的 unicode61 分词器把一整串汉字当作「一个词」
   （"采购合同" → 单个 token），而 trigram 分词器虽然支持子串匹配，
   却要求查询至少 3 个字符 —— 实测「深圳」这种两字查询直接返回空。
   所以这里把 CJK 逐字用空格隔开再入库（"采购合同" → "采 购 合 同"），
   查询同样处理并整体作为短语匹配。两字/四字/长句全部命中。

2. **向量表维度不能写死**
   MiniMax embo-01 的维度在不同资料里有 1024 / 1536 两种说法，
   硬编码会导致插入时维度不匹配。因此维度在首次调用 embedding 后
   探测得到，存进 sys_meta，再据此创建 vec0 表。

3. **索引失败不应影响业务**
   FTS5 / vec0 都是「增强」。文件能不能存、能不能看，不依赖它们，
   所以这里的异常一律吞掉并降级。
"""
from __future__ import annotations

import logging
import math
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings

log = logging.getLogger("kb.index")

# 覆盖基本汉字区 + 扩展 A 区
CJK_RE = re.compile(r"([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])")

FTS_TABLE = "document_fts"
VEC_TABLE = "document_vec"
META_EMBED_DIM = "embed_dim"
META_EMBED_MODEL = "embed_model"
META_VEC_METRIC = "vec_metric"

# 距离度量。vec0 不写这个参数时默认是 L2（欧氏距离），
# 而检索代码一直按「余弦距离」在解释 distance 值 —— 注释与实现对不上。
# 更要命的是：换 embedding 模型后如果新模型输出的向量没有归一化，
# L2 排序会被向量模长带偏，跟语义相关性脱钩。
# 写死 cosine，distance 就恒等于 1 - cos_sim，含义永远成立。
VEC_METRIC = "cosine"


# ---------- 中文分词与查询构造 ----------

def seg_cjk(value: str) -> str:
    """把 CJK 逐字用空格隔开，拉丁词与数字保持完整"""
    return CJK_RE.sub(r" \1 ", value or "")


def fts_query(query: str) -> str:
    """把用户输入转成安全的 FTS5 短语查询

    整体用双引号包成短语，这样：
      - 中文不会被拆成多个必须同时出现的独立 token（避免语义漂移）
      - `AND` / `OR` / `NEAR` / `*` / `(` 等 FTS5 语法符号失效为普通字符，
        用户随手输入 `(` 或 `a*b` 不会导致 SQL 报错
    """
    q = (query or "").strip()
    if not q:
        return ""
    s = " ".join(seg_cjk(q).split())
    return '"' + s.replace('"', '""') + '"'


def tokenize_for_index(*values: str) -> str:
    """把标题/正文等字段拼成入库文本"""
    return "\n".join(seg_cjk(v) for v in values if v)


# ---------- 建表 ----------

async def ensure_index_tables(conn) -> None:
    """创建 FTS5 表；向量表若已知维度则一并创建"""
    # 全文索引 —— 不依赖任何扩展
    try:
        await conn.execute(text(
            f"create virtual table if not exists {FTS_TABLE} using fts5("
            "title, body, tokenize='unicode61 remove_diacritics 2')"
        ))
    except Exception as e:
        log.warning("FTS5 索引表创建失败，全文检索将降级为 LIKE：%s", e)

    # 向量索引 —— 需要 sqlite-vec 扩展
    dim = await get_meta(conn, META_EMBED_DIM)
    if dim:
        await ensure_vec_table(conn, int(dim))


async def ensure_vec_table(conn, dim: int) -> bool:
    """确保向量表存在、维度正确、距离度量正确

    三种情况：

    1. **维度变化**（切换 embedding 模型，1024 ↔ 1536）—— 旧向量无法复用，
       必须 DROP 后重建，并清空所有 chunk 的 embedded 标记等待重新向量化。
    2. **距离度量变化**（老库建表时没写 distance_metric，默认是 L2）——
       向量本身是原始 float32，**可以原样搬到新表**，不必重新调用
       embedding 接口（那是要花钱的）。
    3. 一切正常 —— 什么都不做。
    """
    if dim <= 0:
        return False
    try:
        existing = await get_meta(conn, META_EMBED_DIM)
        cur_dim = int(existing) if existing else 0
        metric = await get_meta(conn, META_VEC_METRIC)
        table_exists = await _table_exists(conn, VEC_TABLE)

        if table_exists and cur_dim and cur_dim != dim:
            log.warning("向量维度由 %s 变为 %s，重建向量表", cur_dim, dim)
            await conn.execute(text(f"drop table if exists {VEC_TABLE}"))
            await conn.execute(text("update document_chunk set embedded = 0"))
            # 只清 chunk 的 embedded 位不够：document.embed_status 还停在 'ok'，
            # 后台补向量任务只挑 pending/failed —— 于是这些文件永远不会被
            # 重新向量化，语义检索静默失效，且体检面板还显示「已建向量索引」。
            await conn.execute(
                text("update document set embed_status = 'pending' "
                     "where embed_status in ('ok', 'partial')")
            )
            table_exists = False

        if table_exists and metric != VEC_METRIC:
            # 老表没有度量记录（默认 L2），或度量被改过：
            # 向量字节可以原样搬过去，重建表但不重新向量化
            log.warning("向量表距离度量由 %s 变为 %s，重建向量表并搬运原有向量",
                        metric or "L2(默认)", VEC_METRIC)
            saved = await _dump_vectors(conn)
            await conn.execute(text(f"drop table if exists {VEC_TABLE}"))
            await conn.execute(text(
                f"create virtual table {VEC_TABLE} using vec0("
                f"embedding float[{dim}] distance_metric={VEC_METRIC})"
            ))
            moved = 0
            for cid, blob in saved:
                try:
                    await conn.execute(
                        text(f"insert into {VEC_TABLE}(rowid, embedding) "
                             "values (:r, :e)"), {"r": cid, "e": blob})
                    moved += 1
                except Exception as e:
                    log.warning("向量搬运失败 chunk=%s：%s", cid, e)
            log.info("已搬运 %s/%s 条向量到新表", moved, len(saved))
            table_exists = True

        if not table_exists:
            await conn.execute(text(
                f"create virtual table {VEC_TABLE} using vec0("
                f"embedding float[{dim}] distance_metric={VEC_METRIC})"
            ))
        await set_meta(conn, META_EMBED_DIM, str(dim))
        await set_meta(conn, META_VEC_METRIC, VEC_METRIC)
        return True
    except Exception as e:
        log.warning("向量表创建失败，语义检索将不可用：%s", e)
        return False


async def _dump_vectors(conn, batch: int = 500) -> list[tuple[int, bytes]]:
    """把向量表里的原始字节取出来（用于换表时原样搬运）

    分批取，别一次性把整库向量读进内存 —— 20 万条 × 6 KB 就是 1.2 GB。
    """
    out: list[tuple[int, bytes]] = []
    last = 0
    while True:
        rows = (await conn.execute(
            text(f"select rowid, embedding from {VEC_TABLE} "
                 "where rowid > :last order by rowid limit :lim"),
            {"last": last, "lim": batch},
        )).all()
        if not rows:
            break
        for rid, blob in rows:
            out.append((rid, blob))
            last = rid
    return out


def similarity(distance: float, metric: str | None) -> float:
    """把 vec0 给的 distance 换算成 0~1 的相似度

    cosine 表：distance = 1 - cos_sim，直接取补。
    L2 老表：单位向量下 cos = 1 - d²/2（embo-01 实测模长恒为 1）。
    """
    d = float(distance or 0.0)
    if metric == VEC_METRIC:
        return max(0.0, min(1.0, 1.0 - d))
    return max(0.0, min(1.0, 1.0 - (d * d) / 2.0))


async def _table_exists(conn, name: str) -> bool:
    r = await conn.execute(
        text("select 1 from sqlite_master where type='table' and name=:n"), {"n": name}
    )
    return r.scalar() is not None


# ---------- sys_meta 读写 ----------

async def get_meta(conn, key: str) -> str | None:
    r = await conn.execute(text("select value from sys_meta where key=:k"), {"k": key})
    row = r.scalar()
    return row


async def set_meta(conn, key: str, value: str) -> None:
    await conn.execute(text(
        "insert into sys_meta(key, value, updated_at) values (:k, :v, datetime('now')) "
        "on conflict(key) do update set value=:v, updated_at=datetime('now')"
    ), {"k": key, "v": value})


# ---------- 文档写入索引 ----------

async def index_document(db: AsyncSession, doc_id: int, title: str,
                         filename: str, tags: list | None,
                         summary: str, body: str) -> None:
    """把文档写进 FTS5（rowid = document.id，先删后插保证幂等）"""
    try:
        await db.execute(
            text(f"delete from {FTS_TABLE} where rowid = :rid"), {"rid": doc_id}
        )
        await db.execute(
            text(f"insert into {FTS_TABLE}(rowid, title, body) values (:rid, :t, :b)"),
            {
                "rid": doc_id,
                "t": tokenize_for_index(title, filename, " ".join(tags or [])),
                "b": tokenize_for_index(summary, body),
            },
        )
    except Exception as e:
        log.warning("FTS 索引写入失败 doc=%s：%s", doc_id, e)


async def remove_fts(db: AsyncSession, doc_id: int) -> None:
    """只从 FTS5 移除，不动向量表（供「仅重建全文索引」的场景使用）"""
    try:
        await db.execute(text(f"delete from {FTS_TABLE} where rowid = :rid"), {"rid": doc_id})
    except Exception as e:
        log.warning("FTS 索引删除失败 doc=%s：%s", doc_id, e)


async def remove_document(db: AsyncSession, doc_id: int) -> None:
    """从 FTS5 与向量表移除文档"""
    await remove_fts(db, doc_id)

    try:
        rows = (await db.execute(
            text("select id from document_chunk where document_id = :d"), {"d": doc_id}
        )).scalars().all()
        for cid in rows:
            await db.execute(
                text(f"delete from {VEC_TABLE} where rowid = :rid"), {"rid": cid}
            )
    except Exception as e:
        log.warning("向量索引删除失败 doc=%s：%s", doc_id, e)


# ---------- 检索 ----------

async def fts_search(db: AsyncSession, query: str, limit: int = 30) -> list[dict]:
    """FTS5 检索，返回 [{document_id, score}]（score 越大越相关）"""
    fq = fts_query(query)
    if not fq:
        return []
    try:
        rows = (await db.execute(
            text(f"select rowid, bm25({FTS_TABLE}) as r from {FTS_TABLE} "
                 f"where {FTS_TABLE} match :q order by rank limit :lim"),
            {"q": fq, "lim": limit},
        )).all()
        # bm25() 是「越小越相关」的负数，取反得到越大越相关
        return [{"document_id": r[0], "score": -float(r[1] or 0.0)} for r in rows]
    except Exception as e:
        log.warning("FTS 检索失败（降级为 LIKE）：%s", e)
        return await like_search(db, query, limit)


async def like_search(db: AsyncSession, query: str, limit: int = 30) -> list[dict]:
    """兜底：短查询或 FTS 不可用时的 LIKE 检索"""
    kw = (query or "").strip()
    if not kw:
        return []
    like = f"%{kw}%"
    rows = (await db.execute(
        text(
            "select id, "
            "  (case when title like :l then 2 else 0 end) "
            "+ (case when filename like :l then 1 else 0 end) as score "
            "from document where deleted_at is null "
            "and (title like :l or filename like :l or tags like :l or extracted_text like :l) "
            "order by score desc, id desc limit :lim"
        ),
        {"l": like, "lim": limit},
    )).all()
    return [{"document_id": r[0], "score": float(r[1] or 0.0) + 0.5} for r in rows]


async def vec_search(db: AsyncSession, vector: list[float], limit: int = 30) -> list[dict]:
    """向量 KNN 检索，返回 [{chunk_id, document_id, distance, text}]

    这里把命中块的正文一并带出来。块是向量检索的最小单位，
    也是唯一知道「答案落在哪一段」的东西 —— 只回一个 document_id，
    等于把这个信息扔掉：上层只好重新拿整篇文档的前几千字去喂模型，
    长文档里命中在后面的段落就永远答不对（这正是「向量库换了也没用」
    的根因：索引准了，取材没跟上）。
    """
    if not vector:
        return []
    try:
        import sqlite_vec
        blob = sqlite_vec.serialize_float32(vector)
        rows = (await db.execute(
            text(
                f"select rowid, distance from {VEC_TABLE} "
                "where embedding match :q order by distance limit :lim"
            ),
            {"q": blob, "lim": limit},
        )).all()
        if not rows:
            return []
        chunk_ids = [r[0] for r in rows]
        # 把 chunk 映射回 document，顺带把块的正文取出来
        id_map = {}
        qmarks = ",".join(f":c{i}" for i in range(len(chunk_ids)))
        params = {f"c{i}": cid for i, cid in enumerate(chunk_ids)}
        cmap = (await db.execute(
            text(f"select id, document_id, text from document_chunk where id in ({qmarks})"),
            params,
        )).all()
        for cid, did, ctext in cmap:
            id_map[cid] = (did, ctext or "")

        out = []
        for cid, dist in rows:
            got = id_map.get(cid)
            if got is None:
                continue
            did, ctext = got
            out.append({
                "chunk_id": cid,
                "document_id": did,
                "distance": float(dist),
                "text": ctext,
            })
        return out
    except Exception as e:
        log.warning("向量检索失败：%s", e)
        return []


# ---------- 块级关键词定位 ----------

# 连续汉字串 / 拉丁词
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
_LATIN_RUN = re.compile(r"[A-Za-z0-9_.\-]{2,}")


_WS_RE = re.compile(r"\s+")


def _flat(text: str) -> str:
    """去掉所有空白 —— 中文正文里的换行会把词劈开，比对前要先压平"""
    return _WS_RE.sub("", text or "")


def keyword_terms(query: str, max_cjk: int = 12, max_latin: int = 6) -> list[str]:
    """把查询拆成用于块级扫描的关键词

    为什么不能直接拿原句去 LIKE：用户问的是「项目预算是多少」，
    正文里根本不会出现这整句话，永远命中不了。
    改成「连续汉字取 2 字滑窗 + 拉丁词整词」，命中面宽但不啰嗦。

    拉丁词单独留配额：像 vault、agent、git 这类词，
    往往比汉字滑窗更有指向性，不能被汉字挤掉。
    """
    q = (query or "").strip()
    if not q:
        return []
    latin: list[str] = []
    for w in _LATIN_RUN.findall(q):
        w = w.lower()
        if w not in latin:
            latin.append(w)
    cjk: list[str] = []
    for run in _CJK_RUN.findall(q):
        for i in range(len(run) - 1):
            t = run[i:i + 2]
            if t not in cjk and t not in latin:
                cjk.append(t)
    return latin[:max_latin] + cjk[:max_cjk]


async def chunk_keyword_scan(db: AsyncSession, doc_ids: list[int], query: str,
                             limit: int = 12, max_docs: int = 6,
                             max_chunks: int = 1500) -> list[dict]:
    """在指定文档的块里做关键词定位

    FTS5 表一行一篇文档（rowid = document.id），所以关键词通道只能
    告诉你「哪篇文档相关」，说不出「哪一段相关」。长文档里答案常在
    中间偏后，只给模型整篇开头就会答不上来 —— 这一步补上块级定位。

    打分用 BM25 那套 idf：命中「写入」这种到处都是的词，
    不该和命中「27123」这种只出现一次的词等价。
    没有 idf 时，问句里的「是什么」「会怎样」会跟正文里任何一块
    打成平手，真正稀有的那条反而被淹没。

    匹配前把空白去掉再比：抽取出来的正文里，一个词被换行劈开是常事
    （「涉密信息\\n系统集成」），带空白的 LIKE 永远匹配不上，
    带空白的整词查询也会失手。

    只在排名靠前的几篇文档里扫，不扫全库：块级扫描是补漏，不是主通道。
    """
    terms = keyword_terms(query)
    if not terms or not doc_ids:
        return []
    docs = list(dict.fromkeys(int(d) for d in doc_ids))[:max_docs]
    qmarks = ",".join(f":d{i}" for i in range(len(docs)))
    params = {f"d{i}": d for i, d in enumerate(docs)}
    try:
        rows = (await db.execute(
            text(f"select id, document_id, seq, text from document_chunk "
                 f"where document_id in ({qmarks}) limit :lim"),
            {**params, "lim": max_chunks},
        )).all()
    except Exception as e:
        log.warning("块级关键词扫描失败：%s", e)
        return []
    if not rows:
        return []

    flat_terms = [_flat(t) for t in terms]
    total = len(rows)
    df = [0] * len(terms)
    flats = []
    for _cid, _did, _seq, ctext in rows:
        flat = _flat(ctext or "")
        flats.append(flat)
        for i, ft in enumerate(flat_terms):
            if ft and ft in flat:
                df[i] += 1
    idf = [math.log(1.0 + (total - d + 0.5) / (d + 0.5)) for d in df]

    out = []
    for (cid, did, seq, ctext), flat in zip(rows, flats):
        matched = [i for i, ft in enumerate(flat_terms) if ft and ft in flat]
        out.append({
            "chunk_id": cid,
            "document_id": did,
            "seq": seq,
            "text": ctext or "",
            "hits": len(matched),
            "score": sum(idf[i] for i in matched),
        })
    out.sort(key=lambda x: (-x["score"], -x["hits"], x["chunk_id"]))
    return out[:limit]
