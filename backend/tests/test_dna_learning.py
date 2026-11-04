"""「知识学习与总结能力」的回归测试

测的是三件事：

    1. 表达度 / 置信度的新模型：分项齐、权重对、负反馈真的扣分
    2. 学以致用闭环：基因 → 产出 → 被用过 → 分数真的变了 → 事件留痕
    3. 外部开源项目吸收：仓库认得对、许可证认得对、合规提示说得对

跑法（仓库根目录，依赖装在容器里时用这条）：
    docker run --rm -i -v "$PWD/backend:/app" -w /app \
      kb-workbench-backend:latest python -m unittest discover -s tests -v

装了依赖的机器上直接跑：
    python3 -m unittest discover -s backend/tests -v

**全程只碰临时目录**：数据库、文件目录都建在 tempfile 下，
线上的 data/ 与 files/ 一个字节都不会被读到或写到。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

# ---- 环境先钉死，再 import 应用模块 ----
# 应用模块在 import 时就读 config（数据库 URL、文件目录…），
# 环境变量不先设好就会连到线上库。
#
# 这里用统一护栏（tests/_guard.py）而不是自己写一遍：
#   本文件原来自己设了一组环境变量，看起来是安全的 ——
#   但另一个测试文件（test_db_retry.py）用的是 setdefault("KB_DATABASE_URL")，
#   而 KB_ 前缀只有在无前缀的 DATABASE_URL 不存在时才会被提升，
#   容器里 compose 早就设了 DATABASE_URL —— 那个 setdefault 等于没设。
#   两个文件谁先被 import 谁说了算（unittest 按字母序），
#   于是先被 import 的那个用**线上库**跑，tearDown 把线上基因表清空了。
# 护栏统一处理，并额外断言「现在生效的库确实落在临时目录里」。
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _guard  # noqa: E402

_TMP = _guard.use_temp_db()

from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402,F401  让 Base.metadata 认识所有模型
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import DnaAsset, DnaAssetUse, DnaGene, DnaGeneScore  # noqa: E402
from app.services import dna_asset, dna_library, dna_openkb, dna_score  # noqa: E402

# 护栏的第二道：确认 settings 确实固化到了临时库。
# 过了这一关，后面所有 delete 都只可能打在临时库上。
_guard.assert_test_db()


def _mk_gene(**kw) -> DnaGene:
    """造一条基因（只填评分用得到的字段）"""
    base = dict(
        uid=kw.pop("uid", "test-uid"),
        kind=kw.pop("kind", "method"),
        title=kw.pop("title", "配置超时时间的正确做法"),
        content=kw.pop("content", "当请求超过 30 秒时必须重试，最多 3 次。"
                                   "调用 config.set_timeout(30)。"
                                   "注意不要超过 60 秒，否则网关会断开。"),
        summary="",
        tags=kw.pop("tags", ["超时", "重试"]),
        source_kind=kw.pop("source_kind", "code"),
        source_ref=kw.pop("source_ref", "code:abc123"),
        source_title=kw.pop("source_title", "config.py"),
        fingerprint=kw.pop("fingerprint", "fp-test"),
        confidence=kw.pop("confidence", 0.8),
        status="active",
        meta=kw.pop("meta", {}),
    )
    base.update(kw)
    return DnaGene(**base)


class TestScoreModel(unittest.TestCase):
    """评分模型：分项、权重、扣分"""

    def test_weights_sum_to_one(self):
        """两组权重加起来都必须是 1 —— 否则总分不是加权和，解释会骗人"""
        self.assertAlmostEqual(sum(dna_score.EXPRESS_WEIGHTS.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(dna_score.CONF_WEIGHTS.values()), 1.0, places=6)

    def test_expressiveness_parts_present(self):
        """表达度必须四个分项都在，且能给出人话依据"""
        g = _mk_gene()
        res = dna_score.score_expressiveness(g, usage_count=3)
        keys = {p.key for p in res.parts}
        self.assertEqual(keys, set(dna_score.EXPRESS_WEIGHTS.keys()))
        for part in res.parts:
            self.assertTrue(part.detail, f"分项 {part.key} 没有依据")
            self.assertGreaterEqual(part.score, 0.0)
            self.assertLessEqual(part.score, 1.0)

    def test_detailed_beats_vague(self):
        """说得清楚的高分，说得含糊的低分"""
        vague = _mk_gene(title="片段", content="很好用。",
                         tags=[], fingerprint="fp-vague")
        detailed = _mk_gene()
        s_vague = dna_score.score_expressiveness(vague).score
        s_detail = dna_score.score_expressiveness(detailed).score
        self.assertGreater(s_detail, s_vague,
                           f"详细 {s_detail} 应该高于含糊 {s_vague}")

    def test_actionability_detects_four_elements(self):
        """四要素齐的可执行性应该满分"""
        g = _mk_gene(content="当出现 502 时，先查网关日志；如果确认是后端超时，"
                             "就按下面步骤处理：1. 重试 2 次；2. 降级到缓存；"
                             "3. 告警。注意最多重试 3 次。"
                             "处理完会返回 200 与缓存数据。")
        part = [p for p in dna_score.score_expressiveness(g).parts
                if p.key == dna_score.EXPRESS_ACTIONABILITY][0]
        self.assertGreaterEqual(part.score, 0.9)

    def test_confidence_authority_ordering(self):
        """来源权威度：源码实证 > 文档 > 手工粘贴"""
        code = _mk_gene(source_kind="code", source_ref="code:x")
        doc = _mk_gene(source_kind="document", source_ref="doc-1")
        manual = _mk_gene(source_kind="manual", source_ref="manual-1")
        s = []
        for g in (code, doc, manual):
            res = dna_score.score_confidence(g, meta={}, extraction_confidence=0.8)
            part = [p for p in res.parts if p.key == dna_score.CONF_AUTHORITY][0]
            s.append(part.score)
        self.assertGreater(s[0], s[1])
        self.assertGreater(s[1], s[2])

    def test_corrections_penalize(self):
        """人工纠正必须真的把置信度拉下来"""
        g = _mk_gene()
        base = dna_score.score_confidence(g, meta={}).score
        after = dna_score.score_confidence(g, meta={}, corrections=2).score
        self.assertLess(after, base)
        self.assertTrue(dna_score.score_confidence(g, meta={}, corrections=2).penalties)

    def test_usage_success_raises_failure_lowers(self):
        """复用成功抬分、复用失败压分"""
        g = _mk_gene()
        ok = dna_score.score_confidence(g, meta={}, use_success=3, use_fail=0).score
        bad = dna_score.score_confidence(g, meta={}, use_success=0, use_fail=3).score
        neutral = dna_score.score_confidence(g, meta={}).score
        self.assertGreater(ok, neutral)
        self.assertLess(bad, neutral)

    def test_corroboration_raises_confidence(self):
        """多来源印证要抬分"""
        g = _mk_gene()
        one = dna_score.score_confidence(g, meta={}, distinct_sources=1).score
        many = dna_score.score_confidence(g, meta={}, distinct_sources=3).score
        self.assertGreater(many, one)

    def test_freshness_decays_for_technical_sources(self):
        """技术知识会过期，业务事实不会"""
        from datetime import datetime, timedelta
        old = datetime.utcnow() - timedelta(days=400)
        code = _mk_gene(source_kind="code")
        code.updated_at = old
        rec = _mk_gene(source_kind="record")
        rec.updated_at = old
        p_code = [p for p in dna_score.score_confidence(code, meta={}).parts
                  if p.key == dna_score.CONF_FRESHNESS][0]
        p_rec = [p for p in dna_score.score_confidence(rec, meta={}).parts
                 if p.key == dna_score.CONF_FRESHNESS][0]
        self.assertLess(p_code.score, p_rec.score)


class TestAssetExtraction(unittest.TestCase):
    """从基因里抽可复用产出"""

    def test_code_snippet_from_fence(self):
        content = ("调用方式如下：\n\n\x60\x60\x60python\n"
                   "def retry(fn, times=3):\n    for i in range(times):\n"
                   "        try:\n            return fn()\n"
                   "        except Exception:\n            pass\n\x60\x60\x60\n")
        item = dna_asset.extract_code_snippet(content, "python")
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], dna_asset.ASSET_CODE)
        self.assertIn("def retry", item["content"])

    def test_api_contract_from_table(self):
        content = ("| 字段 | 说明 |\n|---|---|\n| id | 主键 |\n"
                   "| name | 名称（必填） |\n| ts | 时间戳 |")
        item = dna_asset.extract_api_contract(content)
        self.assertIsNotNone(item)
        names = [f["name"] for f in item["fields"]]
        self.assertIn("id", names)
        self.assertIn("name", names)

    def test_checklist_from_steps(self):
        content = ("操作步骤：\n1. 先备份数据库\n2. 再执行迁移脚本\n"
                   "3. 最后重启服务")
        item = dna_asset.extract_checklist(content)
        self.assertIsNotNone(item)
        self.assertEqual(len(item["steps"]), 3)

    def test_no_false_positive_on_prose(self):
        """散文不该被硬抽成契约或步骤"""
        self.assertIsNone(dna_asset.extract_api_contract("这是一段普通说明文字。"))
        self.assertIsNone(dna_asset.extract_checklist("这只是一句话。"))


class TestOpenkbHelpers(unittest.TestCase):
    """外部开源项目：引用解析与许可证"""

    def test_parse_repo_ref_variants(self):
        self.assertEqual(dna_openkb.parse_repo_ref("mem0ai/mem0"),
                         ("mem0ai", "mem0"))
        self.assertEqual(
            dna_openkb.parse_repo_ref("https://github.com/langchain-ai/langchain"),
            ("langchain-ai", "langchain"))
        self.assertEqual(dna_openkb.parse_repo_ref("git@github.com:zepdev/zep.git"),
                         ("zepdev", "zep"))

    def test_parse_repo_ref_rejects_garbage(self):
        with self.assertRaises(ValueError):
            dna_openkb.parse_repo_ref("这不是一个仓库")

    def test_license_detection(self):
        self.assertEqual(
            dna_openkb.normalize_license("MIT License\n\nCopyright (c) ..."),
            "MIT")
        self.assertEqual(
            dna_openkb.normalize_license(
                "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3"),
            "AGPL-3.0")

    def test_copyleft_detection_and_notice(self):
        self.assertTrue(dna_openkb.is_copyleft("GPL-3.0"))
        self.assertFalse(dna_openkb.is_copyleft("MIT"))
        notice = dna_openkb.license_notice("GPL-3.0", "foo/bar")
        self.assertIn("传染性", notice)
        self.assertIn("foo/bar", notice)

    def test_unknown_license_notice_is_cautious(self):
        notice = dna_openkb.license_notice("", "foo/bar")
        self.assertIn("保留所有权利", notice)

    def test_public_interfaces_skip_private(self):
        code = ("class Foo:\n    pass\n\n"
                "def public_fn(a, b):\n    return a\n\n"
                "def _private(x):\n    return x\n")
        items = dna_openkb.extract_public_interfaces(code, "python")
        names = {i["name"] for i in items}
        self.assertIn("public_fn", names)
        self.assertIn("Foo", names)
        self.assertNotIn("_private", names)


class TestClosedLoop(unittest.IsolatedAsyncioTestCase):
    """闭环：基因 → 产出 → 被用过 → 分数变了 → 留了痕"""

    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # 评分表结构（dna_gene 补列 + dna_gene_score）
        async with engine.begin() as conn:
            await dna_score.ensure_score_schema(conn)

    async def asyncTearDown(self):
        # 每个用例之间清干净，免得上一条基因的计数影响下一条
        async with engine.begin() as conn:
            for table in ("dna_asset_use", "dna_asset", "dna_gene_score",
                         "dna_gene"):
                await conn.execute(text(f"delete from {table}"))

    async def test_absorb_scores_gene(self):
        """吸收即评分：不需要额外的全量重算"""
        async with SessionLocal() as db:
            gene, created = await dna_library.upsert_gene(
                db, kind="method",
                title="配置超时时间的正确做法",
                content="当请求超过 30 秒时必须重试，最多 3 次。"
                        "调用 config.set_timeout(30)。"
                        "注意不要超过 60 秒，否则网关会断开。",
                tags=["超时", "重试"],
                source_kind="code", source_ref="code:abc",
                source_title="config.py", confidence=0.8,
                meta={"language": "python"})
            self.assertTrue(created)
            await db.commit()
            score = await dna_score.get_score(db, gene.id)
            self.assertGreater(score["expressiveness"], 0)
            self.assertGreater(score["confidence"], 0)
            # 分项与依据都在
            self.assertEqual(len(score["express_parts"]), 4)
            self.assertEqual(len(score["confidence_parts"]), 4)
            for part in score["confidence_parts"].values():
                self.assertTrue(part["detail"])

    async def test_use_asset_changes_score_and_leaves_evidence(self):
        """「用过」要真的改变分数，并留下证据链"""
        async with SessionLocal() as db:
            gene, _ = await dna_library.upsert_gene(
                db, kind="method",
                title="带重试的调用封装",
                content=("封装一个带重试的调用：\n\n\x60\x60\x60python\n"
                         "def call_with_retry(fn, times=3):\n"
                         "    for i in range(times):\n"
                         "        try:\n"
                         "            return fn()\n"
                         "        except Exception:\n"
                         "            continue\n"
                         "\x60\x60\x60\n"
                         "当调用失败时重试，最多 3 次；注意不要超过 5 次。"
                         "成功之后会返回结果对象。"),
                tags=["重试"], source_kind="code", source_ref="code:xyz",
                source_title="retry.py", confidence=0.8)
            await db.commit()
            before = await dna_score.get_score(db, gene.id)
            self.assertEqual(before["use_success"], 0)

            assets = await dna_asset.create_assets_from_gene(db, gene)
            self.assertTrue(assets, "这条基因应该能落出产出")
            asset = assets[0]

            res = await dna_asset.use_asset(
                db, asset.id, project="订单系统", task="接入支付网关",
                outcome="success", actor="tester")
            self.assertEqual(res["event"]["outcome"], "success")

            after = await dna_score.get_score(db, gene.id)
            self.assertEqual(after["use_success"], 1)
            self.assertGreater(after["confidence"], before["confidence"])
            self.assertGreater(after["expressiveness"], before["expressiveness"])
            # 基因的「被用次数」也涨了
            g = (await db.execute(
                __import__("sqlalchemy").select(DnaGene)
                .where(DnaGene.id == gene.id))).scalar_one()
            self.assertEqual(g.usage_count, 1)

            # 证据链：事件落库了
            uses = await dna_asset.list_uses(db, gene_id=gene.id)
            self.assertEqual(uses["total"], 1)
            self.assertEqual(uses["items"][0]["project"], "订单系统")

    async def test_failed_use_lowers_confidence(self):
        """复用失败必须压分（负反馈要真的扣）"""
        async with SessionLocal() as db:
            gene, _ = await dna_library.upsert_gene(
                db, kind="method", title="会失败的调用",
                content="当调用失败时重试，最多 3 次。注意不要超过 5 次。"
                        "成功之后会返回结果对象。调用 client.send() 完成。",
                tags=["重试"], source_kind="code", source_ref="code:bad",
                source_title="bad.py", confidence=0.8)
            await db.commit()
            assets = await dna_asset.create_assets_from_gene(db, gene)
            self.assertTrue(assets)
            base = await dna_score.get_score(db, gene.id)
            await dna_asset.use_asset(db, assets[0].id, project="p",
                                      outcome="fail")
            after = await dna_score.get_score(db, gene.id)
            self.assertEqual(after["use_fail"], 1)
            self.assertLess(after["confidence"], base["confidence"])

    async def test_correction_lowers_confidence(self):
        """人工纠正必须真的扣分"""
        async with SessionLocal() as db:
            gene, _ = await dna_library.upsert_gene(
                db, kind="fact", title="端口配置",
                content="服务默认监听 8080 端口。可以在 config 里改。",
                tags=["端口"], source_kind="document", source_ref="doc-9",
                source_title="部署文档", confidence=0.7)
            await db.commit()
            base = await dna_score.get_score(db, gene.id)
            res = await dna_score.record_correction(db, gene.id, note="端口写错了")
            self.assertIsNotNone(res)
            self.assertEqual(res["corrections"], 1)
            self.assertLess(res["confidence"], base["confidence"])

    async def test_rescore_all_backfills(self):
        """回填：给存量数据补上新分数"""
        async with SessionLocal() as db:
            await dna_library.upsert_gene(
                db, kind="fact", title="存量知识",
                content="这是一条存量知识，用来验证回填。",
                tags=[], source_kind="document", source_ref="doc-1",
                source_title="旧文档", confidence=0.6)
            await db.commit()
            # 把评分版本抹掉，模拟「v8 之前入库的数据」
            await db.execute(
                __import__("sqlalchemy").text(
                    "update dna_gene set score_version = 0"))
            await db.commit()
            res = await dna_score.rescore_all(db, only_stale=True)
            self.assertGreaterEqual(res["scored"], 1)
            rows = (await db.execute(
                __import__("sqlalchemy").select(DnaGeneScore))).scalars().all()
            self.assertTrue(rows)
            self.assertEqual(rows[0].version, dna_score.SCORE_VERSION)

    async def test_source_note_accumulates(self):
        """同一条知识被两个来源提到 → 交叉验证的原料"""
        async with SessionLocal() as db:
            gene, _ = await dna_library.upsert_gene(
                db, kind="fact", title="重复的知识",
                content="同一条知识，出现在两个地方。",
                tags=[], source_kind="document", source_ref="doc-1",
                source_title="A", confidence=0.6)
            await db.commit()
            await dna_score.note_source(db, gene, "doc-2")
            await db.commit()
            self.assertIn("doc-1", (gene.meta or {}).get("sources", []))
            self.assertIn("doc-2", (gene.meta or {}).get("sources", []))


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
