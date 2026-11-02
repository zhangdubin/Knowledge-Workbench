#!/usr/bin/env python3
"""瞬时数据库错误的重试：一次读失败不该变成 500

背景：数据目录常挂在外接盘/网络盘上，这类挂载偶发返回
「disk I/O error」。一次读失败就 500，用户看到的是「系统坏了」，
而这种错误重试一次通常就过去了。
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("KB_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app import database as db  # noqa: E402


class TestTransientRetry(unittest.TestCase):
    def test_marks_transient(self):
        self.assertTrue(db.is_transient_db_error(
            Exception("sqlite3.OperationalError: disk I/O error")))
        self.assertTrue(db.is_transient_db_error(
            Exception("database is locked")))
        self.assertTrue(db.is_transient_db_error(
            Exception("unable to open database file")))

    def test_does_not_mark_permanent(self):
        # 约束冲突、语法错重试多少次都一样，不该重试
        self.assertFalse(db.is_transient_db_error(
            Exception("UNIQUE constraint failed: dna_gene.title")))
        self.assertFalse(db.is_transient_db_error(
            Exception("no such column: foo")))
        self.assertFalse(db.is_transient_db_error(ValueError("普通错误")))

    def test_execute_retries_then_succeeds(self):
        """前两次抛瞬时错误，第三次成功 → 返回成功结果"""
        from sqlalchemy import text

        async def run():
            async with db.SessionLocal() as s:
                calls = {"n": 0}
                real = db.AsyncSession.execute

                async def flaky(self, *args, **kwargs):
                    calls["n"] += 1
                    if calls["n"] < 3:
                        raise Exception("disk I/O error")
                    return await real(self, *args, **kwargs)

                db.AsyncSession.execute = flaky
                try:
                    row = (await s.execute(text("select 1"))).first()
                finally:
                    db.AsyncSession.execute = real
                return calls["n"], row

        n, row = asyncio.run(run())
        self.assertEqual(n, 3, "应该重试到第 3 次才成功")
        self.assertEqual(tuple(row), (1,))

    def test_execute_gives_up_after_limit(self):
        """一直失败 → 重试 3 次后原样抛出，不无限重试"""
        from sqlalchemy import text

        async def run():
            async with db.SessionLocal() as s:
                calls = {"n": 0}
                real = db.AsyncSession.execute

                async def always_fail(self, *args, **kwargs):
                    calls["n"] += 1
                    raise Exception("disk I/O error")

                db.AsyncSession.execute = always_fail
                try:
                    await s.execute(text("select 1"))
                    return calls["n"], None
                except Exception as e:
                    return calls["n"], e
                finally:
                    db.AsyncSession.execute = real

        n, err = asyncio.run(run())
        self.assertEqual(n, 3, "最多重试 3 次")
        self.assertIsNotNone(err)
        self.assertIn("disk I/O error", str(err))

    def test_permanent_error_not_retried(self):
        """非瞬时错误一次就抛，不重试"""
        from sqlalchemy import text

        async def run():
            async with db.SessionLocal() as s:
                calls = {"n": 0}
                real = db.AsyncSession.execute

                async def bad(self, *args, **kwargs):
                    calls["n"] += 1
                    raise Exception("no such column: foo")

                db.AsyncSession.execute = bad
                try:
                    await s.execute(text("select 1"))
                    return calls["n"], None
                except Exception as e:
                    return calls["n"], e
                finally:
                    db.AsyncSession.execute = real

        n, err = asyncio.run(run())
        self.assertEqual(n, 1, "非瞬时错误不该重试")
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
