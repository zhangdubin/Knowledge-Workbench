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
    """确保向量表存在且维度正确；维度变化时重建

    切换 embedding 模型会导致维度不同（1024 ↔ 1536），此时旧表无法复用，
    必须 DROP 后重建，并清空所有 chunk 的 embedded 标记等待重新向量化。
    """
    if dim <= 0:
        return False
    try:
        existing = await get_meta(conn, META_EMBED_DIM)
        cur_dim = int(existing) if existing else 0
        table_exists = await _table_exists(conn, VEC_TABLE)

        if table_exists and cur_dim and cur_dim != dim:
            log.warning("向量维度由 %s 变为 %s，重建向量表", cur_dim, dim)
            await conn.execute(text(f"drop table if exists {VEC_TABLE}"))
            await conn.execute(text("update document_chunk set embedded = 0"))
            table_exists = False

        if not table_exists:
            await conn.execute(text(
                f"create virtual table {VEC_TABLE} using vec0(embedding float[{dim}])"
            ))
        await set_meta(conn, META_EMBED_DIM, str(dim))
        return True
    except Exception as e:
        log.warning("向量表创建失败，语义检索将不可用：%s", e)
        return False


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
    """向量 KNN 检索，返回 [{document_id, distance}]"""
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
        # 把 chunk 映射回 document
        id_map = {}
        qmarks = ",".join(f":c{i}" for i in range(len(chunk_ids)))
        params = {f"c{i}": cid for i, cid in enumerate(chunk_ids)}
        cmap = (await db.execute(
            text(f"select id, document_id from document_chunk where id in ({qmarks})"),
            params,
        )).all()
        for cid, did in cmap:
            id_map[cid] = did

        out = []
        for cid, dist in rows:
            did = id_map.get(cid)
            if did is not None:
                out.append({"document_id": did, "distance": float(dist)})
        return out
    except Exception as e:
        log.warning("向量检索失败：%s", e)
        return []
