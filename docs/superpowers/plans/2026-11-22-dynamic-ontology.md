# Dynamic Ontology Knowledge Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Deliver the approved first-stage loop: versioned ontology, governed objects, document evidence and reviewed facts, queryable through the workspace and AI assistant.

**Architecture:** Add a focused `backend/app/ontology/` domain. Existing EntityRecord and RelationRecord remain the authoritative instance store; published ontology definitions own their compatible schema projections. New additive tables hold immutable revisions, object versions, evidence snapshots, candidate knowledge and server-side change plans. All new actions share authorization and database write serialization. Existing notes/files remain supported, with explicit adoption of business models rather than automatic reinterpretation of old data.

**Tech Stack:** Existing FastAPI/SQLAlchemy/SQLite, Vue3/Element Plus. No new runtime dependency or external ontology vendor required.

**Spec:** docs/superpowers/specs/2026-11-22-dynamic-ontology-design.md (approved).

## Global Constraints

- Use the current managed worktree; never mount production data into test containers. Preserve the verified pre-refactor backup and create a fresh consistent backup before local backend rollout.
- First-stage functionality includes M1-M3; do not claim universal OWL reasoning, causal simulation or vendor OntoGraph integration.
- No arbitrary SQL/Python from models or clients. Scope, result size and traversal depth are bounded.
- Stable IDs, immutable published revisions, explicit migration/impact preview, preserved legacy IDs/data, optimistic object versions and persistent idempotent confirmations.
- New schema changes are additive. Existing records are not auto-adopted, dropped or rewritten on startup. A version marker records installation; no swallowed mandatory migration failures.
- Model/page/feature permissions and source document access apply before returning any content, evidence, graph path or tool result. Deny missing/deleted sources. Imported facts never become accepted automatically.
- Preserve the five-primary navigation. Add one advanced 本体工作室 entry to 全部功能 and command search; do not re-expand the sidebar.
- Perform realistic tests against temporary databases, integration tests on a backup copy, and browser checks on separate loopback ports. Real model calls are optional user-configured product actions; automated tests use controlled model responses and no external network.

## Shared Domain Contract

Ontology schema payload:

```json
{"types":[{"id":"stable-type-id","key":"topic","name":"主题","fields":[{"id":"stable-property-id","key":"name","name":"名称","type":"text","required":true,"options":{}}]}],"relations":[{"id":"stable-relation-id","key":"supports","name":"支持","source":"stable-type-id","target":"stable-type-id","cardinality":"many-to-many"}]}
```

IDs are immutable identities; keys and labels are editable names. Missing IDs on newly added definitions are assigned on draft save; matching existing keys retain IDs, and changing a key requires retaining the previous ID. A field cannot silently acquire a new identity because a client omitted an ID. Supported data types reuse existing field types. Reference target configuration must use the current application's actual conventions.

Endpoints under `/api/ontologies` return plain JSON with existing error conventions. `GET /` lists visible spaces; `POST /` creates `{key,name,description,schema}`; `GET /{id}` returns space, revisions and current schema; `POST /{id}/revisions` and `PUT /{id}/revisions/{revision_id}` save drafts; `POST /{id}/revisions/{revision_id}/validate` returns deterministic diffs and impact/blockers; `POST /{id}/revisions/{revision_id}/plan` stores a publication plan; `GET /changes/{change_id}` previews it; `POST /changes/{change_id}/confirm` executes exactly the stored action. Static routes precede `/{id}`. The confirm body cannot replace action parameters.

`POST /from-model/{type_id}` creates an adoption draft with stable field identities and a legacy binding; internal `note` is a document/notes facility and is not auto-adopted as a business ontology type. Explain unsupported system adoption explicitly rather than pretending its specialized write paths are governed.

Object endpoints: `GET /{id}/objects`, `POST /{id}/objects` with `{type_id,data}`, `GET /objects/{record_id}`, `PUT /objects/{record_id}` with `{data,expected_version}`, and object history. Objects expose existing record ID, semantic type ID, ontology revision, object version and data. Schema changes and object changes preserve audit/history rather than overwriting the past. A missing expected version on managed updates returns 428; a stale version returns 409.

Relations are projected to existing RelationDef/RelationRecord. Definitions for managed types can be changed only by ontology publication; existing editors get an actionable 409. Binding is explicit and unique. A record/type cannot be owned by two ontologies.

Publication and later ingestion changes share a persistent `OntologyChangeSet`: id, kind, actor, payload, payload digest, ontology/base revision, data preconditions, status, expires_at, result/error and timestamps. Successful repeat confirmation returns its stored result. Expired, wrong-actor, stale-schema or changed-data plans do not write. Actual write and domain audit rows share a transaction. Serialize all relevant SQLite writers before reads/validation, with a database lock/transaction mechanism (not only a process mutex); test concurrent writers.

