#!/usr/bin/env python3
"""检索链路的功能自检（不依赖网络也能跑完）

验的是「改了之后功能还对不对」，不是「快不快」（快不快是 bench-retrieval.py 的事）。

覆盖：
  1. 记录级倒排索引（record_fts）的**触发器同步**：
     增 / 改 / 删之后，索引必须跟着变 —— 索引不同步是最阴险的 bug：
     搜索结果看着正常，只是少了新建的那条。
  2. 倒排索引与「全表 LIKE 扫描」的结果集必须**完全一致**：
     索引只用来缩小候选，不该改变答案。
  3. 检索超时降级：语义通道超时后必须返回关键词结果 + 明确的降级说明，
     而不是把请求挂死。
  4. 查询向量缓存：同一句话问两次，第二次不再打远端。

跑法（容器内）：
    docker run --rm -v "$PWD/backend/app:/app/app:ro" \
      -v "$PWD/scripts:/scripts:ro" --entrypoint python \
      kb-workbench-backend:latest /scripts/verify-retrieval-perf.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.environ.get("KB_BACKEND_DIR") or os.path.join(REPO, "backend")
if not os.path.isdir(os.path.join(BACKEND, "app")) and os.path.isdir("/app/app"):
    BACKEND = "/app"
sys.path.insert(0, BACKEND)

FAILED = []


def check(name, cond, detail=""):
    ok = bool(cond)
    if not ok:
        FAILED.append(name)
    print(("✅ " if ok else "❌ ") + name + ("  " + str(detail) if detail else ""))


async def main() -> int:
    workdir = tempfile.mkdtemp(prefix="kb-verify-")
    db_path = os.path.join(workdir, "verify.db")
    os.environ["DATA_DIR"] = workdir
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["FILE_STORE_DIR"] = os.path.join(workdir, "files")
    os.environ["FILE_STORE"] = "fs"
    os.environ["MAINTENANCE_ENABLED"] = "false"
    os.environ["AUTH_ENABLED"] = "false"

    from app.database import SessionLocal, engine, init_db
    from app.models import EntityRecord, EntityType
    from app.services import docindex
    from app.services import record as rec_svc
    from app.services.auth import Principal

    await init_db()

    # 超级权限：自检要能读到所有结果，不受模型权限裁剪影响
    principal = Principal(None, {"all": True, "pages": ["library"]}, auth_disabled=True)

    async with SessionLocal() as s:
        # 一个模型 + 一条记录
        et = EntityType(key="verify_note", name="自检笔记", icon="Notebook")
        s.add(et)
        await s.flush()
        rec = EntityRecord(
            entity_type_id=et.id,
            data={"name": "投标截止时间"},
            search_text="投标截止时间 2026年 采购 知识库",
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)
        rid = rec.id

        # 1) 倒排索引建好了吗
        ready = await docindex.record_fts_ready(s)
        check("记录级倒排索引已建立", ready)

        # 2) 新增后能搜到
        rows = await docindex.record_search(s, "投标截止", 50, None)
        check("新增的记录能被倒排索引搜到",
              rows is not None and any(r["record_id"] == rid for r in rows),
              f"命中 {len(rows) if rows else 0} 条")

        # 3) 结果集与 LIKE 扫描一致
        like_rows = await rec_svc.search_all(s, "投标截止", 50, principal=principal)
        ids_fts = {r["record_id"] for r in (rows or [])}
        ids_like = {r["record_id"] for r in like_rows}
        check("倒排索引与全表扫描的结果集一致", ids_fts == ids_like,
              f"索引 {sorted(ids_fts)} / 扫描 {sorted(ids_like)}")

        # 4) 改内容后索引要跟着变（触发器同步）
        rec.search_text = "换个说法 完全不同的内容"
        await s.commit()
        rows2 = await docindex.record_search(s, "投标截止", 50, None)
        check("改内容后旧词搜不到（触发器同步）",
              rows2 is not None and not any(r["record_id"] == rid for r in rows2))
        rows3 = await docindex.record_search(s, "完全不同的内容", 50, None)
        check("改内容后新词搜得到（触发器同步）",
              rows3 is not None and any(r["record_id"] == rid for r in rows3))

        # 5) 删掉后搜不到
        await s.delete(rec)
        await s.commit()
        rows4 = await docindex.record_search(s, "完全不同的内容", 50, None)
        check("删除后搜不到（触发器同步）",
              rows4 is not None and not any(r["record_id"] == rid for r in rows4))

    # 6) 检索超时降级：把语义通道换成「睡 2 秒」，上界设 0.2 秒
    from app.config import settings
    from app.services import document as doc_svc
    from app.services import embedding as embed_svc

    real_embed = embed_svc.embed_query

    async def slow_embed(q):
        await asyncio.sleep(2.0)
        return await real_embed(q)

    embed_svc.embed_query = slow_embed
    old_timeout = settings.search_timeout
    settings.search_timeout = 0.2
    try:
        async with SessionLocal() as s:
            t0 = time.perf_counter()
            res = await doc_svc.search_documents(s, "知识库采购", limit=5, mode="hybrid")
            dt = (time.perf_counter() - t0) * 1000
        check("语义通道超时后返回了结果（没有挂死）", "items" in res)
        check("语义通道超时后标记为降级", res.get("degraded") is True,
              res.get("degraded_reason"))
        check("超时后有可读的降级说明",
              bool(res.get("degraded_reason")), res.get("degraded_reason"))
        check("超时后在预算内返回", dt < 1500, f"实际 {dt:.0f}ms")
    finally:
        embed_svc.embed_query = real_embed
        settings.search_timeout = old_timeout

    # 7) 查询向量缓存：同一句话问两次，第二次不该再打远端
    #    注意要替换**最底层的 HTTP 调用**而不是 embed_query 本身 ——
    #    缓存就住在 embed_query 里，换掉它等于把缓存也换掉了
    embed_svc._query_cache.clear()
    calls = {"n": 0}
    real_call = embed_svc._call
    real_cfg = embed_svc.get_embed_config

    async def counting_call(batch, c, kind):
        calls["n"] += 1
        return [[0.01] * 8 for _ in batch]

    # 假配置：只要「enabled」，不碰真接口
    embed_svc.get_embed_config = lambda: {
        "enabled": True, "api_key": "self-check",
        "url": "http://127.0.0.1:1/embed", "model": "self-check",
        "style": "v2", "dim": 8,
    }
    embed_svc._call = counting_call
    try:
        await embed_svc.embed_query("缓存自检句")
        await embed_svc.embed_query("缓存自检句")
        check("同一句话第二次命中缓存（不再打远端）", calls["n"] == 1,
              f"实际调用 {calls['n']} 次")
        await embed_svc.embed_query("缓存自检句2")
        check("换一句话会真的去算", calls["n"] == 2, f"实际调用 {calls['n']} 次")
        check("缓存统计能看到命中", embed_svc.cache_stats()["hits"] >= 1,
              str(embed_svc.cache_stats()))
    finally:
        embed_svc._call = real_call
        embed_svc.get_embed_config = real_cfg

    await engine.dispose()
    shutil.rmtree(workdir, ignore_errors=True)

    print()
    if FAILED:
        print("❌ 检索链路自检失败：" + "、".join(FAILED))
        return 1
    print("✅ 检索链路自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
