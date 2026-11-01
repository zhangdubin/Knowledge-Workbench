"""DNA 养料库打包 / 导入 / 离线可用性自检

这个模块要解决的是「断网时系统还能不能跑」这件事。
知识工作台的离线能力不是靠「把模型塞进容器」实现的 ——
那是另一个量级的工程 —— 而是靠**养料库自带一份可搬运的副本**：
把库里的基因、证据、向量、全文索引打成一个自包含的包，
带到没网的机器上 unpack 就能查、能答。

三个对外动作：

    export_bundle   打包（读）
    inspect_bundle  验包（只读，不落盘解压）
    import_bundle   装包（写）
    bundle_readiness 自检：这台机器现在离线可用吗

几个刻意选出来的做法，理由比做法本身重要：

1. **FTS5 虚表不能直接 dump，必须重建。**
   document_fts / chunk_fts / dna_gene_fts 都是 FTS5 虚表，
   它们的物理结构（_data / _idx / _content / _docsize …）是 SQLite 内部格式，
   跨版本、跨构建都不保证能认。所以包里带的 fts.sqlite 是**重新建的**：
   用 docindex 里同一套分词函数，把同一批文本重新灌进去。

   分词函数必须**从 docindex 导入**，不能在这里抄一份。
   两边一旦不一致，后果不是报错，是「查得到但排序全乱」或者「永远查不到」——
   查询语法合法，不报错，只是匹配不上，是最难排查的那类故障。
   所以本模块只调用 docindex.seg_bigram / tokenize_for_index /
   split_chunk_heading，不自己实现切分。

2. **vec0 虚表同样不能 dump，但向量是纯字节，可以原样搬。**
   document_vec 里的 embedding 就是 float32 的原始字节，
   一条条 select rowid, embedding 读出来拼成 vectors.bin，
   落库时按 (rowid, offset, bytes) 原样写回。
   导不出来（扩展没加载、表不存在）就跳过并在 manifest 里标注
   vectors: skipped —— 离线机器仍然能用 FTS 检索，只是少了语义召回。
   宁可少一个通道，也不要整个包导不出来。

3. **包是「文本投影」，不是「原始文件镜像」。**
   证据层带的是抽取后的正文，不是 PDF/Word 原件。
   原因有二：原件体积大十倍，且原件在多数部署里另有备份通道。
   代价必须写进 manifest 的 notes —— 免得运维以为「包里有原件」。

4. **解包不用 extractall。**
   tarfile.extractall 不做路径校验，一个成员名带 ../ 就能把文件写到
   目标目录外面去。本模块自己逐个成员读，路径规整后必须落在目标目录内，
   绝对路径与 .. 一律拒绝，单成员上限 200 MB。

5. **先验后导。**
   import 先跑一遍完整性校验，任何成员对不上就整包拒绝，
   并把错写进 integrity_errors —— 绝不允许「带着损坏的数据静默入库」。
   半截数据比没有数据难查得多。

6. **基因按 uid 去重，证据按 (kind, id) 去重。**
   uid 是跨库稳定的身份（内容指纹派生），同一个包导两次结果必须一样。
   fingerprint 相同视为同一条：uid 算不出来或换了算法时，靠它兜底。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..config import settings
from . import docindex

log = logging.getLogger("kb.dna_bundle")

# ============ 契约常量 ============

BUNDLE_SCHEMA = "dna-bundle/1"
GENERATOR = "kb-workbench/dna_bundle"

M_MANIFEST = "manifest.json"
M_GENES = "genes.jsonl"
M_KNOWLEDGE = "knowledge.jsonl"
M_VECTORS_BIN = "vectors.bin"
M_VECTORS_JSON = "vectors.json"
M_FTS = "fts.sqlite"
M_INTEGRITY = "integrity.json"

# 成员顺序固定：包 diff 起来一眼能看出多了/少了什么
MEMBER_ORDER = (M_MANIFEST, M_GENES, M_KNOWLEDGE,
                M_VECTORS_BIN, M_VECTORS_JSON, M_FTS, M_INTEGRITY)

# 单成员上限。包要能被人用 scp / U 盘搬到别的机器，
# 一个几百 MB 的成员就足以把搬运变成体力活。
MAX_MEMBER_BYTES = 200 * 1024 * 1024

# 知识层里每类东西的 kind
KIND_DOCUMENT = "document"
KIND_CHUNK = "chunk"
KIND_RECORD = "record"
KIND_NOTE = "note"


# ============ 小工具 ============

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(value: Any) -> str:
    """datetime → 秒级 ISO 串

    与 dna.py 的 _iso 同一口径：库里存的是 naive datetime，
    isoformat() 会带微秒，前端显示出来是一串没用的尾巴。
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def _count_words(text: str) -> int:
    """字数 = 去掉所有空白后的字符数

    中文正文几乎没有空格，按空格数出来的「词数」约等于段落数，毫无信息量。
    与 dna.py 的口径保持一致，两边数字才能对得上。
    """
    return len("".join((text or "").split()))


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _record_title(data: Any, rec_id: int) -> str:
    """业务记录的可读标题

    记录的字段全是模型自定义的，标题可能叫 title / name / code，
    只能挨个试；都取不到就用 id 兜底 ——
    显示一个空字符串比显示「记录 #12」糟糕得多。
    （与 dna_library._record_title 同口径；这里自己写一份是刻意的：
      那是另一个模块的私有函数，跨模块 import 私有名会在对方改名时炸掉整个服务。）
    """
    if isinstance(data, dict):
        for key in ("title", "name", "名称", "标题", "subject"):
            v = data.get(key)
            if v:
                return str(v)[:120]
    return f"记录 #{rec_id}"


def _safe_member_name(name: str) -> str | None:
    """把 tar 成员名规整成安全的相对路径；不安全就返回 None

    为什么必须自己校验：tarfile.extractall 不做这件事，
    成员名 "../etc/passwd" 或 "/etc/passwd" 会直接写到目标目录外面。
    这里不信任包里的任何路径 —— 包可能是别人给的。
    """
    if not name:
        return None
    if "\x00" in name:
        return None
    # Windows 盘符（C:foo）也是绝对路径的一种
    if len(name) >= 2 and name[1] == ":" and name[0].isalpha():
        return None
    if name.startswith("/") or name.startswith("\\"):
        return None
    parts: list[str] = []
    for part in name.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


async def _table_exists(db, name: str) -> bool:
    """表在不在

    dna_gene 这张表是后加的，导出时可能还不存在。
    「表没有」不是错误 —— 那一层本来就没有东西可导，
    跳过并记账，比抛异常把整个打包流程打断要好。

    直接问 sqlite_master，而不是用 SQLAlchemy 的 inspect：
    inspect 要一个 Connection，而 AsyncSession.run_sync 递进来的是 Session，
    类型对不上会抛「No inspection system is available」。
    一句 SQL 更省事，也不挑调用方给的是什么。
    """
    try:
        row = (await db.execute(text(
            "select name from sqlite_master where type='table' and name=:n limit 1"),
            {"n": name})).first()
        return row is not None
    except Exception as e:
        log.warning("检查表 %s 是否存在失败：%s", name, e)
        return False


# ============ 收集：基因层 ============

