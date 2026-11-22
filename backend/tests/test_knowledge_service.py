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
        self.assertEqual(len(run["facts"]), 2)
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
