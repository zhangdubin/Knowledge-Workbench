import unittest
from uuid import uuid4

import _guard

_guard.use_temp_db()
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

_guard.assert_test_db()


class Kernel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def test_publish_repeat_and_rename(self):
        client = TestClient(app)
        root = "/api/ontologies"
        key = "t" + uuid4().hex
        schema = {
            "types": [
                {
                    "key": key,
                    "name": "Test",
                    "fields": [{"key": "amount", "name": "Amount", "type": "number"}],
                }
            ],
            "relations": [],
        }
        response = client.post(
            root + "/", json={"key": key, "name": "Test", "schema": schema}
        )
        self.assertEqual(response.status_code, 200, response.text)
        space = response.json()
        url = f"{root}/{space['id']}"
        rev = space["revisions"][0]

        def publish(revision):
            plan = client.post(f"{url}/revisions/{revision}/plan", json={})
            self.assertEqual(plan.status_code, 200, plan.text)
            confirm = f"{root}/changes/{plan.json()['id']}/confirm"
            result = client.post(confirm)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(client.post(confirm).json(), result.json())

        publish(rev["id"])
        schema = rev["schema"]
        obj = client.post(
            url + "/objects",
            json={"type_id": schema["types"][0]["id"], "data": {"amount": 10}},
        )
        self.assertEqual(obj.status_code, 200, obj.text)
        schema["types"][0]["fields"][0]["key"] = "budget"
        next_rev = client.post(url + "/revisions", json={"schema": schema}).json()
        publish(next_rev["id"])
        detail = client.get(f"{root}/objects/{obj.json()['id']}").json()
        self.assertEqual(detail["data"], {"budget": 10})
        self.assertEqual(
            client.put(
                f"{url}/revisions/{rev['id']}", json={"schema": schema}
            ).status_code,
            409,
        )

    async def test_adoption_migration_and_competing_writes(self):
        import asyncio
        from copy import deepcopy
        from app.database import SessionLocal
        from app.models import EntityType, FieldDefinition, EntityRecord
        from app.services.auth import Principal, current_principal
        from sqlalchemy import select

        key = "m" + uuid4().hex
        async with SessionLocal() as db:
            et = EntityType(key=key, name="Legacy")
            db.add(et)
            await db.flush()
            f = FieldDefinition(
                entity_type_id=et.id, key="amount", name="Amount", type="number"
            )
            rec = EntityRecord(
                entity_type_id=et.id, data={"amount": 10, "extension": "keep"}
            )
            db.add_all([f, rec])
            await db.commit()
            tid, fid, rid = et.id, f.id, rec.id
        root = "/api/ontologies"
        client = TestClient(app)
        space = client.post(f"{root}/from-model/{tid}").json()
        url = f"{root}/{space['id']}/revisions"

        def plan(rev, migration=None):
            return client.post(
                f"{url}/{rev['id']}/plan", json={"migration": migration or {}}
            )

        def confirm(plan):
            return client.post(f"{root}/changes/{plan.json()['id']}/confirm")

        original = space["revisions"][0]
        self.assertEqual(confirm(plan(original)).status_code, 200)
        schema = deepcopy(original["schema"])
        fields = schema["types"][0]["fields"]
        fields.append(
            {
                "id": "p-" + key,
                "key": "flag",
                "name": "Flag",
                "type": "boolean",
                "required": True,
            }
        )
        rev = client.post(url, json={"schema": schema}).json()
        self.assertEqual(plan(rev).status_code, 409)
        planned = plan(rev, {"defaults": {"p-" + key: False}})
        self.assertEqual(planned.status_code, 200, planned.text)
        obj_url = f"{root}/objects/{rid}"
        self.assertEqual(
            client.put(obj_url, json={"data": {"amount": 11}}).status_code, 428
        )

        def edit(n):
            return client.put(
                obj_url, json={"data": {"amount": n}, "expected_version": 1}
            ).status_code

        winners = await asyncio.gather(
            asyncio.to_thread(edit, 11), asyncio.to_thread(edit, 12)
        )
        self.assertEqual(sorted(winners), [200, 409])
        self.assertEqual(confirm(planned).status_code, 409)
        self.assertEqual(
            confirm(plan(rev, {"defaults": {"p-" + key: False}})).status_code, 200
        )
        current = client.get(obj_url).json()
        self.assertEqual(current["data"]["extension"], "keep")
        self.assertIs(current["data"]["flag"], False)
        self.assertEqual(current["version"], 3)
        history = client.get(obj_url + "/history").json()
        self.assertEqual(history[0]["data"], {"amount": 10, "extension": "keep"})
        async with SessionLocal() as db:
            self.assertEqual(
                await db.scalar(
                    select(FieldDefinition.id).where(
                        FieldDefinition.entity_type_id == tid,
                        FieldDefinition.key == "amount",
                    )
                ),
                fid,
            )
        app.dependency_overrides[current_principal] = lambda: Principal(
            None, {"models": {key: "none"}}
        )
        try:
            self.assertEqual(client.get(obj_url).status_code, 403)
            self.assertEqual(client.get(obj_url + "/history").status_code, 403)
            self.assertFalse(client.get(f"{root}/{space['id']}/objects").json())
        finally:
            del app.dependency_overrides[current_principal]

    async def test_reference_schema_and_property_identity(self):
        client = TestClient(app)
        root = "/api/ontologies/"
        key = "t" + uuid4().hex
        typ = {
            "key": key,
            "name": "T",
            "fields": [{"key": "ref", "type": "reference", "options": {}}],
        }
        response = client.post(
            root, json={"key": key, "name": "T", "schema": {"types": [typ]}}
        )
        self.assertEqual(response.status_code, 422)

    async def test_removal_requires_nonlossy_mapping_and_legacy_put_denied(self):
        from app.database import SessionLocal
        from app.models import EntityType, EntityRecord, FieldDefinition

        client = TestClient(app)
        async with SessionLocal() as db:
            key = "m" + uuid4().hex
            et = EntityType(key=key, name="Test")
            db.add(et)
            await db.flush()
            db.add(
                FieldDefinition(
                    entity_type_id=et.id, key="old", name="Old", type="text"
                )
            )
            rec = EntityRecord(entity_type_id=et.id, data={"old": "kept"})
            db.add(rec)
            await db.commit()
        root = "/api/ontologies"
        space = client.post(f"{root}/from-model/{et.id}").json()
        url = f"{root}/{space['id']}/revisions"
        rev = space["revisions"][0]
        initial = client.post(f"{url}/{rev['id']}/plan").json()
        self.assertEqual(
            client.post(f"{root}/changes/{initial['id']}/confirm").status_code, 200
        )
        self.assertEqual(
            client.put(
                f"/api/entity-types/{et.id}",
                json={"key": key, "name": "Edited", "fields": []},
            ).status_code,
            409,
        )
        schema = rev["schema"]
        old = schema["types"][0]["fields"][0]
        dest = "dest" + key
        schema["types"][0]["fields"] = [
            dict(key="new", name="New", type="text", id=dest)
        ]
        revision = client.post(url, json={"schema": schema}).json()
        plan_url = f"{url}/{revision['id']}/plan"
        self.assertEqual(client.post(plan_url).status_code, 409)
        response = client.post(
            plan_url, json={"migration": {"field_map": {old["id"]: dest}}}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            client.post(f"{root}/changes/{response.json()['id']}/confirm").status_code,
            200,
        )
        self.assertEqual(
            client.get(f"{root}/objects/{rec.id}").json()["data"], {"new": "kept"}
        )

    async def test_duplicate_or_lost_identity_rejected(self):
        from app.ontology.schemas import normalize
        from fastapi import HTTPException

        previous = {
            "types": [
                {
                    "id": "t",
                    "key": "topic",
                    "name": "Topic",
                    "fields": [
                        {
                            "id": "p",
                            "key": "title",
                            "type": "text",
                            "name": "Title",
                            "required": True,
                            "options": {},
                        }
                    ],
                }
            ],
            "relations": [],
        }
        from copy import deepcopy

        for mutation in ["lost", "duplicate", "replaced"]:
            schema = deepcopy(previous)
            field = schema["types"][0]["fields"][0]
            if mutation == "lost":
                del field["id"]
                field["key"] = "renamed"
            elif mutation == "duplicate":
                schema["types"][0]["fields"].append({**field, "key": "other"})
            else:
                field["id"] = "replacement"
            with self.assertRaises(HTTPException):
                normalize(schema, previous)

    async def test_lifecycle_and_paged_history(self):
        key = "l" + uuid4().hex
        client = TestClient(app)
        root = "/api/ontologies"
        space = client.post(
            root + "/",
            json={
                "key": key,
                "name": key,
                "schema": {"types": [{"key": key, "fields": []}]},
            },
        ).json()
        rev = space["revisions"][0]
        plan = client.post(f"{root}/{space['id']}/revisions/{rev['id']}/plan").json()
        self.assertEqual(
            client.post(f"{root}/changes/{plan['id']}/confirm").status_code, 200
        )
        obj = client.post(
            f"{root}/{space['id']}/objects",
            json={"type_id": rev["schema"]["types"][0]["id"], "data": {}},
        ).json()
        rid = obj["id"]
        self.assertEqual(
            client.delete(f"/api/records/{rid}?expected_version=1").status_code, 200
        )
        recycle = f"/api/recycle/records/{rid}"
        self.assertEqual(client.post(recycle + "/restore").status_code, 428)
        self.assertEqual(
            client.post(recycle + "/restore?expected_version=2").status_code, 200
        )
        self.assertEqual(client.get(f"{root}/objects/{rid}").json()["version"], 3)
        history = client.get(f"{root}/objects/{rid}/history?limit=1&offset=1").json()
        self.assertEqual([x["version"] for x in history], [2])
        self.assertEqual(
            client.delete(f"/api/records/{rid}?expected_version=3").status_code, 200
        )
        self.assertEqual(
            client.delete(recycle + "?expected_version=4").status_code, 409
        )
        summaries = client.get(root + "/?limit=1").json()
        self.assertEqual(len(summaries), 1)
        self.assertNotIn("revisions", summaries[0])

    async def test_legacy_writer_races_publication(self):
        import asyncio
        from threading import Barrier
        from app.database import SessionLocal
        from app.models import EntityType
        from sqlalchemy import select

        root = "/api/ontologies"
        key = "race" + uuid4().hex
        client = TestClient(app)
        space = client.post(
            root + "/",
            json={"key": key, "name": key, "schema": {"types": [{"key": key}]}},
        ).json()
        url = f"{root}/{space['id']}/revisions"
        rev = space["revisions"][0]
        init = client.post(f"{url}/{rev['id']}/plan").json()
        self.assertEqual(
            client.post(f"{root}/changes/{init['id']}/confirm").status_code, 200
        )
        async with SessionLocal() as db:
            type_id = await db.scalar(
                select(EntityType.id).where(EntityType.key == key)
            )
        rev["schema"]["types"][0]["fields"].append(
            {"key": "required", "type": "text", "required": True}
        )
        draft = client.post(url, json={"schema": rev["schema"]}).json()
        change = client.post(f"{url}/{draft['id']}/plan").json()
        barrier = Barrier(2)

        def write(url, body):
            barrier.wait(timeout=3)
            return client.post(url, json=body).status_code

        confirm, legacy = await asyncio.gather(
            asyncio.to_thread(write, f"{root}/changes/{change['id']}/confirm", {}),
            asyncio.to_thread(write, f"/api/records/type/{type_id}", {"data": {}}),
        )
        self.assertIn((confirm, legacy), [(200, 400), (409, 200)])

    async def test_reference_target_evolves_with_type_and_ownership_is_reserved(self):
        from copy import deepcopy

        client = TestClient(app)
        root = "/api/ontologies"
        key = "r" + uuid4().hex
        target = key + "_target"
        initial = {
            "types": [
                {"key": target, "fields": []},
                {
                    "key": key,
                    "fields": [
                        {
                            "key": "ref",
                            "type": "reference",
                            "options": {"target": target},
                        },
                        {"key": "spare", "type": "text"},
                    ],
                },
            ]
        }
        space = client.post(
            root + "/", json={"key": key, "name": key, "schema": initial}
        ).json()
        url = f"{root}/{space['id']}/revisions"

        def plan(rev):
            return client.post(f"{url}/{rev['id']}/plan")

        def confirm(rev):
            result = plan(rev)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(
                client.post(
                    f"{root}/changes/{result.json()['id']}/confirm"
                ).status_code,
                200,
            )

        rev = space["revisions"][0]
        confirm(rev)
        schema = rev["schema"]
        t, owner = schema["types"]
        obj_url = f"{root}/{space['id']}/objects"
        obj = client.post(obj_url, json={"type_id": t["id"], "data": {}}).json()
        self.assertEqual(
            client.post(
                obj_url, json={"type_id": owner["id"], "data": {"ref": obj["id"]}}
            ).status_code,
            200,
        )
        t["key"] += "_new"

        def draft(state):
            return client.post(url, json={"schema": state}).json()

        self.assertEqual(plan(draft(schema)).status_code, 409)
        owner["fields"][0]["options"]["target"] = t["key"]
        confirm(draft(schema))
        spare = owner["fields"].pop()
        moved = deepcopy(schema)
        moved["types"].append({"key": key + "_new", "fields": [spare]})
        self.assertEqual(plan(draft(moved)).status_code, 409)
        confirm(draft(schema))
        self.assertEqual(plan(draft(moved)).status_code, 409)

    async def test_adoption_authorizes_original_and_proposed_models(self):
        from app.services.auth import Principal, current_principal
        from app.database import SessionLocal
        from app.models import EntityType

        key = "a" + uuid4().hex
        newer = key + "_new"
        async with SessionLocal() as db:
            model = EntityType(key=key, name="Legacy")
            db.add(model)
            await db.commit()
        principal = Principal(
            None,
            {
                "pages": ["types"],
                "features": {"model_manage": True},
                "models": {key: "write", newer: "write"},
            },
        )
        app.dependency_overrides[current_principal] = lambda: principal
        client = TestClient(app)
        try:
            space = client.post(f"/api/ontologies/from-model/{model.id}").json()
            rev = space["revisions"][0]
            rev["schema"]["types"][0]["key"] = newer
            url = f"/api/ontologies/{space['id']}/revisions/{rev['id']}"
            self.assertEqual(
                client.put(url, json={"schema": rev["schema"]}).status_code, 200
            )
            plan = client.post(url + "/plan").json()
            principal.perms["models"][key] = "none"
            self.assertEqual(client.post(url + "/validate").status_code, 403)
            self.assertEqual(client.post(url + "/plan").status_code, 403)
            self.assertEqual(
                client.post(
                    f"/api/ontologies/changes/{plan['id']}/confirm"
                ).status_code,
                403,
            )
        finally:
            del app.dependency_overrides[current_principal]
