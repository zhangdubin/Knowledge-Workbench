#!/usr/bin/env python3
"""把全库吸收成 DNA 基因（养料库）

什么时候需要跑：
- 刚部署 0.10.0：养料库是空的，先把已有资料吸成基因
- 新导入了一批资料之后：把新资料也吸进去（重复跑不会重复建基因）
- 想离线用（断网直答）之前：基因库是离线直答的底座，空着就只剩全文检索

用法（在 backend 目录下）：
    python scripts/absorb_library.py                 # 吸收全部文档与记录
    python scripts/absorb_library.py --stats         # 只看现状，不写库
    python scripts/absorb_library.py --code app/services/docindex.py \
        --destroy                                  # 吸收一个源码文件（蒸馏后销毁原文）

容器里跑（宿主机上要先把 backend 停掉，避免两个进程同时写同一个库）：
    docker compose stop backend
    docker compose run --rm --no-deps backend python scripts/absorb_library.py
    docker compose up -d backend
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db  # noqa: E402
from app.services import dna_library as lib  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="DNA 养料库吸收")
    ap.add_argument("--stats", action="store_true", help="只看现状，不写库")
    ap.add_argument("--code", help="吸收一个源码文件（蒸馏成基因）")
    ap.add_argument("--destroy", action="store_true",
                    help="蒸馏后销毁源码原文（只留销毁证明）")
    ap.add_argument("--no-destroy", action="store_true",
                    help="保留原文（只蒸馏，不销毁）")
    args = ap.parse_args()

    await init_db()
    async with SessionLocal() as db:
        if args.code:
            path = Path(args.code)
            if not path.exists():
                print(f"文件不存在：{path}", file=sys.stderr)
                return 2
            text = path.read_text(encoding="utf-8", errors="replace")
            destroy = not args.no_destroy
            gene, is_new = await lib.absorb_code(
                db, text, path.name, destroy=destroy)
            await db.commit()
            print(json.dumps({
                "file": path.name, "genes": 1, "created": is_new,
                "kind": gene.kind, "title": gene.title,
                "destroyed": destroy,
                "attestation": (gene.meta or {}).get("destroyed"),
            }, ensure_ascii=False, indent=2))
            return 0

        if args.stats:
            health = await lib.gene_health(db)
            print(json.dumps(health, ensure_ascii=False, indent=2))
            return 0

        result = await lib.absorb_all(db)
        await db.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        health = await lib.gene_health(db)
        print(json.dumps({
            "total": health.get("total"),
            "by_kind": health.get("by_kind"),
            "no_source": health.get("no_source"),
            "cold": health.get("cold"),
            "destroyed_sources": health.get("destroyed_sources"),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
