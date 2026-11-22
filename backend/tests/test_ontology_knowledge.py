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
        sem = uuid4().hex
        spec = {
            "types": [
                {
                    "id": sem,
                    "key": key,
                    "name": "物品",
                    "fields": [{"key": "count", "name": "数量", "type": "number"}],
                }
            ],
            "relations": [
                dict(
                    key="related",
                    name="Related",
                    source=sem,
                    target=sem,
                    cardinality="many-to-many",
                )
            ],
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
        accepted = []
        for value in [3, 4]:
            response = client.post(url + "/claims", json={**payload, "value": value})
            self.assertEqual(response.status_code, 200, response.text)
            claim = response.json()
            accepted.append(claim["id"])
            self.assertEqual(claim["status"], "candidate")
            review = f"{root}/claims/{claim['id']}/review"
            decision = dict(action="accept", expected_version=1)
            self.assertEqual(client.post(review, json=decision).status_code, 200)
            self.assertEqual(client.post(review, json=decision).status_code, 409)
            history_url = f"{root}/claims/{claim['id']}/history"
            claim_url = f"{root}/claims/{claim['id']}"
            self.assertEqual(client.get(claim_url).json().get("id"), claim["id"])
            history = client.get(history_url)
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.json()[0]["status"], "accepted")
        from app.services.auth import current_principal

        denied = Principal(None, {"models": {key: "write"}, "pages": ["library"]})
        app.dependency_overrides[current_principal] = lambda: denied
        try:
            self.assertEqual(client.get(history_url).status_code, 403)
            self.assertEqual(client.get(claim_url).status_code, 403)
            self.assertEqual(client.get(f"/api/records/{record['id']}").status_code, 200)
            obj_url = root + "/objects/" + str(record["id"])
            for method, path, body in [
                ("GET", url + "/objects", None), ("GET", obj_url, None),
                ("GET", obj_url + "/history", None),
                ("PUT", obj_url, {"data": {}, "expected_version": 1}),
                ("POST", url + "/objects", {"type_id": sem, "data": {}}),
            ]:
                with self.subTest(method=method, path=path):
                    self.assertEqual(client.request(method, path, json=body).status_code, 403)
            blocked = client.post(url + "/query", json={})
            self.assertEqual(blocked.status_code, 403)
            self.assertNotIn("预算", blocked.text)
        finally:
            del app.dependency_overrides[current_principal]
        response = client.post(url + "/query", json=dict(object_id=record["id"]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "conflict")
        self.assertEqual(len(response.json()["facts"]), 2)
        for filters in ({"limit": 1}, {"value": 3}):
            scoped = client.post(url + "/query", json=filters).json()
            self.assertEqual(scoped["status"], "conflict")
            self.assertEqual(len(scoped["facts"]), 1)
        relation = rev["schema"]["relations"][0]
        related = client.post(url + "/objects", json=dict(type_id=sem, data={})).json()[
            "id"
        ]
        edge = {k: v for k, v in payload.items() if k != "value"}
        edge.update(predicate_id=relation["id"], target_id=related)
        new_candidate = client.post(url + "/claims", json=edge)
        self.assertEqual(new_candidate.status_code, 200, new_candidate.text)
        for status in ("candidate", "rejected"):
            if status == "rejected":
                client.post(
                    f"{root}/claims/{new_candidate.json()['id']}/review",
                    json={"action": "reject", "expected_version": 1},
                ).raise_for_status()
            graph = client.post(
                url + "/query",
                json={"status": status, "object_id": record["id"], "depth": 2},
            ).json()
            self.assertEqual(graph["status"], status)
            self.assertEqual(graph["paths"], [])
        async with SessionLocal() as db:
            original_doc = Document(filename="original.txt", extracted_text="数量", extract_status="ok")
            db.add(original_doc)
            await db.commit()
            original_id = original_doc.id
        original = {**payload, "evidence": [{**payload["evidence"][0], "document_id": original_id}]}
        superseded = client.post(url + "/claims", json=original).json()["id"]
        review_url = f"{root}/claims/{superseded}/review"
        first = {"action": "supersede", "expected_version": 1, "superseded_by": accepted[0]}
        client.post(review_url, json=first).raise_for_status()
        repeat = client.post(review_url, json={**first, "expected_version": 2, "superseded_by": accepted[1]})
        with self.subTest("terminal supersession"):
            self.assertEqual(repeat.status_code, 409)
            events = client.get(f"{root}/claims/{superseded}/history").json()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["superseded_by"], accepted[0])
        def ingest_edge(proposal):
            job = client.post(url + "/ingestions", json=dict(document_id=did, mode="manual",
                candidates=dict(objects=[], claims=[], relationships=[proposal]))).json()
            link_plan = client.post(f"{root}/ingestions/{job['id']}/plan").json()
            response = client.post(f"{root}/changes/{link_plan['id']}/confirm")
            response.raise_for_status()
            return response.json()

        def relation_def():
            return next(d for d in client.get("/api/relations/defs").json() if d["key"] == relation["key"])

        links_url = "/api/relations/for-record/" + str(record["id"])
        def visible_count(expected):
            self.assertEqual(len(client.get(links_url).json()), expected)
            graph = client.get(f"/api/graph/record/{record['id']}").json()
            self.assertEqual(len(graph["edges"]), expected)
            self.assertEqual(relation_def()["link_count"], expected)

        imported = ingest_edge(edge)
        review_link = f"{root}/claims/{imported['claims'][0]}/review"
        visible_count(0)
        client.post(review_link, json=dict(action="reject", expected_version=1)).raise_for_status()
        visible_count(0)
        client.post(review_link, json=dict(action="accept", expected_version=2)).raise_for_status()
        visible_count(1)
        def paths():
            return client.post(url + "/query", json=dict(object_id=record["id"], depth=1)).json()["paths"]
        self.assertTrue(paths())
        app.dependency_overrides[current_principal] = lambda: Principal(None, {
            "models": {key: "read"}, "pages": ["types"]})
        try:
            self.assertEqual(client.get(f"/api/records/{related}").status_code, 200)
            visible_count(0)
            self.assertFalse(paths())
        finally:
            del app.dependency_overrides[current_principal]

        manual = client.post("/api/relations/records", json=dict(relation_def_id=relation_def()["id"],
            source_record_id=related, target_record_id=record["id"])).json()["id"]
        reused = ingest_edge({**edge, "object_id": related, "target_id": record["id"]})
        self.assertEqual(reused["relationships"], [manual])
        visible_count(2)

        # Reconstruct a database from the previous metadata version, then repeat installation.
        from sqlalchemy import delete
        from app.ontology.models import RelationSupport, OntologyInstallation
        from app.ontology.migrations import install
        async with SessionLocal() as db:
            await db.execute(delete(RelationSupport))
            await db.execute(delete(OntologyInstallation).where(OntologyInstallation.version == 2))
            await install(db)
            await install(db)
        visible_count(2)
        async with SessionLocal() as db:
            doc = await db.get(Document, did)
            doc.deleted_at = datetime.now()
            await db.commit()
        visible_count(1)
        original_url = f"{root}/claims/{superseded}"
        old = client.get(original_url).json()
        self.assertEqual(old["version"], 2)
        self.assertIsNone(old["superseded_by"])
        self.assertIsNone(client.get(original_url + "/history").json()[0]["superseded_by"])
        self.assertEqual(client.get(f"{root}/claims/{accepted[0]}").status_code, 404)
        self.assertEqual(client.get(links_url).json()[0]["link_id"], manual)
        self.assertFalse(paths())
        async with SessionLocal() as db:
            doc = await db.get(Document, did)
            doc.deleted_at = None
            await db.commit()
        client.post(url + "/claims", json=payload).raise_for_status()
        candidate_query = client.post(
            url + "/query", json={"status": "candidate", "depth": 2}
        ).json()
        self.assertEqual(candidate_query["status"], "candidate")
        self.assertEqual(candidate_query["paths"], [])
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
        from app.services.auth import current_principal
        from types import SimpleNamespace

        peer = Principal(SimpleNamespace(id=742, username="peer"), {"all": True})
        app.dependency_overrides[current_principal] = lambda: peer
        try:
            peer_plan = c.post(f"{root}/ingestions/{job['id']}/plan").json()
        finally:
            del app.dependency_overrides[current_principal]
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
        app.dependency_overrides[current_principal] = lambda: peer
        try:
            peer_url = f"{root}/changes/{peer_plan['id']}"
            self.assertEqual(c.post(peer_url + "/confirm").status_code, 409)
            self.assertEqual(c.get(peer_url).json()["status"], "conflicted")
        finally:
            del app.dependency_overrides[current_principal]
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

        no_ai = Principal(
            None, {"pages": ["types", "library"], "models": {key: "write"}}
        )
        app.dependency_overrides[current_principal] = lambda: no_ai
        try:
            with patch("app.ontology.ingestion.get_full_config", return_value=cfg):
                self.assertEqual(
                    c.post(url + "/ingestions", json=ai_payload).status_code, 403
                )
        finally:
            del app.dependency_overrides[current_principal]
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
        anon_input = {
            "mode": "manual",
            "document_id": did,
            "candidates": {
                "objects": [
                    {
                        "ref": "x",
                        "type_id": typ["id"],
                        "data": {"name": "From anonymous-source projection"},
                    }
                ]
            },
        }
        anon_job = c.post(url + "/ingestions", json=anon_input).json()
        anon_plan = c.post(f"{root}/ingestions/{anon_job['id']}/plan").json()
        other = c.post(f"{root}/changes/{anon_plan['id']}/confirm").json()["objects"][
            "x"
        ]
        from app.ontology.models import Projection

        async with SessionLocal() as db:
            legacy = (await db.get(Projection, typ["id"])).legacy_id
        app.dependency_overrides[current_principal] = lambda: source_denied
        try:
            self.assertEqual(c.get(url + "/claims").json(), [])
            for rid in (other, existing_obj["id"]):
                for path in (
                    f"/api/records/{rid}",
                    f"{root}/objects/{rid}",
                    f"{root}/objects/{rid}/history",
                ):
                    self.assertIn(c.get(path).status_code, (403, 404))
            self.assertEqual(c.get(url + "/objects").json(), [])
            from app.services import agent

            async with SessionLocal() as db:
                self.assertEqual(
                    (
                        await agent.tool_search_records(
                            db, source_denied, "anonymous-source"
                        )
                    )["count"],
                    0,
                )
            self.assertEqual(c.post(url + "/query", json={}).json()["objects"], [])
            self.assertEqual(c.get(f"/api/records/type/{legacy}").json()["total"], 0)
            self.assertNotIn(
                "anonymous-source", c.get(f"/api/records/type/{legacy}/export").text
            )
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

    async def test_derived_note_inherits_every_source(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import select
        from uuid import uuid4
        from app.main import app
        from app.models import EntityRecord, EntityType
        from app.ontology.models import RecordSource
        from app.services.auth import current_principal

        async with engine.begin() as con:
            await con.run_sync(Base.metadata.create_all)
        key = "derived" + uuid4().hex
        async with SessionLocal() as db:
            note_type = await db.scalar(select(EntityType).where(EntityType.key == "note"))
            if not note_type:
                note_type = EntityType(key="note",name="Notes")
                db.add(note_type)
            kind = EntityType(key=key,name="Business")
            docs = [Document(filename="One"),Document(filename="Two")]
            db.add_all([kind, *docs])
            await db.flush()
            source = EntityRecord(entity_type_id=kind.id,data={"name":"Receipt"})
            db.add(source)
            await db.flush()
            db.add_all([RecordSource(record_id=source.id,document_id=d.id) for d in docs])
            await db.commit()
            rid,nid = source.id,note_type.id
            source_ids={d.id for d in docs}
        c=TestClient(app)
        reader=Principal(None,{"models":{key:"read","note":"write"}})
        app.dependency_overrides[current_principal]=lambda:reader
        try:
            denied=c.post("/api/knowledge/note-from-record",json=dict(record_id=rid))
            self.assertIn(denied.status_code,(403,404))
            self.assertNotIn("Receipt",denied.text)
            self.assertEqual(c.get(f"/api/records/type/{nid}",params={"keyword":"Receipt"}).json()["total"],0)
            reader.perms["pages"]=["library"]
            created=c.post("/api/knowledge/note-from-record",json=dict(record_id=rid))
            self.assertEqual(created.status_code,200,created.text)
            note_id=created.json()["note_id"]
            self.assertEqual(c.get(f"/api/records/{note_id}").status_code,200)
            async with SessionLocal() as db:
                inherited=set(await db.scalars(select(RecordSource.document_id).where(RecordSource.record_id==note_id)))
                self.assertEqual(inherited,source_ids)
                doc=await db.get(Document,min(source_ids))
                doc.deleted_at=datetime.now()
                await db.commit()
            self.assertEqual(c.get(f"/api/records/{note_id}").status_code,404)
            self.assertEqual(c.get(f"/api/records/type/{nid}",params={"keyword":"Receipt"}).json()["total"],0)
        finally:
            del app.dependency_overrides[current_principal]
