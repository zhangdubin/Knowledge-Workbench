"""存储诊断与维护

这一层存在的理由：这套系统的数据由三块完全不同的东西组成 ——
文件原文（v0.3 起外置到文件目录）、FTS5 全文索引、sqlite-vec 向量索引。
三者增长速度与故障模式都不一样，混在一起谈「用了多少空间」没意义。

所以这里回答的不是「有多少条数据」，而是：
  1. 体积都花在哪了（分表拆解 + 文件目录实测）
  2. 离各条容量红线还有多远（headroom，含磁盘余量）
  3. 索引与业务表是否还对得上（drift）、原文与记录是否还对得上（orphan）
  4. 哪些维护动作能立刻回收空间

所有体积数字都走 dbstat 虚拟表 / 目录实测，不做估算——SQLite 的页分配与
逻辑行数之间差着空闲页、溢出页和索引，凭行数推算出来的体积没有参考价值。
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from . import settings_store

log = logging.getLogger("kb.maint")

# 页大小固定 4KB，dbstat 也按字节返回，这里只用于把「页」换算成人能读的数
MB = 1024 * 1024

# 容量红线。数值不是理论极限，而是「到这个量级就该规划迁移」的工程经验值：
# 舒适区之内 SQLite 单机完全够用；越过红线后，备份窗口、VACUUM 耗时、
# 崩溃恢复时间会一起变成问题，那时候再动手就被动了。
THRESHOLDS = {
    "db_bytes":          (10 * 1024 * MB, 50 * 1024 * MB),    # 单库文件
    # 文件原文总量 = 外置文件目录 + 仍在库里的 BLOB。
    # 外置之后这一项不再影响库文件大小，但仍受磁盘剩余空间约束，
    # 所以照旧单独设线。
    "blob_bytes":        (20 * 1024 * MB, 100 * 1024 * MB),   # 文件原文总量
    "record_rows":       (200_000, 1_000_000),                # 记录行数
    "chunk_rows":        (200_000, 1_000_000),                # 向量分块数
    "audit_rows":        (1_000_000, 5_000_000),              # 审计行数
    "free_bytes":        (512 * MB, 4 * 1024 * MB),           # 空闲页空洞
    "disk_free":         (20 * 1024 * MB, 5 * 1024 * MB),     # 磁盘剩余（反向：越小越危险）
}


def _level(value: float, warn: float, danger: float) -> str:
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _db_path() -> str:
    from ..database import db_file_path
    return db_file_path()


def _sync_query(sql: str, params: dict | None = None) -> list[tuple]:
    """在直连上跑一条只读查询

    maintenance 里绝大多数 SQL 都是 PRAGMA / dbstat / 汇总，不属于 ORM
    也不该被包进事务，所以统一走 `direct_connection()`。代价是这个连接没有
    加载 sqlite-vec，查不了 document_vec 这类虚拟表 —— 需要向量表的查询
    一律走 async session，见 `index_report`。
    """
    from ..database import direct_connection
    conn = direct_connection()
    try:
        cur = conn.cursor()
        try:
            return cur.execute(sql, params or {}).fetchall()
        finally:
            cur.close()
    finally:
        conn.close()


async def _q(sql: str, params: dict | None = None) -> list[tuple]:
    return await asyncio.to_thread(_sync_query, sql, params)


def _scalar(rows, default=0):
    if not rows:
        return default
    v = rows[0][0]
    return default if v is None else v


# ============================================================ 存储诊断

async def storage_report() -> dict:
    """体积构成 + 行数 + 空洞 + 容量余量，一次给全"""
    path = _db_path()
    started = time.time()

    # ---- 文件层面（不需要连库，即使库锁着也能算） ----
    def _files() -> dict:
        out = {"db": 0, "wal": 0, "shm": 0, "backups": 0, "free_kb": 0, "page_count": 0}
        for suffix, key in (("", "db"), ("-wal", "wal"), ("-shm", "shm")):
            try:
                out[key] = os.path.getsize(path + suffix)
            except OSError:
                out[key] = 0
        # 备份目录的位置是可配的（界面可改），这里按**生效值**统计，
        # 否则改了目录之后，报表还会去统计旧位置
        bdir = str(settings_store.get_value("backup_dir", settings.backup_dir))
        if os.path.isdir(bdir):
            total = 0
            for name in os.listdir(bdir):
                try:
                    total += os.path.getsize(os.path.join(bdir, name))
                except OSError:
                    pass
            out["backups"] = total
        return out

    files = await asyncio.to_thread(_files)

    # ---- PRAGMA 层面 ----
    prag = await _q("pragma page_size")
    page_size = int(_scalar(prag, 4096))
    page_count = int(_scalar(await _q("pragma page_count")))
    free_pages = int(_scalar(await _q("pragma freelist_count")))
    auto_vacuum = int(_scalar(await _q("pragma auto_vacuum")))
    journal = str(_scalar(await _q("pragma journal_mode"), "?"))
    files["page_count"] = page_count
    files["free_kb"] = free_pages * page_size // 1024
    files["page_size"] = page_size

    # ---- 分表体积（dbstat）----
    tables: list[dict] = []
    try:
        rows = await _q(
            "select name, sum(pgsize), sum(ncell) from dbstat "
            "group by name order by sum(pgsize) desc"
        )
        total = sum(int(r[1] or 0) for r in rows)
        for name, pagesize, ncell in rows:
            size = int(pagesize or 0)
            if size < 16 * 1024:          # 小于 16KB 的表不进榜，噪音太大
                continue
            tables.append({
                "name": name,
                "bytes": size,
                "pct": round(100.0 * size / total, 2) if total else 0.0,
                "cells": int(ncell or 0),
            })
        tables = tables[:14]
    except Exception as e:
        log.warning("dbstat 不可用，体积构成退化为整体值：%s", e)

    # ---- 关键计数与内容体量 ----
    counts = {}
    for table in ("entity_type", "entity_record", "document", "document_chunk",
                  "relation_def", "relation_record", "audit_log", "user"):
        try:
            counts[table] = int(_scalar(await _q(f"select count(*) from {table}")))
        except Exception:
            counts[table] = 0

    docs = await _q(
        "select count(*), coalesce(sum(size),0), coalesce(max(size),0), "
        "coalesce(sum(length(data)),0), coalesce(sum(length(extracted_text)),0) "
        "from document where deleted_at is null"
    )
    doc_count, doc_bytes_declared, doc_max, blob_bytes, text_chars = (
        int(docs[0][0]), int(docs[0][1]), int(docs[0][2]),
        int(docs[0][3]), int(docs[0][4]),
    )

    # 外置文件目录的实测占用。与 BLOB 分开列：
    # 迁移过程中两边都有数据，「原文一共多少」必须加起来看，
    # 但「库文件为什么这么大」只看 BLOB 那一列。
    from . import filestore
    fs = filestore.usage()
    fs_bytes = fs["bytes"]

    # 还有多少原文没迁出去（决定「外迁」按钮是不是还有活干）
    pending_rows = await _q(
        "select count(*), coalesce(sum(length(data)),0) from document "
        "where data is not null and (storage is null or storage <> 'fs')"
    )
    pending_count, pending_bytes = int(pending_rows[0][0]), int(pending_rows[0][1])

    total_file_bytes = blob_bytes + fs_bytes

    # 软删除的文件原文仍占着库文件，必须单独暴露出来，
    # 否则「回收站里有 50GB」这件事在看体积时会完全隐形
    trash = await _q(
        "select count(*), coalesce(sum(length(data)),0) from document where deleted_at is not null"
    )
    trash_count, trash_bytes = int(trash[0][0]), int(trash[0][1])

    embed_dim = 0
    try:
        embed_dim = int(_scalar(await _q(
            "select value from sys_meta where key='embed_dim'"), 0) or 0)
    except Exception:
        pass

    embedded_chunks = int(_scalar(await _q(
        "select count(*) from document_chunk where embedded = 1")))

    # 向量索引的体积可以精确算：每块 dim*4 字节，vec0 按 1024 块为一批分配
    vec_logical = embedded_chunks * embed_dim * 4
    vec_alloc = -(-embedded_chunks // 1024) * 1024 * embed_dim * 4 if embed_dim else 0

    fts_bytes = 0
    for t in tables:
        if t["name"].startswith("document_fts"):
            fts_bytes += t["bytes"]

    # ---- 增长趋势（近 30 天，按天） ----
    growth = []
    try:
        rows = await _q(
            "select substr(created_at,1,10) d, count(*) c, coalesce(sum(size),0) b "
            "from document where deleted_at is null "
            "group by d order by d desc limit 30"
        )
        growth = [{"date": r[0], "docs": int(r[1]), "bytes": int(r[2])} for r in rows]
    except Exception:
        pass

    # ---- 容量评估 ----
    db_bytes = files["db"] or (page_count * page_size)
    checks = [
        ("单库文件体积", db_bytes, *THRESHOLDS["db_bytes"], "库文件",
         "备份、VACUUM、崩溃恢复的耗时都随这个数线性增长"),
        ("文件原文总量", total_file_bytes, *THRESHOLDS["blob_bytes"], "文件原文",
         "外置后不影响库文件大小，但受磁盘剩余空间约束，是扩容规划的主变量"),
        ("业务记录行数", counts.get("entity_record", 0), *THRESHOLDS["record_rows"], "条",
         "关键词检索走 LIKE '%kw%'，无法命中索引，按行数线性变慢"),
        ("向量分块数", counts.get("document_chunk", 0), *THRESHOLDS["chunk_rows"], "块",
         "每块向量占 dim×4 字节，是索引里最重的一类"),
        ("审计日志行数", counts.get("audit_log", 0), *THRESHOLDS["audit_rows"], "条",
         "可自动清理，但也可能悄悄涨到很大"),
        ("空闲页空洞", free_pages * page_size, *THRESHOLDS["free_bytes"], "空洞",
         "删除与更新留下的空洞，只有 VACUUM 能回收"),
    ]
    capacity = [{
        "label": label,
        "value": value,
        "unit": unit,
        "level": _level(value, warn, danger),
        "warn_at": warn,
        "danger_at": danger,
        # 百分比按「危险线」为 100%，让进度条有可比性
        "pct": round(min(100.0, 100.0 * value / danger), 2) if danger else 0.0,
        "hint": hint,
    } for label, value, warn, danger, unit, hint in checks]

    # 磁盘剩余空间是「越小越危险」的反向指标，单独算：
    # 原文外置之后，盘满会先于库大发生，而且盘满时写入会静默失败，
    # 所以这一条必须是存储页上最醒目的那根线。
    disk = filestore.disk_free()
    if disk.get("total"):
        warn_free, danger_free = THRESHOLDS["disk_free"]
        free = disk["free"]
        capacity.append({
            "label": "磁盘剩余空间",
            "value": free,
            "unit": "可用",
            "level": "danger" if free <= danger_free else ("warn" if free <= warn_free else "ok"),
            "warn_at": warn_free,
            "danger_at": danger_free,
            # 反向：剩余越少越接近 100%
            "pct": round(min(100.0, 100.0 * warn_free / max(free, 1)), 2),
            "hint": f"{filestore.root()} 所在磁盘，共 "
                    f"{disk['total'] / 1024 ** 3:.1f}GB，已用 {disk['pct_used']}%",
        })

    return {
        "path": os.path.abspath(path),
        "bytes": db_bytes,
        "files": files,
        "page_size": page_size,
        "journal_mode": journal,
        "auto_vacuum": auto_vacuum,
        "auto_vacuum_label": {
            0: "NONE（删除后空间不回收）",
            1: "FULL（每次提交都整理，写放大严重）",
            2: "INCREMENTAL（可手动增量回收，推荐）",
        }.get(auto_vacuum, str(auto_vacuum)),
        "tables": tables,
        "counts": counts,
        "documents": {
            "count": doc_count,
            "bytes": doc_bytes_declared,
            "max_bytes": doc_max,
            "blob_bytes": blob_bytes,
            "text_chars": text_chars,
            "trash_count": trash_count,
            "trash_bytes": trash_bytes,
        },
        "file_store": {
            **fs,
            "mode": filestore.MODE_FS if filestore.enabled() else filestore.MODE_DB,
            "enabled": filestore.enabled(),
            "fsync": settings.file_store_fsync,
            "bytes": fs_bytes,
            "pending_count": pending_count,
            "pending_bytes": pending_bytes,
            "total_bytes": total_file_bytes,
            "disk": disk,
        },
        "index": {
            "embed_dim": embed_dim,
            "embedded_chunks": embedded_chunks,
            "vec_logical_bytes": vec_logical,
            "vec_alloc_bytes": vec_alloc,
            "fts_bytes": fts_bytes,
            "vec_ratio": round(100.0 * vec_alloc / db_bytes, 2) if db_bytes else 0.0,
        },
        "growth": growth,
        "capacity": capacity,
        "tips": _tips(capacity, files, counts, doc_max, trash_bytes, auto_vacuum,
                      {**fs, "pending_count": pending_count,
                       "pending_bytes": pending_bytes, "disk": disk}),
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _tips(capacity, files, counts, doc_max, trash_bytes, auto_vacuum,
          fs: dict) -> list[dict]:
    """把数字翻译成「现在该做什么」

    只给可执行的结论，不复述上面的指标。
    """
    out: list[dict] = []
    worst = max(capacity, key=lambda c: c["pct"])

    if files.get("wal", 0) > 64 * MB:
        out.append({"level": "warn",
                    "text": f"WAL 文件已达 {files['wal'] / MB:.0f} MB，"
                            "说明写入频繁但检查点跟不上，建议执行「检查点」"})
    if trash_bytes > 256 * MB:
        out.append({"level": "warn",
                    "text": f"回收站里还有 {trash_bytes / MB:.0f} MB 文件原文在占空间，"
                            "彻底删除后需再执行「回收空间」才会真正释放"})
    if auto_vacuum == 0 and files.get("free_kb", 0) > 128 * 1024:
        out.append({"level": "warn",
                    "text": f"存在 {files['free_kb'] / 1024:.0f} MB 空闲空洞且未开启 "
                            "auto_vacuum，需要定期手动执行「回收空间」"})
    if auto_vacuum == 0:
        out.append({"level": "info",
                    "text": "auto_vacuum 为 NONE：删除数据不会自动缩小库文件。"
                            "数据还会长期增长时建议保持现状（增量整理有写放大），"
                            "只有确实要缩容时才需要 VACUUM"})

    # 外迁进度：这是「库文件还能不能瘦下来」的直接指标
    pending = int(fs.get("pending_count") or 0)
    if pending:
        out.append({"level": "warn",
                    "text": f"还有 {pending} 个文件的原文（{fs.get('pending_bytes', 0) / MB:.1f} MB）"
                            "以 BLOB 形式留在库里，执行「外迁库内文件原文」可搬到文件目录；"
                            "迁完再执行「整体重整」才能真正腾出库文件空间"})

    disk = fs.get("disk") or {}
    if disk.get("total") and disk["free"] <= THRESHOLDS["disk_free"][0]:
        out.append({"level": "warn" if disk["free"] > THRESHOLDS["disk_free"][1] else "danger",
                    "text": f"文件目录所在磁盘只剩 {disk['free'] / 1024 ** 3:.1f}GB。"
                            "原文外置后盘满会先于库大发生，且盘满时写入静默失败 —— "
                            "请尽快扩容或清理，备份目录也应指向另一块盘"})

    if doc_max > int(settings.large_file_warn_mb) * MB:
        if fs.get("enabled"):
            out.append({"level": "info",
                        "text": f"存在 {doc_max / MB:.0f} MB 的大文件，已超过 "
                                f"{settings.large_file_warn_mb}MB 提示线。原文已外置，"
                                "下载走流式不占内存；但正文抽取仍需整块读入，"
                                "请按最大单文件体积的 2~3 倍预留容器内存"})
        else:
            out.append({"level": "warn",
                        "text": f"存在 {doc_max / MB:.0f} MB 的大文件，已超过 "
                                f"{settings.large_file_warn_mb}MB 提示线。当前原文仍在库里，"
                                "读取 BLOB 是整块进内存的，并发下载大文件会直接把内存打满，"
                                "建议开启外置存储（KB_FILE_STORE=fs）"})

    if worst["level"] == "ok":
        out.append({"level": "ok",
                    "text": f"全部指标都在舒适区，最紧的一项是「{worst['label']}」"
                            f"（{worst['pct']:.0f}% 红线）。当前架构无需迁移"})
    elif worst["level"] == "warn":
        out.append({"level": "warn",
                    "text": f"「{worst['label']}」已进入需留意区间（{worst['pct']:.0f}% 红线）。"
                            "先按下面的备份与维护流程稳住，再评估是否需要拆分存储"})
    else:
        out.append({"level": "danger",
                    "text": f"「{worst['label']}」已越过红线（{worst['pct']:.0f}%）。"
                            "继续增长会让备份窗口与恢复时间失控，建议尽快把文件原文"
                            "拆出库外（见下方迁移建议）"})
    return out


# ============================================================ 索引一致性

async def index_report(db: AsyncSession) -> dict:
    """体检业务表与两个索引是否还对得上

    这两类索引都在写入路径上「尽力而为」地更新，失败只记日志不抛错。
    设计上这是对的（索引挂了不该影响业务），代价是它们会静默漂移：
    分块标记着已嵌入、向量却已经没了，语义检索从此少召回而且查不出来。
    所以需要一个能主动发现差异的体检。

    这里必须走 async session 而不是直连：document_vec 是 vec0 虚拟表，
    只有加载了扩展的连接才认得它，而扩展是在 engine 的 connect 钩子里挂上的。
    """
    out: dict = {"fts": {}, "vec": {}, "ok": True, "problems": []}

    async def ids(sql: str) -> set[int]:
        rows = (await db.execute(text(sql))).fetchall()
        return {r[0] for r in rows}

    # ---- FTS5 ----
    fts_ids = await ids("select rowid from document_fts")
    doc_ids = await ids("select id from document where deleted_at is null")
    out["fts"] = {
        "indexed": len(fts_ids),
        "documents": len(doc_ids),
        "missing": len(doc_ids - fts_ids),
        "orphan": len(fts_ids - doc_ids),
    }
    if doc_ids - fts_ids:
        out["problems"].append(
            f"{len(doc_ids - fts_ids)} 个文件没有全文索引，关键词检索会漏掉它们")
    if fts_ids - doc_ids:
        out["problems"].append(
            f"{len(fts_ids - doc_ids)} 条全文索引指向已不存在的文件（删除时没清干净）")

    # ---- 向量 ----
    try:
        marked = await ids("select id from document_chunk where embedded = 1")
        present = await ids("select rowid from document_vec")
    except Exception as e:
        # 扩展没加载上时这里会报 "no such module: vec0"，当作不可用而不是 500
        marked, present = set(), set()
        out["problems"].append(f"向量表不可读（sqlite-vec 扩展未加载？）：{e}")

    all_chunks = int(_scalar(await _q("select count(*) from document_chunk")))
    out["vec"] = {
        "chunks": all_chunks,
        "marked_embedded": len(marked),
        "vectors": len(present),
        # 标记了但其实没向量 —— 最隐蔽的一种：检索时这些块永远不会被召回
        "marked_but_missing": len(marked - present),
        # 有向量但标记没打开 —— 影响统计与重建判断，检索本身不受影响
        "present_but_unmarked": len(present - marked),
        "unembedded": max(all_chunks - len(marked), 0),
    }
    if marked - present:
        out["problems"].append(
            f"{len(marked - present)} 个分块标记为已向量化但向量缺失，"
            "语义检索会静默漏检（可一键修复）")
    if present - marked:
        out["problems"].append(
            f"{len(present - marked)} 个向量没有被标记，统计与重建判断会失真")

    # ---- 抽取状态 ----
    ext = await _q(
        "select extract_status, count(*) from document where deleted_at is null "
        "group by extract_status"
    )
    out["extract"] = {str(r[0] or "?"): int(r[1]) for r in ext}
    failed = out["extract"].get("failed", 0)
    if failed:
        out["problems"].append(f"{failed} 个文件正文抽取失败，全文与语义检索都用不了它们")

    out["ok"] = not out["problems"]
    return out


async def repair_index(db: AsyncSession, *, rebuild_fts: bool = True) -> dict:
    """修复索引漂移（幂等，可反复执行）

    修的是「状态不一致」，不重算向量本身：向量重算要调外部 embedding 接口，
    属于有成本、有额度的动作，不该混在一次「修复索引」里悄悄发生。
    """
    from . import docindex

    fixed = {"vec_marked_synced": 0, "vec_orphans_removed": 0, "fts_rebuilt": 0}

    # 1) 让 embedded 标记与向量表实际内容对齐
    try:
        rows = await db.execute(text(
            "select id from document_chunk where embedded = 0 "
            "and id in (select rowid from document_vec)"
        ))
        to_mark = [r[0] for r in rows.fetchall()]
        if to_mark:
            await db.execute(text(
                "update document_chunk set embedded = 1 where id in "
                f"({','.join(str(i) for i in to_mark)})"))
            fixed["vec_marked_synced"] = len(to_mark)

        rows = await db.execute(text(
            "select id from document_chunk where embedded = 1 "
            "and id not in (select rowid from document_vec)"
        ))
        to_unmark = [r[0] for r in rows.fetchall()]
        if to_unmark:
            await db.execute(text(
                "update document_chunk set embedded = 0 where id in "
                f"({','.join(str(i) for i in to_unmark)})"))
            fixed["vec_marked_synced"] += len(to_unmark)
        await db.commit()
    except Exception as e:
        log.warning("向量标记同步失败：%s", e)

    # 2) 清掉指向已不存在分块的向量
    try:
        await db.execute(text(
            "delete from document_vec where rowid not in (select id from document_chunk)"))
        await db.commit()
    except Exception as e:
        log.warning("孤立向量清理失败：%s", e)

    # 3) 补全文索引（按 id 逐个重建，避免一次性把正文全读进内存）
    if rebuild_fts:
        try:
            rows = await db.execute(text(
                "select id from document where deleted_at is null "
                "and id not in (select rowid from document_fts)"))
            missing = [r[0] for r in rows.fetchall()]
            from ..models import Document
            for did in missing:
                doc = await db.get(Document, did)
                if not doc:
                    continue
                await docindex.index_document(
                    db, doc.id, doc.title, doc.filename, doc.tags,
                    doc.summary, doc.extracted_text or "")
                fixed["fts_rebuilt"] += 1
            await db.execute(text(
                "delete from document_fts where rowid not in "
                "(select id from document where deleted_at is null)"))
            await db.commit()
        except Exception as e:
            log.warning("全文索引重建失败：%s", e)

    return fixed


# ============================================================ 维护动作

# 每个动作都写清楚「会不会阻塞」——运维在白天点按钮之前必须知道这件事
OPS = {
    "externalize_blobs": {
        "label": "外迁库内文件原文",
        "desc": "把仍以 BLOB 形式存在库里的原文搬到文件目录并清空该列，可反复执行、"
                "分批进行、中断后续跑；全部迁完后配合整体重整才能真正回收空间",
        "blocking": False,
    },
    "verify_files": {
        "label": "原文完整性普查",
        "desc": "检查「有元数据、无内容」与「有文件、无记录」两类不一致，"
                "只读不修改，用于确认备份与迁移是否完整",
        "blocking": False,
    },
    "optimize": {
        "label": "刷新查询计划",
        "desc": "更新统计信息，避免数据量变化后查询仍按旧基数选错索引",
        "blocking": False,
    },
    "checkpoint": {
        "label": "检查点（截断 WAL）",
        "desc": "把 WAL 里的内容合并回主库并清空 WAL，适合备份前执行",
        "blocking": False,
    },
    "analyze": {
        "label": "重新统计（ANALYZE）",
        "desc": "完整重算索引统计，比 optimize 慢但更彻底",
        "blocking": False,
    },
    "incremental_vacuum": {
        "label": "增量回收空闲页",
        "desc": "仅在 auto_vacuum=INCREMENTAL 时有效，逐步释放空洞，几乎不阻塞",
        "blocking": False,
    },
    "vacuum": {
        "label": "整体重整（VACUUM）",
        "desc": "重写整个库文件并回收全部空洞，期间需要独占锁，会阻塞所有请求",
        "blocking": True,
    },
    "integrity_check": {
        "label": "完整性校验",
        "desc": "逐页校验数据库结构，大库上耗时较长，只读不阻塞写入",
        "blocking": False,
    },
}


# ============================================================ 原文外迁 / 一致性普查

async def externalize_blobs(batch: int = 50, max_batches: int = 0) -> dict:
    """把仍以 BLOB 形式留在库里的原文搬到文件目录

    设计要点：
      - **分批 + 逐批提交**：一次性搬完几万个文件会让事务长得离谱，
        中途失败就要全部重来。每批 50 条、批批提交，中断后重跑即可续上。
      - **幂等**：只处理 storage<>'fs' 的行；已迁过的行不再命中，
        所以「跑第二次」是安全的空操作。
      - **先落盘、后清列**：文件先写好（内容寻址、原子 rename）再清空 BLOB，
        任何一步崩掉都不会丢原文 —— 最坏是重复处理同一行。
      - **不清 data 就换 storage 是致命的**：那样读路径会去找一个不存在的文件，
        所以这两件事必须在同一个事务里。
    """
    from ..database import SessionLocal
    from ..models import Document
    from . import filestore
    from sqlalchemy import select as sa_select

    if not filestore.enabled():
        return {"ok": False, "result": "当前 KB_FILE_STORE=db，未启用外置存储"}
    filestore.ensure_root()

    moved = 0
    moved_bytes = 0
    skipped = 0
    batches = 0
    errors: list[str] = []
    started = time.time()

    while True:
        async with SessionLocal() as db:
            rows = (await db.execute(
                sa_select(Document)
                .where(Document.data.is_not(None),
                       (Document.storage.is_(None)) | (Document.storage != "fs"))
                .order_by(Document.id)
                .limit(batch)
            )).scalars().all()
            if not rows:
                break

            for doc in rows:
                blob = doc.data or b""
                if not blob:
                    # 空 BLOB：把归属改成 fs 只会让读路径去找不存在的文件，
                    # 保持原样并跳过，交给「原文完整性普查」去报告
                    skipped += 1
                    continue
                try:
                    rel = filestore.put(blob, doc.sha256, doc.ext)
                    doc.storage = filestore.MODE_FS
                    doc.path = rel
                    doc.data = None          # 与 storage 同事务提交，不能分开
                    moved += 1
                    moved_bytes += len(blob)
                except Exception as e:
                    errors.append(f"#{doc.id}: {type(e).__name__}: {e}")
            await db.commit()

        batches += 1
        if max_batches and batches >= max_batches:
            break

    filestore.invalidate_usage()
    remaining = _pending_blob_count()
    freed_hint = ""
    if remaining == 0 and moved:
        freed_hint = "库内原文已清空；执行「整体重整（VACUUM）」才能真正缩小库文件"

    return {
        "ok": not errors,
        "result": f"已外迁 {moved} 个文件（{moved_bytes / MB:.1f} MB）"
                  f"{'，跳过 ' + str(skipped) + ' 个空原文' if skipped else ''}，"
                  f"剩余待迁 {remaining} 个。{freed_hint}",
        "moved": moved,
        "moved_bytes": moved_bytes,
        "skipped": skipped,
        "remaining": remaining,
        "errors": errors[:10],
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _pending_blob_count() -> int:
    try:
        rows = _sync_query(
            "select count(*) from document where data is not null "
            "and (storage is null or storage <> 'fs')"
        )
        return int(rows[0][0]) if rows else 0
    except Exception:
        return -1


async def verify_files(limit: int = 20) -> dict:
    """原文与记录的一致性普查（只读）

    检查两类不一致：
      A. 记录说有文件，盘上却没有 → 最严重，会导致下载 404 / 抽取失败
      B. 盘上有文件，没有任何记录引用 → 空间泄漏，通常来自失败的删除

    A 类不可能自动修复（内容已经没了，只能从备份恢复）；
    B 类可以清掉，但必须先确认不是备份临时文件或正在写入的半成品。
    """
    from ..database import SessionLocal
    from ..models import Document
    from sqlalchemy import select as sa_select
    from . import filestore

    if not filestore.enabled():
        return {"ok": False, "result": "未启用外置存储，无需普查",
                "missing": [], "orphans": []}

    missing: list[dict] = []
    missing_count = 0
    checked = 0

    async with SessionLocal() as db:
        # 流式分页扫，避免一次性把几十万行读进内存
        page = 0
        while True:
            rows = (await db.execute(
                sa_select(Document.id, Document.filename, Document.path, Document.size)
                .where(Document.storage == filestore.MODE_FS)
                .order_by(Document.id)
                .offset(page * 500).limit(500)
            )).all()
            if not rows:
                break
            for did, name, path, size in rows:
                checked += 1
                if not path or not filestore.exists(path):
                    missing_count += 1
                    if len(missing) < limit:
                        missing.append({"id": did, "filename": name,
                                        "path": path, "size": size})
            page += 1

    # B 类：遍历目录，与库里的 path 集合比对
    known: set[str] = set()
    async with SessionLocal() as db:
        for path, in (await db.execute(
            sa_select(Document.path).where(Document.path.is_not(None))
        )).all():
            if path:
                known.add(str(path))

    orphans: list[dict] = []
    orphan_count = 0
    orphan_bytes = 0
    base = filestore.root()
    if base.is_dir():
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if name.startswith(".tmp-"):
                    continue
                p = os.path.join(dirpath, name)
                rel = os.path.relpath(p, base)
                if rel in known:
                    continue
                orphan_count += 1
                try:
                    orphan_bytes += os.path.getsize(p)
                except OSError:
                    pass
                if len(orphans) < limit:
                    orphans.append({"path": rel})

    ok = missing_count == 0
    msg = (f"已核对 {checked} 条记录：缺失原文 {missing_count} 个，"
           f"无主文件 {orphan_count} 个（{orphan_bytes / MB:.1f} MB）")
    if not ok:
        msg += "。缺失原文无法自动修复，请从备份的 files 目录恢复"
    return {"ok": ok, "result": msg, "checked": checked,
            "missing_count": missing_count, "missing": missing,
            "orphan_count": orphan_count, "orphan_bytes": orphan_bytes,
            "orphans": orphans}


def _sync_op(op: str) -> dict:
    from ..database import direct_connection
    conn = direct_connection()
    cur = conn.cursor()
    started = time.time()
    try:
        if op == "optimize":
            cur.execute("pragma optimize")
            return {"ok": True, "result": "已刷新查询计划"}
        if op == "analyze":
            cur.execute("analyze")
            return {"ok": True, "result": "统计信息已重算"}
        if op == "checkpoint":
            row = cur.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()
            return {"ok": True, "result": f"检查点完成 {list(row or [])}"}
        if op == "incremental_vacuum":
            av = int(cur.execute("pragma auto_vacuum").fetchone()[0] or 0)
            if av != 2:
                return {"ok": False,
                        "result": "当前 auto_vacuum 不是 INCREMENTAL，无法增量回收。"
                                  "改用「整体重整」或先开启增量模式"}
            cur.execute("pragma incremental_vacuum")
            return {"ok": True, "result": "已增量回收空闲页"}
        if op == "vacuum":
            cur.execute("vacuum")
            return {"ok": True, "result": "已重写库文件并回收空洞"}
        if op == "integrity_check":
            row = cur.execute("pragma integrity_check").fetchone()
            msg = str(row[0] if row else "?")
            return {"ok": msg.lower() == "ok", "result": msg}
        return {"ok": False, "result": f"不支持的动作：{op}"}
    except Exception as e:
        return {"ok": False, "result": f"{type(e).__name__}: {e}"}
    finally:
        cur.close()
        conn.close()
        log.info("维护动作 %s 结束，耗时 %.2fs", op, time.time() - started)


async def run_op(op: str, *, batch: int = 50) -> dict:
    if op not in OPS:
        return {"ok": False, "result": f"不支持的动作：{op}", "op": op}

    started = time.time()

    # 这两个动作要读写 ORM 层（不只是跑 PRAGMA），所以不走 _sync_op 的直连通道：
    # 直连连接不加载 sqlite-vec 扩展，也拿不到 ORM 的事务语义。
    # 它们内部各自管理会话与提交，天然是协程。
    if op == "externalize_blobs":
        out = await externalize_blobs(batch=batch)
    elif op == "verify_files":
        out = await verify_files()
    else:
        out = await asyncio.to_thread(_sync_op, op)

    out["op"] = op
    out["label"] = OPS[op]["label"]
    out["elapsed_ms"] = int((time.time() - started) * 1000)
    return out


# ============================================================ 备份（服务内触发）

SNAP_PREFIX = "snap-"


async def backup_dir() -> str:
    """生效的备份目录：运行期设置 > 环境变量 > 配置默认值

    优先级与来源解释见 services/settings_store.py。这里的意义在于
    界面上的「系统设置 → 备份目录」改完**立即生效**，不需要重启容器 ——
    而环境变量以前是最高优先级，导致 `KB_BACKUP_DIR` 一旦在 compose 里
    写死，配置文件里再怎么改都毫无效果。
    """
    return str(settings_store.get_value("backup_dir", settings.backup_dir))


def backup_keep() -> int:
    """生效的备份保留份数（同样可在界面上改）"""
    try:
        return int(settings_store.get_value("backup_keep", settings.backup_keep))
    except (TypeError, ValueError):
        return settings.backup_keep


def _snapshot_stats(root: str) -> dict:
    """统计一份快照的构成（库文件 + 文件目录）"""
    db_bytes = 0
    files_bytes = 0
    files_count = 0
    dbp = os.path.join(root, "kb.db")
    if os.path.isfile(dbp):
        db_bytes = os.path.getsize(dbp)
    froot = os.path.join(root, "files")
    if os.path.isdir(froot):
        for dirpath, _d, filenames in os.walk(froot):
            for name in filenames:
                files_count += 1
                try:
                    files_bytes += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
    return {"db_bytes": db_bytes, "files_count": files_count,
            "files_bytes": files_bytes, "bytes": db_bytes + files_bytes}


async def list_backups() -> list[dict]:
    """列出备份目录下的可用备份

    两种形态都要认：
      - `snap-<时间>/`：v0.3 起的完整快照（kb.db + files/），可独立恢复
      - `kb-<时间>.db`：v0.2 的纯库备份，原文还在 BLOB 里。
        原文外置后这种备份**不再完整**（缺 files 目录），所以要显式标出来，
        否则运维会以为「有备份」而在真出事时发现文件全没了。
    """
    d = await backup_dir()

    def _scan() -> list[dict]:
        if not os.path.isdir(d):
            return []
        out: list[dict] = []
        for name in sorted(os.listdir(d), reverse=True):
            p = os.path.join(d, name)
            if os.path.isdir(p) and name.startswith(SNAP_PREFIX):
                out.append(_snapshot_entry(d, name))
            elif name.endswith(".db"):
                st = os.stat(p)
                out.append({
                    "name": name, "path": p, "kind": "legacy",
                    "complete": not settings.file_store == "fs",
                    "bytes": st.st_size,
                    "db_bytes": st.st_size,
                    "files_count": 0, "files_bytes": 0,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(st.st_mtime)),
                })
        return out

    return await asyncio.to_thread(_scan)


def _snapshot_files(live_root: str, dst_root: str, prev_root: str | None) -> dict:
    """把文件目录快照到 dst（增量：优先从上一份快照硬链接）

    为什么可以用硬链接：原文是**内容寻址且只增不改**的 —— 同一个路径
    永远对应同一份内容。所以上一份快照里已有的文件直接 link 过去即可，
    既省空间（只存增量）又省时间（几十万个文件的备份是秒级而不是分钟级）。

    硬链接失败（备份目录与上一份快照跨了文件系统）时回退为真拷贝，
    语义不变，只是更慢更占空间。
    """
    linked = 0
    copied = 0
    if not os.path.isdir(live_root):
        return {"linked": 0, "copied": 0, "files": 0}

    for dirpath, _dirnames, filenames in os.walk(live_root):
        for name in filenames:
            if name.startswith(".tmp-"):
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, live_root)
            dst = os.path.join(dst_root, rel)
            if os.path.exists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            done = False
            if prev_root:
                cand = os.path.join(prev_root, rel)
                if os.path.isfile(cand):
                    try:
                        os.link(cand, dst)
                        linked += 1
                        done = True
                    except OSError:
                        done = False
            if not done:
                import shutil as _sh
                _sh.copy2(src, dst)
                copied += 1
    return {"linked": linked, "copied": copied,
            "files": linked + copied}


async def make_backup(target_dir: str | None = None, *,
                      with_files: bool = True, keep: int | None = None) -> dict:
    """做一次完整快照：库文件（VACUUM INTO）+ 文件原文目录（增量硬链接）

    为什么原文外置后备份反而更简单了：
      库文件里只剩元数据和索引，`VACUUM INTO` 的拷贝量小了一到两个数量级；
      而文件目录是内容寻址、只增不改的，天然适合增量快照 ——
      「备份慢」这件事从根上被拆掉了。

    为什么不用 cp 备份库：库在 WAL 模式下运行时最新数据可能还在 -wal 文件里，
    单拷 kb.db 会得到一份退回上次检查点的旧库，写入中还可能拷到撕裂的页。
    VACUUM INTO 走读事务快照，一致性由 SQLite 保证，顺带剔掉空闲页。
    """
    target_dir = target_dir or await backup_dir()
    os.makedirs(target_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snap = os.path.join(target_dir, f"{SNAP_PREFIX}{stamp}")
    os.makedirs(snap, exist_ok=True)
    dest = os.path.join(snap, "kb.db")
    part = dest + ".part"

    # 上一份快照作为硬链接来源（按名字倒序，跳过刚建的这个空目录）
    prev = None
    try:
        for name in sorted(os.listdir(target_dir), reverse=True):
            if not name.startswith(SNAP_PREFIX):
                continue
            cand = os.path.join(target_dir, name)
            if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "kb.db")) \
                    and cand != snap:
                prev = os.path.join(cand, "files")
                break
    except OSError:
        prev = None

    def _dump() -> None:
        """在源库上跑 VACUUM INTO。目标先写 .part，避免半成品被当成可用备份。"""
        from ..database import direct_connection
        if os.path.exists(part):
            os.remove(part)
        conn = direct_connection(busy_ms=60000)
        try:
            conn.execute(f"vacuum into '{part}'")
        finally:
            conn.close()

    def _verify() -> dict:
        """校验必须连到**备份文件本身**去查。

        早先图省事复用了源库连接来做 quick_check，那校验的是源库——
        一份损坏的备份照样能全绿通过，等于没校验。
        """
        import sqlite3
        c = sqlite3.connect(f"file:{part}?mode=ro", uri=True)
        try:
            check = str(c.execute("pragma quick_check").fetchone()[0] or "")
            counts = {}
            for t in ("document", "entity_record", "document_chunk", "audit_log"):
                try:
                    counts[t] = c.execute(f"select count(*) from {t}").fetchone()[0]
                except sqlite3.Error:
                    counts[t] = None
            # 原文外置后，「库里有多少行还写着 path」就是备份完整性的另一半：
            # 缺了 files 目录时这几行会全部变成死档
            try:
                counts["fs_documents"] = c.execute(
                    "select count(*) from document where storage='fs'"
                ).fetchone()[0]
            except sqlite3.Error:
                counts["fs_documents"] = None
        finally:
            c.close()
        return {"quick_check": check, "ok": check.lower() == "ok", "counts": counts}

    await asyncio.to_thread(_dump)
    report = await asyncio.to_thread(_verify)
    if not report["ok"]:
        try:
            os.remove(part)
        except OSError:
            pass
        await asyncio.to_thread(_rmtree_quiet, snap)
        return {"ok": False, "error": f"备份校验失败：{report['quick_check']}",
                "path": None}
    await asyncio.to_thread(os.replace, part, dest)

    fs_stats = {"linked": 0, "copied": 0, "files": 0}
    if with_files:
        from . import filestore
        if filestore.enabled():
            fs_stats = await asyncio.to_thread(
                _snapshot_files, str(filestore.root()),
                os.path.join(snap, "files"), prev
            )
            # 空目录也要建出来：「一个文件都没有」和「原文没被备份」
            # 是两回事 —— 前者是完整备份，后者是空壳。
            # 少这个目录，快照会被判定成不完整，界面上的提示就会误导人。
            os.makedirs(os.path.join(snap, "files"), exist_ok=True)

    stats = await asyncio.to_thread(_snapshot_stats, snap)
    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": settings.app_version,
        "file_store": settings.file_store,
        "quick_check": report["quick_check"],
        "counts": report["counts"],
        "db_bytes": stats["db_bytes"],
        "files_count": stats["files_count"],
        "files_bytes": stats["files_bytes"],
        "files_linked": fs_stats["linked"],
        "files_copied": fs_stats["copied"],
    }
    try:
        import json as _json
        await asyncio.to_thread(
            lambda: open(os.path.join(snap, "meta.json"), "w", encoding="utf-8")
            .write(_json.dumps(meta, ensure_ascii=False, indent=2))
        )
    except Exception as e:
        log.warning("备份元信息写入失败（不影响备份可用性）：%s", e)

    removed = await asyncio.to_thread(_rotate, target_dir, keep or backup_keep())

    return {"ok": True, "path": snap, "name": os.path.basename(snap),
            "bytes": stats["bytes"], "db_bytes": stats["db_bytes"],
            "files_count": stats["files_count"], "files_bytes": stats["files_bytes"],
            "files_linked": fs_stats["linked"], "files_copied": fs_stats["copied"],
            "quick_check": report["quick_check"], "counts": report["counts"],
            "removed": removed}


def _rmtree_quiet(path: str) -> None:
    import shutil as _sh
    _sh.rmtree(path, ignore_errors=True)


def _rotate(target_dir: str, keep: int) -> list[str]:
    """只保留最近 keep 份快照。

    删除整份快照（而不是单文件）是硬链接方案的关键：被别的快照链接的
    文件不会被真正回收，所以删掉旧快照是安全的、空间是按增量释放的。
    """
    if keep <= 0:
        return []
    snaps = sorted(
        (n for n in os.listdir(target_dir)
         if n.startswith(SNAP_PREFIX) and os.path.isdir(os.path.join(target_dir, n))),
        reverse=True,
    )
    removed = []
    for name in snaps[keep:]:
        p = os.path.join(target_dir, name)
        _rmtree_quiet(p)
        removed.append(name)
    return removed


# ============================================================ 备份的导出 / 导入
#
# 为什么要有这两个动作：备份目录在容器里，宿主机上的运维、离线归档、
# 「把备份搬到另一台机器上再还原」全都缺一个**能拿走的单文件**。
#   导出 = 把一份备份打成 .tar.gz 交给浏览器下载；
#   导入 = 把这样一份 .tar.gz 收进备份目录、登记成新的快照，
#          之后就能用现有的「还原」流程把它应用回去。
#
# 两条安全边界必须守住：
#   1. 名字来自 URL，必须严查（../、绝对路径、符号链接逃逸）——
#      否则就成了「让服务器吐出任意文件」的漏洞；
#   2. 导入的归档是**用户上传的任意文件**，解压时要防路径穿越与解压炸弹。

EXPORT_SUFFIX = ".tar.gz"
# 上传包本体的上限（相对 upload_max_mb 推导）：导入的是压缩后的包，
# 至少要保证「nginx 放得进来、后端也写得下去」
IMPORT_UPLOAD_FACTOR = 4
# 解压后**绝对**上限：一份备份本来就比上传上限大（库文件 + 全部原文），
# 所以给一个宽裕的倍数；真正的防线是下面的膨胀比与磁盘余量
IMPORT_EXPAND_FACTOR = 8
# 解压膨胀比上限：备份数据本身高度重复（sqlite 页结构、文档头），
# 正常 tar.gz 的膨胀比在 5~20 之间；给到 200 已经很宽松，
# 超过基本可以判定是解压炸弹
IMPORT_MAX_RATIO = 200
# 展开体积的兜底下限：2MB 的包撑出 1GB 也是炸弹
IMPORT_MIN_EXPANDED = 256 * MB
# 归档内最多允许多少个成员：几万个文件很正常，几百万个就是攻击
IMPORT_MAX_MEMBERS = 200_000


class BackupError(Exception):
    """备份导出/导入里的「可解释错误」

    单独一个异常类型而不是复用 HTTPException：这一层是服务，
    不该知道 HTTP 的存在；路由层负责把它翻译成 400 + 中文提示。
    """


# ------------------------------------------------------------ 名字与条目定位

def _safe_backup_name(name: str) -> bool:
    """备份名的白名单校验

    名字会被直接拼进文件路径，所以只放行「字母数字 + . _ -」，
    并显式否掉 .. 与绝对路径 —— 少判一个字符都可能变成目录穿越。
    """
    if not name or len(name) > 200:
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    if name.startswith(".") or ".." in name:
        return False
    return all(c.isalnum() or c in "._-" for c in name)


async def _resolve_backup_entry(name: str) -> dict | None:
    """在备份列表里定位一份备份（导出与还原共用同一套判据）

    刻意**只认 list_backups() 里出现过的东西**：这样「名字合法」与
    「它确实是备份」是同一条判据，不会出现备份目录里恰好有个同名
    的其它文件被当成备份导出去。
    """
    if not _safe_backup_name(name):
        return None
    for item in await list_backups():
        if item["name"] == name:
            return item
    return None


def _read_snapshot_meta(root: str) -> dict:
    """读快照的 meta.json

    读不到或读坏了就当没有：元信息缺失不该让一份可用的备份「消失」，
    但完整性判断要因此更保守（见 _snapshot_complete）。
    """
    import json
    try:
        with open(os.path.join(root, "meta.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _snapshot_complete(root: str, meta: dict) -> bool:
    """快照是否「完整」

    原文外置之后，一份缺 files/ 目录的快照只是空壳：库里记着附件、
    盘上却没有内容，还原后附件全部打不开。这种备份必须显式标成不完整，
    否则运维会以为「有备份」，出事时才发现文件全没了。
    """
    if meta.get("complete") is False:
        return False          # 导入时就没有 files/ 目录（显式标记）
    if os.path.isdir(os.path.join(root, "files")):
        return True
    # 原文本来就在库里（file_store=db）时，快照不需要 files/ 目录
    mode = str(meta.get("file_store") or settings.file_store or "fs").lower()
    return mode != "fs"


def _snapshot_entry(bdir: str, name: str) -> dict:
    """备份列表里的一条快照（列表、导入返回共用同一份形状）"""
    p = os.path.join(bdir, name)
    st = os.stat(p)
    stats = _snapshot_stats(p)
    meta = _read_snapshot_meta(p)
    return {
        "name": name, "path": p, "kind": "snapshot",
        "complete": _snapshot_complete(p, meta),
        "bytes": stats["bytes"],
        "db_bytes": stats["db_bytes"],
        "files_count": stats["files_count"],
        "files_bytes": stats["files_bytes"],
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        # 导入来的快照标一下：它可能来自另一台机器，版本与文件存储模式未必一致
        "imported": bool(meta.get("imported")),
        "app_version": meta.get("app_version") or "",
    }


# ------------------------------------------------------------ 导出

def _add_regular(tf, path: str, arcname: str) -> int:
    """往归档里塞一个普通文件（自己构造 TarInfo，不走 tarfile.add）

    为什么不用 tarfile.add()：它会把符号链接原样打进归档
    （解压端那是个坑），也不保证归档里只有普通文件。
    """
    import stat as _stat
    st = os.lstat(path)
    if not _stat.S_ISREG(st.st_mode):
        # 符号链接 / 设备文件 / fifo 一律不进归档
        return 0
    ti = tarfile.TarInfo(name=arcname)
    ti.size = st.st_size
    ti.mtime = int(st.st_mtime)
    ti.mode = 0o644
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    with open(path, "rb") as fh:
        tf.addfile(ti, fh)
    return 1


def _add_dir(tf, arcname: str) -> None:
    """往归档里写一个目录项

    为什么目录项也要写：一份**没有任何附件**的备份，files/ 是个空目录。
    只写文件的话，这个空目录在归档里凭空消失 ——
    导入端拿不到 files/，就会把这份本来完整的备份标成「不完整」，
    界面上还挂一句「还原后附件会打不开」的吓人提示（其实压根没有附件）。
    """
    ti = tarfile.TarInfo(name=arcname)
    ti.type = tarfile.DIRTYPE
    ti.mode = 0o755
    ti.mtime = 0
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    tf.addfile(ti)


def _build_archive(src: str, out_path: str) -> dict:
    """把一个备份条目打成 tar.gz

    归档里的结构固定为「快照目录的内容」：kb.db / files/… / meta.json，
    解开就是一份可直接还原的快照。

    为什么不用 tarfile.add()：见 _add_regular 的说明。
    """
    files = 0
    with open(out_path, "wb") as fp:
        # mtime=0：同样的备份导两次应当得到同样的字节，方便比对。
        # compresslevel=6：备份包里大多是**已经压过**的内容（PDF / zip /
        # SQLite 页结构），压缩级 9 比 6 多花好几倍 CPU 却几乎不省空间；
        # 而导出是要等在 HTTP 请求里的，每省一分钟都是实打实的等待。
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fp, mtime=0,
                           compresslevel=6)
        try:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tf:
                if os.path.isdir(src):
                    for dirpath, dirnames, filenames in os.walk(src):
                        dirnames.sort()
                        filenames.sort()
                        rel_dir = os.path.relpath(dirpath, src).replace(os.sep, "/")
                        if rel_dir != ".":
                            # 目录项：空目录靠它才能在导入端原样还原
                            _add_dir(tf, rel_dir)
                        for fn in filenames:
                            full = os.path.join(dirpath, fn)
                            rel = os.path.relpath(full, src).replace(os.sep, "/")
                            files += _add_regular(tf, full, rel)
                else:
                    # 旧格式（v0.2 的 kb-<时间>.db）：归档里就一个文件
                    files += _add_regular(tf, src, os.path.basename(src))
        finally:
            gz.close()
    return {"files": files, "bytes": os.path.getsize(out_path)}


async def export_backup(name: str) -> dict:
    """把一份备份打成 .tar.gz，交给调用方下载

    归档先写到临时目录而不是在内存里拼 tar：几 GB 的文件目录
    在内存里打包会直接把后端进程撑爆。

    注意：打包时间算在这个 HTTP 请求里，而网关（nginx）的
    proxy_read_timeout 默认 300s —— 超大备份（几十 GB）打包会超时，
    这种规模得先把网关超时调大。
    """
    item = await _resolve_backup_entry(name)
    if item is None:
        # 名字非法与「备份不存在」要说清楚：前者是有人想试探路径穿越，
        # 后者是正常的「备份已经被轮转掉了」
        if not _safe_backup_name(name):
            return {"ok": False, "error": f"非法的备份名：{name!r}"}
        return {"ok": False, "error": f"备份目录里没有这个备份：{name}"}
    if item["kind"] not in ("snapshot", "legacy"):
        return {"ok": False, "error": f"不支持导出的备份类型：{item['kind']}"}

    bdir = await backup_dir()
    src = os.path.join(bdir, name)
    # 快照必须真的有库文件：缺了 kb.db 的快照（半成品）导出去也用不了，
    # 不如在这里说清楚，别让人拿到一个空包
    if item["kind"] == "snapshot" and not os.path.isfile(os.path.join(src, "kb.db")):
        return {"ok": False, "error": f"这份快照不完整（缺 kb.db），无法导出：{name}"}
    # 双保险：解析后的真实路径必须仍在备份目录里（挡符号链接逃逸）
    real_bdir = os.path.realpath(bdir)
    real_src = os.path.realpath(src)
    try:
        inside = os.path.commonpath([real_bdir, real_src]) == real_bdir
    except ValueError:
        inside = False
    if not inside:
        return {"ok": False, "error": f"备份路径越界，已拒绝导出：{name}"}

    tmpdir = tempfile.mkdtemp(prefix="kb-export-")
    out_path = os.path.join(tmpdir, f"kb-backup-{name}{EXPORT_SUFFIX}")
    try:
        info = await asyncio.to_thread(_build_archive, src, out_path)
    except Exception as e:
        _rmtree_quiet(tmpdir)
        return {"ok": False, "error": f"导出失败：{type(e).__name__}: {e}"}

    return {"ok": True, "name": name, "kind": item["kind"],
            "path": out_path, "tmp_dir": tmpdir,
            "filename": f"kb-backup-{name}{EXPORT_SUFFIX}",
            "bytes": info["bytes"], "files": info["files"]}


def cleanup_export(out: dict) -> None:
    """下载结束后清掉临时归档（由 FileResponse 的 BackgroundTask 调用）"""
    try:
        path = out.get("path")
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    tmp = out.get("tmp_dir")
    if tmp:
        _rmtree_quiet(tmp)


# ------------------------------------------------------------ 导入

def import_upload_max_bytes() -> int:
    """上传包本体的上限（相对 upload_max_mb 推导）"""
    return max(int(settings.upload_max_mb or 0), 1) * MB * IMPORT_UPLOAD_FACTOR


def _import_limits(compressed_bytes: int) -> dict:
    """导入的体积上限

    三道闸，缺一不可：
      1. 绝对上限：upload_max_mb 的若干倍 —— 一份备份本来就比上传上限大
         （库文件 + 全部原文），所以给一个宽裕的倍数；
      2. 膨胀比上限：解压炸弹的典型特征就是「很小的包撑出巨大的内容」；
      3. 磁盘余量：再离谱的上限也不能超过盘上还装得下的量。
    """
    absolute = max(int(settings.upload_max_mb or 0), 1) * MB * IMPORT_EXPAND_FACTOR
    ratio = max(int(compressed_bytes) * IMPORT_MAX_RATIO, IMPORT_MIN_EXPANDED)
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        free = 0
    disk = int(free * 0.8) if free else 0
    limit = min(absolute, ratio)
    if disk:
        limit = min(limit, disk)
    return {"expanded": max(limit, 1), "absolute": absolute,
            "ratio": ratio, "disk": disk}


def _safe_member_name(name: str) -> str:
    """归档成员名的安全校验（返回规范化后的相对路径）

    tar 里的成员名是**攻击者完全可控**的字符串。这里逐条否掉：
      - 绝对路径（/etc/passwd）与 Windows 盘符（C:\\...）
      - 任何一段是 ..（目录穿越）
      - 反斜杠（Windows 上会被当成分隔符）
    """
    if not name:
        return ""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        raise BackupError(f"压缩包里含非法路径（绝对路径）：{name}")
    parts = []
    for seg in n.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise BackupError(f"压缩包里含越界路径（..）：{name}")
        parts.append(seg)
    return "/".join(parts)


def _extract_archive(archive_path: str, dest: str, limits: dict) -> dict:
    """把归档解到临时目录（严格模式）

    用流式模式（r|*）逐个成员处理：成员表不一次性读进内存，
    边读边校验边落盘，任何一条不合法立刻中止（临时目录随后被删掉）。
    """
    dest_abs = os.path.abspath(dest)
    total = 0
    members = 0
    files = 0
    try:
        tf = tarfile.open(archive_path, "r|*")
    except Exception as e:
        raise BackupError(f"压缩包无法读取（确认是 tar.gz）：{type(e).__name__}: {e}")

    with tf:
        for m in tf:
            members += 1
            if members > IMPORT_MAX_MEMBERS:
                raise BackupError("压缩包里的条目太多，已拒绝导入")
            rel = _safe_member_name(m.name)
            if m.isdir():
                # 目录项也要落地：空目录（没有附件的备份）靠它才能
                # 在导入端还原出 files/ 这个结构
                target = os.path.join(dest, rel.replace("/", os.sep)) if rel else dest
                if os.path.commonpath([dest_abs, os.path.abspath(target)]) != dest_abs:
                    raise BackupError(f"压缩包里含越界路径：{m.name}")
                os.makedirs(target, exist_ok=True)
                continue
            if not m.isfile():
                # 符号链接 / 硬链接 / 设备文件 / fifo 一律拒绝：
                # 它们在别的系统上能指向完全不同的东西
                raise BackupError(
                    f"压缩包里含非普通文件（{m.name}），已拒绝导入")
            if not rel:
                raise BackupError(f"压缩包里含非法路径：{m.name}")
            target = os.path.join(dest, rel.replace("/", os.sep))
            # 规范化后再比一次：即使前面漏了规则，也不可能写到 dest 之外
            if os.path.commonpath([dest_abs, os.path.abspath(target)]) != dest_abs:
                raise BackupError(f"压缩包里含越界路径：{m.name}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limits["expanded"]:
                        raise BackupError(
                            f"压缩包解压后超过上限"
                            f"（{limits['expanded'] // MB} MB），疑似解压炸弹，"
                            "已拒绝导入")
                    out.write(chunk)
            files += 1
    return {"members": members, "files": files, "bytes": total}


def _pick_files_dir(root: str, base: str) -> str:
    """找文件原文目录：优先库文件旁边那份，其次包根目录那份

    两种摆法都见过：files/ 与 kb.db 同级；或者 files/ 在包根目录、
    而库文件被多包了一层目录。
    """
    for cand in (os.path.join(base, "files"), os.path.join(root, "files")):
        if os.path.isdir(cand):
            return cand
    return ""


def _locate_kb_db(root: str) -> tuple[str, str, str] | None:
    """在解压结果里找库文件，返回 (库文件, 库文件所在目录, files 目录或 "")

    允许两种位置：根目录的 kb.db，或一层子目录里的 kb.db
    （别人手工打的包常常多包一层目录）。

    找不到 kb.db 但整个包里只有一个 .db 文件时，把它当库文件用 ——
    那是 v0.2 时代的备份（kb-<时间>.db）导出来的包，
    直接拒掉等于让「导出旧备份」变成死路。
    """
    direct = os.path.join(root, "kb.db")
    if os.path.isfile(direct):
        return direct, root, _pick_files_dir(root, root)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for name in entries:
        sub = os.path.join(root, name)
        if not os.path.isdir(sub):
            continue
        cand = os.path.join(sub, "kb.db")
        if os.path.isfile(cand):
            return cand, sub, _pick_files_dir(root, sub)
    dbs: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(".db"):
                dbs.append(os.path.join(dirpath, fn))
    if len(dbs) == 1:
        base = os.path.dirname(dbs[0])
        return dbs[0], base, _pick_files_dir(root, base)
    return None


def _meta_has_no_files(meta: dict) -> bool:
    """这份备份本来就没有文件原文吗

    为什么要问：一份**一个附件都没有**的备份，files/ 是空的，
    归档里未必带得上这个空目录（别的工具打的包常常不带目录项）。
    缺 files/ 目录 ≠ 缺东西 —— 库里本来就没记着任何附件。
    判错了的后果是吓人：界面会给一份完好的备份挂上
    「不完整，还原后附件会打不开」的警告。

    没有 meta.json 时不猜（返回 False）—— 宁可保守，也不能把
    「真的缺原文」的包说成完整。
    """
    try:
        n = int(meta.get("files_count"))
    except (TypeError, ValueError):
        return False
    return n == 0


def _install_imported(kb_db: str, files_src: str, bdir: str, report: dict,
                      original_name: str, src_meta: dict | None = None) -> dict:
    """把解压出来的备份装进备份目录，登记成一个新的快照"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{SNAP_PREFIX}{stamp}-imported"
    # 同一秒内导入两份要错开名字，否则第二份会把第一份顶掉
    seq = 1
    dest = os.path.join(bdir, name)
    while os.path.exists(dest):
        name = f"{SNAP_PREFIX}{stamp}-imported-{seq}"
        dest = os.path.join(bdir, name)
        seq += 1
    os.makedirs(dest, exist_ok=True)

    shutil.move(kb_db, os.path.join(dest, "kb.db"))
    complete = True
    if files_src and os.path.isdir(files_src):
        shutil.move(files_src, os.path.join(dest, "files"))
    elif _meta_has_no_files(src_meta or {}):
        # 这份备份本来就没有原文（一个附件都没有）——
        # files/ 只是空着，不是「缺东西」。
        # 补一个空目录，结构与本机做的快照保持一致。
        os.makedirs(os.path.join(dest, "files"), exist_ok=True)
    else:
        # 没有 files/ 目录 = 只有库，没有原文。
        # 接受它（总比把人挡在门外强），但必须标成不完整：
        # 还原之后这些附件会打不开，运维得知道。
        complete = False

    stats = _snapshot_stats(dest)
    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": settings.app_version,
        "file_store": settings.file_store,
        "quick_check": report["quick_check"],
        "counts": report["counts"],
        "db_bytes": stats["db_bytes"],
        "files_count": stats["files_count"],
        "files_bytes": stats["files_bytes"],
        "imported": True,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "imported_from": original_name,
        "complete": complete,
    }
    try:
        import json as _json
        with open(os.path.join(dest, "meta.json"), "w", encoding="utf-8") as fh:
            fh.write(_json.dumps(meta, ensure_ascii=False, indent=2))
    except Exception as e:
        log.warning("导入快照的元信息写入失败（不影响备份可用性）：%s", e)

    return _snapshot_entry(bdir, name)


