#!/usr/bin/env python3
"""检索性能基准：把「搜一下到底多快」变成可重复的 p50/p95 数字

用户诉求是「AI 对话、查询、后续软件调用知识经验的效率要提升」。
效率问题的第一步永远是**测量**：凭感觉优化只能换来「好像快了一点」。

这个脚本测两类东西：

  **第一层（纯 SQL，只依赖标准库 sqlite3）**
  存储层本身的耗时：FTS5 全文、块级 FTS5、记录级 LIKE 全表扫、N+1 模式。
  这一层在任何装了 Python 的机器上都能跑，用来回答「数据变多之后查询会不会变慢」。

  **第二层（走应用服务，需要后端依赖）**
  用户真正感受到的路径：document.search_documents 的三种模式、
  知识关联查询、基因检索、Agent 工具调用、DNA 图谱构建、AI 首字延迟。
  这一层要 SQLAlchemy / sqlite-vec / httpx，跑在容器里最省事。

跑法（推荐：容器里跑，依赖齐全，且能访问外网测 embedding/大模型延迟）：

    docker run --rm -v "$PWD/backend/app:/app/app:ro" \
      -v "$PWD/scripts:/scripts:ro" -v "$PWD/data:/app/data:ro" \
      --entrypoint python kb-workbench-backend:latest \
      /scripts/bench-retrieval.py

也可以在本机跑（只跑第一层；应用依赖缺失时自动跳过并说明）：

    python3 scripts/bench-retrieval.py --tier sql

**只读保证**：脚本先把源库复制到临时目录再操作，源库一个字节都不会被写。
复制的是 db + wal + shm 三个文件（只拷 db 会丢掉还在 WAL 里的数据），
之后在副本上做 checkpoint 与快照，测量对象永远是副本。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# 默认查询集：覆盖「短中文词 / 长问句 / 中英混合 / 库里真有的词」
# 四种形态。只用一种形态测出来的数字，换个问法就失真了。
DEFAULT_QUERIES = [
    "知识库采购项目",
    "投标截止时间",
    "git fetch",
    "客户案例",
    "深圳",
    "V-MAX 手册 HTTP 27123 端口",
]

_CJK_RE = re.compile(r"([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])")


# ---------------- 统计 ----------------

def pct(values: list[float], q: float) -> float:
    """百分位（nearest-rank 法）

    为什么不插值：延迟这种分布长尾很重，插值出来的 p95 是个
    「不存在」的数；nearest-rank 报的是**真实发生过的第几个样本**，
    拿来定超时上限最稳。
    """
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = max(1, math.ceil(q / 100.0 * len(s)))
    return s[k - 1]


class Bench:
    """收集每条路径的耗时样本"""

    def __init__(self, iterations: int, warmup: int = 1):
        self.iterations = iterations
        self.warmup = warmup
        self.rows: list[dict[str, Any]] = []

    async def run(self, name: str, fn: Callable[[], Any], *, note: str = "") -> None:
        """跑一条路径

        warmup 是必要的：第一次调用要把 SQL 语句编好、把页读进缓存，
        把这第一次算进 p50 会把「冷路径」和「热路径」混在一起，
        而用户抱怨的从来不是热路径。
        """
        for _ in range(self.warmup):
            try:
                r = fn()
                if asyncio.iscoroutine(r):
                    await r
            except Exception as e:
                self.rows.append({
                    "name": name, "n": 0, "p50": 0.0, "p95": 0.0,
                    "mean": 0.0, "min": 0.0, "max": 0.0,
                    "note": f"跳过：{type(e).__name__}: {e}",
                })
                return
        samples: list[float] = []
        err = ""
        for _ in range(self.iterations):
            t0 = time.perf_counter()
            try:
                r = fn()
                if asyncio.iscoroutine(r):
                    await r
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                break
            samples.append((time.perf_counter() - t0) * 1000.0)
        if err:
            self.rows.append({
                "name": name, "n": len(samples), "p50": 0.0, "p95": 0.0,
                "mean": 0.0, "min": 0.0, "max": 0.0,
                "note": f"中断：{err}",
            })
            return
        self.rows.append({
            "name": name,
            "n": len(samples),
            "p50": pct(samples, 50),
            "p95": pct(samples, 95),
            "mean": statistics.fmean(samples),
            "min": min(samples),
            "max": max(samples),
            "note": note,
        })

    def report(self, title: str) -> None:
        print()
        print(f"== {title} ==")
        print(f"{'场景':<34}{'n':>4}{'p50(ms)':>10}{'p95(ms)':>10}"
              f"{'mean':>9}{'min':>8}{'max':>9}  备注")
        print("-" * 118)
        for r in self.rows:
            note = r.get("note") or ""
            if r["n"] == 0:
                print(f"{r['name']:<34}{0:>4}{'-':>10}{'-':>10}"
                      f"{'-':>9}{'-':>8}{'-':>9}  {note}")
                continue
            print(f"{r['name']:<34}{r['n']:>4}{r['p50']:>10.2f}{r['p95']:>10.2f}"
                  f"{r['mean']:>9.2f}{r['min']:>8.2f}{r['max']:>9.2f}  {note}")




# ---------------- 库快照（只读保证） ----------------

def snapshot_db(src: str, workdir: str) -> str:
    """把源库复制成一份可自由折腾的快照，返回快照路径

    要连 wal / shm 一起拷：只拷 .db 会丢掉还在 WAL 里没 checkpoint 的数据，
    测出来的就不是用户正在用的那个库了。
    """
    import sqlite3

    dst = os.path.join(workdir, "kb-bench.db")
    for ext in ("", "-wal", "-shm"):
        s = src + ext
        if os.path.exists(s):
            shutil.copy2(s, dst + ext)
    # 在副本上做一次 checkpoint，让快照是自洽的一份
    conn = sqlite3.connect(dst)
    try:
        conn.execute("pragma wal_checkpoint(TRUNCATE)")
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
    return dst


def db_stats(path: str) -> dict:
    import sqlite3
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out: dict[str, Any] = {}
    try:
        def one(sql: str) -> int:
            try:
                return int(conn.execute(sql).fetchone()[0] or 0)
            except Exception:
                return 0
        out["documents"] = one("select count(*) from document where deleted_at is null")
        out["chunks"] = one("select count(*) from document_chunk")
        out["records"] = one("select count(*) from entity_record where deleted_at is null")
        out["genes"] = one("select count(*) from dna_gene")
        out["relations"] = one("select count(*) from relation_record")
        out["fts_rows"] = one("select count(*) from document_fts")
        out["chunk_fts_rows"] = one("select count(*) from chunk_fts")
        out["bytes"] = os.path.getsize(path)
    finally:
        conn.close()
    return out


# ---------------- 分词（与后端 docindex 同构，独立实现只为免依赖） ----------------

def seg_cjk(value: str) -> str:
    """CJK 逐字空格隔开 —— 与 docindex.seg_cjk 同构"""
    return _CJK_RE.sub(r" \1 ", value or "")


def fts_query(query: str) -> str:
    """文档级 FTS 的 MATCH 表达式 —— 与 docindex.fts_query 同构"""
    q = " ".join(seg_cjk(query).split())
    if not q:
        return ""
    return '"' + q.replace('"', '""') + '"'


def _bigram_groups(value: str) -> list[list[str]]:
    """块级 bigram 切分 —— 与 docindex._token_groups 同构"""
    groups: list[list[str]] = []
    for m in re.finditer(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+|[A-Za-z0-9]+", value or ""):
        s = m.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+", s):
            n = len(s)
            groups.append([s] if n == 1 else [s[i:i + 2] for i in range(n - 1)])
        else:
            groups.append([s.lower()])
    return groups


def chunk_fts_query(query: str, *, column: str = "") -> str:
    """块级 FTS 的 MATCH 表达式 —— 与 docindex.chunk_fts_query 同构"""
    terms: list[str] = []
    for g in _bigram_groups(query):
        for t in g:
            if t not in terms:
                terms.append(t)
    if not terms:
        return ""
    parts = []
    for t in terms:
        phrase = '"' + t + '"'
        parts.append(f"{{{column}}} : {phrase}" if column else phrase)
    return " OR ".join(parts)


def chunk_fts_phrase_query(query: str, *, column: str = "") -> str:
    """块级短语表达式 —— 与 docindex.chunk_fts_phrase_query 同构"""
    parts = []
    for g in _bigram_groups(query):
        phrase = '"' + " ".join(g) + '"'
        parts.append(f"{{{column}}} : {phrase}" if column else phrase)
    return " OR ".join(parts)


# ---------------- 第一层：纯 SQL 存储层 ----------------

async def bench_sql_layer(snap: str, queries: list[str], iterations: int) -> Bench:
    """用裸 SQL 测存储层：这是「数据量涨上去会怎样」的最直接答案"""
    import sqlite3

    b = Bench(iterations)
    conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    conn.execute("pragma cache_size=-65536")
    conn.execute("pragma mmap_size=268435456")

    def q(sql: str, params: tuple = ()) -> list:
        return conn.execute(sql, params).fetchall()

    q0 = queries[0]

    await b.run("SQL 文档级 FTS5", lambda: q(
        "select rowid, bm25(document_fts) as r from document_fts "
        "where document_fts match ? order by rank limit 60",
        (fts_query(q0),)))

    await b.run("SQL 块级 FTS5（正文）", lambda: q(
        "select rowid, bm25(chunk_fts) as r from chunk_fts "
        "where chunk_fts match ? order by rank limit 60",
        (chunk_fts_query(q0),)))

    await b.run("SQL 块级 FTS5（标题列）", lambda: q(
        "select rowid, bm25(chunk_fts) as r from chunk_fts "
        "where chunk_fts match ? order by rank limit 60",
        (chunk_fts_phrase_query(q0, column="heading"),)))

    await b.run("SQL 记录级 LIKE 全表扫", lambda: q(
        "select id, entity_type_id, search_text from entity_record "
        "where search_text like ? and deleted_at is null "
        "order by updated_at desc limit 50",
        (f"%{q0}%",)))

    # N+1 模式：先取 50 条记录，再逐条查一次 EntityType
    def n_plus_one():
        rows = q("select id, entity_type_id from entity_record "
                 "where deleted_at is null order by updated_at desc limit 50")
        for _rid, tid in rows:
            q("select id, key, name from entity_type where id = ?", (tid,))
        return len(rows)

    await b.run("SQL 记录检索 + N+1 取类型", n_plus_one,
          note="每条记录回表一次 EntityType")

    # 批量 JOIN —— 这是 N+1 修好之后该有的形态
    def batch_join():
        return q(
            "select r.id, r.entity_type_id, t.key, t.name "
            "from entity_record r left join entity_type t on t.id = r.entity_type_id "
            "where r.deleted_at is null order by r.updated_at desc limit 50")

    await b.run("SQL 记录检索 + 批量 JOIN", batch_join,
          note="一次查询拿完类型")

    # 记录级 FTS5（如果装了）—— 加索引前后的直接对照
    try:
        row = conn.execute(
            "select count(*) from sqlite_master where type='table' "
            "and name='record_fts'").fetchone()
        if row and row[0]:
            await b.run("SQL 记录级 FTS5", lambda: q(
                "select rowid, bm25(record_fts) as r from record_fts "
                "where record_fts match ? order by rank limit 50",
                (fts_query(q0),)), note="倒排索引")
        else:
            await b.run("SQL 记录级 FTS5", lambda: q(
                "select 1"), note="未安装 record_fts（优化前）")
    except Exception as e:
        await b.run("SQL 记录级 FTS5", lambda: q("select 1"),
                    note=f"未安装 record_fts：{e}")

    conn.close()
    return b




# ---------------- 第二层：应用服务层 ----------------

def setup_env(snap: str, workdir: str, backend_dir: str) -> None:
    """把运行环境钉到快照上

    必须先设环境变量再 import 应用模块：config 在 import 时就会读数据库 URL，
    顺序反了就会连到线上库去（那会把基准跑成一场事故）。
    """
    os.environ["DATA_DIR"] = workdir
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{snap}"
    os.environ["FILE_STORE_DIR"] = os.path.join(workdir, "files")
    os.environ["FILE_STORE"] = "fs"
    os.environ["MAINTENANCE_ENABLED"] = "false"
    os.environ["AUTH_ENABLED"] = "false"
    # 把源库里的 ai_config.json 复制过来：embedding / 大模型配置在那儿，
    # 没有它就测不到「调远端接口」这一段真实延迟
    src_cfg = os.path.join(REPO, "data", "ai_config.json")
    if os.path.exists(src_cfg):
        shutil.copy2(src_cfg, os.path.join(workdir, "ai_config.json"))
    if backend_dir and os.path.isdir(backend_dir):
        sys.path.insert(0, backend_dir)


async def ensure_indexes() -> None:
    """在快照上补建新索引（record_fts 等）

    为什么要「在快照上建」而不是去动线上库：
    基准只读线上库；要对比「加索引前 / 加索引后」，
    就得让同一份数据在两种索引状态下各测一遍。
    """
    try:
        from app.database import engine  # type: ignore
        from app.services import docindex  # type: ignore
        async with engine.begin() as conn:
            await docindex.ensure_index_tables(conn)
            if hasattr(docindex, "ensure_record_fts"):
                await docindex.ensure_record_fts(conn)
        print("[提示] 已在快照上补建索引（含 record_fts）")
    except Exception as e:
        print(f"[提示] 补建索引失败：{type(e).__name__}: {e}")


async def bench_app_layer(snap: str, workdir: str, queries: list[str],
                          iterations: int, with_network: bool,
                          backend_dir: str, ensure_index: bool) -> Bench:
    """走真实服务代码测用户能感知的路径"""
    b = Bench(iterations)

    setup_env(snap, workdir, backend_dir)

    from sqlalchemy import text  # type: ignore

    from app.database import SessionLocal  # type: ignore
    from app.services import docindex  # type: ignore
    from app.services import document as doc_svc  # type: ignore
    from app.services import knowledge as kb_svc  # type: ignore
    from app.services import dna_library  # type: ignore
    from app.services import record as rec_svc  # type: ignore
    from app.services import agent as agent_svc  # type: ignore
    from app.services import auth as auth_svc  # type: ignore
    from app.services.permissions import admin_perms  # type: ignore

    principal = auth_svc.Principal(None, admin_perms(), auth_disabled=True)
    q0 = queries[0]

    # ai_config.json 的位置是按模块文件算出来的（backend/app/services → backend/data），
    # 容器里是 /app/data。若那边没有，就从仓库的 data/ 补一份过去，
    # 否则 embedding / 大模型那一段会因「未配置」而测成假数据。
    try:
        from app.services import ai_config as ai_cfg_svc  # type: ignore
        if not ai_cfg_svc.CONFIG_PATH.exists():
            fallback = os.path.join(REPO, "data", "ai_config.json")
            if os.path.exists(fallback):
                ai_cfg_svc.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fallback, ai_cfg_svc.CONFIG_PATH)
    except Exception as e:
        print(f"[提示] AI 配置准备失败（网络场景会退化）：{type(e).__name__}: {e}")

    # 按需在**快照**上补建新索引：这样「加索引前 / 加索引后」可以在
    # 同一份数据上直接对照，而不是拿两批不同的库比。
    if ensure_index:
        await ensure_indexes()

    async with SessionLocal() as db:
        # --- 存储层直调 ---
        await b.run("svc 文档级 FTS5",
                    lambda: docindex.fts_search(db, q0, 30))
        await b.run("svc 块级 FTS5 正文",
                    lambda: docindex.chunk_fts_search(db, q0, 30))
        await b.run("svc 块级 FTS5 标题",
                    lambda: docindex.chunk_heading_search(db, q0, 30))

        # --- 用户路径 ---
        await b.run("svc 检索（关键词模式）",
                    lambda: doc_svc.search_documents(db, q0, limit=20, mode="keyword"))
        await b.run("svc 检索（混合模式）",
                    lambda: doc_svc.search_documents(db, q0, limit=20, mode="hybrid"))
        await b.run("svc 检索（带块片段）",
                    lambda: doc_svc.search_documents(db, q0, limit=20,
                                                     mode="hybrid", with_chunks=True))
        await b.run("svc AI 上下文组装",
                    lambda: doc_svc.build_ai_context(db, q0, max_docs=5,
                                                     principal=principal))
        await b.run("svc 记录检索（全局搜索）",
                    lambda: rec_svc.search_all(db, q0, 50, principal=principal))
        # 倒排索引版：记录一多（经验数据正是最会长大的那批）
        # LIKE 全表扫描会越来越慢，这一条走 record_fts
        _fts_ready = False
        try:
            _fts_ready = bool(await docindex.record_fts_ready(db))
        except Exception:
            _fts_ready = False
        await b.run("svc 记录检索（倒排索引）",
                    lambda: docindex.record_search(db, q0, 50, None),
                    note=("record_fts 候选 + LIKE 精确过滤"
                          if _fts_ready else "record_fts 未就绪（加 --ensure-index 重测）"))
        await b.run("svc 基因检索",
                    lambda: dna_library.search_genes(db, q0, limit=12))

        # 知识关联：取一条真实记录来查
        rows = (await db.execute(
            text("select id from entity_record where deleted_at is null limit 1")
        )).scalars().all()
        if rows:
            rid = int(rows[0])
            await b.run("svc 记录→知识关联",
                        lambda: kb_svc.list_notes_for_record(db, rid))
            await b.run("svc 笔记→记录反向关联",
                        lambda: kb_svc.list_records_for_note(db, rid))

        # --- Agent 工具 ---
        await b.run("工具 search_records",
                    lambda: agent_svc.tool_search_records(db, principal, q0, limit=10))
        await b.run("工具 stats_records（计数）",
                    lambda: agent_svc.tool_stats_records(db, principal, "project",
                                                         operation="count"))
        await b.run("工具 search_documents",
                    lambda: agent_svc.tool_search_documents(db, q0, limit=8))

        # --- DNA 图谱 ---
        try:
            from app.services import dna as dna_svc  # type: ignore
            await b.run("DNA 图谱构建", lambda: dna_svc.build_graph(db, principal))
        except Exception as e:
            print(f"[提示] DNA 图谱场景跳过：{type(e).__name__}: {e}")

    # --- 网络段（embedding / 大模型）---
    if with_network:
        from app.services import embedding as embed_svc  # type: ignore
        await b.run("远端 embedding（查询向量）",
                    lambda: embed_svc.embed_query(q0),
                    note="单次 HTTP，含网络往返")
        # 重复同一句：命中缓存后应为 0ms 级
        try:
            await embed_svc.embed_query(q0)
        except Exception:
            pass
        await b.run("远端 embedding（同句重复）",
                    lambda: embed_svc.embed_query(q0),
                    note="第二次起应命中缓存")
        # 冷路径：每次都换一句，绕开缓存，量的是真实的远端往返
        # （「第一次问要等多久」才是用户真正抱怨的那一次）
        _cold = {"n": 0}

        async def _cold_embed():
            _cold["n"] += 1
            return await embed_svc.embed_query(f"{q0} 冷路径{_cold['n']}")

        await b.run("远端 embedding（冷路径）", _cold_embed,
                    note="每次换新句，量真实网络往返")

        from app.services import ai as ai_svc  # type: ignore

        async def chat_once():
            """测 AI 首字延迟与总耗时"""
            it = await ai_svc.chat_real(
                [{"role": "user", "content": "用一句话说明这个知识库里有什么。"}],
                stream=True)
            t0 = time.perf_counter()
            first = None
            n = 0
            async for piece in it:
                if first is None:
                    first = (time.perf_counter() - t0) * 1000.0
                n += len(piece)
            total = (time.perf_counter() - t0) * 1000.0
            return {"first_ms": first or 0.0, "total_ms": total, "chars": n}

        samples = []
        for _ in range(max(3, iterations // 4)):
            try:
                samples.append(await chat_once())
            except Exception as e:
                print(f"[提示] AI 对话场景跳过：{type(e).__name__}: {e}")
                break
        if samples:
            firsts = [s["first_ms"] for s in samples]
            totals = [s["total_ms"] for s in samples]
            b.rows.append({
                "name": "AI 对话（首字/总）",
                "n": len(samples),
                "p50": pct(firsts, 50),
                "p95": pct(firsts, 95),
                "mean": statistics.fmean(totals),
                "min": min(totals),
                "max": max(totals),
                "note": f"p50/p95 为首字延迟；mean/min/max 为总耗时 "
                        f"(p50总={pct(totals, 50):.0f}ms)",
            })
    return b




# ---------------- 主流程 ----------------

def main() -> int:
    ap = argparse.ArgumentParser(description="检索性能基准")
    ap.add_argument("--db", default=os.path.join(REPO, "data", "kb.db"),
                    help="源库路径（只读，脚本会先做快照）")
    ap.add_argument("--iterations", type=int, default=20, help="每条路径的采样次数")
    ap.add_argument("--warmup", type=int, default=1, help="预热次数（不计入统计）")
    ap.add_argument("--queries", default="", help="自定义查询集，逗号分隔")
    ap.add_argument("--tier", choices=["sql", "app", "auto"], default="auto",
                    help="测哪一层：sql（纯标准库）/ app（走服务）/ auto（都测）")
    ap.add_argument("--skip-network", action="store_true",
                    help="不测 embedding / 大模型（离线环境用）")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    ap.add_argument("--backend", default="",
                    help="后端代码目录（含 app/ 包）。默认按脚本所在位置推断")
    ap.add_argument("--ensure-index", action="store_true",
                    help="在快照上补建新索引（record_fts 等）后再测，"
                         "用于「加索引后」的对照")
    args = ap.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()] or DEFAULT_QUERIES
    if not os.path.exists(args.db):
        print(f"找不到库文件：{args.db}", file=sys.stderr)
        return 2

    workdir = tempfile.mkdtemp(prefix="kb-bench-")
    try:
        print(f"源库：{args.db}")
        print(f"快照：{os.path.join(workdir, 'kb-bench.db')}（源库只读，测量全在副本上做）")
        snap = snapshot_db(args.db, workdir)
        stats = db_stats(snap)
        print("数据量：" + "，".join(f"{k}={v}" for k, v in stats.items()))
        print(f"查询集（{len(queries)} 条）：{'、'.join(queries)}")
        print(f"采样：每条路径 {args.iterations} 次，预热 {args.warmup} 次")

        all_rows: list[dict] = []

        run_sql = args.tier in ("sql", "auto")
        run_app = args.tier in ("app", "auto")

        backend_dir = args.backend or os.path.join(REPO, "backend")
        if not os.path.isdir(backend_dir) and os.path.isdir("/app/app"):
            backend_dir = "/app"
        # 应用层要用的环境先钉好（config 在 import 时就读数据库 URL）。
        # 索引补建也在这之后做：这样第一层测的就是「加了索引」的库。
        if run_app or args.ensure_index:
            setup_env(snap, workdir, backend_dir)
            if args.ensure_index:
                asyncio.run(ensure_indexes())

        if run_sql:
            try:
                b = asyncio.run(bench_sql_layer(snap, queries, args.iterations))
                b.report("第一层：存储层（纯 SQL）")
                all_rows.extend(b.rows)
            except Exception as e:
                print(f"[提示] 第一层异常：{type(e).__name__}: {e}")
                if args.tier == "sql":
                    raise

        if run_app:
            try:
                b = asyncio.run(bench_app_layer(
                    snap, workdir, queries, args.iterations,
                    with_network=not args.skip_network,
                    backend_dir=backend_dir,
                    ensure_index=args.ensure_index))
                b.report("第二层：应用服务（用户可感知路径）")
                all_rows.extend(b.rows)
            except ModuleNotFoundError as e:
                print(f"[提示] 第二层跳过：应用依赖缺失（{e}）。"
                      f"在本机跑请用 --tier sql，或用容器跑（见脚本头部说明）。")
            except Exception as e:
                print(f"[提示] 第二层异常：{type(e).__name__}: {e}")

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({"db": args.db, "stats": stats,
                           "queries": queries, "rows": all_rows},
                          f, ensure_ascii=False, indent=2)
            print(f"\n结果已写入 {args.json}")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
