#!/usr/bin/env python3
"""重建全库索引：重新抽取正文 → 重建全文索引 → 重新分块 → 重新向量化

什么时候需要跑：
- 升级了后端，而分块 / 文本归一化 / 向量维度逻辑变了
- 换过 embedding 模型（维度变了，旧向量没法复用）
- 怀疑索引跟正文对不上（比如明明入库了却搜不到）

用法（在 backend 目录下）：
    python scripts/reindex_all.py            # 重建并重新向量化
    python scripts/reindex_all.py --no-embed # 只重建正文与全文索引，向量原样保留
    python scripts/reindex_all.py --id 3     # 只重建某几篇

只重建块级全文索引（chunk_fts）—— 上线新分词方案时用这个：
    python scripts/reindex_all.py --chunk-fts-only

    块级索引是从 document_chunk 派生的，不需要重新抽取正文、
    更不需要调用 embedding（那是要花钱的）—— 全库重建一次几秒钟。
    服务启动时也会自动重建一次（靠 sys_meta 里的 chunk_fts_version 判定），
    这个脚本是给「不想重启服务 / 想在停机窗口里做」的人准备的。

容器里跑（宿主机上要先把 backend 停掉，避免两个进程同时写同一个库）：
    docker compose stop backend
    docker compose run --rm --no-deps backend python scripts/reindex_all.py
    docker compose up -d backend
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 让脚本能从任意目录运行：把 backend 根目录塞进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Document  # noqa: E402
from app.services import docindex  # noqa: E402
from app.services import document as doc_svc  # noqa: E402
from app.services import filestore  # noqa: E402


async def rebuild_chunk_index(db) -> int:
    """按当前分词方案重建块级索引，并写版本记号

    记号（sys_meta.chunk_fts_version）是「这张表是不是当前分词写的」
    的唯一判据：服务启动时看到记号对不上就会自己重建一遍。

    重建完当场做两道自检，不过就报错退出 ——
    索引与查询不同构时，这条通道的表现是「搜不到」，
    静默退化比直接失败难查得多。
    """
    # 第一道：索引侧与查询侧的切分必须是同一套（纯函数级）
    docindex.chunk_fts_selfcheck()
    n = await docindex.rebuild_chunk_fts(db)
    await docindex.set_meta(db, docindex.META_CHUNK_FTS_VERSION,
                             docindex.CHUNK_FTS_VERSION)
    await db.commit()
    # 第二道：拿库里真实的块查回来（数据级）
    rt = await docindex.chunk_fts_roundtrip_check(db, limit=5)
    if rt["body_miss"] or rt["head_miss"]:
        raise SystemExit(
            f"块级索引自检未通过：正文查不回 {rt['body_miss']}，"
            f"标题查不回 {rt['head_miss']} —— 索引与查询不同构")
    return n


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true", help="只重建正文与全文索引，不动向量")
    ap.add_argument("--id", type=int, action="append", dest="ids",
                    help="只处理指定文档 id（可重复）")
    ap.add_argument("--chunk-fts-only", action="store_true",
                    help="只重建块级全文索引（chunk_fts），不抽取正文也不向量化")
    args = ap.parse_args()

    os.environ.setdefault("MAINTENANCE_ENABLED", "false")
    await init_db()

    async with SessionLocal() as db:
        if args.chunk_fts_only:
            n = await rebuild_chunk_index(db)
            print(f"块级全文索引已重建：{n} 块（分词方案 {docindex.CHUNK_FTS_VERSION}）")
            return 0

        ok = failed = skipped = 0
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if args.ids:
            stmt = stmt.where(Document.id.in_(args.ids))
        docs = (await db.execute(stmt.order_by(Document.id))).scalars().all()
        print(f"待处理文档 {len(docs)} 篇", flush=True)
        for doc in docs:
            title = (doc.title or doc.filename or "")[:40]
            # 原文不在了就不重建 —— 重建会把已经抽好的正文清成空，
            # 等于把「文件丢了」变成「连搜索都搜不到」，两个故障叠一起更难查。
            if (doc.storage or "db") == "fs" and doc.path:
                if not filestore.exists(doc.path):
                    skipped += 1
                    print(f"  ⏭ [{doc.id}] {title} —— 原文文件缺失，跳过（不覆盖已有正文）",
                          flush=True)
                    continue
            try:
                await doc_svc.reindex_document(db, doc, do_embed=not args.no_embed)
                ok += 1
                print(f"  ✓ [{doc.id}] {title}", flush=True)
            except Exception as e:  # noqa: BLE001
                failed += 1
                await db.rollback()
                print(f"  ✗ [{doc.id}] {title} —— {type(e).__name__}: {e}", flush=True)
        # 收尾再整表重建一次块级索引：
        # 上面逐篇重建时，跳过（原文缺失）和向量失败的那几篇，
        # 块级索引可能还是旧的。整表重建一次，保证这张表跟
        # document_chunk 完全一致 —— 半新半旧的索引比没有索引更难查。
        n = await rebuild_chunk_index(db)
        print(f"块级全文索引已重建：{n} 块（分词方案 {docindex.CHUNK_FTS_VERSION}）")
    print(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