### Task 1: Implement ontology kernel, constraints and legacy bridge

**Files:**

- Create `backend/app/ontology/{__init__,models,schemas,validation,registry,objects,changes,policy,migrations,router}.py`. Keep units focused; introduce a small locking helper if needed.
- Modify `backend/app/models/__init__.py` only to register the additive ontology tables with Base metadata.
- Modify `backend/app/main.py` to register the ontology router and mandatory initialization marker.
- Modify `backend/app/services/entity_type.py`, `record.py`, `relation.py` for governed writes and stable schema projection. Modify their routers/schemas only for structured version/validation parameters and errors.
- Modify the existing agent payload validation to reuse central rules, preserving note formatting and confirmation behavior. Later Task 2 owns full tool integration.
- Create `backend/tests/test_ontology_kernel.py`, `test_ontology_constraints.py`; use the existing test DB guard.

**Interfaces:** `registry` handles schema validation, diff/impact, draft save and plan creation; `changes.confirm_change(db, principal, change_id)` executes stored publication plans. `objects` handles record binding/version/history. Central async record validator supports required/number/boolean/date/enum/reference/multivalue checks and is used by UI/API/import/AI paths. Required `0` and `False` are valid. Existing unchanged unknown legacy keys may be preserved, but introducing new unknown keys is rejected. Existing invalid data is reported, never silently deleted or coerced during adoption.

- [x] Write failing kernel tests first: new space/draft, valid publication creates projections; published revision immutable; property rename by stable ID preserves values and old history; lost/duplicate identity rejected; removal/type change/new required field blocks incompatible data; explicit compatible migration succeeds; legacy adoption preserves IDs; managed type old editor cannot bypass governance.

```python
assert original_record_id == migrated_record_id
assert migrated.data["budget"] == 10
assert "amount" not in migrated.data
assert old_revision.schema["types"][0]["fields"][0]["key"] == "amount"
```

- [x] Write failing constraints tests: missing required/invalid numbers/unknown new fields rejected through service, API, import and agent; zero/false accepted; references validate target existence/type; soft-deleted endpoints rejected; all four supported relation cardinalities hold; duplicate relations are idempotent, including concurrent creation.
- [x] Implement additive tables and explicit installation marker, schema normalization, deterministic impact report and authoritative projections. Preserve existing field rows for stable property IDs. Do not delete old fields first. Removed populated fields block publication unless a non-lossy explicit migration is provided. No arbitrary client migration code.
- [x] Implement persistent publication plans with current-revision and affected-data fingerprints; revalidate under the shared database writer serialization at confirmation. Repeating a confirmed plan is safe across sessions. Record snapshots only from the migration baseline onward, never fabricate historical edits. Include affected type/record/relation counts and human-readable changes.
- [x] Route normal writes, imports and AI writes through shared validation/version hooks. Preserve original note/system field behavior; JSON and CSV errors must identify invalid rows, and failed rows cannot partly mutate state. Keep unrelated legacy fields unchanged when editing a record; don't adopt malformed legacy schema automatically.
- [x] Add object list/detail/history/update APIs with permission checks and CAS. Updating the same version concurrently permits one winner. Serialize relation and schema changes so a concurrent writer cannot sneak in a new schema/cardinality violation.
- [x] Run focused RED/GREEN tests and all existing backend tests in a disposable container with no production mounts/network. Self-review, commit backend files and write full evidence to task report.

### Task 2: Implement evidence, candidate knowledge and assistant capabilities

**Files:**

- Add focused `backend/app/ontology/{evidence,knowledge,ingestion,query,capabilities}.py`; extend ontology models/schemas/router with knowledge tables and endpoints.
- Modify `backend/app/services/agent.py` and `backend/app/routers/ai.py` for principal-aware tools and persistent record-write plans. Keep transport/continuation behavior.
- Add tests `backend/tests/test_ontology_knowledge.py`, `test_ontology_agent.py` and API integration coverage.

**Interfaces:** reuse Task 1's schema and changeset contracts. Evidence contains document ID, immutable source SHA/text/parse identity, exact quote offsets, snapshot ID, original optional chunk ID, creation actor/time. Claims contain ontology/type/object/predicate/value or target, evidence IDs, confidence (extractor score), status, effective interval, recorded time and conflict/supersession links. Objects reference original records, never duplicate authoritative data.

Endpoints: `GET /{id}/claims`, `POST /{id}/claims` (candidate only), `POST /claims/{claim_id}/review` (accept/reject/dispute/supersede with expected version); `GET /evidence/{id}`; `GET/POST /{id}/ingestions` (source document ID, extractor mode); `GET /ingestions/{job_id}`; `POST /ingestions/{job_id}/plan` creates reviewed ingestion publication changes; `POST /{id}/query` returns bounded facts/objects/evidence/path and explicit conflicts/unknown status. `GET /capabilities` exposes available typed read and proposed-write capabilities.