async def _collect_genes(db) -> tuple[list[dict], bool]:
    """取基因层

    字段严格按约定那一份（uid/kind/title/content/summary/tags/
    source_kind/source_ref/source_title/fingerprint/confidence/status/
    meta/created_at/updated_at），不多不少。

    为什么不多带 usage_count / last_used_at / superseded_by：
      usage_count 是「这台机器上被引用过几次」，是本地计数器不是知识本身，
      带着走会让两台机器互相污染；
      superseded_by 存的是行号（跨库必然对不上），status=superseded 已经
      表达了「被取代了」这个事实，够用了。
    """
    if not await _table_exists(db, "dna_gene"):
        return [], False
    try:
        rows = (await db.execute(text(
            "select uid, kind, title, content, summary, tags, source_kind, "
            "source_ref, source_title, fingerprint, confidence, status, meta, "
            "created_at, updated_at from dna_gene order by id"))).all()
    except Exception as e:
        log.warning("读取 dna_gene 失败，基因层本次跳过：%s", e)
        return [], False

    out: list[dict] = []
    for r in rows:
        out.append({
            "uid": r[0] or "",
            "kind": r[1] or "",
            "title": r[2] or "",
            "content": r[3] or "",
            "summary": r[4] or "",
            "tags": _as_list(r[5]),
            "source_kind": r[6] or "",
            "source_ref": r[7] or "",
            "source_title": r[8] or "",
            "fingerprint": r[9] or "",
            "confidence": float(r[10] or 0.0),
            "status": r[11] or "active",
            "meta": _as_dict(r[12]),
            "created_at": _iso(r[13]),
            "updated_at": _iso(r[14]),
        })
    return out, True


# ============ 收集：证据层 ============

async def _collect_knowledge(db) -> tuple[list[dict], dict[str, str]]:
    """取证据层

    一行一条，字段固定：kind/id/title/text/heading/source_kind/
    source_ref/words/updated_at。

    source_ref 的约定（与 dna_library 抽基因时用的口径一致）：
      文档 doc-3      —— 自己
      块   doc-3      —— 所属文档（块要靠它找回父文档）
      记录 record-14  —— 自己
      笔记 note-25    —— 自己

    块的父文档靠 source_ref 传，块本身没有 document_id 可带，
    而 document_chunk.document_id 是非空的 —— 不带就装不回去。

    另外返回 record_types：{记录 id: 实体类型 key}。
    记录属于哪个「模型」是模型自定义的，知识行里放不下（字段固定），
    只能在 manifest 里带一份映射；装回去时按 key 找目标库的模型，
    找不到就跳过并记账 —— 硬塞进别的模型会造出一条字段对不上的脏记录。
    """
    rows: list[dict] = []
    record_types: dict[str, str] = {}

    # ---- 文档 ----
    try:
        docs = (await db.execute(text(
            "select id, title, filename, tags, summary, extracted_text, updated_at "
            "from document where deleted_at is null order by id"))).all()
    except Exception as e:
        log.warning("读取 document 失败：%s", e)
        docs = []
    for d in docs:
        body = d[5] or ""
        rows.append({
            "kind": KIND_DOCUMENT,
            "id": int(d[0]),
            "title": d[1] or "",
            "text": body,
            "heading": "",
            "source_kind": KIND_DOCUMENT,
            "source_ref": f"doc-{int(d[0])}",
            "words": _count_words(body),
            "updated_at": _iso(d[6]),
        })

    # ---- 文档块（顺带把文档的 filename/tags/summary 留给 FTS 重建用）----
    try:
        chunks = (await db.execute(text(
            "select c.id, c.document_id, c.text, d.updated_at from document_chunk c "
            "join document d on d.id = c.document_id "
            "where d.deleted_at is null order by c.document_id, c.id"))).all()
    except Exception as e:
        log.warning("读取 document_chunk 失败：%s", e)
        chunks = []
    for c in chunks:
        text_body = c[2] or ""
        heading, _ = docindex.split_chunk_heading(text_body)
        rows.append({
            "kind": KIND_CHUNK,
            "id": int(c[0]),
            "title": "",
            "text": text_body,
            "heading": heading,
            "source_kind": KIND_DOCUMENT,
            "source_ref": f"doc-{int(c[1])}",
            "words": _count_words(text_body),
            "updated_at": _iso(c[3]),
        })

    # ---- 业务记录与笔记（笔记就是 note 模型的记录）----
    try:
        recs = (await db.execute(text(
            "select er.id, et.key, er.data, er.search_text, er.updated_at "
            "from entity_record er join entity_type et on et.id = er.entity_type_id "
            "where er.deleted_at is null order by er.id"))).all()
    except Exception as e:
        log.warning("读取 entity_record 失败：%s", e)
        recs = []
    for r in recs:
        rec_id = int(r[0])
        type_key = r[1] or ""
        data = _as_dict(r[2])
        body = r[3] or ""
        title = _record_title(data, rec_id)
        is_note = (type_key == "note")
        rows.append({
            "kind": KIND_NOTE if is_note else KIND_RECORD,
            "id": rec_id,
            "title": title,
            "text": body,
            "heading": "",
            "source_kind": KIND_NOTE if is_note else KIND_RECORD,
            "source_ref": f"note-{rec_id}" if is_note else f"record-{rec_id}",
            "words": _count_words(body),
            "updated_at": _iso(r[4]),
        })
        record_types[str(rec_id)] = type_key

    return rows, record_types


async def _collect_entity_types(db) -> dict:
    """实体模型的 key → 名字

    记录属于哪个模型，导入那台机器没有这个模型时，
    要按这个名字建一个空的 —— 名字得跟原机器一致，
    运维才不会看到两个同名不同样的模型。
    """
    out: dict[str, str] = {}
    try:
        rows = (await db.execute(text(
            "select key, name from entity_type where deleted_at is null"))).all()
    except Exception as e:
        log.warning("读取 entity_type 失败：%s", e)
        return out
    for r in rows:
        if r[0]:
            out[str(r[0])] = str(r[1] or r[0])
    return out


# ============ 收集：向量 ============

async def _collect_vectors(db, out_bin: Path) -> dict:
    """把 document_vec 里的原始 float32 向量倒成 vectors.bin

    vec0 是虚表，不能 dump；但向量本身是纯字节，可以原样搬。
    一条条 select rowid, embedding 读出来 —— 不能 select 整表再序列化，
    那样会在内存里同时驻留整个向量库。

    导不出来不报错中断：跳过并标注 vectors=skipped，
    离线机器仍然能用 FTS 检索，只是少了语义召回这一路。
    """
    result = {"status": "skipped", "dim": 0, "count": 0, "reason": ""}
    if not await _table_exists(db, "document_vec"):
        result["reason"] = "document_vec 表不存在"
        return result

    entries: list[dict] = []
    offset = 0
    try:
        rows = (await db.execute(text(
            "select rowid, embedding from document_vec"))).all()
    except Exception as e:
        result["reason"] = f"读取 document_vec 失败：{e}"
        log.warning("导出向量失败，本次跳过向量层：%s", e)
        return result

    with open(out_bin, "wb") as fh:
        for rowid, emb in rows:
            if not emb:
                continue
            blob = bytes(emb)
            if result["dim"] == 0:
                result["dim"] = len(blob) // 4
            fh.write(blob)
            entries.append({"rowid": int(rowid), "offset": offset, "bytes": len(blob)})
            offset += len(blob)

    result.update({"status": "ok", "count": len(entries)})
    return {"status": "ok", "dim": result["dim"], "count": len(entries),
            "entries": entries, "reason": ""}


# ============ 构造包内的 fts.sqlite ============

