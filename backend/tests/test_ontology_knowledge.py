import unittest
from datetime import datetime

import _guard

_guard.use_temp_db()
from fastapi import HTTPException
from app.database import Base, SessionLocal, engine
from app.models import Document
from app.services.auth import Principal

_guard.assert_test_db()


class EvidenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_verified_snapshot_and_live_access(self):
        from app.ontology.evidence import capture, read_evidence

        admin = Principal(None, {"all": True}, auth_disabled=True)
        denied = Principal(None, {})
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            document = Document(
                filename="brief.txt", extracted_text="预算为零。", extract_status="ok"
            )
            db.add(document)
            await db.flush()
            citation = dict(document_id=document.id, quote="预算", start=0, end=2)
            for changes in ({"quote": "利润"}, {"start": -1}, {"end": 88}):
                with self.assertRaises(HTTPException) as error:
                    await capture(db, admin, {**citation, **changes})
                self.assertEqual(error.exception.status_code, 422)
            row = await capture(db, admin, citation)
            document.extracted_text = "重解析文本"
            await db.flush()
            self.assertEqual((await read_evidence(db, admin, row.id))["quote"], "预算")
            with self.assertRaises(HTTPException) as error:
                await read_evidence(db, denied, row.id)
            self.assertEqual(error.exception.status_code, 403)
            document.deleted_at = datetime.now()
            await db.flush()
            with self.assertRaises(HTTPException) as error:
                await read_evidence(db, admin, row.id)
            self.assertEqual(error.exception.status_code, 404)

    async def test_claim_review_query_conflict(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from uuid import uuid4

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            doc = Document(
                filename="claims.txt", extracted_text="数量3或4", extract_status="ok"
            )
            db.add(doc)
            await db.commit()
            did = doc.id
        client = TestClient(app)
        root = "/api/ontologies"
        key = "q" + uuid4().hex
        spec = {
            "types": [
                {
                    "key": key,
                    "name": "物品",
                    "fields": [{"key": "count", "name": "数量", "type": "number"}],
                }
            ],
            "relations": [],
        }
        space = client.post(
            root + "/", json=dict(key=key, name=key, schema=spec)
        ).json()
        url = root + "/" + space["id"]
        rev = space["revisions"][0]
        plan = client.post(f"{url}/revisions/{rev['id']}/plan", json={}).json()
        self.assertEqual(
            client.post(f"{root}/changes/{plan['id']}/confirm").status_code, 200
        )
        typ = rev["schema"]["types"][0]
        record = client.post(
            url + "/objects", json=dict(type_id=typ["id"], data={})
        ).json()
        payload = dict(
            object_id=record["id"],
            predicate_id=typ["fields"][0]["id"],
            value=3,
            evidence=[dict(document_id=did, quote="数量", start=0, end=2)],
            effective_from="2020-01-01",
        )
        self.assertEqual(
            client.post(url + "/claims", json={**payload, "value": "bad"}).status_code,
            422,
        )
        for value in [3, 4]:
            response = client.post(url + "/claims", json={**payload, "value": value})
            self.assertEqual(response.status_code, 200, response.text)
            claim = response.json()
            self.assertEqual(claim["status"], "candidate")
            review = f"{root}/claims/{claim['id']}/review"
            decision = dict(action="accept", expected_version=1)
            self.assertEqual(client.post(review, json=decision).status_code, 200)
            self.assertEqual(client.post(review, json=decision).status_code, 409)
        from app.services.auth import current_principal

        denied = Principal(None, {"models": {key: "read"}, "pages": ["library"]})
        app.dependency_overrides[current_principal] = lambda: denied
        try:
            blocked = client.post(url + "/query", json={})
            self.assertEqual(blocked.status_code, 403)
            self.assertNotIn("预算", blocked.text)
        finally:
            del app.dependency_overrides[current_principal]
        response = client.post(url + "/query", json=dict(object_id=record["id"]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "conflict")
        self.assertEqual(len(response.json()["facts"]), 2)
        self.assertEqual(
            client.post(url + "/query", json=dict(as_of="2019-01-01")).json()["status"],
            "unknown",
        )

    async def test_ingestion_replay_and_ai_modes(self):
        import json
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4
        from fastapi.testclient import TestClient
        from app.main import app

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            doc = Document(
                filename="brief", extracted_text="Alpha costs 9", extract_status="ok"
            )
            db.add(doc)
            await db.commit()
            did = doc.id
        c = TestClient(app)
        root = "/api/ontologies"
        key = "obj" + uuid4().hex
        definition = {
            "types": [
                {
                    "key": key,
                    "name": "Object",
                    "fields": [
                        {"key": "name", "name": "Name", "type": "text"},
                        {"key": "cost", "name": "Cost", "type": "number"},
                    ],
                }
            ],
            "relations": [],
        }
        space = c.post(
            root + "/", json=dict(key=key, name=key, schema=definition)
        ).json()
        url = root + "/" + space["id"]
        revision = space["revisions"][0]
        schema_plan = c.post(f"{url}/revisions/{revision['id']}/plan", json={}).json()
        c.post(f"{root}/changes/{schema_plan['id']}/confirm").raise_for_status()
        typ = revision["schema"]["types"][0]
        result = dict(
            objects=[
                dict(
                    ref="a",
                    source_id="alpha",
                    type_id=typ["id"],
                    data={"name": "Alpha"},
                )
            ],
            relationships=[],
            claims=[
                dict(
                    object_ref="a",
                    predicate_id=typ["fields"][1]["id"],
                    value=9,
                    evidence=[dict(document_id=did, start=12, end=13, quote="9")],
                )
            ],
        )
        payload = dict(document_id=did, mode="manual", candidates=result)
        run = c.post(url + "/ingestions", json=payload)
        self.assertEqual(run.status_code, 200, run.text)
        job = run.json()
        self.assertEqual(
            c.post(url + "/ingestions", json=payload).json()["id"], job["id"]
        )
        plan = c.post(f"{root}/ingestions/{job['id']}/plan", json={}).json()
        confirm = f"{root}/changes/{plan['id']}/confirm"
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)

        def submit():
            barrier.wait()
            return TestClient(app).post(confirm)

        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(responses[0].json(), responses[1].json())
        applied = responses[0]
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(c.post(confirm).json(), applied.json())
        self.assertEqual(len(c.get(url + "/objects").json()), 1)
        self.assertEqual(c.get(url + "/claims").json()[0]["status"], "candidate")
        ai_payload = dict(document_id=did, mode="ai")
        with patch("app.ontology.ingestion.get_full_config", return_value={}):
            self.assertEqual(
                c.post(url + "/ingestions", json=ai_payload).json()["status"],
                "not_configured",
            )
        cfg = dict(
            enabled=True, model="controlled", api_key="unused", base_url="http://unused"
        )
        with patch("app.ontology.ingestion.get_full_config", return_value=cfg):
            with patch(
                "app.ontology.ingestion.extract_ai", new=AsyncMock(return_value="{bad")
            ):
                self.assertEqual(
                    c.post(url + "/ingestions", json=ai_payload).json()["status"],
                    "failed",
                )
            with patch(
                "app.ontology.ingestion.extract_ai",
                new=AsyncMock(return_value=json.dumps(result)),
            ):
                self.assertEqual(
                    c.post(url + "/ingestions", json=ai_payload).json()["status"],
                    "ready",
                )

        from app.services.auth import current_principal
        from app.models import EntityRecord
        from sqlalchemy import select
        from copy import deepcopy

        ambiguity = deepcopy(payload)
        ambiguity["candidates"]["objects"][0]["source_id"] = "different"
        ambiguous = c.post(url + "/ingestions", json=ambiguity).json()
        self.assertEqual(ambiguous["status"], "needs_review")
        self.assertEqual(
            c.post(f"{root}/ingestions/{ambiguous['id']}/plan").status_code, 409
        )
        # A new candidate tied to the same exact source reuses the record.
        reuse = deepcopy(payload)
        reuse["candidates"]["claims"][0]["confidence"] = 0.7
        reuse_job = c.post(url + "/ingestions", json=reuse).json()
        replay_plan = c.post(f"{root}/ingestions/{reuse_job['id']}/plan").json()
        existing_obj = c.get(url + "/objects").json()[0]
        c.put(
            f"{root}/objects/{existing_obj['id']}",
            json={"expected_version": 1, "data": {"name": "Changed"}},
        ).raise_for_status()
        self.assertEqual(
            c.post(f"{root}/changes/{replay_plan['id']}/confirm").status_code, 409
        )
        self.assertEqual(len(c.get(url + "/claims").json()), 1)
        source_denied = Principal(None, {"pages": ["types"], "models": {key: "write"}})
        app.dependency_overrides[current_principal] = lambda: source_denied
        try:
            self.assertEqual(c.get(url + "/claims").json(), [])
            self.assertEqual(c.get(f"{root}/ingestions/{job['id']}").status_code, 403)
            self.assertNotIn("Alpha", c.get(f"{root}/changes/{replay_plan['id']}").text)
        finally:
            del app.dependency_overrides[current_principal]
        # A fresh plan becomes stale if its source is replaced after review.
        fresh_plan = c.post(f"{root}/ingestions/{reuse_job['id']}/plan").json()
        async with SessionLocal() as db:
            original = await db.get(Document, did)
            original.extracted_text = "Changed at source"
            await db.commit()
        self.assertEqual(
            c.post(f"{root}/changes/{fresh_plan['id']}/confirm").status_code, 409
        )
