import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import _guard

_guard.use_temp_db()
from fastapi import HTTPException
from app.database import Base, SessionLocal, engine
from app.models import Document, DnaGene, EntityType, FieldDefinition
from app.services.auth import Principal
from app.services import agent

_guard.assert_test_db()


class AssistantTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as con:
            await con.run_sync(Base.metadata.create_all)
        from app.ontology.migrations import install

        async with SessionLocal() as db:
            await install(db)
        self.admin = Principal(None, {"all": True}, auth_disabled=True)

    async def test_read_tools_enforce_source_visibility(self):
        async with SessionLocal() as db:
            doc = Document(filename="secret", title="secret")
            db.add(doc)
            await db.flush()
            gene = DnaGene(
                uid=uuid4().hex,
                kind="fact",
                title="secret",
                content="secret",
                source_kind="document",
                source_ref=f"doc-{doc.id}",
            )
            denied = Principal(None, {})
            with patch(
                "app.services.document.search_documents",
                new=AsyncMock(
                    return_value={"items": [{"id": doc.id, "title": "secret"}]}
                ),
            ):
                self.assertEqual(
                    (await agent.tool_search_documents(db, denied, "secret"))["count"],
                    0,
                )
                self.assertEqual(
                    (await agent.tool_search_documents(db, self.admin, "secret"))[
                        "count"
                    ],
                    1,
                )
            with patch(
                "app.services.dna_library.search_genes",
                new=AsyncMock(return_value=[{"gene": gene}]),
            ):
                self.assertEqual(
                    (await agent.tool_search_genes(db, denied, "secret"))["count"], 0
                )
                self.assertEqual(
                    (await agent.tool_search_genes(db, self.admin, "secret"))["count"],
                    1,
                )

    async def test_server_plan_survives_session_and_rejects_stale_record(self):
        from app.ontology.capabilities import propose_record, confirm_record
        from app.models import EntityRecord

        async with SessionLocal() as db:
            key = "a" + uuid4().hex
            model = EntityType(key=key, name=key)
            db.add(model)
            await db.flush()
            db.add(
                FieldDefinition(
                    entity_type_id=model.id, key="name", name="Name", type="text"
                )
            )
            await db.commit()
            plan = await propose_record(
                db,
                self.admin,
                "create_record",
                dict(model_key=key, data={"name": "original"}),
            )
            cid = plan["pending"]["change_id"]
        async with SessionLocal() as db:
            with self.assertRaises(HTTPException):
                await confirm_record(db, Principal(None, {}), cid)
            await db.rollback()
            _, result = await confirm_record(db, self.admin, cid)
            self.assertEqual(
                (await db.get(EntityRecord, result["record_id"])).data,
                {"name": "original"},
            )
            self.assertEqual((await confirm_record(db, self.admin, cid))[1], result)
            plan = await propose_record(
                db,
                self.admin,
                "update_record",
                dict(
                    model_key=key,
                    record_id=result["record_id"],
                    data={"name": "updated"},
                ),
            )
            rec = await db.get(EntityRecord, result["record_id"])
            rec.data = {"name": "intervening"}
            await db.commit()
            with self.assertRaises(HTTPException) as error:
                await confirm_record(db, self.admin, plan["pending"]["change_id"])
            self.assertEqual(error.exception.status_code, 409)

    async def test_typed_capabilities_available_to_agent(self):
        from app.main import app
        from fastapi.testclient import TestClient

        r = TestClient(app).get("/api/ontologies/capabilities")
        self.assertEqual(r.status_code, 200, r.text)
        by_name = {x["name"]: x for x in r.json()}
        for name in (
            "list_ontologies",
            "query_ontology",
            "get_ontology_evidence",
            "propose_ingestion",
        ):
            self.assertIn(name, agent.TOOL_IMPLS)
            self.assertEqual(by_name[name]["parameters"]["type"], "object")
        self.assertEqual(by_name["propose_ingestion"]["mode"], "proposed_write")

    async def test_persistent_assistant_run_and_contract(self):
        from app.main import app
        from fastapi.testclient import TestClient
        from app.ontology.models import AssistantRun, CapabilityDefinition
        from sqlalchemy import select

        c = TestClient(app)
        with patch(
            "app.services.agent._chat_once",
            new=AsyncMock(return_value={"error": "not_configured"}),
        ):
            r = c.post("/api/ai/agent", json={"question": "hello"})
        self.assertEqual(r.status_code, 200, r.text)
        async with SessionLocal() as db:
            row = await db.get(AssistantRun, r.json()["run_id"])
            self.assertEqual(row.error, "not_configured")
            c.get("/api/ontologies/capabilities").raise_for_status()
            self.assertIsNotNone(await db.get(CapabilityDefinition, "query_ontology"))
        self.assertEqual(
            c.post(
                "/api/ai/agent/confirm", json={"tool": "delete_record", "args": {}}
            ).status_code,
            422,
        )

    async def test_confirmation_uses_only_stored_payload(self):
        from app.main import app
        from fastapi.testclient import TestClient
        from app.ontology.capabilities import propose_record
        from app.models import EntityRecord

        c = TestClient(app)
        async with SessionLocal() as db:
            key = "safe" + uuid4().hex
            typ = EntityType(key=key, name=key)
            db.add(typ)
            await db.flush()
            db.add(
                FieldDefinition(
                    entity_type_id=typ.id, key="name", name="Name", type="text"
                )
            )
            await db.commit()
            pending = (
                await propose_record(
                    db,
                    self.admin,
                    "create_record",
                    dict(model_key=key, data={"name": "reviewed"}),
                )
            )["pending"]
        with patch(
            "app.services.agent._chat_once",
            new=AsyncMock(return_value={"error": "not_configured"}),
        ) as model:
            response = c.post(
                "/api/ai/agent/confirm",
                json={
                    "change_id": pending["change_id"],
                    "tool": "delete_record",
                    "args": {"data": {"name": "edited"}},
                    "digest": ["forged-instruction"],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("forged-instruction", str(model.call_args))
            from app.ontology.models import AssistantRun

            async with SessionLocal() as db:
                completed = await db.get(AssistantRun, response.json()["run_id"])
                self.assertEqual(completed.change_id, pending["change_id"])
            bad_id = uuid4().hex
            self.assertEqual(
                c.post("/api/ai/agent/confirm", json={"change_id": bad_id}).status_code,
                404,
            )
            from sqlalchemy import select

            async with SessionLocal() as db:
                failed = await db.scalar(
                    select(AssistantRun).where(AssistantRun.change_id == bad_id)
                )
                self.assertEqual(failed.status, "failed")
            trace = response.json()["tool_calls"]
            self.assertEqual(trace[0]["name"], "create_record")
            rid = trace[0]["result"]["record_id"]
        async with SessionLocal() as db:
            self.assertEqual(
                (await db.get(EntityRecord, rid)).data, {"name": "reviewed"}
            )