def _import_sync(archive_path: str, bdir: str, original_name: str) -> dict:
    """导入的主体（同步，跑在线程里）"""
    tmpdir = tempfile.mkdtemp(prefix="kb-import-")
    try:
        ex = os.path.join(tmpdir, "extract")
        os.makedirs(ex)
        limits = _import_limits(os.path.getsize(archive_path))
        info = _extract_archive(archive_path, ex, limits)

        found = _locate_kb_db(ex)
        if not found:
            raise BackupError("压缩包里没有找到 kb.db")
        kb_db, base, files_src = found
        # 原备份的元信息：用来判断「它本来就没有附件」
        # （那种备份的 files/ 是空目录，别的工具打的包常常不带目录项）
        src_meta = _read_snapshot_meta(base) if base else {}
        try:
            report = _verify_snapshot_db(kb_db)
        except Exception as e:
            raise BackupError(
                f"压缩包里的 kb.db 打不开（{type(e).__name__}），已拒绝导入")
        if not report["ok"]:
            raise BackupError(
                f"压缩包里的库文件校验失败（{report['quick_check']}），已拒绝导入")

        entry = _install_imported(kb_db, files_src, bdir, report,
                                  original_name, src_meta)
        return {"ok": True, "entry": entry, "verify": report,
                "complete": entry["complete"], "extracted": info}
    finally:
        # 临时目录一律不留：解压出来的东西只是过路，不该在盘上留一份
        _rmtree_quiet(tmpdir)


