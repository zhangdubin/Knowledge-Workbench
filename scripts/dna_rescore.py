#!/usr/bin/env python3
"""基因评分回填：给存量数据补上新的表达度 / 置信度

背景：表达度与置信度从「两个裸数字」改成了「分数 + 分项 + 依据」。
新吸收的知识会自动带上评分，但**存量**的基因还是旧口径 ——
不��填，这批知识在新界面里就永远是 0 分，看起来像「全都不合格」。

跑法（**在正在运行的后端容器里跑**）：
    docker exec -i kb-backend python - < scripts/dna_rescore.py

为什么必须是 docker exec，而不是另起一个容器去写同一个库：
    后端容器以 WAL 模式打开着 kb.db，而 WAL 的索引（-shm）是按
    「打开它的这一组进程」共享的。另起一个容器挂同一个 data 目录去写，
    两边会拿到**两份 -shm**，各自回放 WAL ——
    轻则 "disk I/o error"，重则 "file is not a database"，
    把线上库搞得读不出来。docker exec 是在**同一个容器进程空间**里跑，
    共享同一份 -shm，才是安全的。

也可以在装了依赖、且确认没有别的进程在写这个库的机器上直接跑：
    python3 scripts/dna_rescore.py

常用参数：
    --dry-run          只看会算成什么样，不写库
    --db <路径>        指定别的 SQLite 文件（默认用配置里的库）
    --all              连版本最新的也重算（默认只算口径落后的）
    --assets           回填完之后，顺手从高分基因里落一批可复用产出
    --min-score 0.6    --assets 时的分数线

安全说明：���个脚本**只写不删** —— 它新增评分行、更新基因上的两个镜像列，
不会动基因正文、不会删任何一条知识。--dry-run 下连镜像列都不写。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile

# ---- 环境先钉死，再 import 应用模块 ----
# 应用模块在 import 时就读 config（数据库 URL、文件目录…），
# 环境变量不先设好就会连到线上库。
_HERE = os.path.dirname(os.path.abspath(__file__))
# 找 backend 的位置：脚本在仓库的 scripts/ 下就找 ../backend；
# 被单独挂到容器里时就找当前目录与当前目录下的 backend。
for _cand in (os.path.join(os.path.dirname(_HERE), "backend"),
              os.path.dirname(_HERE),
              os.getcwd(),
              os.path.join(os.getcwd(), "backend")):
    # 必须是真正的应用包（app/__init__.py 在），
    # 光有个 app 目录会被当成命名空间包，import app.models 直接失败
    if os.path.isfile(os.path.join(_cand, "app", "__init__.py")) \
            and _cand not in sys.path:
        sys.path.insert(0, _cand)
        break

DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(
    tempfile.gettempdir(), "kb-dna-rescore")
os.makedirs(DATA_DIR, exist_ok=True)
os.environ.setdefault("DATA_DIR", DATA_DIR)
os.environ.setdefault("DATABASE_URL",
                      f"sqlite+aiosqlite:///{DATA_DIR}/kb.db")
os.environ.setdefault("FILE_STORE_DIR", os.path.join(DATA_DIR, "files"))
os.environ.setdefault("FILE_STORE", "fs")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("MAINTENANCE_ENABLED", "false")

from app import models  # noqa: E402,F401  让 Base.metadata 认识所有模型
from app.database import Base, SessionLocal, engine  # noqa: E402


async def _ensure_schema() -> None:
    """补齐评分相关的表与列（幂等）

    先用应用自己的模型建表（全新库时 sys_meta 这些表还不存在），
    再走 migrate_v8 —— 与应用启动时用的是同一份逻辑，
    不会出现「脚本建的结构」与「应用建的结构」不一样的情况。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.services.migrate_v8 import migrate_dna_learning_v8
    res = await migrate_dna_learning_v8()
    print(f"结构补齐：补列 {res['columns']} 个，表 {res['tables']} 张"
          f"{'（此前已迁移过）' if res.get('skipped') else ''}")


