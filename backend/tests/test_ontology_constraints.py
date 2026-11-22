import unittest
from uuid import uuid4

import _guard

_guard.use_temp_db()

from app.database import Base, engine, SessionLocal
from app.models import EntityType, FieldDefinition
from app.services.record import create_record

_guard.assert_test_db()


class RecordConstraints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            model = EntityType(name="Budget", key=uuid4().hex)
            db.add(model)
            await db.flush()
            self.type_id = model.id
            db.add(
                FieldDefinition(
                    entity_type_id=model.id,
                    key="amount",
                    name="Amount",
                    type="number",
                    required=True,
                )
            )
            await db.commit()

    async def test_invalid_values_never_create_records(self):
        for data in [
            {},
            {"amount": True},
            {"amount": "ten"},
            {"amount": 0, "extra": 5},
        ]:
            with self.subTest(data=data):
                async with SessionLocal() as db:
                    with self.assertRaises(ValueError):
                        await create_record(db, self.type_id, data)

    async def test_required_zero(self):
        async with SessionLocal() as db:
            record = await create_record(db, self.type_id, {"amount": 0})
            self.assertEqual(record.data["amount"], 0)

    async def test_import_reports_exact_rows(self):
        from app.services.record import import_records

        async with SessionLocal() as db:
            result = await import_records(
                db,
                self.type_id,
                '[{"amount":0},{"amount":1,"extra":2},{"amount":true}]',
                "json",
            )
            self.assertEqual(result["created"], 1)
            self.assertEqual([e["row"] for e in result["errors"]], [2, 3])
            result = await import_records(
                db, self.type_id, "amount,extra\n2,3\n", "csv"
            )
            self.assertEqual(result["errors"][0]["row"], 2)

    async def test_agent_requires_valid_values_and_accepts_zero(self):
        from app.services.agent import prepare_write
        from app.services.auth import _anonymous_principal

        async with SessionLocal() as db:
            et = await db.get(EntityType, self.type_id)
            for value, expected in [(0, "pending"), (True, "error")]:
                result = await prepare_write(
                    db,
                    _anonymous_principal(),
                    "create_record",
                    {"model_key": et.key, "data": {"amount": value}},
                )
                self.assertIn(expected, result)

    async def test_atomic_relation_cardinality_and_duplicate(self):
        import asyncio
        from fastapi import HTTPException
        from app.services import relation

        async with SessionLocal() as db:
            endpoints = [
                (await create_record(db, self.type_id, {"amount": 0})).id
                for _ in range(4)
            ]
        for cardinality in ["one-to-one", "one-to-many", "many-to-one", "many-to-many"]:
            async with SessionLocal() as db:
                rd = await relation.create_relation_def(
                    db,
                    {
                        "key": uuid4().hex,
                        "source_type_id": self.type_id,
                        "target_type_id": self.type_id,
                        "cardinality": cardinality,
                    },
                )

            async def link(source, target):
                async with SessionLocal() as db:
                    try:
                        return (
                            await relation.create_relation_record(
                                db,
                                {
                                    "relation_def_id": rd.id,
                                    "source_record_id": endpoints[source],
                                    "target_record_id": endpoints[target],
                                },
                            )
                        ).id
                    except HTTPException as error:
                        self.assertEqual(error.status_code, 409)
                        return None

            first, second = await asyncio.gather(link(0, 1), link(0, 1))
            self.assertEqual(first, second)
            self.assertIsNotNone(first)
            self.assertEqual((await link(0, 2)) is None, cardinality.endswith("-one"))
            self.assertEqual((await link(3, 1)) is None, cardinality.startswith("one-"))

    async def test_reference_and_deleted_relation_target(self):
        from datetime import datetime
        from fastapi import HTTPException
        from app.services import relation

        async with SessionLocal() as db:
            et = await db.get(EntityType, self.type_id)
            target = await create_record(db, et.id, {"amount": 1})
            other = EntityType(key=uuid4().hex, name="other")
            db.add(other)
            await db.flush()
            db.add(
                FieldDefinition(
                    entity_type_id=other.id,
                    key="ref",
                    type="reference",
                    name="ref",
                    options={"target": et.key},
                    required=True,
                )
            )
            await db.commit()
            obj = await create_record(db, other.id, {"ref": target.id})
            for ref in [obj.id, 999999]:
                with self.assertRaises(ValueError):
                    await create_record(db, other.id, {"ref": ref})
            rd = await relation.create_relation_def(
                db,
                {"key": uuid4().hex, "source_type_id": et.id, "target_type_id": et.id},
            )
            target.deleted_at = datetime.now()
            await db.commit()
            with self.assertRaises(ValueError):
                await create_record(db, other.id, {"ref": target.id})
            with self.assertRaises(HTTPException):
                await relation.create_relation_record(
                    db,
                    {
                        "relation_def_id": rd.id,
                        "source_record_id": target.id,
                        "target_record_id": target.id,
                    },
                )