def _build_fts_sqlite(path: Path, genes: list[dict], docs: list[dict],
                      chunks: list[dict]) -> dict:
    """重建一份独立的 FTS5 小库

    表名与列跟线上库完全一致（document_fts / chunk_fts / dna_gene_fts），
    这样离线机器把它挂上去就能用现成的检索代码，
    不需要「另一套专用查询」—— 两套查询迟早会分叉。

    额外给一个 genes_fts 视图：约定里写的是 genes_fts，
    而线上真名是 dna_gene_fts，两个名字都给到，
    免得对接的人按约定找表找不到。

    文本用 docindex 的同一套函数重新分词，
    不从线上 FTS 表里反读 —— 反读只能拿到「线上索引当前的样子」，
    线上索引没建或建到一半时就会导出一份空索引。
    """
    conn = sqlite3.connect(str(path))
    counts = {"document_fts": 0, "chunk_fts": 0, "dna_gene_fts": 0}
    try:
        conn.execute("pragma journal_mode=DELETE")
        conn.execute(
            "create virtual table document_fts using fts5("
            "title, body, tokenize='unicode61 remove_diacritics 2')")
        conn.execute(
            "create virtual table chunk_fts using fts5("
            "heading, body, tokenize='unicode61 remove_diacritics 2')")
        conn.execute(
            "create virtual table dna_gene_fts using fts5("
            "title, content, tags, tokenize='unicode61 remove_diacritics 2')")
        # 约定里的别名：视图，不是另一张表，避免两份数据两套真相
        conn.execute(
            "create view genes_fts as select rowid, title, content, tags from dna_gene_fts")
        # 行号 → 基因 uid 的映射：FTS 的 rowid 只是行号，
        # 出了这个包就没法反查是哪条基因，单独记一张映射表
        conn.execute("create table gene_map(rowid integer primary key, uid text)")

        # ---- 文档 ----
        for d in docs:
            title = docindex.tokenize_for_index(
                d.get("title", ""), d.get("filename", ""),
                " ".join(d.get("tags") or []))
            body = docindex.tokenize_for_index(d.get("summary", ""), d.get("text", ""))
            conn.execute("insert into document_fts(rowid, title, body) values (?,?,?)",
                         (int(d["id"]), title, body))
            counts["document_fts"] += 1

        # ---- 块 ----
        for c in chunks:
            heading, body = docindex.split_chunk_heading(c.get("text", ""))
            conn.execute("insert into chunk_fts(rowid, heading, body) values (?,?,?)",
                         (int(c["id"]), docindex.seg_bigram(heading),
                          docindex.seg_bigram(body)))
            counts["chunk_fts"] += 1

        # ---- 基因 ----
        for i, g in enumerate(genes):
            conn.execute(
                "insert into dna_gene_fts(rowid, title, content, tags) values (?,?,?,?)",
                (i + 1, docindex.seg_bigram(g.get("title", "")),
                 docindex.seg_bigram((g.get("content") or "")[:4000]),
                 docindex.seg_bigram(" ".join(g.get("tags") or []))))
            conn.execute("insert into gene_map(rowid, uid) values (?,?)",
                         (i + 1, g.get("uid", "")))
            counts["dna_gene_fts"] += 1

        conn.commit()
    finally:
        conn.close()
    return counts


# ============ 导出 ============

