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
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 护栏：先把库指到临时目录，再 import 应用模块。
#
# 原来这里写的是 os.environ.setdefault("KB_DATABASE_URL", "sqlite+aiosqlite:///:memory:")，
# 有三个问题，一个比一个隐蔽：
#   1. setdefault —— 容器里 DATABASE_URL 早就被 compose 设好了，这行什么也没做；
#   2. KB_ 前缀 —— app/config.py 的 _promote_kb_env() 只在**无前缀**的
#      DATABASE_URL 不存在时才提升，compose 设过就永远轮不到这里；
#   3. 结果：app.config 在 import 时固化成了**线上库**，
#      而本文件按字母序排在 test_dna_learning 之前 ——
#      它的 import 把 config 提前固化了，后一个文件再设环境变量已经太晚。
#      线上 60 条基因就是这样被 tearDown 清掉的。
import _guard  # noqa: E402

_guard.use_temp_db()

from app import database as db  # noqa: E402

# 护栏的第二道：确认 settings 确实固化到了临时库
_guard.assert_test_db()


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

    def test_no_retry_when_transaction_already_wrote(self):
        """事务里已经有写入时，瞬时错误**不重试**，直接把错误抛出去

        为什么：重试前的 rollback() 回滚的是整个事务，
        而重试只重跑失败的那一条语句 ——
        「前面已经写进去的东西」会被冲掉，「重试成功的那一条」却留下了。

        踩过：文档入库时先 flush 写了文档行，紧接着的 FTS 插入遇到瞬时锁，
        回滚把文档行冲掉 → 重试成功 → commit 提交了 FTS 行 →
        库里留下指向不存在文档的 FTS 行，接口照样返回 200，文件静默丢失。

        所以事务里有写入时，宁可报错（整个事务回滚、调用方看得见），
        也不能重试出一个「少了数据的成功」。
        """
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
                    # 先标记「这个事务已经写过了」
                    s._kb_has_writes = True
                    await s.execute(text("select 1"))
                    return calls["n"], None
                except Exception as e:
                    return calls["n"], e
                finally:
                    db.AsyncSession.execute = real

        n, err = asyncio.run(run())
        self.assertEqual(n, 1, "有写入时不该重试")
        self.assertIsNotNone(err, "有写入时应该把错误抛出去，而不是重试后成功")

    def test_write_statement_marks_session(self):
        """写语句要能把会话标记成「已有写入」"""
        from sqlalchemy import text

        async def run():
            async with db.SessionLocal() as s:
                before = s._kb_has_writes
                await s.execute(text("create table if not exists t_probe (id int)"))
                await s.execute(text("insert into t_probe (id) values (1)"))
                after = s._kb_has_writes
            return before, after

        before, after = asyncio.run(run())
        self.assertFalse(before, "新会话一开始不该算有写入")
        self.assertTrue(after, "执行写语句后应该标记成有写入")

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