async def import_backup(archive_path: str, *, original_name: str = "") -> dict:
    """导入一份本地备份文件，登记成新的快照（**不触碰线上数据**）

    导入只做一件事：把备份放进备份目录、让它出现在备份列表里。
    真正的还原仍然走 restore_snapshot —— 那条路有退路快照、自检与自动回滚，
    不能因为「文件是用户自己导出的」就绕过去。

    名字带 -imported 后缀：一眼能看出这份备份来自别的机器。
    时间戳用的是**导入时刻**而不是原备份的时刻，所以导入的快照在列表里
    排在最新，不会被轮转立刻清掉 —— 但它同样计入保留份数。
    """
    bdir = await backup_dir()
    try:
        os.makedirs(bdir, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"备份目录不可写：{e}"}
    try:
        return await asyncio.to_thread(_import_sync, archive_path, bdir, original_name)
    except BackupError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"导入失败：{type(e).__name__}: {e}"}


# ==================== 在线还原（不停止服务） ====================
#
# 与 scripts/restore.sh 的分工：
#   - restore.sh：服务起不来 / 容器都挂了时的灾难恢复 —— 它停容器、换文件，
#     属于「机房级」操作。
#   - 本函数：服务正常运行时，从页面上点一下就把数据回到某个快照时刻。
#
# 为什么可以不停止服务：
#   1. SQLite 自带的在线备份 API（src.backup(dst)）是官方支持的热替换方式，
#      对 WAL 模式、FTS5 全文表、vec0 向量表全部兼容（已实测：连接池里的
#      老连接无需重建，下一个事务自动看到新内容）。
#   2. 文件原文是内容寻址、只增不改的 —— 先把快照里的文件补进线上目录
#     （能硬链接就硬链接，跨文件系统退化为拷贝），再把「快照里没有」的
#      无主文件清掉，与 restore.sh 的 rsync --delete 语义一致。
#
# 安全顺序（每一步失败都不会损坏线上数据）：
#   校验快照 → 给当前状态留退路快照 → 置全局「还原中」标志（中间件把
#   其他 API 全部挡成 503）→ 同步文件 → 在线换库 → 刷新缓存 → 自检；
#   自检不过就自动用退路快照再换回去。