async def export_bundle(db, out_path: str) -> dict:
    """把养料库打成 tar.gz

    返回 manifest 摘要：{path, bytes, members, counts, sha256}

    打包顺序（先重后轻）不是随意的：
    索引先建好，失败就早失败 —— 一个没有 FTS 的包到了另一台机器上
    才发现，比在这边发现贵得多。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="dna-bundle-"))
    notes: dict[str, Any] = {}
    integrity_errors: list[str] = []
    try:
        # ---- 1. 基因 ----
        genes, gene_table = await _collect_genes(db)
        if not gene_table:
            notes["gene_table_missing"] = True

        # ---- 2. 证据 ----
        knowledge, record_types = await _collect_knowledge(db)
        entity_types = await _collect_entity_types(db)

        # ---- 3. 文档的附加字段（FTS 重建要用 filename/tags/summary）----
        doc_meta = await _collect_doc_meta(db)

        # ---- 4. 向量 ----
        vectors = await _collect_vectors(db, staging / M_VECTORS_BIN)
        if vectors.get("status") != "ok":
            notes["vectors"] = "skipped"
            notes["vectors_reason"] = vectors.get("reason", "")
            # 空的 vectors.bin 不该留在包里占位
            (staging / M_VECTORS_BIN).unlink(missing_ok=True)
        else:
            (staging / M_VECTORS_JSON).write_text(
                json.dumps({"dim": vectors["dim"], "entries": vectors["entries"]},
                           ensure_ascii=False, sort_keys=True),
                encoding="utf-8")

        # ---- 5. 基因层 / 证据层落成 jsonl ----
        with open(staging / M_GENES, "w", encoding="utf-8") as fh:
            for g in genes:
                fh.write(json.dumps(g, ensure_ascii=False, sort_keys=True) + "\n")
        with open(staging / M_KNOWLEDGE, "w", encoding="utf-8") as fh:
            for k in knowledge:
                fh.write(json.dumps(k, ensure_ascii=False, sort_keys=True) + "\n")

        # ---- 6. 重建 FTS ----
        docs_for_fts = []
        chunks_for_fts = []
        for k in knowledge:
            if k["kind"] == KIND_DOCUMENT:
                d = dict(k)
                d.update(doc_meta.get(str(k["id"]), {}))
                docs_for_fts.append(d)
            elif k["kind"] == KIND_CHUNK:
                chunks_for_fts.append(k)
        fts_counts = _build_fts_sqlite(staging / M_FTS, genes, docs_for_fts,
                                       chunks_for_fts)

        # ---- 7. 统计 ----
        counts = {
            "genes": len(genes),
            "documents": sum(1 for k in knowledge if k["kind"] == KIND_DOCUMENT),
            "chunks": sum(1 for k in knowledge if k["kind"] == KIND_CHUNK),
            "records": sum(1 for k in knowledge if k["kind"] == KIND_RECORD),
            "notes": sum(1 for k in knowledge if k["kind"] == KIND_NOTE),
            "vectors": int(vectors.get("count", 0)) if vectors.get("status") == "ok" else 0,
            "fts_document": fts_counts["document_fts"],
            "fts_chunk": fts_counts["chunk_fts"],
            "fts_gene": fts_counts["dna_gene_fts"],
        }

        # ---- 8. manifest ----
        notes["counts_zh"] = {
            "genes": "基因条数（可复用的结论）",
            "documents": "文档数（证据层）",
            "chunks": "文档块数（块级检索的最小单位）",
            "records": "业务记录数",
            "notes": "笔记数",
            "vectors": "向量条数（0 表示未导出，离线只剩全文检索）",
            "fts_document": "包内 FTS 文档行数",
            "fts_chunk": "包内 FTS 块行数",
            "fts_gene": "包内 FTS 基因行数",
        }
        notes["evidence_is_projection"] = (
            "证据层是抽取后的文本投影，不是原始文件镜像；"
            "PDF/Word 原件不在包内。")
        notes["records_are_projection"] = (
            "业务记录只带标题与可搜索正文，不带模型字段值；"
            "目标机缺模型时会按 entity_types 建一个空模型（字段需自行补）。")
        notes["fts_tables"] = {
            "document_fts": "title, body",
            "chunk_fts": "heading, body",
            "dna_gene_fts": "title, content, tags（genes_fts 是它的视图别名）",
        }
        notes["tokenizer"] = {
            "document_fts": "docindex.tokenize_for_index（汉字逐字）",
            "chunk_fts": "docindex.seg_bigram（汉字 2-gram）",
            "dna_gene_fts": "docindex.seg_bigram（汉字 2-gram）",
        }
        if vectors.get("status") == "ok":
            notes["vector_dim"] = vectors["dim"]

        created_at = datetime.now().replace(microsecond=0).isoformat()
        member_files = [M_GENES, M_KNOWLEDGE, M_FTS]
        if vectors.get("status") == "ok":
            member_files += [M_VECTORS_BIN, M_VECTORS_JSON]
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "created_at": created_at,
            "app_version": settings.app_version,
            "generator": GENERATOR,
            "counts": counts,
            "members": _hash_members(staging, member_files),
            "requires": {
                "sqlite_fts5": True,
                "sqlite_vec": vectors.get("status") == "ok",
                "llm": False,
                "python": ">=3.10",
            },
            "record_types": record_types,
            "entity_types": entity_types,
            "notes": notes,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False,
                                    indent=2, sort_keys=True).encode("utf-8")
        (staging / M_MANIFEST).write_bytes(manifest_bytes)

        # ---- 9. 完整性清单（覆盖 manifest 本身）----
        integrity_files = list(MEMBER_ORDER[:-1])  # 不含 integrity.json 自己
        integrity = {
            "schema": BUNDLE_SCHEMA,
            "algorithm": "sha256",
            "members": _hash_members(staging, integrity_files),
        }
        (staging / M_INTEGRITY).write_text(
            json.dumps(integrity, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")

        # ---- 10. 打包 ----
        # 成员 mtime 统一取 manifest 的 created_at：包里所有时间戳指向同一刻
        stamp = datetime.fromisoformat(created_at).timestamp()
        _write_tar_gz(out, staging, int(stamp))

        size = out.stat().st_size
        digest = _sha256_file(out)
        return {
            "path": str(out),
            "bytes": size,
            "members": manifest["members"],
            "counts": counts,
            "sha256": digest,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def _collect_doc_meta(db) -> dict:
    """文档的附加字段（FTS 重建要用 filename / tags / summary）

    document_fts 的 title 列是「标题 + 文件名 + 标签」一起分词，
    body 列是「摘要 + 正文」。少了这三个字段，
    重建出来的索引就跟线上那份对不上了 ——
    离线机器上「搜文件名能搜到」这种行为会消失。
    """
    out: dict[str, dict] = {}
    try:
        rows = (await db.execute(text(
            "select id, filename, tags, summary from document "
            "where deleted_at is null"))).all()
    except Exception as e:
        log.warning("读取文档附加字段失败：%s", e)
        return out
    for r in rows:
        out[str(int(r[0]))] = {
            "filename": r[1] or "",
            "tags": _as_list(r[2]),
            "summary": r[3] or "",
        }
    return out


def _hash_members(base: Path, names: list[str]) -> dict:
    """算一组成员的 sha256 与字节数"""
    out: dict[str, dict] = {}
    for name in names:
        p = base / name
        if not p.exists():
            continue
        data = p.read_bytes()
        out[name] = {"sha256": _sha256_bytes(data), "bytes": len(data)}
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _write_tar_gz(out: Path, staging: Path, mtime: int) -> None:
    """把 staging 目录打成 tar.gz

    gzip 的 mtime 固定成 0、tar 里每个成员的 mtime 统一取 manifest 的 created_at：
    包里所有时间戳指向同一刻，而不是各处散着不同的“打包时刻”。
    gzip 头里那个时间戳尤其要清掉 —— 它藏得深，最容易在比对两包时对不上。

    注意：包**不是**逐字节可复现的。manifest 里的 created_at 记的是
    「这份快照是什么时候取的」，它本来就该变；两次导出的 sha256 不同是正常的。
    要比内容就比成员哈希（integrity.json 里有），别比整包的 sha256。
    """
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tf:
                for name in MEMBER_ORDER:
                    src = staging / name
                    if not src.exists():
                        continue
                    info = tarfile.TarInfo(name)
                    info.size = src.stat().st_size
                    info.mtime = mtime
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with open(src, "rb") as fh:
                        tf.addfile(info, fh)
    os.replace(tmp, out)


# ============ 检查（只读，不解压到磁盘）============

def inspect_bundle(path: str) -> dict:
    """只读检查一个包（不解压到磁盘）

    返回 {ok, manifest, members, integrity_errors[], counts}

    「不解压到磁盘」是硬要求：检查一个来路不明的包时，
    不该在检查这一步就把它的内容写进文件系统 ——
    那正是路径穿越攻击要利用的时机。
    这里全程只在内存里读成员、算哈希。
    """
    errors: list[str] = []
    manifest: dict = {}
    members: dict = {}
    counts: dict = {}
    p = Path(path)
    if not p.exists():
        return {"ok": False, "manifest": {}, "members": {},
                "integrity_errors": [f"包不存在：{path}"], "counts": {}}
    if not p.is_file():
        return {"ok": False, "manifest": {}, "members": {},
                "integrity_errors": [f"不是一个文件：{path}"], "counts": {}}

    try:
        with tarfile.open(str(p), "r:gz") as tf:
            names = set()
            for m in tf.getmembers():
                safe = _safe_member_name(m.name)
                if safe is None:
                    errors.append(f"成员路径不安全，已拒绝：{m.name!r}")
                    continue
                if not m.isfile():
                    errors.append(f"成员不是普通文件，已拒绝：{m.name!r}")
                    continue
                if m.size > MAX_MEMBER_BYTES:
                    errors.append(
                        f"成员超过大小上限 {MAX_MEMBER_BYTES} 字节，已拒绝：{m.name}")
                    continue
                names.add(safe)

            # ---- manifest ----
            manifest = _read_json_member(tf, M_MANIFEST, errors)
            counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}

            # ---- integrity.json ----
            integrity = _read_json_member(tf, M_INTEGRITY, errors)
            declared = integrity.get("members", {}) if isinstance(integrity, dict) else {}
            if not isinstance(declared, dict):
                errors.append("integrity.json 的 members 结构不对")
                declared = {}

            for name, want in declared.items():
                safe = _safe_member_name(name)
                if safe is None:
                    errors.append(f"完整性清单里的成员路径不安全：{name!r}")
                    continue
                if safe not in names:
                    errors.append(f"成员缺失：{safe}")
                    continue
                f = tf.extractfile(name)
                if f is None:
                    errors.append(f"成员读不出来：{safe}")
                    continue
                h = hashlib.sha256()
                total = 0
                while True:
                    block = f.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    h.update(block)
                got = h.hexdigest()
                want_hash = (want or {}).get("sha256")
                if want_hash and got != want_hash:
                    errors.append(
                        f"成员 {safe} 校验不符：期望 {want_hash[:12]}… 实际 {got[:12]}…")
                else:
                    members[safe] = {"sha256": got, "bytes": total}

            # ---- manifest 里声明的成员也要在包里 ----
            man_members = manifest.get("members", {}) if isinstance(manifest, dict) else {}
            if isinstance(man_members, dict):
                for name in man_members:
                    safe = _safe_member_name(name)
                    if safe is None or safe not in names:
                        errors.append(f"manifest 声明的成员不在包里：{name}")
                    elif safe not in declared:
                        errors.append(f"成员 {safe} 不在完整性清单里")

            # ---- 包里多出来的成员也要说 ----
            for name in sorted(names - set(declared.keys())):
                if name != M_INTEGRITY:
                    errors.append(f"包里有清单外的成员：{name}")
    except tarfile.TarError as e:
        errors.append(f"包读不出来（可能损坏或不是 tar.gz）：{e}")
    except Exception as e:
        errors.append(f"检查包时出错：{e}")

    return {
        "ok": not errors,
        "manifest": manifest,
        "members": members,
        "integrity_errors": errors,
        "counts": counts,
    }


def _read_json_member(tf: tarfile.TarFile, name: str, errors: list[str]) -> dict:
    try:
        f = tf.extractfile(name)
    except KeyError:
        errors.append(f"包里没有 {name}")
        return {}
    if f is None:
        errors.append(f"{name} 读不出来")
        return {}
    raw = f.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        errors.append(f"{name} 不是合法 JSON：{e}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{name} 结构不对（应为对象）")
        return {}
    return data


# ============ 导入 ============

async def import_bundle(db, path: str, *, mode: str = "merge") -> dict:
    """把包导回目标库

    mode:
      merge   —— 按 uid/fingerprint 去重合并（默认）
      replace —— 清空知识层后导入

    返回 {imported, skipped, updated, counts, integrity_errors[]}

    先验后导：任何成员对不上就整包拒绝。
    半截数据比没有数据难查得多 —— 缺了一条基因，
    表面上系统照常跑，只是某条知识再也答不出来了。
    """
    if mode not in ("merge", "replace"):
        raise ValueError("mode 只能是 'merge' 或 'replace'")

    rep = inspect_bundle(path)
    if rep["integrity_errors"]:
        # 明确拒绝：不让损坏的数据进库
        return {"imported": 0, "skipped": 0, "updated": 0,
                "counts": {}, "integrity_errors": rep["integrity_errors"]}

    p = Path(path)
    with tarfile.open(str(p), "r:gz") as tf:
        genes = _read_jsonl(tf, M_GENES)
        knowledge = _read_jsonl(tf, M_KNOWLEDGE)
        fts_blob = _read_bytes(tf, M_FTS)
        vec_bin = _read_bytes(tf, M_VECTORS_BIN)
        vec_json = _read_json_dict(tf, M_VECTORS_JSON)
        manifest = rep["manifest"]

    imported = skipped = updated = 0
    counts = {"genes": 0, "documents": 0, "chunks": 0, "records": 0,
              "notes": 0, "vectors": 0, "fts_document": 0, "fts_chunk": 0,
              "fts_gene": 0, "entity_types_created": 0}
    errors: list[str] = []

    if mode == "replace":
        await _clear_knowledge_layer(db)

    # ---- 基因 ----
    # 目标库没有 dna_gene 表就整层跳过：基因层是可选增强，
    # 目标机还没上这个功能，不该让整次导入失败 ——
    # 证据层照样能导进去，那才是知识库的主体。
    has_gene_table = await _table_exists(db, "dna_gene")
    if genes and not has_gene_table:
        errors.append("目标库没有 dna_gene 表，基因层本次未导入")
        genes = []
    gene_by_uid: dict[str, int] = {}
    gene_by_fp: dict[str, int] = {}
    for g in genes:
        uid = (g.get("uid") or "").strip()
        fp = (g.get("fingerprint") or "").strip()
        if not uid and not fp:
            skipped += 1
            continue
        # 已存在？uid 是跨库身份，fingerprint 是同一内容的另一种口径
        existing = None
        if uid:
            row = (await db.execute(text(
                "select id, fingerprint from dna_gene where uid = :u limit 1"),
                {"u": uid})).first()
            if row:
                existing = row
        if existing is None and fp:
            row = (await db.execute(text(
                "select id, fingerprint from dna_gene where fingerprint = :f limit 1"),
                {"f": fp})).first()
            if row:
                existing = row
        if existing is not None:
            if uid:
                gene_by_uid[uid] = int(existing[0])
            if fp:
                gene_by_fp[fp] = int(existing[0])
            # 内容一样就是同一条，跳过；指纹一样但内容变了，算更新
            if (existing[1] or "") == fp:
                skipped += 1
            else:
                await _update_gene(db, int(existing[0]), g)
                updated += 1
            continue

        new_id, fts_ok = await _insert_gene(db, g)
        if uid:
            gene_by_uid[uid] = new_id
        if fp:
            gene_by_fp[fp] = new_id
        imported += 1
        counts["genes"] += 1
        if fts_ok:
            counts["fts_gene"] += 1

    # ---- 证据层 ----
    doc_ids: set[int] = set()
    chunk_ids: set[int] = set()
    seq_by_doc: dict[int, int] = {}
    for k in knowledge:
        kind = k.get("kind")
        kid = k.get("id")
        if not isinstance(kid, int):
            skipped += 1
            continue
        if kind == KIND_DOCUMENT:
            existed = await _row_exists(db, "document", kid)
            if existed and mode == "merge":
                skipped += 1
                doc_ids.add(kid)
                continue
            await _insert_document(db, k)
            doc_ids.add(kid)
            imported += 1
            counts["documents"] += 1
        elif kind == KIND_CHUNK:
            parent = _ref_id(k.get("source_ref"))
            if parent is None:
                skipped += 1
                continue
            existed = await _row_exists(db, "document_chunk", kid)
            if existed and mode == "merge":
                skipped += 1
                chunk_ids.add(kid)
                seq_by_doc[parent] = seq_by_doc.get(parent, 0) + 1
                continue
            seq = seq_by_doc.get(parent, 0)
            seq_by_doc[parent] = seq + 1
            await _insert_chunk(db, kid, parent, seq, k.get("text", ""))
            chunk_ids.add(kid)
            imported += 1
            counts["chunks"] += 1
        elif kind in (KIND_RECORD, KIND_NOTE):
            type_key = (manifest.get("record_types") or {}).get(str(kid), "")
            type_id = await _entity_type_id(db, type_key)
            if type_id is None and type_key:
                # 目标库里没有这个模型：照 manifest 里记的名字建一个空模型，
                # 好让记录有地方放。
                # 不建的话记录只能丢着 —— 记录是「这机器上见过的业务对象」，
                # 丢一条就等于丢一份业务上下文。
                # 字段定义不在包里（那是模型设计，不是知识），
                # 建出来的模型没有字段，记录靠 title/content 呈现。
                type_id = await _create_entity_type(
                    db, type_key, (manifest.get("entity_types") or {}).get(type_key))
                if type_id is not None:
                    counts["entity_types_created"] = counts.get(
                        "entity_types_created", 0) + 1
                    errors.append(
                        f"目标库没有模型 {type_key!r}，已按 manifest 建了一个空模型"
                        f"（字段定义需自行补）")
            if type_id is None:
                skipped += 1
                errors.append(
                    f"记录 {kid} 属于模型 {type_key!r}，目标库里没有这个模型，已跳过")
                continue
            existed = await _row_exists(db, "entity_record", kid)
            if existed and mode == "merge":
                skipped += 1
                continue
            await _insert_record(db, kid, type_id, k)
            imported += 1
            counts["notes" if kind == KIND_NOTE else "records"] += 1

    # ---- 向量 ----
    if vec_bin and isinstance(vec_json, dict) and vec_json.get("entries"):
        n = await _restore_vectors(db, vec_bin, vec_json, chunk_ids, mode)
        counts["vectors"] = n
        imported += n
    elif vec_json:
        errors.append("包里有向量清单但缺少 vectors.bin，向量未导入")

    # ---- FTS ----
    if fts_blob:
        fts_counts = await _restore_fts(db, fts_blob, doc_ids, chunk_ids)
        counts["fts_document"] = fts_counts.get("document_fts", 0)
        counts["fts_chunk"] = fts_counts.get("chunk_fts", 0)
        imported += (counts["fts_document"] + counts["fts_chunk"])

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "updated": updated,
        "counts": counts,
        "integrity_errors": errors,
    }


async def _row_exists(db, table: str, row_id: int) -> bool:
    row = (await db.execute(text(
        f"select 1 from {table} where id = :i limit 1"), {"i": row_id})).first()
    return row is not None


async def _rowid_exists(db, table: str, rowid: int) -> bool:
    """FTS5 虚表里没有 id 列，只有 rowid —— 用 id 查会直接报 no such column"""
    row = (await db.execute(text(
        f"select 1 from {table} where rowid = :r limit 1"), {"r": rowid})).first()
    return row is not None


def _ref_id(ref: Any) -> int | None:
    """从 'doc-3' 里取出 3

    块靠 source_ref 找回父文档，格式不对就当没有 ——
    宁可少装一条，也不要把块挂到错的文档下面。
    """
    if not isinstance(ref, str) or "-" not in ref:
        return None
    tail = ref.rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None


async def _entity_type_id(db, key: str) -> int | None:
    """按 key 找实体模型的 id

    软删除的模型当作没有：它已经被扔进回收站了，
    往里塞记录等于把删掉的东西复活。
    """
    if not key:
        return None
    row = (await db.execute(text(
        "select id from entity_type where key = :k and deleted_at is null limit 1"),
        {"k": key})).first()
    return int(row[0]) if row else None


async def _create_entity_type(db, key: str, name: Any) -> int | None:
    """按 manifest 里的信息补一个空的实体模型

    只补 key 和名字，不补字段定义 ——
    字段定义是「这个业务怎么建模」的设计决定，不属于知识本身，
    打包带走会让两台机器的模型定义无声地对不上。
    补出来的空模型让记录有地方落；字段由运维在目标机上补。
    """
    if not key:
        return None
    if not await _table_exists(db, "entity_type"):
        return None
    existing = await _entity_type_id(db, key)
    if existing is not None:
        return existing
    label = (name or key or "").strip() or key
    try:
        res = await db.execute(text(
            "insert into entity_type(key, name, icon, app, \"order\") "
            "values (:k, :n, '📦', 'default', 0)"),
            {"k": key, "n": label[:120]})
        return int(res.lastrowid or 0) or None
    except Exception as e:
        log.warning("建实体模型 %s 失败：%s", key, e)
        return None


async def _clear_knowledge_layer(db) -> None:
    """replace 模式：清空知识层

    只清知识与基因这一层，不碰用户、角色、审计、应用这些系统表 ——
    「导入一个养料库」不该把整个系统重置掉。

    document / document_chunk / entity_record 的外键都是 ondelete CASCADE，
    所以关联记录会跟着走，不需要手工清。
    """
    statements = [
        "delete from dna_gene_fts where 1=1" if await _table_exists(db, "dna_gene_fts")
        else None,
        "delete from dna_gene",
        "delete from chunk_fts",
        "delete from document_fts",
        "delete from document_vec",
        "delete from document_chunk",
        "delete from document",
        "delete from entity_record",
    ]
    for stmt in statements:
        if not stmt:
            continue
        try:
            await db.execute(text(stmt))
        except Exception as e:
            # 清不掉的表（比如这张表根本不存在）不该让整次导入失败
            log.warning("清空 %s 失败：%s", stmt.split(" from ")[-1].split()[0], e)


async def _insert_gene(db, g: dict) -> tuple[int, bool]:
    """插入一条基因（保留包里带来的 uid 与时间戳）

    返回 (新 id, 基因索引是否写进去了)。

    为什么不用 dna_library.upsert_gene：它会用 kind+fingerprint 重算 uid，
    而包里的 uid 是「这台机器上这条基因的身份」，
    重算就等于换了身份 —— 跨库去重靠的正是这个 uid。
    """
    now = datetime.now().replace(microsecond=0)
    created = _parse_iso(g.get("created_at")) or now
    updated = _parse_iso(g.get("updated_at")) or now
    uid = (g.get("uid") or "").strip()
    if not uid:
        uid = hashlib.sha1(
            f"{g.get('kind', '')}:{g.get('fingerprint', '')}".encode("utf-8")).hexdigest()
    res = await db.execute(text(
        "insert into dna_gene(uid, kind, title, content, summary, tags, source_kind, "
        "source_ref, source_title, fingerprint, confidence, status, meta, "
        "created_at, updated_at) "
        "values (:uid, :kind, :title, :content, :summary, :tags, :source_kind, "
        ":source_ref, :source_title, :fingerprint, :confidence, :status, :meta, "
        ":created_at, :updated_at)"),
        {
            "uid": uid, "kind": g.get("kind") or "fact",
            "title": g.get("title") or "", "content": g.get("content") or "",
            "summary": g.get("summary") or "", "tags": json.dumps(_as_list(g.get("tags"))),
            "source_kind": g.get("source_kind") or "",
            "source_ref": g.get("source_ref") or "",
            "source_title": g.get("source_title") or "",
            "fingerprint": g.get("fingerprint") or "",
            "confidence": float(g.get("confidence") or 0.0),
            "status": g.get("status") or "active",
            "meta": json.dumps(_as_dict(g.get("meta")), ensure_ascii=False),
            "created_at": created, "updated_at": updated,
        })
    new_id = int(res.lastrowid or 0)
    fts_ok = await _index_gene_row(db, new_id, g)
    return new_id, fts_ok


async def _update_gene(db, gid: int, g: dict) -> None:
    """更新一条已存在的基因（内容变了才更新）"""
    await db.execute(text(
        "update dna_gene set kind=:kind, title=:title, content=:content, "
        "summary=:summary, tags=:tags, source_kind=:source_kind, "
        "source_ref=:source_ref, source_title=:source_title, fingerprint=:fingerprint, "
        "confidence=:confidence, status=:status, meta=:meta, updated_at=:updated_at "
        "where id=:id"),
        {
            "id": gid, "kind": g.get("kind") or "fact",
            "title": g.get("title") or "", "content": g.get("content") or "",
            "summary": g.get("summary") or "",
            "tags": json.dumps(_as_list(g.get("tags"))),
            "source_kind": g.get("source_kind") or "",
            "source_ref": g.get("source_ref") or "",
            "source_title": g.get("source_title") or "",
            "fingerprint": g.get("fingerprint") or "",
            "confidence": float(g.get("confidence") or 0.0),
            "status": g.get("status") or "active",
            "meta": json.dumps(_as_dict(g.get("meta")), ensure_ascii=False),
            "updated_at": _parse_iso(g.get("updated_at")) or datetime.now(),
        })
    await _index_gene_row(db, gid, g)


async def _index_gene_row(db, gid: int, g: dict) -> bool:
    """把基因写进基因级 FTS

    表名从 dna_library 取（不写死）：那边改名了这边跟着走，
    不会出现「这边建了一张表，那边检索的是另一张」的分裂。
    分词同样走 docindex.seg_bigram —— 与 chunk_fts 同构。

    rowid 用的是**目标库里的基因 id**，不是包里的行号 ——
    索引的行号必须指向真正存在的那一行。
    """
    try:
        from . import dna_library
        table = dna_library.GENE_FTS_TABLE
    except Exception:
        table = "dna_gene_fts"
    try:
        await db.execute(text(f"delete from {table} where rowid = :r"), {"r": gid})
        await db.execute(
            text(f"insert into {table}(rowid, title, content, tags) "
                 "values (:r, :t, :c, :g)"),
            {"r": gid,
             "t": docindex.seg_bigram(g.get("title") or ""),
             "c": docindex.seg_bigram((g.get("content") or "")[:4000]),
             "g": docindex.seg_bigram(" ".join(_as_list(g.get("tags"))))})
        return True
    except Exception as e:
        log.warning("基因索引写入失败 gene=%s：%s", g.get("uid"), e)
        return False


async def _insert_document(db, k: dict) -> None:
    """插入一条文档（文本投影）

    只带得动文本：原件不在包里，所以 storage='db' 且 data 存正文本身。
    这样离线机器上的文档仍能打开、能检索，
    只是拿不到原始 PDF/Word —— manifest 的 notes 里写明了这一点。
    """
    body = k.get("text") or ""
    raw = body.encode("utf-8")
    title = k.get("title") or f"bundle-{k.get('id')}"
    await db.execute(text(
        "insert into document(id, title, filename, ext, mime, size, sha256, storage, "
        "path, kind, tags, summary, description, source, app, extracted_text, "
        "extract_status, embed_status, embed_dim, created_at, updated_at) "
        "values (:id, :title, :filename, 'md', 'text/markdown', :size, '', 'db', '', "
        "'other', '[]', '', '', 'bundle', 'default', :text, 'ok', 'pending', 0, "
        ":created_at, :updated_at)"),
        {
            "id": int(k["id"]), "title": title,
            "filename": f"{title or 'bundle'}.md"[:500],
            "size": len(raw), "text": body,
            "created_at": _parse_iso(k.get("updated_at")) or datetime.now(),
            "updated_at": _parse_iso(k.get("updated_at")) or datetime.now(),
        })


async def _insert_chunk(db, cid: int, doc_id: int, seq: int, text_body: str) -> None:
    await db.execute(text(
        "insert into document_chunk(id, document_id, seq, text, char_len, embedded, "
        "created_at) values (:id, :did, :seq, :text, :len, 0, :created_at)"),
        {"id": cid, "did": doc_id, "seq": seq, "text": text_body,
         "len": len(text_body or ""), "created_at": datetime.now()})


async def _insert_record(db, rid: int, type_id: int, k: dict) -> None:
    """插入一条业务记录 / 笔记

    data 只保留标题与正文：模型自定义的字段值不在知识行里
    （证据层是文本投影，不是模型实例的备份）。
    记录仍然能被 LIKE 搜到（search_text 完整），
    但字段级别的数据不会跟着走 —— manifest 的 notes 里说明。
    """
    title = k.get("title") or ""
    body = k.get("text") or ""
    await db.execute(text(
        "insert into entity_record(id, entity_type_id, data, search_text, "
        "created_at, updated_at) "
        "values (:id, :tid, :data, :search, :created_at, :updated_at)"),
        {"id": rid, "tid": type_id,
         "data": json.dumps({"title": title, "content": body}, ensure_ascii=False),
         "search": f"{title} {body}".strip(),
         "created_at": _parse_iso(k.get("updated_at")) or datetime.now(),
         "updated_at": _parse_iso(k.get("updated_at")) or datetime.now()})


async def _restore_vectors(db, blob: bytes, meta: dict,
                           chunk_ids: set[int], mode: str = "merge") -> int:
    """把向量写回 document_vec

    rowid 对不上目标库的块就跳过：向量表的 rowid 与 document_chunk.id 一一对应，
    对不上就是孤儿向量，插进去只会让检索命中不存在的块。

    merge 模式**不清空**目标库的向量表：那边可能已经有本机算好的向量，
    连带清掉等于把目标机自己的索引也毁了。
    只补目标库里还没有的那些行 —— 同一个包导两次，第二次一条都不写。
    replace 模式才整表重来（那一层已经被清空了）。
    """
    if not await _table_exists(db, "document_vec"):
        log.warning("目标库没有 document_vec，向量跳过")
        return 0
    entries = meta.get("entries") or []
    ok = 0
    if mode == "replace":
        try:
            await db.execute(text("delete from document_vec"))
        except Exception as e:
            log.warning("清空 document_vec 失败：%s", e)
    for ent in entries:
        try:
            rowid = int(ent["rowid"])
            offset = int(ent["offset"])
            size = int(ent["bytes"])
        except Exception:
            continue
        if chunk_ids and rowid not in chunk_ids:
            continue
        piece = blob[offset:offset + size]
        if len(piece) != size:
            continue
        if mode != "replace" and await _rowid_exists(db, "document_vec", rowid):
            continue
        try:
            await db.execute(text(
                "insert into document_vec(rowid, embedding) values (:r, :e)"),
                {"r": rowid, "e": piece})
            ok += 1
        except Exception as e:
            log.warning("向量写入失败 rowid=%s：%s", rowid, e)
    return ok


async def _restore_fts(db, fts_blob: bytes, doc_ids: set[int],
                        chunk_ids: set[int]) -> dict:
    """把包里的 FTS 行写回目标库的 FTS 表

    包里的 FTS 存的是**已经分好词**的文本，直接搬过去即可：
    FTS5 插入时会再分词一次，而这两套分词对同一段文本是幂等的
    （词与词之间有空格，unicode61 切出来还是同一批词）。
    搬已分词的文本比重新分词更稳 —— 它不会因为两边读到的原文
    有细微差别而产生不同的词表。

    只写「目标库里还没有的行」：同一个包导两次，第二次一行都不该写进去，
    这样 imported 才是 0，而不是每次导入都假装又导了一遍。
    反过来，索引漏了的那几行会被补上（索引缺失时自愈）。

    基因级索引不在这里处理：基因 FTS 的 rowid 必须是**目标库里的基因 id**，
    而包里的 rowid 是打包时的行号 —— 搬过去会指向别的基因。
    基因索引由 _index_gene_row 按目标库的 id 现写。
    """
    counts = {"document_fts": 0, "chunk_fts": 0}
    tmp = Path(tempfile.mkdtemp(prefix="dna-fts-")) / "fts.sqlite"
    try:
        tmp.write_bytes(fts_blob)
        src = sqlite3.connect(str(tmp))
        try:
            # ---- 文档级 ----
            if await _table_exists(db, "document_fts"):
                try:
                    rows = src.execute(
                        "select rowid, title, body from document_fts").fetchall()
                except sqlite3.Error:
                    rows = []
                for rowid, title, body in rows:
                    rid = int(rowid)
                    if doc_ids and rid not in doc_ids:
                        continue
                    if await _rowid_exists(db, "document_fts", rid):
                        continue
                    await db.execute(text(
                        "insert into document_fts(rowid, title, body) values (:r,:t,:b)"),
                        {"r": rid, "t": title, "b": body})
                    counts["document_fts"] += 1

            # ---- 块级 ----
            if await _table_exists(db, "chunk_fts"):
                try:
                    rows = src.execute(
                        "select rowid, heading, body from chunk_fts").fetchall()
                except sqlite3.Error:
                    rows = []
                for rowid, heading, body in rows:
                    rid = int(rowid)
                    if chunk_ids and rid not in chunk_ids:
                        continue
                    if await _rowid_exists(db, "chunk_fts", rid):
                        continue
                    await db.execute(text(
                        "insert into chunk_fts(rowid, heading, body) values (:r,:h,:b)"),
                        {"r": rid, "h": heading, "b": body})
                    counts["chunk_fts"] += 1
        finally:
            src.close()
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return counts


def _parse_iso(value: Any):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _read_bytes(tf: tarfile.TarFile, name: str) -> bytes:
    try:
        f = tf.extractfile(name)
    except KeyError:
        return b""
    if f is None:
        return b""
    return f.read()


def _read_json_dict(tf: tarfile.TarFile, name: str) -> dict:
    """从包里读一个 JSON 对象（读不出就返回空 dict）"""
    raw = _read_bytes(tf, name)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_jsonl(tf: tarfile.TarFile, name: str) -> list[dict]:
    raw = _read_bytes(tf, name)
    out: list[dict] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# ============ 离线可用性自检 ============

def bundle_readiness(db) -> dict:
    """离线可用性自检（同步函数，内部不 await）

    返回 {ok, checks:[{key, ok, detail}], capabilities:{fts, vector, llm, genes, bundle}}

    为什么是同步：自检会被塞进健康检查这种同步路径里，
    而且它要读的全是「文件与表的现状」，没有必须 await 的理由。
    为了不跟调用方的会话抢事务，这里**另开一个只读连接**，
    而不是复用传进来的那个会话 —— 自检绝不该把别人的事务拖住。

    db 可以是 AsyncSession / Session / sqlite3.Connection / 库文件路径。
    """
    checks: list[dict] = []
    capabilities = {"fts": False, "vector": False, "llm": False,
                    "genes": False, "bundle": False}

    def _add(key: str, ok: bool, detail: str) -> None:
        checks.append({"key": key, "ok": bool(ok), "detail": detail})

    conn, own = _open_sync_conn(db)
    if conn is None:
        _add("db", False, "打不开数据库")
        return {"ok": False, "checks": checks, "capabilities": capabilities}

    doc_rows = chunk_rows = gene_rows = vec_rows = 0
    try:
        # ---- 表在不在 ----
        tables = set()
        try:
            tables = {r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'")}
            _add("db", True, f"数据库可读，{len(tables)} 张表")
        except sqlite3.Error as e:
            _add("db", False, f"读表清单失败：{e}")

        # ---- FTS5 ----
        fts5_ok = False
        try:
            conn.execute("create virtual table if not exists temp.__fts_probe "
                         "using fts5(x)")
            conn.execute("drop table if exists temp.__fts_probe")
            fts5_ok = True
        except sqlite3.Error as e:
            _add("fts5", False, f"当前 SQLite 没有 FTS5：{e}")

        doc_rows = chunk_rows = gene_rows = 0
        for tbl in ("document_fts", "chunk_fts"):
            if tbl in tables:
                try:
                    n = conn.execute(f"select count(*) from {tbl}").fetchone()[0]
                except sqlite3.Error:
                    n = 0
                if tbl == "document_fts":
                    doc_rows = n
                else:
                    chunk_rows = n
        gene_table = "dna_gene_fts"
        if gene_table in tables:
            try:
                gene_rows = conn.execute(
                    f"select count(*) from {gene_table}").fetchone()[0]
            except sqlite3.Error:
                gene_rows = 0
        if fts5_ok:
            _add("fts5", True, "FTS5 可用")
            _add("fts_document", doc_rows > 0,
                 f"document_fts {doc_rows} 行"
                 if "document_fts" in tables else "没有 document_fts 表")
            _add("fts_chunk", chunk_rows > 0,
                 f"chunk_fts {chunk_rows} 行"
                 if "chunk_fts" in tables else "没有 chunk_fts 表")
            _add("fts_gene", gene_rows > 0,
                 f"{gene_table} {gene_rows} 行"
                 if gene_table in tables else f"没有 {gene_table} 表")
            capabilities["fts"] = bool(doc_rows or chunk_rows or gene_rows)

        # ---- 向量 ----
        vec_ok = False
        vec_rows = 0
        dim = 0
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
            conn.enable_load_extension(False)
            vec_ok = True
        except Exception as e:
            _add("vec_extension", False, f"sqlite-vec 扩展加载不了：{e}")
        if vec_ok and "document_vec" in tables:
            try:
                vec_rows = conn.execute(
                    "select count(*) from document_vec").fetchone()[0]
            except sqlite3.Error:
                vec_rows = 0
            try:
                row = conn.execute(
                    "select value from sys_meta where key='embed_dim'").fetchone()
                dim = int(row[0]) if row and row[0] else 0
            except sqlite3.Error:
                dim = 0
            _add("vector_index", vec_rows > 0,
                 f"document_vec {vec_rows} 行，维度 {dim or '未知'}")
            capabilities["vector"] = vec_rows > 0
        elif vec_ok:
            _add("vector_index", False, "没有 document_vec 表（未建向量索引）")

        # ---- 基因 ----
        gene_count = 0
        if "dna_gene" in tables:
            try:
                gene_count = conn.execute(
                    "select count(*) from dna_gene").fetchone()[0]
            except sqlite3.Error:
                gene_count = 0
            _add("genes", gene_count > 0, f"dna_gene {gene_count} 条")
            capabilities["genes"] = gene_count > 0
        else:
            _add("genes", False, "没有 dna_gene 表（基因层未启用）")

        # ---- 离线模式 ----
        offline = False
        try:
            row = conn.execute(
                "select value from sys_meta where key='dna_offline_mode'").fetchone()
            offline = bool(row and str(row[0]) == "1")
        except sqlite3.Error:
            offline = False
        _add("offline_mode", True, "离线模式已开启" if offline else "离线模式未开启")

        # ---- 证据层体量 ----
        try:
            ev = 0
            for t in ("document", "document_chunk", "entity_record"):
                if t in tables:
                    ev += conn.execute(f"select count(*) from {t}").fetchone()[0]
            _add("evidence", ev > 0, f"证据层共 {ev} 条（文档/块/记录）")
        except sqlite3.Error:
            pass

        # ---- LLM 配置 ----
        llm_ok, llm_detail = _llm_readiness(offline)
        _add("llm", llm_ok, llm_detail)
        capabilities["llm"] = llm_ok

        # ---- 能不能打包 ----
        bundle_ok, bundle_detail = _bundle_writable(tables)
        _add("bundle", bundle_ok, bundle_detail)
        capabilities["bundle"] = bundle_ok
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass

    # 「能不能离线跑」不是「每个通道都得满」：
    # 没有向量索引但有全文索引，照样答得出来；
    # 没有基因层（dna_gene 表还没上线）也不影响当普通知识库用。
    # 所以硬门槛只有三条：库能打开、FTS5 在、能打出包；
    # 再加一条「至少有一个检索通道里有东西」，否则答什么都答不出来。
    # 其余的通道状态由 capabilities 单独汇报，不用一个 ok 盖棺定论。
    by_key = {c["key"]: c["ok"] for c in checks}
    has_content = bool(doc_rows or chunk_rows or gene_rows or vec_rows)
    ok = bool(by_key.get("db", False)
              and by_key.get("fts5", False)
              and by_key.get("bundle", False)
              and has_content)
    if not has_content:
        _add("content", False, "库里没有任何可检索的内容")
    return {"ok": ok, "checks": checks, "capabilities": capabilities}


def _open_sync_conn(db):
    """归一成同步 sqlite3 连接

    返回 (连接, 是否由本次调用创建)。由调用方创建的直接用、关不掉；
    自己开的那种用完要关。

    支持三种入参：会话（AsyncSession/Session）、sqlite3 连接、库文件路径。
    路径这种最省事 —— 健康检查里多半只有一个路径在手。

    优先只读打开：自检不该有写权限，更不该在只读模式下
    因为 WAL 的共享内存文件缺失而失败 —— 那种情况下退回普通连接。
    """
    if isinstance(db, sqlite3.Connection):
        return db, False

    path = None
    if isinstance(db, (str, os.PathLike)):
        path = str(db)
    else:
        ss = getattr(db, "sync_session", None)
        try:
            if ss is not None:
                path = ss.get_bind().url.database
            else:
                path = db.get_bind().url.database
        except Exception:
            path = None
    if not path:
        return None, False
    path = os.path.abspath(path)
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True), True
    except sqlite3.Error:
        try:
            return sqlite3.connect(path), True
        except sqlite3.Error:
            return None, False


def _llm_readiness(offline: bool) -> tuple[bool, str]:
    """模型配置就绪吗

    离线模式下不需要模型 —— 系统走「直答」，
    把命中的基因与证据原样端出来。所以离线模式开启时，
    「没有模型」不是缺陷，是设计。
    """
    try:
        from . import ai_config
        cfg = ai_config.load_config()
    except Exception as e:
        return (True, f"读不到模型配置（离线模式已开，不影响）：{e}") if offline \
            else (False, f"读不到模型配置：{e}")
    if not cfg.get("enabled"):
        return (True, "未启用真实模型（离线直答可用）") if offline \
            else (False, "未启用真实模型（当前用 mock 规则引擎）")
    model = (cfg.get("model") or "").strip()
    if not model:
        return (False, "启用了模型但没填模型名")
    base = (cfg.get("base_url") or "").strip()
    where = base or cfg.get("provider") or "openai"
    return True, f"模型 {model}（{where}）"


def _bundle_writable(tables: set[str]) -> tuple[bool, str]:
    """这台机器能不能打得出包

    要有地方放临时文件（打包要建 FTS 库），也要有源表可导。
    """
    missing = [t for t in ("document", "document_chunk", "entity_record")
               if t not in tables]
    try:
        with tempfile.TemporaryDirectory(prefix="dna-bundle-probe-") as td:
            probe = Path(td) / "probe.bin"
            probe.write_bytes(b"x")
    except Exception as e:
        return False, f"临时目录不可写：{e}"
    if missing:
        return False, f"源表缺失：{', '.join(missing)}"
    return True, "可打包"