async def _stats(db) -> dict:
    """回填前的分布（用来对比）"""
    from sqlalchemy import func, select
    from app.models import DnaGene
    rows = (await db.execute(
        select(DnaGene.id, DnaGene.expressiveness, DnaGene.confidence,
               DnaGene.score_version)
        .where(DnaGene.status == "active"))).all()
    total = len(rows)
    expr = [float(r[1] or 0) for r in rows]
    conf = [float(r[2] or 0) for r in rows]
    stale = sum(1 for r in rows if int(r[3] or 0) == 0)
    return {
        "total": total,
        "expressiveness_avg": round(sum(expr) / total, 3) if total else 0.0,
        "confidence_avg": round(sum(conf) / total, 3) if total else 0.0,
        "stale": stale,
        "vague": sum(1 for v in expr if v < 0.4),
        "uncertain": sum(1 for v in conf if v < 0.5),
    }


def _print_stats(label: str, st: dict) -> None:
    print(f"\n[{label}]")
    print(f"  当前基因        : {st['total']}")
    print(f"  表达度均值      : {st['expressiveness_avg']}"
          f"（说得含糊 <0.4 的有 {st['vague']} 条）")
    print(f"  置信度均值      : {st['confidence_avg']}"
          f"（可信度不足 <0.5 的有 {st['uncertain']} 条）")
    print(f"  口径落后待重算  : {st['stale']}")


async def main_async(args) -> int:
    await _ensure_schema()
    from app.services import dna_asset, dna_score
    from sqlalchemy import select
    from app.models import DnaGene

    async with SessionLocal() as db:
        before = await _stats(db)
        _print_stats("回填前", before)

        if args.dry_run:
            print("\n--dry-run：不写库。先算前 5 条看看结果。")
            rows = (await db.execute(
                select(DnaGene).where(DnaGene.status == "active")
                .order_by(DnaGene.id).limit(5))).scalars().all()
            for g in rows:
                ex = dna_score.score_expressiveness(g, usage_count=g.usage_count or 0)
                cf = dna_score.score_confidence(
                    g, meta=g.meta or {},
                    extraction_confidence=float(g.confidence or 0.7))
                print(f"  #{g.id} {g.title[:36]}")
                print(f"     表达度 {ex.score:.3f} / 置信度 {cf.score:.3f}")
                for part in ex.parts:
                    print(f"       · {part.label} {part.score:.2f} — {part.detail}")
                for part in cf.parts:
                    print(f"       · {part.label} {part.score:.2f} — {part.detail}")
            return 0

        res = await dna_score.rescore_all(db, batch=args.batch,
                                          only_stale=not args.all)
        print(f"\n重算完成：{res['scored']} 条（评分口径 v{res['version']}）")
        after = await _stats(db)
        _print_stats("回填后", after)

        if args.assets:
            stmt = (select(DnaGene)
                    .where(DnaGene.status == "active",
                           DnaGene.expressiveness >= args.min_score,
                           DnaGene.confidence >= args.min_score)
                    .order_by(DnaGene.expressiveness.desc())
                    .limit(50))
            genes = (await db.execute(stmt)).scalars().all()
            created = await dna_asset.create_assets_from_genes(
                db, [g.id for g in genes])
            print(f"\n落出可复用产出 {len(created)} 条"
                  f"（来自 {len(genes)} 条高分基因）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="基因评分回填：给存量数据补上新的表达度 / 置信度")
    ap.add_argument("--dry-run", action="store_true",
                    help="只看不写")
    ap.add_argument("--all", action="store_true",
                    help="连口径最新的也重算")
    ap.add_argument("--batch", type=int, default=200,
                    help="每批多少条（默认 200）")
    ap.add_argument("--assets", action="store_true",
                    help="回填后顺手落一批可复用产出")
    ap.add_argument("--min-score", type=float, default=0.6,
                    help="--assets 时的分数线（默认 0.6）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
