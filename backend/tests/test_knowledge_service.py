"""Synthetic Chinese knowledge acceptance cases, network-free and guarded."""

import unittest
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import _guard

_guard.use_temp_db()
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Document, DocumentLink, AuditLog
from app.services.auth import Principal, current_principal

_guard.assert_test_db()


class KnowledgeServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        self.c = TestClient(app)
        self.admin = Principal(None, {"all": True}, auth_disabled=True)
        self.p = self.admin
        app.dependency_overrides[current_principal] = lambda: self.p
        self.key = "ks" + uuid4().hex[:12]
        r = self.c.post(
            "/api/knowledge-service/template",
            json={"key": self.key, "name": "保障知识"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.preview = r.json()
        self.sid = r.json()["space_id"]
        self.change = r.json()["change_id"]
        self.confirm = self.c.post(
            f"/api/knowledge-service/template/{self.change}/confirm", json={}
        )
        self.assertEqual(self.confirm.status_code, 200, self.confirm.text)
        self.schema = self.c.get("/api/knowledge-service/template").json()["schema"]
        space = self.c.get("/api/ontologies/" + self.sid).json()
        self.typ, self.term = space["schema"]["types"][:2]
        self.rid = self.obj(
            {
                "title": "维护规程〔2026〕01号",
                "summary": "维护周期",
                "scope": "保障",
                "topic": "维护",
            }
        )
        self.text = "维护规程😀\n维护周期为三天。文号〔2026〕01号。"
        async with SessionLocal() as db:
            doc = Document(
                filename="维护规程.txt",
                title="维护规程",
                extracted_text=self.text,
                extract_status="ok",
            )
            db.add(doc)
            await db.flush()
            self.did = doc.id
            db.add(DocumentLink(document_id=doc.id, record_id=self.rid))
            await db.commit()
        self.rev = self.c.post(
            "/api/knowledge-service/sources", json=self.source_payload()
        ).json()
        self.claim = self.add_claim("三天")
        self.reader = Principal(
            SimpleNamespace(id=91001, username="知识读者"),
            {
                "pages": ["knowledge_service"],
                "models": {self.typ["key"]: "read", self.term["key"]: "read"},
            },
        )
        self.p = self.reader

    async def asyncTearDown(self):
        app.dependency_overrides.pop(current_principal, None)

    def obj(self, data, typ=None):
        r = self.c.post(
            "/api/ontologies/" + self.sid + "/objects",
            json={"type_id": (typ or self.typ)["id"], "data": data},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def source_payload(self, **extra):
        return dict(
            ontology_id=self.sid,
            document_id=self.did,
            group_key="maintenance",
            label="规程第一版",
            scope="保障",
            topic="维护",
            effective_from="2020-01-01",
            **extra,
        )

    def add_claim(
        self,
        value,
        *,
        accepted=True,
        rid=None,
        target=None,
        start="2020-01-01",
        end=None,
    ):
        body = dict(
            object_id=rid or self.rid,
            predicate_id=self.typ["fields"][1]["id"],
            value=value,
            evidence=[dict(document_id=self.did, quote="维护规程😀", start=0, end=5)],
            effective_from=start,
            effective_to=end,
        )
        if target:
            body.pop("value")
            body.update(target_id=target, predicate_id=self.schema_relation)
        r = self.c.post("/api/ontologies/" + self.sid + "/claims", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        claim = r.json()
        if accepted:
            self.c.post(
                "/api/ontologies/claims/" + claim["id"] + "/review",
                json=dict(action="accept", expected_version=1),
            ).raise_for_status()
        return claim

    def query(self, **extra):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(
                ontology_id=self.sid, question="维护规程", as_of="2026-11-22", **extra
            ),
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def feedback(self, **extra):
        run = self.query()
        return self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                run_id=run["run_id"],
                category="引用不正确",
                message="请核对",
                idempotency_key=uuid4().hex,
                **extra,
            ),
        )

    def test_D01_catalog(self):
        catalog = self.c.get("/api/knowledge-service/catalog").json()
        self.assertIn(self.sid, [s["id"] for s in catalog["spaces"]])
        self.assertFalse(catalog["can_manage"])

    def test_D02_preview_not_publish(self):
        self.p = self.admin
        r = self.c.post(
            "/api/knowledge-service/template",
            json={"key": self.key + "b", "name": "新空间"},
        ).json()
        space = self.c.get("/api/ontologies/" + r["space_id"]).json()
        self.assertIsNone(space["current_revision_id"])

    def test_D03_confirm(self):
        self.assertTrue(self.confirm.json()["revision_id"])

    def test_D04_duplicate_confirm(self):
        self.p = self.admin
        self.assertEqual(
            self.c.post(
                f"/api/knowledge-service/template/{self.change}/confirm", json={}
            ).json(),
            self.confirm.json(),
        )

    def test_D05_item(self):
        r = self.c.get(f"/api/knowledge-service/items/{self.rid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["title"], "维护规程〔2026〕01号")

    def test_D06_original(self):
        r = self.c.get("/api/knowledge-service/sources/" + self.rev["id"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["text"], self.text)

    def test_D07_terms(self):
        self.p = self.admin
        tid = self.obj(
            dict(
                preferred="维护规程",
                aliases="保养手册",
                definition="维护说明",
                scope="保障",
            ),
            self.term,
        )
        self.p = self.reader
        self.assertIn(
            tid,
            [
                t["id"]
                for t in self.c.get(
                    "/api/knowledge-service/terms",
                    params=dict(ontology_id=self.sid, q="维护"),
                ).json()["items"]
            ],
        )

    def test_D08_alias(self):
        self.p = self.admin
        self.obj(
            dict(
                preferred="维护规程",
                aliases="保养手册",
                definition="说明",
                scope="保障",
            ),
            self.term,
        )
        self.p = self.reader
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="保养手册"),
        ).json()
        self.assertEqual(r["status"], "supported")

    def test_D09_document_number(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="[2026]01号"),
        ).json()
        self.assertEqual(r["status"], "supported")

    def test_D10_punctuation(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="维护，规程"),
        ).json()
        self.assertEqual(r["status"], "supported")

    def test_D11_empty_input(self):
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="  "),
            ).status_code,
            422,
        )

    def test_D12_no_model(self):
        with patch("app.knowledge_service.answers.model_config", return_value={}):
            self.assertEqual(self.query(generate=True)["generation"], "disabled")

    def test_X01_two_sources(self):
        self.p = self.admin

        async def noop():
            pass

        second = self.add_claim("三天")
        self.p = self.reader
        self.assertEqual(len(self.query()["facts"]), 2)

    def test_X02_same_evidence(self):
        self.p = self.admin
        self.add_claim("三天")
        self.p = self.reader
        self.assertEqual(self.query()["conflicts"], [])

    def test_X03_conflict_before_limit(self):
        self.p = self.admin
        self.add_claim("四天")
        self.p = self.reader
        self.assertEqual(self.query(limit=1)["status"], "conflict")

    def test_X04_candidate_rejected(self):
        self.p = self.admin
        candidate = self.add_claim("四天", accepted=False)
        self.c.post(
            "/api/ontologies/claims/" + candidate["id"] + "/review",
            json=dict(action="reject", expected_version=1),
        )
        self.p = self.reader
        self.assertEqual(len(self.query()["facts"]), 1)

    def test_X05_accepted_relationship(self):
        self.p = self.admin
        target = self.obj(dict(title="润滑规范", scope="保障"))
        self.schema_relation = self.c.get("/api/ontologies/" + self.sid).json()[
            "schema"
        ]["relations"][0]["id"]
        self.add_claim(None, target=target)
        self.p = self.reader
        self.assertTrue(self.query(depth=2)["relations"])

    def test_X06_candidate_relationship(self):
        self.p = self.admin
        target = self.obj(dict(title="候选规范", scope="保障"))
        self.schema_relation = self.c.get("/api/ontologies/" + self.sid).json()[
            "schema"
        ]["relations"][0]["id"]
        self.add_claim(None, target=target, accepted=False)
        self.p = self.reader
        self.assertFalse(self.query(depth=2)["relations"])

    def test_X07_ambiguity(self):
        self.p = self.admin
        for name in ("维护规程", "培训规程"):
            self.obj(dict(preferred=name, aliases="手册", scope="保障"), self.term)
        self.p = self.reader
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="手册"),
        ).json()
        self.assertEqual(r["status"], "ambiguous")

    def test_X08_different_scope(self):
        self.p = self.admin
        other = self.obj(dict(title="维护规程", scope="培训"))
        self.add_claim("四天", rid=other)
        self.p = self.reader
        self.assertEqual(self.query()["conflicts"], [])

    def test_H01_current(self):
        self.assertEqual(self.query()["status"], "supported")

    def test_H02_past(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="维护", as_of="2010-01-01"),
        ).json()
        self.assertEqual(r["status"], "insufficient")

    def test_H03_future(self):
        self.p = self.admin
        self.add_claim("四天", start="2030-01-01")
        self.p = self.reader
        self.assertEqual(len(self.query()["facts"]), 1)

    async def test_H04_explicit_supersedes(self):
        self.p = self.admin
        r = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "effective_from": "2030-01-01",
                "supersedes_id": self.rev["id"],
                "label": "第二版",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.p = self.reader
        self.assertEqual(self.query()["status"], "supported")

    def test_H05_bad_date(self):
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="维护", as_of="2026-22-01"),
            ).status_code,
            422,
        )

    def test_H06_no_automatic_replacement(self):
        self.p = self.admin
        r = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "effective_from": "2025-01-01",
                "label": "新版",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.p = self.reader
        self.assertEqual(
            len(
                self.c.get(
                    "/api/knowledge-service/sources", params={"ontology_id": self.sid}
                ).json()["items"]
            ),
            2,
        )

    def test_P01_without_types(self):
        self.assertFalse(self.reader.has_page("types"))
        r = self.query()
        self.assertEqual(r["status"], "supported")
        for ev in r["citations"]:
            self.assertEqual(self.text[ev["start"] : ev["end"]], ev["quote"])

    def test_P02_no_entry(self):
        self.reader.perms["pages"] = []
        self.assertEqual(self.c.get("/api/knowledge-service/catalog").status_code, 403)

    def test_P03_model_denied(self):
        self.reader.perms["models"] = {}
        self.assertNotIn(
            self.sid,
            [
                s["id"]
                for s in self.c.get("/api/knowledge-service/catalog").json()["spaces"]
            ],
        )

    async def test_P04_source_denied(self):
        async with SessionLocal() as db:
            d = await db.get(Document, self.did)
            d.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.assertEqual(self.query()["status"], "insufficient")

    async def test_P05_run_revocation(self):
        run = self.query()
        self.reader.perms["models"] = {}
        r = self.c.get("/api/knowledge-service/runs/" + run["run_id"])
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn("三天", r.text)

    def test_P06_other_run(self):
        run = self.query()
        self.p = Principal(
            SimpleNamespace(id=91002, username="其他人"), self.reader.perms
        )
        self.assertEqual(
            self.c.get("/api/knowledge-service/runs/" + run["run_id"]).status_code, 404
        )

    def test_I01_empty(self):
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="不存在的内容"),
            ).json()["status"],
            "insufficient",
        )

        self.p = self.admin
        preview = self.c.post(
            "/api/knowledge-service/template",
            json=dict(key=self.key + "empty", name="空知识空间"),
        ).json()
        self.c.post(
            "/api/knowledge-service/template/" + preview["change_id"] + "/confirm",
            json={},
        ).raise_for_status()
        for typ in preview["preview"]["schema"]["types"]:
            self.reader.perms["models"][typ["key"]] = "read"
        self.p = self.reader
        response = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=preview["space_id"], question="维护规程"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "insufficient")
        for name in ("items", "facts", "citations", "sources"):
            self.assertEqual(result[name], [])

    def test_I02_no_evidence(self):
        self.p = self.admin
        self.obj(dict(title="没有依据", scope="保障"))
        self.p = self.reader
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="没有依据"),
            ).json()["status"],
            "insufficient",
        )

    async def test_I03_invalid_quote(self):
        from app.ontology.models import Evidence

        async with SessionLocal() as db:
            ev = await db.scalar(
                select(Evidence).where(Evidence.claim_id == self.claim["id"])
            )
            ev.end = 999
            await db.commit()
        self.assertEqual(self.query()["status"], "insufficient")

    def test_I04_scan_budget(self):
        with patch("app.knowledge_service.retrieval.SCAN_BUDGET", 0):
            self.assertTrue(self.query()["incomplete"])

    def test_F01_idempotency(self):
        run = self.query()
        body = dict(
            run_id=run["run_id"],
            category="引用不正确",
            message="核对",
            idempotency_key=uuid4().hex,
        )
        a = self.c.post("/api/knowledge-service/feedback", json=body)
        b = self.c.post("/api/knowledge-service/feedback", json=body)
        self.assertEqual(a.status_code, 200, a.text)
        self.assertEqual(a.json(), b.json())
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/feedback",
                json={**body, "message": "另一个问题"},
            ).status_code,
            409,
        )

    def test_F02_forged_association(self):
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/feedback",
                json=dict(
                    run_id="forged",
                    category="引用不正确",
                    message="核对",
                    idempotency_key=uuid4().hex,
                ),
            ).status_code,
            404,
        )

    def test_F03_stale_version(self):
        f = self.feedback().json()
        self.reader.perms["features"] = {"knowledge_review": True}
        r = self.c.post(
            "/api/knowledge-service/feedback/" + f["id"] + "/resolve",
            json=dict(
                expected_version=0, resolution="核实", idempotency_key=uuid4().hex
            ),
        )
        self.assertEqual(r.status_code, 409, r.text)

    async def test_F04_audit(self):
        f = self.feedback().json()
        self.reader.perms["features"] = {"knowledge_review": True}
        body = dict(
            expected_version=1, resolution="已核实", idempotency_key=uuid4().hex
        )
        a = self.c.post(
            "/api/knowledge-service/feedback/" + f["id"] + "/resolve", json=body
        )
        self.assertEqual(a.status_code, 200, a.text)
        self.assertEqual(
            a.json(),
            self.c.post(
                "/api/knowledge-service/feedback/" + f["id"] + "/resolve", json=body
            ).json(),
        )
        async with SessionLocal() as db:
            logs = list(
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "knowledge_feedback_resolve",
                        AuditLog.resource_id == f["id"],
                    )
                )
            )
            self.assertEqual(len(logs), 1)

    async def test_S01_snapshot_pinned_and_current_hash_drift(self):
        async with SessionLocal() as db:
            doc = await db.get(Document, self.did)
            doc.extracted_text = "新解析内容"
            doc.sha256 = "changed"
            await db.commit()
        r = self.c.get("/api/knowledge-service/sources/" + self.rev["id"]).json()
        self.assertEqual(r["text"], self.text)
        self.assertTrue(r["original_document_changed"])
        self.assertEqual(r["group_revisions"][0]["id"], self.rev["id"])

    async def test_S02_feedback_retry_after_item_edit(self):
        body = dict(
            record_id=self.rid,
            record_version=1,
            category="引用不正确",
            message="核对",
            idempotency_key=uuid4().hex,
        )
        first = self.c.post("/api/knowledge-service/feedback", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.p = self.admin
        self.c.put(
            "/api/ontologies/objects/" + str(self.rid),
            json=dict(
                data={"title": "调整后的维护规程", "scope": "保障"}, expected_version=1
            ),
        ).raise_for_status()
        self.p = self.reader
        retry = self.c.post("/api/knowledge-service/feedback", json=body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(first.json()["id"], retry.json()["id"])

    def test_S03_model_foreign_citation_rejected(self):
        self.reader.perms["features"] = {"ai": True}
        mock = AsyncMock(
            return_value=dict(
                content='{"answer":"错误答复","citations":[{"evidence_id":"foreign","quote":"维护规程😀","start":0,"end":5}]}',
                model="controlled",
                mock=False,
                truncated=False,
            )
        )
        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch("app.knowledge_service.answers.ai.chat_real_meta", mock):
            r = self.query(generate=True)
        self.assertEqual(r["generation"], "error")
        self.assertIsNone(r["answer"])

    def test_S04_model_mock_never_evidence(self):
        self.reader.perms["features"] = {"ai": True}
        mock = AsyncMock(
            return_value=dict(content="mock answer", mock=True, finish_reason="mock")
        )
        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch("app.knowledge_service.answers.ai.chat_real_meta", mock):
            self.assertEqual(self.query(generate=True)["generation"], "error")

    def test_S05_model_uses_only_authorized_evidence(self):
        self.reader.perms["features"] = {"ai": True}

        async def controlled(messages, **kwargs):
            import json

            context = json.loads(messages[1]["content"])
            ev = context["evidence"][0]
            self.assertEqual(ev["quote"], "维护规程😀")
            return dict(
                content=json.dumps(dict(answer="请参阅维护规程。", citations=[ev])),
                model="controlled",
                mock=False,
                truncated=False,
            )

        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch(
            "app.knowledge_service.answers.ai.chat_real_meta", side_effect=controlled
        ):
            r = self.query(generate=True)
        self.assertEqual(r["generation"], "generated")
        self.assertEqual(r["model_version"], "controlled")

    async def test_S06_reviewer_revocation_all_paths(self):
        run = self.query()
        f = self.feedback().json()
        self.reader.perms["features"] = {"knowledge_review": True}
        async with SessionLocal() as db:
            doc = await db.get(Document, self.did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        for path in [
            "/runs/" + run["run_id"],
            "/feedback/" + f["id"],
            "/sources/" + self.rev["id"],
        ]:
            response = self.c.get("/api/knowledge-service" + path)
            self.assertIn(response.status_code, (403, 404))
            self.assertNotIn("三天", response.text)
        self.assertEqual(
            self.c.get("/api/knowledge-service/feedback").json()["items"], []
        )

    def test_S07_source_write_restricted(self):
        self.assertEqual(
            self.c.post(
                "/api/knowledge-service/sources", json=self.source_payload()
            ).status_code,
            403,
        )
        catalog = self.c.get("/api/knowledge-service/catalog").json()
        self.assertEqual(catalog["source_candidates"], [])

    def test_S08_limit_depth_bounds(self):
        for kwargs in [
            dict(limit=0),
            dict(limit=51),
            dict(depth=3),
            dict(limit=True),
            dict(generate="yes"),
        ]:
            response = self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="维护", **kwargs),
            )
            self.assertEqual(response.status_code, 422, response.text)

    def test_S09_cross_scope_supersession_rejected(self):
        self.p = self.admin
        r = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "scope": "培训",
                "effective_from": "2027-01-01",
                "supersedes_id": self.rev["id"],
            },
        )
        self.assertEqual(r.status_code, 422, r.text)

    def test_S10_unlinked_source_requires_existing_access(self):
        self.reader.perms["models"] = {self.term["key"]: "read"}
        r = self.c.get("/api/knowledge-service/sources/" + self.rev["id"])
        self.assertEqual(r.status_code, 403, r.text)

    def test_S11_historical_objects_not_leaked(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="维护", as_of="2010-01-01"),
        ).json()
        self.assertEqual(r["items"], [])
        self.assertEqual(r["citations"], [])

    async def test_S12_two_distinct_document_sources(self):
        self.p = self.admin
        original = self.did
        async with SessionLocal() as db:
            doc = Document(
                filename="参考资料.txt",
                title="参考资料",
                extracted_text=self.text,
                extract_status="ok",
            )
            db.add(doc)
            await db.flush()
            self.did = doc.id
            db.add(DocumentLink(document_id=doc.id, record_id=self.rid))
            await db.commit()
        self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "group_key": "reference",
                "label": "参考资料",
            },
        ).raise_for_status()
        self.add_claim("三天")
        self.p = self.reader
        result = self.query()
        self.assertEqual(
            {ev["document_id"] for ev in result["citations"]}, {original, self.did}
        )

    async def test_S13_model_revocation_terms_details_feedback(self):
        f = self.feedback().json()
        self.reader.perms["models"] = {}
        for path in [f"/items/{self.rid}", "/feedback/" + f["id"]]:
            self.assertIn(
                self.c.get("/api/knowledge-service" + path).status_code, (403, 404)
            )
        self.assertEqual(
            self.c.get(
                "/api/knowledge-service/terms", params={"ontology_id": self.sid}
            ).status_code,
            403,
        )

    def test_S14_foreign_feedback_run_and_record_mismatch(self):
        run = self.query()
        self.p = self.admin
        other = self.obj(dict(title="其他条目", scope="保障"))
        self.p = self.reader
        body = dict(
            run_id=run["run_id"],
            record_id=other,
            record_version=1,
            category="引用不正确",
            message="核对",
            idempotency_key=uuid4().hex,
        )
        self.assertEqual(
            self.c.post("/api/knowledge-service/feedback", json=body).status_code, 422
        )

    def test_S15_reader_cannot_template_install(self):
        r = self.c.post(
            "/api/knowledge-service/template",
            json={"key": self.key + "forged", "name": "伪造"},
        )
        self.assertEqual(r.status_code, 403, r.text)

    async def test_S16_hidden_replacement_never_revives_old_authority(self):
        self.p = self.admin
        async with SessionLocal() as db:
            doc = Document(
                filename="新规程.txt",
                title="新规程",
                extracted_text="新维护规程",
                extract_status="ok",
            )
            db.add(doc)
            await db.commit()
            new_id = doc.id
        revision = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "document_id": new_id,
                "label": "第二版",
                "effective_from": "2025-01-01",
                "supersedes_id": self.rev["id"],
            },
        )
        self.assertEqual(revision.status_code, 200, revision.text)
        self.p = self.reader
        self.assertEqual(self.query()["status"], "insufficient")

    def test_S17_original_document_entry_is_existing_route(self):
        source = self.c.get("/api/knowledge-service/sources/" + self.rev["id"]).json()
        self.assertEqual(source["document"]["url"], f"/api/documents/{self.did}/raw")

    def test_S18_run_evidence_complete_for_conflict(self):
        self.p = self.admin
        self.add_claim("四天")
        self.p = self.reader
        result = self.query(limit=1)
        run = self.c.get("/api/knowledge-service/runs/" + result["run_id"]).json()
        self.assertEqual(
            [fact["id"] for fact in run["facts"]],
            [fact["id"] for fact in result["facts"]],
        )
        self.assertEqual(len(run["facts"]) + len(run["conflict_facts"]), 2)
        self.assertTrue(
            all(
                fact["purpose"] == "conflict_evidence" for fact in run["conflict_facts"]
            )
        )
        self.assertEqual(run["status"], "conflict")

    def test_S19_ordinary_chinese_question(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="维护规程规定的维护周期是多少？"),
        ).json()
        self.assertEqual(r["status"], "supported")
        self.assertEqual(r["facts"][0]["value"], "三天")

    def test_S20_ordinary_title_question(self):
        r = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="请问维护规程有哪些要求？"),
        ).json()
        self.assertEqual(r["status"], "supported")

    def test_S21_source_scan_budget_explicit(self):
        with patch("app.knowledge_service.sources.SOURCE_BUDGET", 0, create=True):
            self.assertTrue(self.query()["incomplete"])

    def test_S22_model_boolean_offset_rejected(self):
        self.reader.perms["features"] = {"ai": True}

        async def controlled(messages, **kwargs):
            import json

            context = json.loads(messages[1]["content"])
            ev = context["evidence"][0]
            ev["start"] = False
            return dict(
                content=json.dumps(dict(answer="请参阅维护规程。", citations=[ev])),
                model="controlled",
                mock=False,
                truncated=False,
            )

        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch(
            "app.knowledge_service.answers.ai.chat_real_meta", side_effect=controlled
        ):
            self.assertEqual(self.query(generate=True)["generation"], "error")

    async def test_S23_run_retains_all_conflict_evidence_ids(self):
        from app.knowledge_service.models import QueryRun

        self.p = self.admin
        second = self.add_claim("四天")
        self.p = self.reader
        result = self.query(limit=1)
        async with SessionLocal() as db:
            run = await db.get(QueryRun, result["run_id"])
            self.assertEqual(len(run.references["evidence_ids"]), 2)

    async def test_S24_attempted_model_version_is_auditable_on_error(self):
        from app.knowledge_service.models import QueryRun

        self.reader.perms["features"] = {"ai": True}
        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(
                enabled=True,
                api_key="test",
                base_url="https://invalid",
                model="controlled-attempt",
            ),
        ), patch(
            "app.knowledge_service.answers.ai.chat_real_meta",
            side_effect=RuntimeError("controlled failure"),
        ):
            result = self.query(generate=True)
        async with SessionLocal() as db:
            run = await db.get(QueryRun, result["run_id"])
            self.assertEqual(run.model_version, "controlled-attempt")

    def test_S25_provider_mock_fallback_never_grounded(self):
        self.reader.perms["features"] = {"ai": True}

        async def controlled(messages, **kwargs):
            import json

            ev = json.loads(messages[1]["content"])["evidence"][0]
            return dict(
                content=json.dumps(
                    dict(answer="伪装成有效JSON的本地回退", citations=[ev])
                ),
                model="controlled",
                mock=False,
                truncated=False,
                finish_reason="mock_fallback",
            )

        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch(
            "app.knowledge_service.answers.ai.chat_real_meta", side_effect=controlled
        ):
            self.assertEqual(self.query(generate=True)["generation"], "error")

    async def test_S26_generation_budget_usage_persisted(self):
        from app.knowledge_service.models import QueryRun

        self.reader.perms["features"] = {"ai": True}

        async def controlled(messages, **kwargs):
            import json

            self.assertEqual(kwargs.get("max_tokens_ceiling"), 1200)
            self.assertEqual(kwargs.get("max_retries"), 0)
            ev = json.loads(messages[1]["content"])["evidence"][0]
            return dict(
                content=json.dumps(dict(answer="受控回答", citations=[ev])),
                model="controlled",
                mock=False,
                truncated=False,
                finish_reason="stop",
                max_tokens=1200,
                retried=False,
                retry_count=0,
                usage=dict(prompt_tokens=42, completion_tokens=16, total_tokens=58),
            )

        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(enabled=True, api_key="test", base_url="https://invalid"),
        ), patch(
            "app.knowledge_service.answers.ai.chat_real_meta", side_effect=controlled
        ):
            result = self.query(generate=True)
        self.assertEqual(result["generation"], "generated")
        async with SessionLocal() as db:
            run = await db.get(QueryRun, result["run_id"])
            self.assertEqual(run.budget["generation"]["usage"]["total_tokens"], 58)
            self.assertEqual(run.budget["generation"]["max_tokens"], 1200)
            self.assertEqual(run.budget["generation"]["max_retries"], 0)

    async def test_S27_shared_ai_adapter_honors_explicit_no_retry(self):
        import inspect
        from app.services import ai

        self.assertIn("max_retries", inspect.signature(ai.chat_real_meta).parameters)
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: dict(
                choices=[dict(message={"content": ""}, finish_reason="length")],
                usage=dict(total_tokens=8),
            ),
        )
        client = AsyncMock()
        client.post.return_value = response
        manager = AsyncMock()
        manager.__aenter__.return_value = client
        cfg = dict(
            enabled=True,
            api_key="test",
            base_url="https://invalid",
            model="controlled",
            max_tokens_ceiling=2400,
            auto_retry=True,
        )
        with patch("app.services.ai.cfg_svc.get_full_config", return_value=cfg), patch(
            "app.services.ai.httpx.AsyncClient", return_value=manager
        ), patch(
            "app.services.ai.chat_mock", AsyncMock(return_value="controlled mock")
        ):
            meta = await ai.chat_real_meta(
                [dict(role="user", content="synthetic")],
                max_tokens=1200,
                max_tokens_ceiling=1200,
                max_retries=0,
            )
        self.assertEqual(client.post.await_count, 1)
        self.assertFalse(meta["retried"])
        self.assertEqual(meta["finish_reason"], "mock_fallback")

    async def test_S28_query_budget_does_not_count_hidden_claims(self):
        async with SessionLocal() as db:
            document = await db.get(Document, self.did)
            document.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        result = self.query()
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["budget"]["scanned"], 0)

    def _reviewer(self, models=None):
        return Principal(
            SimpleNamespace(id=91003, username="独立审核人"),
            dict(
                pages=["knowledge_service"],
                models=models or self.reader.perms["models"].copy(),
                features={"knowledge_review": True},
            ),
        )

    async def _document_revision(
        self, text=None, scope="保障", group="extra", supersedes=None, linked=True
    ):
        async with SessionLocal() as db:
            doc = Document(
                filename=group + ".txt",
                title=group,
                extracted_text=text or self.text,
                extract_status="ok",
            )
            db.add(doc)
            await db.flush()
            if linked:
                db.add(DocumentLink(document_id=doc.id, record_id=self.rid))
            await db.commit()
            did = doc.id
        response = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "document_id": did,
                "group_key": group,
                "scope": scope,
                "label": group,
                "effective_from": "2025-01-01",
                "supersedes_id": supersedes,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return did, response.json()

    def test_R01_selected_empty_type_revocation_blocks_reviewer_and_feedback(self):
        response = self.c.post(
            "/api/knowledge-service/query",
            json=dict(
                ontology_id=self.sid, type_id=self.typ["id"], question="不存在的知识"
            ),
        ).json()
        f = self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                run_id=response["run_id"],
                category="回答不完整",
                message="原始范围受限",
                idempotency_key=uuid4().hex,
            ),
        ).json()
        self.p = self._reviewer({self.term["key"]: "read"})
        for path in ["/runs/" + response["run_id"], "/feedback/" + f["id"]]:
            r = self.c.get("/api/knowledge-service" + path)
            self.assertIn(r.status_code, (403, 404), r.text)
            self.assertNotIn("原始范围受限", r.text)

    async def test_R02_ambiguous_term_dependencies_rechecked(self):
        from app.ontology.models import RecordSource

        self.p = self.admin
        ids = [
            self.obj(dict(preferred=n, aliases="手册", scope="保障"), self.term)
            for n in ("维护规程", "培训规范")
        ]
        async with SessionLocal() as db:
            db.add_all(
                [RecordSource(record_id=rid, document_id=self.did) for rid in ids]
            )
            await db.commit()
        self.p = self.reader
        run = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="手册"),
        ).json()
        self.assertEqual(run["status"], "ambiguous")
        f = self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                run_id=run["run_id"],
                category="存在分歧",
                message="术语问题",
                idempotency_key=uuid4().hex,
            ),
        ).json()
        async with SessionLocal() as db:
            doc = await db.get(Document, self.did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.p = self._reviewer()
        self.assertIn(
            self.c.get("/api/knowledge-service/runs/" + run["run_id"]).status_code,
            (403, 404),
        )
        self.assertIn(
            self.c.get("/api/knowledge-service/feedback/" + f["id"]).status_code,
            (403, 404),
        )

    async def test_R03_resolution_plaintext_never_enters_generic_audit(self):
        f = self.feedback().json()
        self.reader.perms["features"] = {"knowledge_review": True}
        secret = "引用原文不应进入通用审计"
        r = self.c.post(
            "/api/knowledge-service/feedback/" + f["id"] + "/resolve",
            json=dict(
                expected_version=1, resolution=secret, idempotency_key=uuid4().hex
            ),
        )
        self.assertEqual(r.status_code, 200, r.text)
        async with SessionLocal() as db:
            log = await db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "knowledge_feedback_resolve",
                    AuditLog.resource_id == f["id"],
                )
            )
            import json

            self.assertNotIn(secret, json.dumps(log.detail, ensure_ascii=False))
            self.assertEqual(log.detail["status"], "resolved")
        self.p = Principal(
            SimpleNamespace(id=91004, username="通用审计人"),
            dict(pages=["system"], models={}, features={"audit_view": True}),
        )
        audits = self.c.get(
            "/api/system/audit", params={"action": "knowledge_feedback_resolve"}
        )
        self.assertEqual(audits.status_code, 200, audits.text)
        self.assertNotIn(secret, audits.text)

    async def test_R04_successor_outside_scan_window_stops_old_authority(self):
        from app.knowledge_service.models import SourceRevision
        from datetime import datetime

        original_run = self.query()
        self.p = self.admin
        _, spacer = await self._document_revision(group="spacer", linked=False)
        _, replacement = await self._document_revision(
            group="maintenance", supersedes=self.rev["id"], linked=False
        )
        async with SessionLocal() as db:
            for rid, year in [
                (self.rev["id"], 2020),
                (spacer["id"], 2021),
                (replacement["id"], 2022),
            ]:
                row = await db.get(SourceRevision, rid)
                row.recorded_at = datetime(year, 1, 1)
            await db.commit()
        self.p = self.reader
        with patch("app.knowledge_service.sources.SOURCE_BUDGET", 1):
            result = self.query()
            self.assertEqual(result["facts"], [])
            item = self.c.get(f"/api/knowledge-service/items/{self.rid}").json()
            self.assertEqual(item["facts"], [])
            self.assertEqual(
                self.c.get(
                    "/api/knowledge-service/runs/" + original_run["run_id"]
                ).status_code,
                404,
            )

    def test_R05_graph_respects_depth_and_scope_at_fact_boundary(self):
        self.p = self.admin
        self.schema_relation = self.c.get("/api/ontologies/" + self.sid).json()[
            "schema"
        ]["relations"][0]["id"]
        nodes = [
            self.obj(dict(title="流程" + str(i), scope="保障", topic="维护"))
            for i in range(3)
        ]
        for a, b in zip([self.rid, *nodes], nodes):
            self.add_claim(None, rid=a, target=b)
        excluded = self.obj(dict(title="跨范围目标", scope="培训", topic="维护"))
        self.add_claim(None, target=excluded)
        self.p = self.reader
        for depth in (1, 2):
            result = self.query(depth=depth, scope="保障")
            actual = {
                (f["object_id"], f["target_id"])
                for f in result["facts"]
                if f["target_id"] is not None
            }
            expected = {(self.rid, nodes[0])}
            if depth == 2:
                expected.add((nodes[0], nodes[1]))
            self.assertEqual(actual, expected)
            self.assertNotIn(
                excluded,
                [
                    i["id"]
                    for i in self.c.get(
                        "/api/knowledge-service/runs/" + result["run_id"]
                    ).json()["items"]
                ],
            )

        self.p = self.admin
        term_target = self.obj(dict(preferred="专用术语", scope="保障"), self.term)
        self.schema_relation = self.c.get("/api/ontologies/" + self.sid).json()[
            "schema"
        ]["relations"][2]["id"]
        self.add_claim(None, target=term_target)
        self.p = self.reader
        filtered = self.query(type_id=self.typ["id"], depth=2, scope="保障")
        self.assertNotIn(
            term_target,
            [f["target_id"] for f in filtered["facts"] if f["target_id"] is not None],
        )

    async def test_R06_same_object_distinct_source_domains_do_not_conflict(self):
        self.p = self.admin
        self.c.put(
            "/api/ontologies/objects/" + str(self.rid),
            json=dict(data={"title": "维护规程", "topic": "维护"}, expected_version=1),
        ).raise_for_status()
        original = self.did
        self.did, _ = await self._document_revision(scope="培训", group="training")
        self.add_claim("四天")
        self.did = original
        self.p = self.reader
        result = self.query()
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["conflicts"], [])
        self.assertEqual({f["scope"] for f in result["facts"]}, {"保障", "培训"})
        self.assertEqual(len(self.query(scope="保障")["facts"]), 1)

    async def test_R07_run_pins_original_evidence_revision_assignment(self):
        from app.knowledge_service.models import SourceRevision
        from datetime import datetime

        result = self.query()
        original = result["citations"][0]["revision_id"]
        self.p = self.admin
        added = self.c.post(
            "/api/knowledge-service/sources",
            json={
                **self.source_payload(),
                "label": "后来登记",
                "effective_from": "2021-01-01",
            },
        ).json()
        async with SessionLocal() as db:
            row = await db.get(SourceRevision, added["id"])
            row.recorded_at = datetime(2030, 1, 1)
            await db.commit()
        self.p = self.reader
        replay = self.c.get("/api/knowledge-service/runs/" + result["run_id"])
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["citations"][0]["revision_id"], original)
        self.assertIn(original, [r["id"] for r in replay.json()["sources"]])

    def test_R08_feedback_page_stops_and_reuses_run_authorization(self):
        from app.knowledge_service import sources

        result = self.query()
        for i in range(10):
            self.c.post(
                "/api/knowledge-service/feedback",
                json=dict(
                    run_id=result["run_id"],
                    category="回答不完整",
                    message="问题" + str(i),
                    idempotency_key=uuid4().hex,
                ),
            ).raise_for_status()
        with patch(
            "app.knowledge_service.feedback.sources.selected", wraps=sources.selected
        ) as visible:
            page = self.c.get(
                "/api/knowledge-service/feedback", params={"limit": 2}
            ).json()
        self.assertEqual(len(page["items"]), 2)
        self.assertEqual(visible.await_count, 1)

    async def test_R09_source_excerpt_centers_unicode_hit(self):
        self.p = self.admin
        text = "前言😀\n" * 200 + "维护规程😀" + "补充内容" * 200
        _, revision = await self._document_revision(text=text, group="long-reference")
        self.p = self.reader
        excerpt = next(r for r in self.query()["sources"] if r["id"] == revision["id"])
        self.assertIn("维护规程", excerpt["quote"])
        self.assertGreater(excerpt["start"], 0)
        self.assertEqual(text[excerpt["start"] : excerpt["end"]], excerpt["quote"])

    async def test_R10_optional_vector_recall_rerank_authorized_candidates_only(self):
        from app.knowledge_service import retrieval

        self.assertTrue(hasattr(retrieval, "ranking"))
        from app.ontology.models import RecordSource
        import json

        self.p = self.admin
        recalled = self.obj(dict(title="设备保养", scope="保障", topic="维护"))
        self.add_claim("五天", rid=recalled)
        hidden = self.obj(dict(title="禁止发送的对象", scope="保障", topic="维护"))
        self.add_claim("秘密周期", rid=hidden)
        async with SessionLocal() as db:
            doc = Document(
                filename="hidden.txt", extracted_text="禁止发送", extract_status="ok"
            )
            db.add(doc)
            await db.flush()
            db.add(RecordSource(record_id=hidden, document_id=doc.id))
            await db.commit()
        self.p = self.reader
        self.reader.perms["features"] = {"ai": True}

        async def embed(texts, **kwargs):
            self.assertNotIn("禁止发送", " ".join(texts))
            return [[1.0, 0.0] if "设备保养" in t else [0.8, 0.6] for t in texts]

        async def rerank(messages, **kwargs):
            serialized = json.dumps(messages, ensure_ascii=False)
            self.assertNotIn("禁止发送", serialized)
            return dict(
                content=json.dumps(
                    {
                        "items": [
                            {"id": recalled, "score": 1.0},
                            {"id": self.rid, "score": 0.2},
                        ]
                    }
                ),
                mock=False,
                truncated=False,
                finish_reason="stop",
                model="controlled-ranker",
                usage={"total_tokens": 40},
                max_tokens=512,
                retry_count=0,
                retried=False,
            )

        cfg = dict(
            embedding_enabled=True,
            rerank_enabled=True,
            embedding_model="controlled-vector",
            model="controlled-ranker",
        )
        with patch(
            "app.knowledge_service.ranking.configuration", return_value=cfg
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_query",
            AsyncMock(return_value=[1.0, 0.0]),
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_texts", side_effect=embed
        ), patch(
            "app.knowledge_service.ranking.ai.chat_real_meta", side_effect=rerank
        ):
            result = self.query()
        self.assertEqual(result["items"][0]["id"], recalled)
        self.assertNotIn(hidden, [r["id"] for r in result["items"]])
        self.assertEqual(result["budget"]["ranking"]["status"], "ranked")
        self.assertLessEqual(result["budget"]["ranking"]["candidate_count"], 50)

    def test_R11_template_preview_failure_is_retryable(self):
        self.p = self.admin
        payload = dict(key=self.key + "retry", name="可重试空间")
        with patch(
            "app.knowledge_service.template.KnowledgeSpace",
            side_effect=RuntimeError("controlled registration failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.c.post("/api/knowledge-service/template", json=payload)
        retry = self.c.post("/api/knowledge-service/template", json=payload)
        self.assertEqual(retry.status_code, 200, retry.text)

    async def test_R12_replay_diagnostics_safe_for_changed_source_permissions(self):
        self.p = self.admin
        original = self.did
        self.did, _ = await self._document_revision(
            text="财务制度😀\n财务值", group="unmatched", linked=False
        )
        other = self.obj(dict(title="财务规则", scope="保障", topic="维护"))
        candidate = self.c.post(
            "/api/ontologies/" + self.sid + "/claims",
            json=dict(
                object_id=other,
                predicate_id=self.typ["fields"][1]["id"],
                value="财务值",
                evidence=[
                    dict(document_id=self.did, quote="财务制度😀", start=0, end=5)
                ],
            ),
        ).json()
        self.c.post(
            "/api/ontologies/claims/" + candidate["id"] + "/review",
            json=dict(action="accept", expected_version=1),
        ).raise_for_status()
        self.did = original
        self.p = self.reader
        self.reader.perms["pages"].append("library")
        run = self.query()
        self.assertGreater(run["budget"]["scanned"], 1)
        self.p = self._reviewer()
        replay = self.c.get("/api/knowledge-service/runs/" + run["run_id"])
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertNotIn("scanned", replay.json()["budget"])
        self.assertNotIn("generation", replay.json()["budget"])
        self.p = self.reader
        self.reader.perms["pages"].remove("library")
        own_replay = self.c.get("/api/knowledge-service/runs/" + run["run_id"])
        self.assertEqual(own_replay.status_code, 200, own_replay.text)
        self.assertNotIn("scanned", own_replay.json()["budget"])

    def test_R13_real_stable_field_rename_preserves_roles_alias_and_scope(self):
        import copy

        self.p = self.admin
        self.obj(
            dict(
                preferred="维护规程",
                aliases="保养手册",
                definition="维护说明",
                scope="保障",
            ),
            self.term,
        )
        schema = copy.deepcopy(
            self.c.get("/api/ontologies/" + self.sid).json()["schema"]
        )
        changes = {
            "scope": "audience",
            "summary": "abstract",
            "preferred": "label",
            "aliases": "synonyms",
            "definition": "meaning",
        }
        for typ in schema["types"]:
            for field in typ["fields"]:
                field["key"] = changes.get(field["key"], field["key"])
        rev = self.c.post(
            "/api/ontologies/" + self.sid + "/revisions", json={"schema": schema}
        ).json()
        plan = self.c.post(
            f"/api/ontologies/{self.sid}/revisions/{rev['id']}/plan", json={}
        ).json()
        published = self.c.post("/api/ontologies/changes/" + plan["id"] + "/confirm")
        self.assertEqual(published.status_code, 200, published.text)
        self.p = self.reader
        result = self.query(scope="保障")
        self.assertEqual(result["status"], "supported")
        item = next(i for i in result["items"] if i["id"] == self.rid)
        self.assertEqual(item["summary"], "维护周期")
        self.assertEqual(item["scope"], "保障")
        self.assertEqual(item["data"]["audience"], "保障")
        alias = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="保养手册", scope="保障"),
        ).json()
        self.assertEqual(alias["status"], "supported")
        self.assertEqual(alias["terms"][0]["preferred"], "维护规程")

    async def test_R14_history_51st_row_marks_incomplete(self):
        from app.ontology.models import ObjectHistory

        async with SessionLocal() as db:
            db.add_all(
                [
                    ObjectHistory(
                        record_id=self.rid,
                        version=i,
                        revision_id=self.confirm.json()["revision_id"],
                        data={"title": "历史维护规程"},
                    )
                    for i in range(2, 53)
                ]
            )
            await db.commit()
        item = self.c.get(f"/api/knowledge-service/items/{self.rid}").json()
        self.assertEqual(len(item["history"]), 50)
        self.assertTrue(item["incomplete"])

    async def test_R15_revision_pagination_caps_public_results(self):
        from app.knowledge_service.models import SourceRevision

        async with SessionLocal() as db:
            db.add_all(
                [
                    SourceRevision(
                        ontology_id=self.sid,
                        document_id=self.did,
                        snapshot_id=self.rev["snapshot_id"],
                        source_sha=self.rev["source_sha"],
                        group_key="batch",
                        label="修订" + str(i),
                        scope="保障",
                        topic="维护",
                        effective_from="2020-01-01",
                        actor="local",
                    )
                    for i in range(55)
                ]
            )
            await db.commit()
        page = self.c.get(
            "/api/knowledge-service/sources",
            params=dict(ontology_id=self.sid, limit=50, offset=0),
        ).json()
        self.assertEqual(len(page["items"]), 50)
        self.assertTrue(page["incomplete"])
        more = self.c.get(
            "/api/knowledge-service/sources",
            params=dict(ontology_id=self.sid, limit=50, offset=50),
        ).json()
        self.assertEqual(len(more["items"]), 6)

    async def test_R16_item_fact_cap_and_truncation(self):
        from app.ontology.models import Claim

        async with SessionLocal() as db:
            db.add_all(
                [
                    Claim(
                        ontology_id=self.sid,
                        revision_id=self.confirm.json()["revision_id"],
                        type_id=self.typ["id"],
                        object_id=self.rid,
                        predicate_id=self.typ["fields"][1]["id"],
                        value="三天",
                        evidence_ids=self.claim["evidence_ids"],
                        extractor="manual/1",
                        status="accepted",
                        version=2,
                    )
                    for _ in range(55)
                ]
            )
            await db.commit()
        item = self.c.get(f"/api/knowledge-service/items/{self.rid}").json()
        self.assertLessEqual(len(item["facts"]), 50)
        self.assertTrue(item["incomplete"])

    def test_R17_scalar_identifiers_have_chinese_422(self):
        c = TestClient(app, raise_server_exceptions=False)
        for value in ({"bad": "id"}, ["bad"], True, 123):
            r = c.post(
                "/api/knowledge-service/feedback",
                json=dict(
                    run_id=value,
                    category="回答不完整",
                    message="核对",
                    idempotency_key=uuid4().hex,
                ),
            )
            self.assertEqual(r.status_code, 422, r.text)
        self.p = self.admin
        for value in ({"bad": "id"}, ["bad"], True, 123):
            r = c.post(
                "/api/knowledge-service/sources",
                json={**self.source_payload(), "supersedes_id": value},
            )
            self.assertEqual(r.status_code, 422, r.text)

    def test_R18_catalog_propagates_source_truncation(self):
        with patch("app.knowledge_service.sources.SOURCE_BUDGET", 0):
            catalog = self.c.get("/api/knowledge-service/catalog").json()
        self.assertTrue(catalog["incomplete"])

    def test_R19_ambiguity_keeps_scan_truncation(self):
        self.p = self.admin
        for name in ("维护规程", "培训规程", "保障规程"):
            self.obj(dict(preferred=name, aliases="手册", scope="保障"), self.term)
        self.p = self.reader
        with patch("app.knowledge_service.retrieval.OBJECT_BUDGET", 2):
            result = self.c.post(
                "/api/knowledge-service/query",
                json=dict(ontology_id=self.sid, question="手册"),
            ).json()
        self.assertEqual(result["status"], "ambiguous")
        self.assertTrue(result["incomplete"])

    async def test_R20_hidden_predecessor_id_redacted_everywhere(self):
        self.p = self.admin
        _, replacement = await self._document_revision(
            group="maintenance", supersedes=self.rev["id"]
        )
        async with SessionLocal() as db:
            doc = await db.get(Document, self.did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.p = self.reader
        detail = self.c.get(
            "/api/knowledge-service/sources/" + replacement["id"]
        ).json()
        self.assertIsNone(detail["supersedes_id"])
        listing = self.c.get(
            "/api/knowledge-service/sources", params={"ontology_id": self.sid}
        ).json()
        self.assertTrue(all(r["supersedes_id"] is None for r in listing["items"]))
        self.assertTrue(
            all(r["supersedes_id"] is None for r in self.query()["sources"])
        )

    def test_R21_conflict_sampling_has_bounded_memory(self):
        from app.knowledge_service import retrieval

        self.assertTrue(hasattr(retrieval, "conflict_sample"))
        import tracemalloc

        facts = [
            dict(
                id=str(i),
                object_id=1,
                predicate_id="p",
                value=i,
                target_id=None,
                scope="保障",
                scopes=["保障"],
            )
            for i in range(2000)
        ]
        tracemalloc.start()
        pairs, found = retrieval.conflict_sample(facts)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertTrue(found)
        self.assertLessEqual(len(pairs), 50)
        self.assertLess(peak, 8_000_000)

    async def test_R22_alias_term_not_in_limited_items_still_revokes_run(self):
        from app.ontology.models import RecordSource

        self.p = self.admin
        tid = self.obj(
            dict(preferred="维护规程", aliases="保养手册", scope="保障"), self.term
        )
        async with SessionLocal() as db:
            doc = Document(
                filename="词表依据.txt", extracted_text="词表依据", extract_status="ok"
            )
            db.add(doc)
            await db.flush()
            db.add(RecordSource(record_id=tid, document_id=doc.id))
            db.add(DocumentLink(record_id=tid, document_id=doc.id))
            await db.commit()
            did = doc.id
        self.p = self.reader
        run = self.c.post(
            "/api/knowledge-service/query",
            json=dict(ontology_id=self.sid, question="保养手册", limit=1),
        ).json()
        self.assertNotIn(tid, [i["id"] for i in run["items"]])
        async with SessionLocal() as db:
            doc = await db.get(Document, did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.assertIn(
            self.c.get("/api/knowledge-service/runs/" + run["run_id"]).status_code,
            (403, 404),
        )

    async def test_R23_relation_not_in_limited_facts_still_revokes_feedback(self):
        from app.knowledge_service.models import SourceRevision
        from datetime import datetime

        self.p = self.admin
        self.schema_relation = self.c.get("/api/ontologies/" + self.sid).json()[
            "schema"
        ]["relations"][0]["id"]
        original = self.did
        edges = []
        for i in range(3):
            self.did, _ = await self._document_revision(
                text="维护规程😀\n关系依据", group="edge" + str(i)
            )
            target = self.obj(
                dict(title="相关规范" + str(i), scope="保障", topic="维护")
            )
            claim = self.add_claim(None, target=target)
            edges.append((claim["id"], self.did))
        self.did = original
        async with SessionLocal() as db:
            row = await db.get(SourceRevision, self.rev["id"])
            row.recorded_at = datetime(2020, 1, 1)
            await db.commit()
        self.p = self.reader
        run = self.query(depth=1, limit=1)
        f = self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                run_id=run["run_id"],
                category="回答不完整",
                message="关系需要核对",
                idempotency_key=uuid4().hex,
            ),
        ).json()
        selected = {item["id"] for item in run["facts"]}
        _, did = next(edge for edge in edges if edge[0] not in selected)
        async with SessionLocal() as db:
            doc = await db.get(Document, did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.assertIn(
            self.c.get("/api/knowledge-service/feedback/" + f["id"]).status_code,
            (403, 404),
        )

    async def test_R24_item_only_feedback_rechecks_original_documentary_sources(self):
        f = self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                record_id=self.rid,
                record_version=1,
                category="引用不正确",
                message="条目原文问题",
                idempotency_key=uuid4().hex,
            ),
        )
        self.assertEqual(f.status_code, 200, f.text)
        async with SessionLocal() as db:
            doc = await db.get(Document, self.did)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        self.assertIn(
            self.c.get("/api/knowledge-service/feedback/" + f.json()["id"]).status_code,
            (403, 404),
        )

    def test_R25_foreign_rerank_id_cannot_enter_retrieval(self):
        self.reader.perms["features"] = {"ai": True}
        import json

        meta = dict(
            content=json.dumps({"items": [{"id": 999999, "score": 1.0}]}),
            mock=False,
            truncated=False,
            finish_reason="stop",
        )
        cfg = dict(
            embedding_enabled=True,
            rerank_enabled=True,
            embedding_model="controlled",
            model="controlled",
        )
        with patch(
            "app.knowledge_service.ranking.configuration", return_value=cfg
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_query",
            AsyncMock(return_value=[1.0, 0.0]),
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_texts",
            AsyncMock(return_value=[[1.0, 0.0]]),
        ), patch(
            "app.knowledge_service.ranking.ai.chat_real_meta",
            AsyncMock(return_value=meta),
        ):
            result = self.query()
        self.assertEqual(result["budget"]["ranking"]["status"], "error")
        self.assertNotIn(999999, [item["id"] for item in result["items"]])

    async def test_R26_vector_candidate_and_text_budget_is_hard(self):
        from app.knowledge_service import ranking

        self.reader.perms["features"] = {"ai": True}
        candidates = [dict(id=i + 1, text="测试内容" * 500) for i in range(51)]

        async def embed(texts, **kwargs):
            self.assertEqual(len(texts), 50)
            self.assertTrue(all(len(text) <= 512 for text in texts))
            return [[1.0, 0.0] for _ in texts]

        budget = {}
        with patch(
            "app.knowledge_service.ranking.configuration",
            return_value=dict(embedding_enabled=True, rerank_enabled=False),
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_query",
            AsyncMock(return_value=[1.0, 0.0]),
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_texts", side_effect=embed
        ):
            _, _, deps = await ranking.rank(
                self.reader, "维护问题", candidates, set(), budget
            )
        self.assertEqual(len(deps), 50)
        self.assertTrue(budget["ranking"]["truncated"])
        self.assertLessEqual(budget["ranking"]["input_characters"], 32000)

    async def test_R27_generation_input_budget_blocks_oversized_payload(self):
        from app.knowledge_service import answers

        self.reader.perms["features"] = {"ai": True}
        result = self.query()
        result["citations"] = [
            dict(id="synthetic-" + str(i), quote="证据" * 4096, start=0, end=8192)
            for i in range(5)
        ]
        request = dict(question="维护问题", generate=True)
        model = AsyncMock()
        with patch(
            "app.knowledge_service.answers.model_config",
            return_value=dict(
                enabled=True,
                api_key="test",
                base_url="https://invalid",
                model="controlled",
            ),
        ), patch("app.knowledge_service.answers.ai.chat_real_meta", model):
            await answers.generate(self.reader, request, result)
        self.assertEqual(model.await_count, 0)
        self.assertEqual(result["generation"], "error")

    async def test_T201_excerpt_anchor_outside_display_revokes_run_and_feedback(self):
        from app.ontology.models import RecordSource
        from app.knowledge_service.models import SourceRevision
        from datetime import datetime

        self.p = self.admin
        anchor = self.obj(
            dict(title="维护规程补充", summary="罕见锚点", scope="保障", topic="维护")
        )
        async with SessionLocal() as db:
            doc = Document(
                filename="锚点对象来源.txt",
                extracted_text="受控对象来源",
                extract_status="ok",
            )
            db.add(doc)
            await db.flush()
            db.add(DocumentLink(document_id=doc.id, record_id=anchor))
            db.add(RecordSource(document_id=doc.id, record_id=anchor))
            await db.commit()
            anchor_doc = doc.id
        _, excerpt_revision = await self._document_revision(
            text="公开资料：罕见锚点及补充说明。", group="anchor-excerpt"
        )
        async with SessionLocal() as db:
            row = await db.get(SourceRevision, excerpt_revision["id"])
            row.recorded_at = datetime(2019, 1, 1)
            await db.commit()
        self.p = self.reader
        result = self.query(limit=1)
        self.assertEqual(result["sources"][0]["id"], excerpt_revision["id"])
        self.assertNotIn(anchor, [item["id"] for item in result["items"]])
        f = self.c.post(
            "/api/knowledge-service/feedback",
            json=dict(
                run_id=result["run_id"],
                category="回答不完整",
                message="摘录来源需要核对",
                idempotency_key=uuid4().hex,
            ),
        ).json()
        async with SessionLocal() as db:
            doc = await db.get(Document, anchor_doc)
            doc.deleted_at = __import__("datetime").datetime.now()
            await db.commit()
        for path in ["/runs/" + result["run_id"], "/feedback/" + f["id"]]:
            response = self.c.get("/api/knowledge-service" + path)
            self.assertIn(response.status_code, (403, 404), response.text)
            self.assertNotIn("摘录来源需要核对", response.text)

    def _semantic_public_selection(self):
        import json

        self.p = self.admin
        candidate = self.obj(dict(title="季度预算", scope="保障", topic="维护"))
        self.add_claim("四百", rid=candidate)
        self.p = self.reader
        self.reader.perms["features"] = {"ai": True}

        async def embed(texts, **kwargs):
            return [[0.0, 1.0] if "季度预算" in text else [1.0, 0.0] for text in texts]

        meta = dict(
            content=json.dumps({"items": [{"id": self.rid, "score": 1.0}]}),
            mock=False,
            truncated=False,
            finish_reason="stop",
            model="controlled-public-selection",
        )
        cfg = dict(
            embedding_enabled=True,
            rerank_enabled=True,
            embedding_model="controlled",
            model="controlled-public-selection",
        )
        with patch(
            "app.knowledge_service.ranking.configuration", return_value=cfg
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_query",
            AsyncMock(return_value=[1.0, 0.0]),
        ), patch(
            "app.knowledge_service.ranking.embedding.embed_texts", side_effect=embed
        ), patch(
            "app.knowledge_service.ranking.ai.chat_real_meta",
            AsyncMock(return_value=meta),
        ):
            result = self.query(limit=1)
        self.assertEqual([item["id"] for item in result["items"]], [self.rid])
        self.assertEqual([fact["value"] for fact in result["facts"]], ["三天"])
        return result, candidate

    def test_T202_replay_preserves_selected_arrays_and_limit(self):
        result, candidate = self._semantic_public_selection()
        response = self.c.get("/api/knowledge-service/runs/" + result["run_id"])
        self.assertEqual(response.status_code, 200, response.text)
        replay = response.json()
        for key in ("items", "facts", "citations", "sources"):
            self.assertEqual(
                [item["id"] for item in replay[key]],
                [item["id"] for item in result[key]],
                key,
            )
            self.assertLessEqual(len(replay[key]), result["budget"]["result_limit"])
        self.assertEqual(replay["relations"], result["relations"])
        self.assertEqual(replay["terms"], result["terms"])
        for old, new in zip(result["sources"], replay["sources"]):
            self.assertEqual(
                (old["snapshot_id"], old["start"], old["end"], old["quote"]),
                (new["snapshot_id"], new["start"], new["end"], new["quote"]),
            )
        self.assertNotIn(candidate, [item["id"] for item in replay["items"]])

    async def test_T203_replay_preserves_semantic_ranking_order(self):
        saved = {}
        original = self.query

        def track(**kwargs):
            result = original(**kwargs)
            saved["result"] = result
            return result

        self.query = track
        try:
            await self.test_R10_optional_vector_recall_rerank_authorized_candidates_only()
        finally:
            self.query = original
        result = saved["result"]
        replay = self.c.get("/api/knowledge-service/runs/" + result["run_id"]).json()
        self.assertEqual(
            [item["id"] for item in replay["items"]],
            [item["id"] for item in result["items"]],
        )
        self.assertEqual(
            [fact["id"] for fact in replay["facts"]],
            [fact["id"] for fact in result["facts"]],
        )

    def test_T204_feedback_uses_original_public_item_set(self):
        result, candidate = self._semantic_public_selection()
        base = dict(
            run_id=result["run_id"],
            record_version=1,
            category="回答不完整",
            message="核对该条目",
        )
        selected = self.c.post(
            "/api/knowledge-service/feedback",
            json={**base, "record_id": self.rid, "idempotency_key": uuid4().hex},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        not_selected = self.c.post(
            "/api/knowledge-service/feedback",
            json={**base, "record_id": candidate, "idempotency_key": uuid4().hex},
        )
        self.assertEqual(not_selected.status_code, 422, not_selected.text)

    def test_T205_replay_retains_original_item_version_after_edit(self):
        result = self.query()
        original = result["items"][0]
        self.p = self.admin
        self.c.put(
            "/api/ontologies/objects/" + str(self.rid),
            json=dict(
                data=dict(
                    title="维护规程新版",
                    summary="维护周期已调整",
                    scope="保障",
                    topic="维护",
                ),
                expected_version=original["version"],
            ),
        ).raise_for_status()
        self.p = self.reader
        current = self.c.get("/api/knowledge-service/items/" + str(self.rid)).json()
        self.assertGreater(current["version"], original["version"])
        replay = self.c.get("/api/knowledge-service/runs/" + result["run_id"])
        self.assertEqual(replay.status_code, 200, replay.text)
        historical = replay.json()["items"][0]
        self.assertEqual(historical["version"], original["version"])
        self.assertEqual(historical["data"], original["data"])
        self.assertEqual(historical["title"], original["title"])
