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
import logging
import os
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
                st = os.stat(p)
                stats = _snapshot_stats(p)
                out.append({
                    "name": name, "path": p, "kind": "snapshot",
                    "complete": True,
                    "bytes": stats["bytes"],
                    "db_bytes": stats["db_bytes"],
                    "files_count": stats["files_count"],
                    "files_bytes": stats["files_bytes"],
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(st.st_mtime)),
                })
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