RESTORE_STATE: dict = {"active": False, "step": "", "started_at": 0.0, "by": ""}


def restore_in_progress() -> bool:
    return bool(RESTORE_STATE["active"])


def _verify_snapshot_db(snap_db: str) -> dict:
    """快照库必须先证明自己可用 —— 拿坏备份覆盖好数据是还原最大的风险"""
    import sqlite3
    c = sqlite3.connect(f"file:{snap_db}?mode=ro", uri=True)
    try:
        check = str(c.execute("pragma quick_check").fetchone()[0] or "")
        counts: dict[str, int | None] = {}
        for t in ("document", "entity_record", "document_chunk"):
            try:
                counts[t] = c.execute(f"select count(*) from {t}").fetchone()[0]
            except sqlite3.Error:
                counts[t] = None
        try:
            counts["fs_documents"] = c.execute(
                "select count(*) from document where storage='fs'").fetchone()[0]
        except sqlite3.Error:
            counts["fs_documents"] = 0
        return {"quick_check": check, "ok": check.lower() == "ok", "counts": counts}
    finally:
        c.close()


def _restore_files(snap_root: str, live_root: str) -> dict:
    """把快照的 files 目录同步到线上（补缺 + 清无主文件）

    无主文件（线上有、快照没有）先不删任何东西——它们都已经在退路快照里
    有副本了，这里的删除才敢做。与 rsync --delete 语义一致。
    """
    import shutil as _sh
    linked = copied = removed = kept = 0

    snap_set: set[str] = set()
    if os.path.isdir(snap_root):
        for dirpath, _dirnames, filenames in os.walk(snap_root):
            for name in filenames:
                if name.startswith(".tmp-"):
                    continue
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, snap_root)
                snap_set.add(rel)
                dst = os.path.join(live_root, rel)
                if os.path.exists(dst) and \
                        os.path.getsize(dst) == os.path.getsize(src):
                    kept += 1
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                done = False
                try:                      # 同盘优先硬链接：瞬时且零空间
                    os.link(src, dst)
                    linked += 1
                    done = True
                except FileExistsError:
                    _sh.copy2(src, dst)   # 已存在但大小不同的，覆盖为快照版本
                    copied += 1
                    done = True
                except OSError:           # 跨文件系统 / 不支持硬链接
                    done = False
                if not done:
                    _sh.copy2(src, dst)
                    copied += 1

    # 清无主文件：目录从深到浅删，最后清掉空目录
    if os.path.isdir(live_root):
        for dirpath, _dirnames, filenames in os.walk(live_root, topdown=False):
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), live_root)
                if rel not in snap_set:
                    try:
                        os.remove(os.path.join(dirpath, name))
                        removed += 1
                    except OSError:
                        pass
        for dirpath, _dirnames, _files in os.walk(live_root, topdown=False):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass

    return {"linked": linked, "copied": copied, "kept": kept,
            "removed": removed, "files": len(snap_set)}


