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
from app.services import document as doc_svc  # noqa: E402
from app.services import filestore  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true", help="只重建正文与全文索引，不动向量")
    ap.add_argument("--id", type=int, action="append", dest="ids",
                    help="只处理指定文档 id（可重复）")
    args = ap.parse_args()

    os.environ.setdefault("MAINTENANCE_ENABLED", "false")
    await init_db()

    ok = failed = skipped = 0
    async with SessionLocal() as db:
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
    print(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