- [ ] Write RED tests for an exact supported quote creating a candidate, rejecting fabricated quotes/out-of-range offsets and wrong types, source/model access denial before serialization, immutable evidence after source re-chunking, withdrawn/deleted source denial, two contradictory accepted claims retained and flagged, and time filtering.
- [ ] Implement source snapshots and exact evidence verification. Permission must be checked on every read, including historical snapshots. A claim's evidence cannot be swapped after acceptance. Re-review uses version checks. A model's confidence is never asserted as objective truth.
- [ ] Implement persistent ingestion jobs and explicit manual/AI extractor modes. Deterministic/manual candidate input must work with no configured model; AI mode must clearly return not-configured and never call mock answer fallbacks. AI responses use the selected published schema and exact quotes and remain candidates. Record input hash, parser/extractor/schema versions, bounded text/model budgets and any truncation/unsupported size. Duplicate input/version requests must not duplicate published objects or facts. Exact source identifiers may reuse an object; same-name ambiguity produces a review item and never silently merges.
- [ ] Implement ingestion plans that show proposed objects, relationships and claims before publication. Confirmation validates schema/data/source preconditions and writes projections/facts/audit atomically. Partial failures roll back; repeated confirmation and process restart do not duplicate effects.
- [ ] Implement bounded query service: type/property filters, text, claim status/effective time, depth 0-2 and result cap (maximum 50). Apply permissions before graph expansion and returned aggregates; distinguish evidence, conflict and absent evidence. Return stable citations with source/quote/location. Reuse existing document FTS/vector context where appropriate, but never invent a generated answer when AI is not configured.
- [ ] Register principal-aware assistant tools for ontology discovery, object/fact/evidence query and proposed changes. Fix existing document/gene tools bypassing source permissions. Replace frontend-trusted record confirmations with server change IDs while retaining legacy read interactions. Agent proposals must bind actor, arguments, object version, expiry and idempotency; confirmations only execute stored arguments and fail if edited since preview. Update frontend contract in Task 3.
- [ ] Test controlled extraction model responses without network, malformed model output, source access, contradictory facts, repeated ingestion, concurrent confirmations, stale plans, persistent run records and AI-disabled behavior. Run backend suite and commit with detailed evidence.

### Task 3: Implement the ontology studio and integrated assistant experience

**Files:**

- Create focused `frontend/src/views/ontology/OntologyWorkspace.vue` and components for ontology list, type/property/relationship editor, revision/impact plan, objects/history, ingestion review and facts/evidence/query.
- Create `frontend/src/api/ontology.js`; add route `/ontology` to router and one advanced catalog entry. Extend useNavItems permission mapping and tests without increasing primary navigation.
- Adapt existing record editors/API wrappers to send the loaded managed object version; legacy records continue their existing flow. Adapt AgentChat confirmation to stored change IDs, preserving previews/continuation.
- Add meaningful frontend behavior tests for schema editor construction and plan/evidence formatting; use browser for integrated interactions.

- [ ] Test editor state before implementation: stable IDs survive rename/reorder; new fields get stable identity from save; invalid duplicate keys/types/cardinalities fail; object version travels with save; review confirmations send only change ID and expected review version.
- [ ] Build a visual type/property/relation editor plus optional advanced JSON input. Labels are business concepts, not internal table names. Explain draft/current/history and show real validation blockers, changed fields and affected counts before publish. A default sample is user-created through an explicit button, not silently seeded into their live ontology.
- [ ] Add object browsing/edit/history with stale-version error and reload action, and record navigation without breaking existing editors. Governance redirects from old managed model editor point to 本体工作室.
- [ ] Add document selection, manual exact-quote candidate entry and AI extraction action with real status/error; display proposed objects/claims and evidence; review/confirm through stored plans. Accept/reject/dispute actions must be explicit. Facts expose source links and pinned quote/location, conflict/time status and history.
- [ ] Add evidence-based query/exploration UI and integrate ontology capability tool names/citations into existing AI assistant. No fake AI responses, invented provenance, silent auto-publish, or unreachable decorative controls. Preserve the compact daily home and mobile/dark/keyboard behavior.
- [ ] Run frontend tests/build and end-to-end API/browser loop on a fresh backup copy: create two types/relation, publish, import a document, create/extract candidates, preview/confirm, query exact evidence, revise a field key with data migration, verify object CAS and old evidence, reject invalid/unprivileged writes. Use controlled fixtures for deterministic tests; actual provider call remains optional.
- [ ] Create a new consistent production backup before rollout, verify restored-copy migration and all old counts/IDs/files, run whole-branch review, then apply additive backend/frontend builds locally with existing data/config. Retain prior images, export new schema metadata and document rollback limits after new writes. Verify health/version/API and original flows; never replace live DB with a test database.