def _swap_db_online(src_db: str) -> None:
    """用 SQLite 在线备份 API 把 src_db 的内容灌进线上库。

    不走「engine.dispose + os.replace」：当前请求的连接池还开着，换文件
    inode 会让那些连接悄悄指向已删除的旧文件；备份 API 是官方支持的热
    替换，老连接下一个事务自动看到新内容。
    """
    import sqlite3
    from ..database import direct_connection

    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    dst = direct_connection(busy_ms=120000)
    try:
        try:                              # 加载 vec0，防止逻辑级拷贝时虚拟表不认识
            import sqlite_vec
            dst.load_extension(sqlite_vec.loadable_path())
        except Exception:
            pass
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _live_counts() -> dict:
    import sqlite3
    from ..database import direct_connection
    c = direct_connection()
    try:
        out = {"document": c.execute("select count(*) from document").fetchone()[0]}
        try:
            out["fs_documents"] = c.execute(
                "select count(*) from document where storage='fs'").fetchone()[0]
        except sqlite3.Error:
            out["fs_documents"] = None
        return out
    finally:
        c.close()


async def restore_snapshot(name: str, *, who: str = "") -> dict:
    """在线把整个系统还原到快照 `name` 的时刻（不停服务）"""
    if RESTORE_STATE["active"]:
        return {"ok": False, "error": "已有还原任务在进行中，请稍候"}

    # ---- 名字校验：只允许备份目录下真实存在的快照目录 ----
    if not name.startswith(SNAP_PREFIX) or "/" in name or "\\" in name or ".." in name:
        return {"ok": False, "error": f"非法的快照名：{name!r}"}
    bdir = await backup_dir()
    snap = os.path.join(bdir, name)
    snap_db = os.path.join(snap, "kb.db")
    snap_files = os.path.join(snap, "files")
    if not os.path.isdir(snap) or not os.path.isfile(snap_db):
        return {"ok": False, "error": f"备份目录里没有这个快照：{name}"}

    t0 = time.time()
    RESTORE_STATE.update(active=True, step="校验快照", started_at=t0, by=who)
    try:
        return await _do_restore(snap, snap_db, snap_files, t0)
    finally:
        RESTORE_STATE.update(active=False, step="")


