#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关联图谱「笔记 ↔ 数据中心记录」关联边的验收脚本

为什么要有这个脚本：
    用户原话「关联图谱没体现出关联关系，例如：笔记-数据中心的管理，
    只显示了数据中心里面某个文件」。
    根因是 get_global_graph 把「对端是笔记」的记录直接跳过 ——
    节点不进来，边也就画不出来，整条关联从图上消失。

这个脚本要证明三件事（不是打印，是断言）：
    1. 业务记录 → 笔记 的「关联知识」关系：
       两个节点都在图里，且这条边在；
    2. 笔记被删除（软删）后：节点和边一起消失；
    3. 读权限不足时：读不到的节点不出现（边也跟着消失）。

跑法（容器里）：
    docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
        --entrypoint python kb-workbench-backend:latest - < scripts/verify-graph-note-links.py
"""
from __future__ import annotations

import asyncio
import datetime
import os
import sys
import tempfile
import uuid

# 环境变量必须在导入 app 之前设好：
# 数据库指到临时目录（这个脚本不碰线上库），
# 鉴权关掉（接口层断言要能直接调通）。
_TMP = tempfile.mkdtemp(prefix="kb-graph-verify-")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(_TMP, "kb.db")
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["FILE_STORE_DIR"] = os.path.join(_TMP, "files")
os.environ["AUTH_ENABLED"] = "false"
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["FILE_STORE_DIR"], exist_ok=True)

sys.path.insert(0, os.environ.get("APP_ROOT", "/app"))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import EntityRecord, EntityType, RelationDef, RelationRecord  # noqa: E402
from app.services import graph as graph_svc  # noqa: E402
from app.services.auth import Principal  # noqa: E402

# 管理员身份：鉴权关闭时接口就是这个口径
SUPER = Principal(None, {"all": True}, auth_disabled=True)

PASSED = 0
FAILED = 0


def check(cond: bool, label: str, extra: str = "") -> bool:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  ✓ %s" % label)
    else:
        FAILED += 1
        print("  ✗ %s%s" % (label, (" | " + extra) if extra else ""))
    return bool(cond)


def node_ids(graph: dict) -> set:
    return {n.get("id") for n in (graph.get("nodes") or [])}


def edge_pairs(graph: dict) -> set:
    out = set()
    for e in graph.get("edges") or []:
        out.add((e.get("source"), e.get("target")))
        out.add((e.get("target"), e.get("source")))
    return out


def find_edge(graph: dict, src: str, tgt: str, relation: str) -> bool:
    for e in graph.get("edges") or []:
        if {e.get("source"), e.get("target")} != {src, tgt}:
            continue
        if (e.get("relation") or "") == relation:
            return True
    return False


async def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    # 建表 + 种子（容器里跑的时候数据库是空的）
    await init_db()
    async with SessionLocal() as db:
        # ---------- 造数据 ----------
        note_et = (await db.execute(
            select(EntityType).where(EntityType.key == "note")
        )).scalar_one_or_none()
        if not note_et:
            print("  ! 库里没有笔记模型，先跑一次初始化再验")
            return 2
        biz_et = (await db.execute(
            select(EntityType).where(EntityType.key != "note")
        )).scalars().first()
        if not biz_et:
            # 库里一个业务模型都没有：自己建一个，省得依赖种子数据
            biz_et = EntityType(key="verify_biz_%s" % suffix, name="验收记录",
                                icon="🧪")
            db.add(biz_et)
            await db.commit()
            await db.refresh(biz_et)

        note = EntityRecord(
            entity_type_id=note_et.id,
            data={"title": "验收用笔记-%s" % suffix, "tags": ["验收"]},
            search_text="验收用笔记-%s" % suffix,
        )
        biz = EntityRecord(
            entity_type_id=biz_et.id,
            data={"title": "验收用记录-%s" % suffix},
            search_text="验收用记录-%s" % suffix,
        )
        db.add_all([note, biz])
        await db.commit()
        await db.refresh(note)
        await db.refresh(biz)

        # 关系定义复用「关联知识」那一类（名字要对得上用户看到的那条边）
        rd = (await db.execute(
            select(RelationDef).where(RelationDef.name == "关联知识")
        )).scalars().first()
        if rd is None:
            rd = RelationDef(key="kb_link_verify_%s" % suffix, name="关联知识")
            db.add(rd)
            await db.commit()
            await db.refresh(rd)

        rel = RelationRecord(
            relation_def_id=rd.id,
            source_record_id=biz.id,
            target_record_id=note.id,
        )
        db.add(rel)
        await db.commit()
        await db.refresh(rel)

        src_id = graph_svc.rid_node_id(biz.id)
        tgt_id = graph_svc.rid_node_id(note.id)
        print("== 1. 关联图谱（全局）里，业务记录与笔记之间那条边要在 ==")
        g = await graph_svc.get_global_graph(db, limit=300, principal=None)
        check(src_id in node_ids(g), "业务记录节点在图里：%s" % src_id)
        check(tgt_id in node_ids(g), "笔记节点也在图里：%s" % tgt_id)
        check(find_edge(g, src_id, tgt_id, "关联知识"),
              "「关联知识」这条边在图里",
              "现有边：%s" % sorted(edge_pairs(g))[:6])
        note_node = next((n for n in g.get("nodes") or [] if n.get("id") == tgt_id), None)
        check((note_node or {}).get("type_name") == "笔记",
              "笔记节点标着 type_name=笔记",
              "实际：%s" % (note_node or {}).get("type_name"))
        check((note_node or {}).get("kind") == "record",
              "笔记节点还是记录节点（前端点它能跳到笔记详情）")

        print("== 2. 知识图谱里，笔记连到业务记录的边也要在 ==")
        gn = await graph_svc.get_notes_graph(db, limit=300, principal=SUPER)
        check(find_edge(gn, src_id, tgt_id, "关联知识"),
              "「关联知识」这条边在知识图谱里")
        check(src_id in node_ids(gn), "对端业务记录节点也补进来了：%s" % src_id)

        print("== 2b. 接口层（GET /api/graph/global）也要能看到这条边 ==")
        try:
            from starlette.testclient import TestClient

            from app.main import app
            with TestClient(app) as client:
                resp = client.get("/api/graph/global?limit=300")
                check(resp.status_code == 200,
                      "GET /api/graph/global 200（实际 %d）" % resp.status_code)
                api_graph = resp.json()
                check(src_id in node_ids(api_graph),
                      "接口返回里有业务记录节点：%s" % src_id)
                check(tgt_id in node_ids(api_graph),
                      "接口返回里有笔记节点：%s" % tgt_id)
                check(find_edge(api_graph, src_id, tgt_id, "关联知识"),
                      "接口返回里有「关联知识」这条边")
        except Exception as e:
            check(False, "接口层验证跑不起来", "%s: %s" % (type(e).__name__, e))

        print("== 2c. 养料 DNA 图谱合并后也要有这条边 ==")
        try:
            from app.services import dna as dna_svc

            dna_graph = await dna_svc.build_graph(db, SUPER)
            dna_nodes = {n.get("id") for n in (dna_graph.get("nodes") or [])}
            dna_edges = dna_graph.get("edges") or []
            # DNA 图谱用的是自己的 id 口径（rec-12 / doc-3）
            check(dna_svc._record_node_id(note.id) in dna_nodes,
                  "DNA 图谱里有笔记节点：%s" % dna_svc._record_node_id(note.id))
            check(any(
                {e.get("source"), e.get("target")} ==
                {dna_svc._record_node_id(biz.id), dna_svc._record_node_id(note.id)}
                and (e.get("label") or e.get("relation")) == "关联知识"
                for e in dna_edges
            ), "DNA 图谱里有「关联知识」这条边")
        except Exception as e:
            check(False, "DNA 图谱验证跑不起来", "%s: %s" % (type(e).__name__, e))

        print("== 3. 笔记被删除后，节点和边一起消失 ==")
        note.deleted_at = datetime.datetime.now()
        await db.commit()
        g2 = await graph_svc.get_global_graph(db, limit=300, principal=None)
        check(tgt_id not in node_ids(g2), "删掉的笔记节点不在图里了")
        check(not find_edge(g2, src_id, tgt_id, "关联知识"), "指向删掉笔记的边也没了")
        gn2 = await graph_svc.get_notes_graph(db, limit=300, principal=SUPER)
        check(tgt_id not in node_ids(gn2), "知识图谱里删掉的笔记也没了")

        # 还原（后面还要用它测权限）
        note.deleted_at = None
        await db.commit()

        print("== 4. 读权限不足时，读不到的节点不出现 ==")
        # 只能读笔记，读不到业务模型
        only_note = Principal(None, {"models": {"note": "read"}}, auth_disabled=False)
        g3 = await graph_svc.get_global_graph(db, limit=300, principal=only_note)
        check(tgt_id in node_ids(g3), "读得到笔记模型时，笔记节点在")
        check(src_id not in node_ids(g3), "读不到业务模型时，业务记录节点不在")
        check(not find_edge(g3, src_id, tgt_id, "关联知识"),
              "指向读不到节点的边也没了")
        gn3 = await graph_svc.get_notes_graph(db, limit=300, principal=only_note)
        check(src_id not in node_ids(gn3), "知识图谱里也拿不到读不到的业务记录")
        check(not find_edge(gn3, src_id, tgt_id, "关联知识"),
              "知识图谱里指向它的边也没了")

        print("== 5. 清理 ==")
        await db.delete(rel)
        await db.delete(biz)
        await db.delete(note)
        await db.commit()
        print("  ✓ 验收数据已清理")

    print()
    print("共 %d 项检查，失败 %d 项" % (PASSED + FAILED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