async def _do_restore(snap: str, snap_db: str, snap_files: str, t0: float) -> dict:
    # ---- 1. 校验快照 ----
    report = await asyncio.to_thread(_verify_snapshot_db, snap_db)
    if not report["ok"]:
        return {"ok": False,
                "error": f"快照库校验失败（{report['quick_check']}），已中止"}
    fs_docs = report["counts"].get("fs_documents") or 0
    if fs_docs > 0 and not os.path.isdir(snap_files):
        return {"ok": False,
                "error": f"快照里有 {fs_docs} 个外置文件的记录，但缺 files 目录，"
                         "恢复它会让这些附件全部打不开。已中止"}

    # ---- 2. 给当前状态留退路（失败就中止：绝不裸还原） ----
    RESTORE_STATE["step"] = "留取退路快照"
    safety = await make_backup()
    if not safety.get("ok"):
        return {"ok": False,
                "error": f"退路快照创建失败，已中止（线上数据未动）："
                         f"{safety.get('error')}"}

    # ---- 3. 同步文件原文（先文件后库：中途挂掉顶多多个无主文件） ----
    fs_stats: dict = {}
    from . import filestore
    if filestore.enabled():
        RESTORE_STATE["step"] = "同步文件原文"
        if os.path.isdir(snap_files):
            fs_stats = await asyncio.to_thread(
                _restore_files, snap_files, str(filestore.root()))

    # ---- 4. 在线换库 ----
    RESTORE_STATE["step"] = "切换数据库"
    await asyncio.to_thread(_swap_db_online, snap_db)

    # ---- 5. 刷新进程内缓存 + 自检 ----
    RESTORE_STATE["step"] = "刷新缓存与自检"
    await settings_store.reload()
    filestore.invalidate_usage()
    vec_fix = await asyncio.to_thread(_ensure_vec_table_after_swap)
    live = await asyncio.to_thread(_live_counts)

    # 自检：线上文档数应与快照一致（软删除的也在 document 表里）
    snap_docs = report["counts"].get("document")
    rollback = None
    if snap_docs is not None and live.get("document") != snap_docs:
        rollback = (f"自检不符：快照 {snap_docs} 条文档，线上 "
                    f"{live.get('document')} 条")
    # 外置文件存在性抽验：库里有记录、盘上必须有文件
    if live.get("fs_documents"):
        miss = await asyncio.to_thread(_check_files_exist, 50)
        if miss:
            rollback = f"有 {len(miss)} 个文件的原文不在盘上：{miss[:3]}"

    if rollback:
        # 自动回滚到退路快照 —— 宁可保持原状，也不留给用户一个半新半旧的库
        log.error("还原自检失败，自动回滚：%s", rollback)
        safety_db = os.path.join(safety["path"], "kb.db")
        safety_files = os.path.join(safety["path"], "files")
        if filestore.enabled() and os.path.isdir(safety_files):
            await asyncio.to_thread(
                _restore_files, safety_files, str(filestore.root()))
        await asyncio.to_thread(_swap_db_online, safety_db)
        await settings_store.reload()
        filestore.invalidate_usage()
        return {"ok": False, "error": f"{rollback}；已自动回滚到还原前状态",
                "safety_snapshot": safety["name"]}

    return {"ok": True, "name": os.path.basename(snap),
            "restored": report["counts"], "files": fs_stats,
            "vec_table": vec_fix,
            "safety_snapshot": safety["name"],
            "elapsed_ms": int((time.time() - t0) * 1000),
            "note": "已还原到快照时刻。若快照早于当前登录会话，需要用备份时刻"
                    "的账号口令重新登录。"}


def _ensure_vec_table_after_swap() -> str:
    """还原后兜底向量表。返回 created / kept / none / failed。

    场景：实例已配置 embedding（sys_meta 有 embed_dim），但快照来自更早、
    还没配置的时期 —— 里面没有 document_vec。直接还原会让语义检索
    报「no such table」。补建空表并把分块的 embedded 清零，让后台
    向量化流程自然重算。两侧都没配置时返回 none，什么都不用做。
    """
    from ..database import direct_connection
    c = direct_connection()
    try:
        has = c.execute("select 1 from sqlite_master "
                        "where type='table' and name='document_vec'").fetchone()
        if has:
            return "kept"
        dim_row = c.execute(
            "select value from sys_meta where key='embed_dim'").fetchone()
        try:
            dim = int(str(dim_row[0])) if dim_row else 0
        except (TypeError, ValueError):
            dim = 0
        if dim <= 0:
            return "none"
        try:
            import sqlite_vec
            c.load_extension(sqlite_vec.loadable_path())
            c.execute(f"create virtual table document_vec "
                      f"using vec0(embedding float[{dim}])")
            c.execute("update document_chunk set embedded = 0")
            log.info("快照缺向量表，已补建（dim=%s）并标记重新向量化", dim)
            return "created"
        except Exception as e:
            log.warning("向量表补建失败（可在存储页手动修复索引）：%s", e)
            return "failed"
    finally:
        c.close()


def _check_files_exist(limit: int) -> list[str]:
    """抽验外置文件：库里有记录的，盘上必须真有（还原后的最后一道防线）"""
    from ..database import direct_connection
    from . import filestore
    c = direct_connection()
    try:
        rows = c.execute(
            "select path from document where storage='fs' and path <> '' "
            "and deleted_at is null order by id limit ?",
            (limit,)).fetchall()
    finally:
        c.close()
    missing = []
    root = filestore.root()
    for (p,) in rows:
        if p and not (root / p).is_file():
            missing.append(p)
    return missing


