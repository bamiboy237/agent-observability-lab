# Agent Reliability Lab — Reviewable Build Roadmap

## Objective

Build a customer-support agent and a reliability backend that converts selected LangSmith traces into reviewed failure groups, versioned regression cases, deterministic replays, and evidence-backed recommendations.

The roadmap is intentionally divided into small checkpoints. Every checkpoint must leave the repository runnable, add one observable behavior, and produce something a reviewer can verify before work continues.

## Instructions for the implementing agent

Treat each numbered checkpoint as a separate unit of work.

1. Implement **one checkpoint only** unless the reviewer explicitly asks for more.
2. Do not begin a checkpoint until all checkpoints it depends on are accepted.
3. Add the production code, tests, fixtures, migrations, and documentation needed for that checkpoint to work.
4. Run the checkpoint's focused verification and the repository quality gate.
5. Report:
   - behavior added;
   - files changed;
   - commands run and their results;
   - the manual review procedure and expected result;
   - assumptions, deferred work, and any known limitations.
6. Stop and wait for review.

Do not combine checkpoints merely because their code is small. A checkpoint may be split further if it becomes difficult to review, but it may not silently absorb work from a later checkpoint.

### Definition of a reviewable checkpoint

A checkpoint is complete only when all of the following are true:

- **Runnable:** a clean process can import and start the application with documented configuration.
- **Observable:** the new behavior can be seen through a test, API response, CLI output, persisted row, trace fixture, or generated artifact.
- **Deterministic by default:** automated tests do not require model, LangSmith, embedding, reranking, or voice network calls.
- **Tested at a stable boundary:** tests assert outcomes rather than private implementation details.
- **Backward-safe:** all previously accepted focused tests still pass.
- **Reviewable:** the report contains a short procedure a person can run or inspect.
- **Scoped:** unrelated refactors and speculative abstractions are excluded.

### Verification levels

Every checkpoint defines a focused command. In addition, run the quality gate before requesting review:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

If a checkpoint needs PostgreSQL, mark its tests with `integration` and document the required `DATABASE_URL`. Network-dependent smoke tests must be opt-in and skipped when their credentials are absent. A network-dependent test never replaces an offline test.

### Review artifact convention

Use the smallest useful artifact for the behavior:

- API behavior: exact request, status code, and response body.
- Persistence behavior: migration state plus the relevant rows or counts.
- Pure domain behavior: focused test names and representative input/output.
- Trace behavior: a local captured span tree or sanitized fixture.
- Evaluation behavior: a versioned JSON/JSONL result with metric values.
- Workflow behavior: a state-transition or event transcript.
- Security behavior: a negative test proving disallowed data or access is rejected.

Generated review artifacts belong under `artifacts/` only when they are useful as versioned evidence. Temporary logs and credentials must not be committed.

## Scope and ownership

### Reuse

- OpenTelemetry for trace IDs, context propagation, spans, and OTLP export.
- LangSmith for trace storage, search, inspection, annotation queues, and standard evaluations. Send traces through its OTLP endpoint rather than a bespoke export client.
- LangGraph for workflow orchestration: nodes, conditional edges, retries, checkpointing, and human-in-the-loop interrupts. It must not contain raw model-call logic.
- PydanticAI for every chat or agent model call: structured output, tool calling, retries, and provider selection. It is the only place a chat-model name string may appear.
- FastAPI, PostgreSQL, pgvector, Alembic, and established clustering/statistical libraries.

### Build as adapters

- `TraceSource`, beginning with `LangSmithTraceSource`.
- Instrumentation helpers that add project-specific semantic attributes to built-in PydanticAI and LangGraph spans.
- Small provider protocols and one concrete adapter each for embeddings, reranking, transcription, and speech. Only those adapter modules may directly import their provider SDKs.

### Build as the product

- A LangSmith-independent canonical agent-event model.
- Explainable failure signatures and cross-trace grouping.
- Reviewer-confirmed failure records.
- Regression-case generation with deterministic retrieval and tool fixtures.
- Baseline/candidate replay, constraint-based comparison, and recommendations linked to evidence.

### Deferred from the MVP

- Custom telemetry ingestion/storage and a generic trace dashboard.
- Direct OTLP ingestion and ClickHouse.
- Voice, fine-tuning, multitenancy, billing, agent hosting, and automatic production changes.

## Architectural constraints

- **Model calls:** chat and agent calls go through a PydanticAI `Agent`. Domain and workflow modules never import provider chat SDKs.
- **Orchestration:** a LangGraph node calls one model adapter or one domain service and returns only the state keys it changed.
- **Offline tests:** default tests use deterministic model, retrieval, tool, trace, embedding, and voice fakes.
- **Side effects:** every external side effect must be replaceable by a recorded fixture or fake.
- **Identity:** preserve source trace/run IDs while assigning stable internal IDs.
- **Versioning:** version prompts, workflows, evaluators, fixtures, cases, and datasets.
- **Privacy:** persist identifiers and summaries by default; allowlist fields before trace persistence or case generation.
- **Review:** a predicted failure is not labeled truth until a human confirms it.
- **Experiments:** change one major variable at a time.
- **Recommendations:** never modify production automatically.

## Project layout

```text
src/app/
  main.py
  config.py
  db.py
  logging.py
  api/
  domain/
    support/
    agent/
    retrieval/
    workflow/
    traces/
    failures/
    regression/
    replay/
    voice/
scripts/
alembic/versions/
tests/
  unit/<domain>/
  integration/
  fixtures/
artifacts/
```

Keep routers thin: parse the request, call one domain service, and return the response. A domain package should gain separate `models.py`, repository/service/analyzer modules, and matching tests only as those files become necessary.

---

# MVP checkpoints

## Phase 0 — Backend foundation

**Phase outcome:** a FastAPI service starts with validated settings, migrates PostgreSQL, reports health, emits structured request logs, and passes automated checks.

### Checkpoint 0.1 — Validated application configuration

**Build**

- Keep configuration in `src/app/config.py` using `pydantic-settings`.
- Require `database_url: PostgresDsn`.
- Support `environment: local | test | production`, defaulting to `local`.
- Add optional LangSmith tracing settings, disabled by default.
- Cache `get_settings()` per process and allow FastAPI dependency overrides in tests.
- Add `.env.example` with names and safe placeholders only; ensure `.env` is ignored.

**Automated proof**

- `tests/unit/test_config.py` proves missing `DATABASE_URL` raises `ValidationError`.
- Prove valid environment values load and invalid values fail.
- Prove tracing is off by default and no secret appears in serialized/logged settings.

```bash
uv run pytest tests/unit/test_config.py -q
```

**Manual review**

- Inspect `.env.example` and confirm it contains no usable credential.
- Run a one-line settings load with a test URL and confirm the normalized environment value.

**Accept when:** invalid configuration fails before app startup and valid test configuration loads without network access.

### Checkpoint 0.2 — Database session and baseline migration

**Build**

- Configure an async SQLAlchemy engine with `pool_pre_ping=True` for Neon connections.
- Expose an `async_sessionmaker` and `get_session()` dependency.
- Configure Alembic's async template without recreating or deleting existing migration files.
- Add one baseline migration, even if it creates no product tables yet.

**Automated proof**

- An integration test opens a session and executes `SELECT 1`.
- A migration test upgrades a clean database to `head`, downgrades to `base`, and upgrades again.
- Unit tests may replace the session dependency without opening a real connection.

```bash
uv run pytest tests/integration/test_database.py -q
uv run alembic upgrade head
uv run alembic current
```

**Manual review**

- Show the Alembic current revision and the successful `SELECT 1` result against the review database.

**Accept when:** a clean database reaches `head`, the app can acquire a session, and the same migration can be reapplied from `base`.

### Checkpoint 0.3 — App factory and health endpoints

**Build**

- Implement `create_app(settings: Settings | None = None)` in `src/app/main.py`.
- Add `GET /healthz` that never touches the database.
- Add `GET /readyz` that executes `SELECT 1` and returns `503` with a stable error body when unavailable.
- Inject the session dependency so tests can provide success and failure fakes.

**Automated proof**

- `healthz` returns `200` and `{"status": "ok"}` while the database dependency is broken.
- `readyz` returns `200` for a healthy session and `503` for a database exception.

```bash
uv run pytest tests/unit/test_health.py -q
```

**Manual review**

```bash
uv run uvicorn app.main:create_app --factory
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

**Accept when:** liveness and readiness visibly have different failure semantics.

### Checkpoint 0.4 — Request IDs, structured logs, and stable errors

**Build**

- Emit JSON logs using stdlib logging plus a JSON formatter, or `structlog` if added deliberately.
- Add middleware that accepts or generates `x-request-id`, stores it on `request.state`, returns it as a response header, and includes it in request logs.
- Define a `DomainError` base with stable `code`, safe `message`, and HTTP status.
- Add one application exception handler returning `{"error": {"code": ..., "message": ...}, "request_id": ...}`.
- Do not expose raw exception text or secrets.

**Automated proof**

- A supplied request ID is preserved; a missing ID is generated.
- Structured log records and error responses contain the same request ID.
- A synthetic domain error maps to its expected status and safe body.
- A synthetic unexpected exception does not expose its message in production mode.

```bash
uv run pytest tests/unit/test_logging.py tests/unit/test_errors.py -q
```

**Manual review**

- Send one request with `x-request-id: review-0.4` and show the matching response header and JSON log record.

**Accept when:** a reviewer can correlate one request, its logs, and its safe error response by ID.

### Checkpoint 0.5 — Continuous integration quality gate

**Build**

- Add one CI workflow that installs with `uv sync --frozen` and runs Ruff, mypy, and pytest.
- Run PostgreSQL integration tests against an isolated Neon branch or another explicitly configured scratch database.
- Keep network smoke tests excluded from the default job.
- Document local commands in `README.md`.

**Automated proof**

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

**Manual review**

- Show a green CI run from a clean checkout.
- Confirm the workflow contains no committed credentials and does not target a shared production database.

**Accept when:** the exact local quality gate also runs in CI and a clean checkout passes it.

---

## Phase 1 — Deterministic support domain

**Phase outcome:** a fictional support backend performs order lookup, ticket creation, and guarded refunds without an LLM.

### Checkpoint 1.1 — Support schemas, tables, and migration

**Build**

- Add customers, orders, and tickets with SQLAlchemy declarative models.
- Use UUID primary keys and explicit constrained status values.
- Add matching Pydantic read/command schemas using `from_attributes=True` where appropriate.
- Create and review an autogenerated migration including indexes and foreign keys.
- Return Pydantic schemas outside the repository boundary, not live ORM objects.

**Automated proof**

- Schema tests reject invalid status and negative monetary values.
- Integration tests insert and read each model and prove foreign-key enforcement.
- Upgrade/downgrade migration tests still pass.

```bash
uv run pytest tests/unit/support/test_models.py tests/integration/test_support_schema.py -q
```

**Manual review**

- Inspect the migration and show one inserted order converted to its public read schema.

**Accept when:** domain constraints are enforced both during validation and in PostgreSQL where applicable.

### Checkpoint 1.2 — Deterministic, idempotent seed data

**Build**

- Add `src/app/domain/support/seed.py` and the thin entrypoint `scripts/seed.py`.
- Derive fixed IDs with `uuid5`, not `uuid4`.
- Seed customers, orders covering useful statuses, and one versioned policy document for Phase 3.
- Upsert or ignore conflicts so rerunning the same seed is a no-op.

**Automated proof**

- Run the seeder twice and assert identical IDs, row counts, and content hashes.
- Prove no existing mutable order state is reset by a second seed unless explicitly documented.

```bash
uv run pytest tests/integration/test_seed.py -q
```

**Manual review**

- Run `uv run python scripts/seed.py` twice and show equal summary counts on both runs.

**Accept when:** tests and reviewers can rely on stable entity and document IDs.

### Checkpoint 1.3 — Repository behavior

**Build**

- Add a small async repository for required persistence operations: order lookup/save and ticket creation/read.
- Keep business policy out of the repository.
- Define a repository protocol or fake only where the service tests immediately need substitution.

**Automated proof**

- Contract tests run against the PostgreSQL repository.
- The in-memory fake used by unit tests passes the same observable contract where relevant.
- Missing records return `None`; writes are visible after transaction commit.

```bash
uv run pytest tests/integration/test_support_repository.py -q
```

**Manual review**

- Show repository input/output for one existing and one missing order.

**Accept when:** persistence behavior is established without embedding authorization or transition rules.

### Checkpoint 1.4 — Order lookup authorization

**Build**

- Implement `SupportService.get_order(order_id, actor_id)`.
- Return a public order schema.
- Raise typed `OrderNotFound` and `Forbidden` errors.
- Connect those errors to the Phase 0 error handler.

**Automated proof**

- Cover owner lookup, missing order, and another customer's order.
- Assert error type, status, stable code, and absence of private order data.

```bash
uv run pytest tests/unit/support/test_get_order.py -q
```

**Manual review**

- Demonstrate the same order returning `200` for its owner and `403` for another actor after Checkpoint 1.6 exposes routes.
- Until then, show the focused service test's representative result.

**Accept when:** ownership cannot be bypassed by changing request data outside the service.

### Checkpoint 1.5 — Ticket creation and refund transitions

**Build**

- Implement deterministic ticket creation.
- Implement `request_refund(RefundCommand)` with authorization and allowed-state checks.
- Only allow the explicitly documented source states to transition to `refunded`.
- Raise `OrderNotFound`, `Forbidden`, or `InvalidTransition`; never return error strings.
- Persist successful transitions atomically.

**Automated proof**

- Cover successful ticket and refund behavior.
- Cover missing order, forbidden actor, every disallowed source state, and repository failure rollback.
- Assert both returned result and final persisted state.

```bash
uv run pytest tests/unit/support/test_ticket.py tests/unit/support/test_refund.py -q
```

**Manual review**

- Show a before/after order snapshot for a successful refund and unchanged state for a rejected refund.

**Accept when:** no caller, including a future agent, can bypass refund policy.

### Checkpoint 1.6 — Thin support API

**Build**

- Add one route per accepted service operation.
- Use dependency injection for the service.
- Keep routes free of business-rule branches.
- Define stable request and response examples in OpenAPI.

**Automated proof**

- API tests cover success and every typed domain error.
- Override the service in unit tests; add one PostgreSQL-backed happy-path integration test.

```bash
uv run pytest tests/unit/support/test_api.py tests/integration/test_support_api.py -q
```

**Manual review**

- Use the generated OpenAPI UI or documented `curl` commands to look up an order, create a ticket, and request a refund.

**Accept when:** all Phase 1 behaviors can be reviewed over HTTP and match direct service behavior.

---

## Phase 2 — Typed text agent and local tracing

**Phase outcome:** a typed agent completes one support interaction offline and can optionally export a sanitized trace to LangSmith.

### Checkpoint 2.1 — Typed model contract and deterministic fake

**Build**

- Add `SupportRequest`, `RoutingDecision`, `AnswerContext`, and `SupportResponse` schemas.
- Constrain route intent to `refund | order_status | policy | escalate` and confidence to `[0, 1]`.
- Define the smallest model-provider protocol required by the use cases.
- Add a scripted fake whose missing script entries fail with a descriptive test error.

**Automated proof**

- Schema tests cover invalid intent/confidence and valid round trips.
- Fake-provider tests prove deterministic routing/answering and no network access.

```bash
uv run pytest tests/unit/agent/test_contract.py tests/unit/agent/test_fake_provider.py -q
```

**Manual review**

- Show a representative support request and the fake's typed routing and answer outputs.

**Accept when:** later workflow tests can completely control model outcomes with typed fixtures.

### Checkpoint 2.2 — Versioned routing prompt and PydanticAI adapter

**Build**

- Add immutable `route_v1.py` with `ROUTE_PROMPT_V1`.
- Add a PydanticAI routing `Agent` with structured `RoutingDecision` output and instrumentation enabled.
- Keep the model string in this adapter module only.
- Make agent construction injectable so offline tests can use PydanticAI's test model/function model or a local fake.
- Tag runs with `prompt.version=route_v1`.

**Automated proof**

- Adapter contract tests run offline and prove typed output and prompt-version metadata.
- A static/import-boundary test proves provider chat SDKs are not imported outside sanctioned adapter modules.

```bash
uv run pytest tests/unit/agent/test_pydantic_adapter.py tests/unit/test_import_boundaries.py -q
```

**Manual review**

- Show the structured result and captured prompt version from one offline adapter run.

**Accept when:** changing provider later requires changing only the model string/configuration, not callers.

### Checkpoint 2.3 — Text interaction service and API

**Build**

- Add an application service that takes a `SupportRequest`, asks the provider to route and answer, and returns a typed response.
- At this checkpoint, do not execute support mutations; refund requests may produce a proposal or escalation only.
- Add a thin text-support API endpoint using the service.

**Automated proof**

- Offline API tests cover each route using scripted model output.
- Prove malformed model output becomes a typed safe failure.
- Prove no support repository mutation occurs during a text interaction.

```bash
uv run pytest tests/unit/agent/test_service.py tests/unit/agent/test_api.py -q
```

**Manual review**

- Submit one request to the local API and show the typed route and response.

**Accept when:** the first end-to-end text interaction is usable and deterministic without credentials.

### Checkpoint 2.4 — OpenTelemetry span shape with an in-memory exporter

**Build**

- Configure OpenTelemetry only when enabled by settings.
- Capture a parent interaction span and the PydanticAI child model span.
- Add project attributes only from an explicit allowlist.
- Ensure test mode uses an in-memory exporter and never starts an OTLP network exporter.

**Automated proof**

- Assert parent/child relationships, status, duration presence, route, and prompt version.
- Assert raw sensitive message/response fields are absent by default.
- Assert tracing-disabled mode exports zero spans.

```bash
uv run pytest tests/unit/agent/test_tracing.py -q
```

**Manual review**

- Generate `artifacts/phase-2-local-trace.json` from a deterministic request and inspect its sanitized span tree.

**Accept when:** trace semantics are reviewable locally before LangSmith is involved.

### Checkpoint 2.5 — Opt-in LangSmith export and field audit

**Build**

- Point the OTLP HTTP exporter at LangSmith only when `LANGSMITH_TRACING=true` and required configuration exists.
- Use `OTEL_EXPORTER_OTLP_ENDPOINT` and headers; do not build a custom export client.
- Define `ALLOWED_TRACE_FIELDS` and `FORBIDDEN_TRACE_FIELDS` constants based on the local trace shape.
- Add a credentials-gated live smoke test.

**Automated proof**

- Configuration tests reject tracing enabled without required settings.
- Offline sanitizer tests enforce the field allowlist.
- Live smoke test is skipped without credentials and asserts a trace ID when enabled.

```bash
uv run pytest tests/unit/agent/test_trace_policy.py -q
uv run pytest tests/live/test_langsmith_export.py -q
```

**Manual review**

- With credentials, run one known request and provide its LangSmith trace URL/ID.
- Compare its fields with `artifacts/phase-2-local-trace.json` and confirm forbidden content is absent.

**Accept when:** the same sanitized nested trace is inspectable locally and in LangSmith.

---

## Phase 3 — Hybrid retrieval

**Phase outcome:** policy questions return exact source citations through measured keyword/vector retrieval.

### Checkpoint 3.1 — Deterministic chunking and embedding contract

**Build**

- Add `SourceDocument`, `DocumentChunk`, and `EmbeddingProvider` contracts.
- Implement deterministic token-aware chunking with explicit size and overlap.
- Add a stable fake embedding provider for tests.
- Add the real OpenAI embedding adapter in one sanctioned module; pin model name and vector dimension together.

**Automated proof**

- Chunk boundaries, order, IDs, and content hashes are stable for a fixed document.
- Fake embeddings have deterministic dimensions and values.
- Real adapter tests use a mocked SDK client and preserve input order.

```bash
uv run pytest tests/unit/retrieval/test_chunking.py tests/unit/retrieval/test_embeddings.py -q
```

**Manual review**

- Show chunks and IDs generated from the seeded policy document.

**Accept when:** ingestion inputs can be reproduced without a provider call.

### Checkpoint 3.2 — pgvector schema and idempotent ingestion

**Build**

- Add the pgvector extension and a chunks table containing text, generated English `tsvector`, embedding, content hash, document/version identity, and source metadata.
- Use the dimension required by the configured embedding model.
- Upsert by stable document/version/content identity.
- Do not leave partially ingested documents after an embedding or database failure.

**Automated proof**

- Ingesting the same document twice leaves row counts and IDs unchanged.
- A changed document creates the documented new version without corrupting the old one.
- Failure injection proves transactional rollback.

```bash
uv run pytest tests/integration/test_retrieval_ingestion.py -q
```

**Manual review**

- Run ingestion twice and show identical chunk counts and hashes.

**Accept when:** the exact retrieval corpus is versioned and reproducible.

### Checkpoint 3.3 — Keyword retriever

**Build**

- Implement `Retriever.search(query, limit)` returning typed `RetrievalHit` records.
- Use PostgreSQL full-text search with safe query construction and ranked results.
- Include chunk/document IDs, exact text, score, source=`keyword`, and corpus version.

**Automated proof**

- Fixed policy queries return expected chunks in deterministic rank order.
- Empty, punctuation-heavy, and no-match queries return safe results.
- Query text cannot alter SQL structure.

```bash
uv run pytest tests/integration/test_keyword_retriever.py -q
```

**Manual review**

- Show top hits and scores for one policy question and resolve the citation back to stored chunk text.

**Accept when:** policy retrieval works without embeddings.

### Checkpoint 3.4 — Vector retriever

**Build**

- Implement cosine-distance vector search behind the same `Retriever` contract.
- Embed the query through `EmbeddingProvider`.
- Return normalized comparable scores with source=`vector`.

**Automated proof**

- Tests use deterministic fake embeddings and a fixed corpus.
- Cover top-k ordering, dimension mismatch, no corpus, and embedding-provider failure.

```bash
uv run pytest tests/integration/test_vector_retriever.py -q
```

**Manual review**

- Show vector top hits for the same question used in Checkpoint 3.3.

**Accept when:** vector behavior is independently understandable before fusion.

### Checkpoint 3.5 — Reciprocal-rank fusion

**Build**

- Add a pure RRF function and `FusedRetriever`.
- Deduplicate by chunk ID, retain contributing ranks/sources, and use a documented `k` default.
- Apply deterministic tie-breaking.

**Automated proof**

- Pure unit tests cover overlap, disjoint lists, ties, empty stages, deduplication, and limit handling.

```bash
uv run pytest tests/unit/retrieval/test_fusion.py -q
```

**Manual review**

- Show keyword, vector, and fused ranks side by side for one query.

**Accept when:** every fused score can be explained from its source ranks.

### Checkpoint 3.6 — Versioned retrieval evaluation

**Build**

- Add `tests/fixtures/retrieval_eval_v1.jsonl` with 20–30 hand-authored queries and expected chunk IDs from the seeded policy version.
- Implement Recall@k and at least one rank-sensitive metric.
- Add an evaluation CLI that writes corpus/config versions and metrics to JSON.
- Set an initial CI floor from the measured baseline, not an invented target.

**Automated proof**

- Metric functions have pure unit tests.
- An integration test evaluates the fixed set and enforces the accepted floor.

```bash
uv run pytest tests/unit/retrieval/test_metrics.py tests/integration/test_retrieval_eval.py -q
uv run python -m app.domain.retrieval.evaluate --dataset retrieval_eval_v1
```

**Manual review**

- Review `artifacts/retrieval-eval-v1.json`, failed queries, and metric floor before accepting it.

**Accept when:** retrieval quality is a versioned number that can fail CI.

### Checkpoint 3.7 — Retrieval tracing and cited policy answers

**Build**

- Emit spans for keyword, vector, and fusion stages with query hash, corpus version, hit IDs, ranks, and scores; omit raw query text by default.
- Connect fused retrieval to policy-answer generation.
- Require returned citations to reference actual hits supplied to the model.

**Automated proof**

- In-memory tracing tests assert stage order and attributes.
- Agent tests reject hallucinated citation IDs and prove cited text matches stored chunks.

```bash
uv run pytest tests/unit/retrieval/test_tracing.py tests/unit/agent/test_policy_answers.py -q
```

**Manual review**

- Ask one policy question and inspect the answer, citations, and local retrieval span tree.

**Accept when:** a reviewer can trace an answer sentence to exact evidence and retrieval scores.

### Checkpoint 3.8 — Optional reranker experiment

Do not start this checkpoint until Checkpoint 3.6 has an accepted baseline.

**Build**

- Add a `Reranker` protocol, deterministic fake, and one sanctioned adapter.
- Keep reranking optional and preserve pre-rerank scores/ranks.
- Change no other major retrieval variable.

**Automated proof**

- Contract/error tests run offline.
- Re-run the exact v1 evaluation set with reranking enabled.

**Manual review**

- Present baseline vs candidate metrics, latency, and cost in one artifact.

**Accept when:** the reviewer sees a measured improvement that justifies the dependency. Otherwise remove or leave the feature disabled and record the result.

---

## Phase 4 — Multi-agent workflow and controlled actions

**Phase outcome:** LangGraph routes requests, retrieves evidence, generates responses, pauses before mutations, retries transient failures, and escalates safely.

### Checkpoint 4.1 — Typed workflow state and isolated nodes

**Build**

- Add a typed `SupportState` containing request, route, evidence, proposed action, confirmation, response, errors, and escalation state.
- Implement node factories with explicit injected dependencies.
- Each node calls exactly one dependency and returns only changed state keys.

**Automated proof**

- Unit-test routing, retrieval, response generation, and action execution nodes independently with fakes.
- Prove input state is not unexpectedly mutated.

```bash
uv run pytest tests/unit/workflow/test_nodes.py -q
```

**Manual review**

- Show input and state delta for each node using one scripted request.

**Accept when:** each node has one clear responsibility and deterministic output.

### Checkpoint 4.2 — Read-only graph paths

**Build**

- Compile routes for order status, policy answer, and direct escalation.
- Add explicit conditional edges and a versioned workflow identifier.
- Do not include mutation execution yet.

**Automated proof**

- Assert exact node sequences and final states for each route.
- Cover incorrect/low-confidence routing and empty retrieval results.

```bash
uv run pytest tests/unit/workflow/test_read_only_graph.py -q
```

**Manual review**

- Produce a transition transcript for status, policy, and escalation requests.

**Accept when:** reviewers can verify routing from state transitions without reading LangGraph internals.

### Checkpoint 4.3 — Refund proposal and confirmation interrupt

**Build**

- Generate a typed refund proposal, but compile the graph with an interrupt before action execution.
- Persist/checkpoint state required to resume.
- Resume only from an explicit confirmation decision tied to the same actor and request.
- Rejection ends without mutation.

**Automated proof**

- Prove pre-interrupt state contains a proposal and unchanged order.
- Prove confirmation executes exactly once.
- Prove rejection, wrong actor, duplicate resume, and expired/missing checkpoint do not mutate state.

```bash
uv run pytest tests/unit/workflow/test_confirmation.py tests/integration/test_workflow_checkpoint.py -q
```

**Manual review**

- Run a refund request, inspect the pause, reject it, then run another and confirm it; show order state after each.

**Accept when:** no model output or graph path can execute a refund without explicit valid confirmation.

### Checkpoint 4.4 — Retry policy and escalation

**Build**

- Use LangGraph `RetryPolicy` for transient model/retrieval errors.
- Do not retry authorization, invalid transition, or other permanent domain errors.
- Escalate with a typed reason after retry exhaustion or known unsafe conditions.

**Automated proof**

- Cover success after one transient failure, retry exhaustion, no retry for permanent errors, and exact call counts.

```bash
uv run pytest tests/unit/workflow/test_retries.py tests/unit/workflow/test_escalation.py -q
```

**Manual review**

- Show event transcripts for one recovered request and one exhausted request.

**Accept when:** retry and escalation decisions are explicit, bounded, and observable.

### Checkpoint 4.5 — Workflow API and trace hierarchy

**Build**

- Expose start, inspect, confirm, and reject operations through authenticated-ready service boundaries; actual auth arrives in Phase 9.
- Enable LangGraph/PydanticAI instrumentation and add only necessary edge-decision attributes.
- Return stable workflow/run IDs to callers.

**Automated proof**

- API tests exercise read-only, paused, confirmed, rejected, retried, and escalated runs.
- In-memory spans prove interaction → graph → node → model/retrieval/tool hierarchy.

```bash
uv run pytest tests/unit/workflow/test_api.py tests/unit/workflow/test_tracing.py -q
```

**Manual review**

- Complete one interaction over HTTP and inspect its local trace and state transcript.

**Accept when:** the complete support workflow is reviewable offline through API, state, and traces.

---

## Phase 5 — Canonical traces and LangSmith adapter

**Phase outcome:** the reliability backend reads local and LangSmith traces through one vendor-neutral contract.

### Checkpoint 5.1 — Canonical trace schema

**Build**

- Define strict `CanonicalTrace`, `CanonicalEvent`, `EventKind`, and `SourceReference` schemas.
- Support model call, retrieval, tool call, decision, handoff, evaluation, and correction events.
- Preserve source vendor, trace ID, run ID, parent relationships, timestamps, duration, status, and allowlisted scalar attributes.
- Assign stable internal IDs from source identity.

**Automated proof**

- Validate a hand-built event tree.
- Reject cycles, orphan parents, duplicate IDs, invalid duration, and non-allowlisted attribute types.
- Serialization round trips produce identical canonical content.

```bash
uv run pytest tests/unit/traces/test_canonical.py -q
```

**Manual review**

- Inspect one canonical JSON fixture and its rendered parent/child tree.

**Accept when:** downstream code no longer needs a vendor run type.

### Checkpoint 5.2 — TraceSource contract and fixture source

**Build**

- Define async `get_trace` and `list_traces` operations plus typed query/summary models.
- Add a local JSON fixture implementation.
- Create reusable contract tests for any `TraceSource`.

**Automated proof**

- Contract tests cover lookup, listing/filtering, missing trace, malformed source, stable ordering, and pagination semantics if exposed.

```bash
uv run pytest tests/unit/traces/test_source_contract.py -q
```

**Manual review**

- List fixtures and fetch one by source ID through the protocol.

**Accept when:** all reliability development can proceed without LangSmith credentials.

### Checkpoint 5.3 — LangSmith raw-run mapping

**Build**

- Add sanitized raw LangSmith run fixtures under `tests/fixtures/traces/langsmith/`.
- Implement one pure `_to_canonical` mapping function.
- Map LangGraph nodes to decision/handoff events and PydanticAI spans to model-call events.
- Ignore unknown optional vendor fields in the raw parser, but keep canonical models strict.

**Automated proof**

- Golden tests compare each raw fixture to expected canonical JSON.
- Cover missing optional fields, unknown fields, failed runs, timestamps, and parent ordering.

```bash
uv run pytest tests/unit/traces/test_langsmith_mapping.py -q
```

**Manual review**

- Review one raw-to-canonical diff and verify every canonical event links to its source run ID.

**Accept when:** vendor-specific interpretation is isolated and fixture-tested.

### Checkpoint 5.4 — Async LangSmithTraceSource

**Build**

- Implement `LangSmithTraceSource` using the read client, separate from OTLP export.
- Wrap the synchronous client with `asyncio.to_thread` so the event loop is not blocked.
- Translate not-found, authentication, rate-limit, and unavailable failures to typed source errors.

**Automated proof**

- Run the reusable contract against a mocked client.
- Add a concurrency test proving another coroutine progresses during a blocked client call.
- Add an opt-in live parity smoke test against one known trace.

```bash
uv run pytest tests/unit/traces/test_langsmith_source.py -q
uv run pytest tests/live/test_langsmith_source.py -q
```

**Manual review**

- Fetch one live trace and compare its canonical form with the approved fixture shape.

**Accept when:** LangSmith is replaceable and cannot block the async server loop.

### Checkpoint 5.5 — Idempotent canonical trace storage

**Build**

- Add traces/events tables and indexes on source identity, trace ID, and parent event ID.
- Import transactionally using unique `(vendor, source_trace_id)` identity.
- Define how a re-import updates newly available optional data without duplicating events.

**Automated proof**

- Import the same trace twice and assert stable IDs/counts.
- Import an enriched version and assert the documented update behavior.
- Inject a mid-import failure and prove rollback.

```bash
uv run pytest tests/integration/test_trace_import.py -q
```

**Manual review**

- Show import summaries and row counts for first import, repeat import, and enriched import.

**Accept when:** all later phases read persisted `CanonicalTrace` values, never LangSmith runs.

---

## Phase 6 — Failure detection, grouping, and review

**Phase outcome:** explainable candidates become reviewer-confirmed failure groups with source evidence.

### Checkpoint 6.1 — Failure taxonomy and deterministic labeled trace set

**Build**

- Define routing, retrieval, tool, generation, policy, and infrastructure failure kinds.
- Create versioned canonical fixtures containing successes and representative failures.
- Generate fixtures through the accepted workflow where practical; document intentional hand-built edge cases.

**Automated proof**

- Fixtures validate against the canonical schema and expected labels.
- Regeneration produces equivalent canonical content after volatile fields are normalized.

```bash
uv run pytest tests/unit/failures/test_trace_dataset.py -q
```

**Manual review**

- Review the dataset manifest, class counts, and one trace per failure kind.

**Accept when:** failure analysis has stable, understandable input data.

### Checkpoint 6.2 — Feedback and annotation import

**Build**

- Add a feedback model keyed to trace/event source identity.
- Import LangSmith annotations through a fixture-backed adapter path.
- Preserve annotation source, score/label, timestamp, and reviewer identity where available.

**Automated proof**

- Cover idempotent import, unknown trace/event references, corrected annotation, and malformed optional data.

```bash
uv run pytest tests/unit/failures/test_feedback_mapping.py tests/integration/test_feedback_import.py -q
```

**Manual review**

- Show one canonical trace before and after linked feedback import.

**Accept when:** user/reviewer signals retain provenance and do not overwrite trace facts.

### Checkpoint 6.3 — Explainable failure feature extraction

**Build**

- Add `FailureCandidate` with predicted kind, hand-named feature values, and evidence event IDs.
- Extract explainable features such as retry count, minimum retrieval score, escalation, tool error code, and correction/feedback signals.
- Return no candidate for accepted success traces.

**Automated proof**

- Table-driven tests cover each labeled fixture and exact feature values.
- Every candidate's evidence IDs resolve to events in the source trace.

```bash
uv run pytest tests/unit/failures/test_features.py -q
```

**Manual review**

- Show one feature vector and follow each feature back to its evidence event.

**Accept when:** a reviewer can understand why every trace was proposed as a failure.

### Checkpoint 6.4 — Failure grouping baseline

**Build**

- Normalize mixed feature types deterministically.
- Group candidates with a simple tested baseline such as DBSCAN over cosine distance.
- Persist algorithm/config/dataset versions and treat outliers explicitly.
- Do not use opaque raw text embeddings in the baseline.

**Automated proof**

- Fixed fixtures produce stable expected groups and outliers.
- Input ordering does not change memberships or stable group IDs.
- Write clustering quality/coverage metrics to an artifact.

```bash
uv run pytest tests/unit/failures/test_grouping.py -q
uv run python -m app.domain.failures.evaluate --dataset failure_traces_v1
```

**Manual review**

- Review `artifacts/failure-grouping-v1.json`, including members, shared features, and outliers.

**Accept when:** proposed similarity is reproducible and evidence can be inspected.

### Checkpoint 6.5 — Human review lifecycle

**Build**

- Persist proposed groups and review decisions: confirm, correct kind, or reject.
- Record reviewer, timestamp, reason, source traces, evidence events, and algorithm version.
- Prevent a previously rejected equivalent proposal from silently reopening.
- Expose list/detail/review service and API operations.

**Automated proof**

- Cover each decision, invalid transitions, concurrent duplicate reviews, authorization-ready reviewer identity, and re-proposal after rejection.
- Confirmed groups retain full provenance.

```bash
uv run pytest tests/unit/failures/test_review.py tests/integration/test_failure_review_api.py -q
```

**Manual review**

- Review one proposal through the API, correct its kind, and inspect the stored audit record.

**Accept when:** only explicit human decisions create labeled truth.

---

## Phase 7 — Regression-case generation

**Phase outcome:** a confirmed failure produces a privacy-safe, versioned case that runs without production side effects.

### Checkpoint 7.1 — Strict regression-case schema

**Build**

- Define `RegressionCase`, `ExpectedBehavior`, retrieval fixtures, tool fixtures, and source references.
- Keep `case_id` stable and make version explicit.
- Include schema, workflow, prompt, corpus, and fixture versions needed for replay.

**Automated proof**

- Validate representative cases for each failure kind.
- Reject missing provenance, invalid fixture references, unknown schema version, and internally inconsistent expectations.
- Serialization is stable.

```bash
uv run pytest tests/unit/regression/test_schema.py -q
```

**Manual review**

- Inspect one complete case JSON without executing it.

**Accept when:** a case contains everything replay needs and no hidden live dependency.

### Checkpoint 7.2 — Allowlist redaction policy

**Build**

- Derive allowed fields from the accepted Phase 2 trace audit.
- Strip every field not explicitly allowed rather than attempting best-effort masking.
- Add deterministic replacements for identifiers that must retain within-case relationships.
- Never persist raw secret, email, address, payment, or free-form sensitive fields.

**Automated proof**

- Property/table tests inject sensitive values at every nesting level and prove absence from output and serialized JSON.
- Preserve only explicitly accepted fields and stable pseudonymous relationships.

```bash
uv run pytest tests/unit/regression/test_redaction.py -q
```

**Manual review**

- Inspect a redaction before/after example containing seeded fake PII.

**Accept when:** regression data is safe by default and fails closed on new fields.

### Checkpoint 7.3 — Deterministic fixture extraction

**Build**

- Extract exact retrieval hits and tool outcomes from canonical source events.
- Do not rerun retrieval or tools while building a case.
- Fail with a typed, actionable error when required evidence is absent.

**Automated proof**

- Golden tests assert exact fixture order, IDs, scores, responses, and errors.
- A network-denial test proves extraction performs no external calls.

```bash
uv run pytest tests/unit/regression/test_fixture_extraction.py -q
```

**Manual review**

- Compare source event attributes and generated fixtures side by side.

**Accept when:** replay inputs are snapshots of observed evidence, not reconstructed guesses.

### Checkpoint 7.4 — Reviewed case builder and expected behavior

**Build**

- Build cases only from confirmed groups/failures.
- Require a human-authored or explicitly reviewed `ExpectedBehavior`; do not copy the failed model response as truth.
- Apply redaction and fixture extraction in one deterministic builder.
- Record author/reviewer provenance.

**Automated proof**

- Reject unconfirmed failures and missing expected behavior.
- Build the same input/version twice and compare canonical serialized content.
- Prove a source failure's incorrect output is not used as the expectation.

```bash
uv run pytest tests/unit/regression/test_builder.py -q
```

**Manual review**

- Generate one case from a confirmed group and approve its expected behavior and provenance.

**Accept when:** the first reviewed failure is a deterministic, privacy-safe test case.

### Checkpoint 7.5 — Versioned persistence and leakage-safe dataset split

**Build**

- Persist every case version without overwriting prior versions.
- Group by source conversation/trace family before train/eval splitting.
- Generate a versioned dataset manifest with deterministic split seed and case versions.

**Automated proof**

- Updating fixtures creates a new version while old content remains readable.
- No conversation or source family appears in both splits.
- Repeating the split with the same manifest inputs is identical.

```bash
uv run pytest tests/integration/test_regression_store.py tests/unit/regression/test_dataset_split.py -q
```

**Manual review**

- Inspect case history and the v1 dataset manifest.

**Accept when:** regression history is immutable and evaluation leakage is prevented.

---

## Phase 8 — Deterministic replay and recommendations

**Phase outcome:** the backend compares one controlled candidate with a baseline and returns a reproducible, evidence-linked recommendation.

### Checkpoint 8.1 — Fixture-backed replay dependencies

**Build**

- Implement fixture-backed retriever and support/tool service using the existing protocols.
- Match calls by stable semantic request identity and record all consumed fixtures.
- Reject an unexpected or duplicate side effect instead of falling through to a live dependency.

**Automated proof**

- Protocol/contract tests cover success, recorded errors, missing fixture, and exact call counts.
- A network/database-denial test proves these implementations remain offline.

```bash
uv run pytest tests/unit/replay/test_fixture_dependencies.py -q
```

**Manual review**

- Execute one case's dependencies directly and show consumed fixture IDs.

**Accept when:** replay cannot touch production retrieval, database state, or tools.

### Checkpoint 8.2 — Single-case replay runner

**Build**

- Run the accepted Phase 4 graph with fixture-backed dependencies.
- Add `AgentConfiguration` with versioned prompt/workflow/retrieval settings.
- Capture output, deterministic evaluator inputs, latency/cost metadata, errors, and execution transcript.

**Automated proof**

- Replay one case twice with fixed model output and compare normalized results.
- Cover pass, expected failure, unexpected fixture access, escalation, and interrupted action.

```bash
uv run pytest tests/unit/replay/test_runner.py -q
```

**Manual review**

- Show a case, its execution transcript, and normalized replay result.

**Accept when:** one regression case is a runnable offline test of the real workflow.

### Checkpoint 8.3 — Deterministic evaluators and batch result

**Build**

- Implement exact/structural evaluators against `ExpectedBehavior` first.
- Version evaluator configuration.
- Aggregate case results without hiding per-case outcomes.
- Keep model-judge evaluation optional and separate; if added, use a PydanticAI-backed judge and record its model/prompt version.

**Automated proof**

- Unit tests cover each evaluator and aggregation edge case.
- Batch replay of the v1 dataset emits stable metrics and case-level results.

```bash
uv run pytest tests/unit/replay/test_evaluators.py tests/unit/replay/test_batch.py -q
```

**Manual review**

- Inspect `artifacts/replay-baseline-v1.json`, especially failed cases and evaluator evidence.

**Accept when:** the project has a reproducible baseline before any candidate is compared.

### Checkpoint 8.4 — One-variable experiment validation

**Build**

- Require exactly one major difference between baseline and candidate configuration.
- Reject experiments with no difference or multiple major changes.
- Record dataset, case, workflow, prompt, retrieval, evaluator, and fixture versions.

**Automated proof**

- Cover valid prompt-only and retrieval-only experiments plus invalid zero/multi-variable experiments.

```bash
uv run pytest tests/unit/replay/test_experiment_config.py -q
```

**Manual review**

- Inspect one accepted experiment manifest and identify the sole changed variable.

**Accept when:** result attribution is meaningful by construction.

### Checkpoint 8.5 — Constraint-based comparison and evidence linking

**Build**

- Compare baseline/candidate quality, latency, cost, errors, and sample size.
- Return `recommend_candidate`, `keep_baseline`, or `insufficient_evidence`.
- Any violated constraint, missing metric, or undersized sample must prevent a positive recommendation.
- Include all case IDs, source trace IDs, metric values, configuration versions, and changed variable.

**Automated proof**

- Cover an improvement, regression, tie, cost violation, latency violation, missing metric, and insufficient sample.
- Repeating comparison with identical inputs yields identical output.

```bash
uv run pytest tests/unit/replay/test_compare.py -q
```

**Manual review**

- Review one deliberately improved candidate and one constraint-violating candidate with linked evidence.

**Accept when:** no recommendation is possible without reproducible supporting evidence.

---

## Phase 9 — MVP integration and operational hardening

**Phase outcome:** one documented command reproduces the full failure-to-regression path safely from a clean checkout.

### Checkpoint 9.1 — Offline end-to-end demo

**Build**

- Add `scripts/demo.py` using fixture trace source, analyzer, review input, case builder, replay runner, and comparison service.
- Produce a human-readable summary and machine-readable artifact.
- Make repeated runs deterministic after normalizing timestamps/run IDs.

**Automated proof**

- A subprocess integration test runs the demo without network credentials and validates the artifact schema/content.

```bash
uv run pytest tests/integration/test_offline_demo.py -q
uv run python scripts/demo.py --offline
```

**Manual review**

- Inspect the complete transcript: canonical trace → candidate group → review → case → baseline/candidate replay → recommendation.

**Accept when:** the entire product thesis is demonstrable offline in one command.

### Checkpoint 9.2 — Clean-checkout setup path

**Build**

- Document `.env` setup, `uv sync`, migration, seed, server, offline demo, and optional live tracing.
- Add a setup verification command/script that checks configuration and dependencies without mutating production data.
- Clearly distinguish scratch/test database URLs from production.

**Automated proof**

- Run setup in a clean temporary checkout or CI job using only documented commands.

```bash
uv sync --frozen
uv run alembic upgrade head
uv run python scripts/seed.py
uv run python scripts/demo.py --offline
```

**Manual review**

- A reviewer follows only `README.md` from a clean checkout and records any missing step.

**Accept when:** undocumented local state is not required.

### Checkpoint 9.3 — Mutating API authentication and authorization

**Build**

- Require authentication on confirmation, rejection, failure review, and case-authoring routes.
- Carry stable actor/reviewer identity into audit records.
- Separate authentication failure (`401`) from authorization failure (`403`).
- Use a deterministic test auth provider; do not hardcode secrets.

**Automated proof**

- Cover missing/invalid credentials, wrong role/actor, valid reviewer/action owner, and audit identity.

```bash
uv run pytest tests/unit/test_auth.py tests/integration/test_mutating_api_auth.py -q
```

**Manual review**

- Attempt one mutating request unauthenticated, unauthorized, and authorized; inspect responses and audit row.

**Accept when:** no state-changing operation is anonymous or attributable to the wrong actor.

### Checkpoint 9.4 — Degraded external-service behavior

**Build**

- Translate LangSmith/model/embedding/reranking rate-limit, auth, timeout, and unavailable failures into typed safe errors.
- For MVP trace import, fail clearly when LangSmith is unavailable rather than silently queuing.
- Ensure readiness semantics document which external providers, if any, affect readiness.

**Automated proof**

- Failure-injection tests cover each error family, safe API body, request ID, retryability, and absence of secret/raw provider text.

```bash
uv run pytest tests/unit/test_provider_errors.py tests/unit/traces/test_degraded_mode.py -q
```

**Manual review**

- Simulate LangSmith unavailability and inspect the typed import failure and correlated log.

**Accept when:** external outages are explicit, safe, and do not corrupt local state.

### Checkpoint 9.5 — Reproducibility, privacy, and performance evidence

**Build**

- Add an operational script that times trace import and replay, rebuilds a case twice, and repeats deterministic comparison three times.
- Re-run privacy tests over stored canonical traces, generated cases, artifacts, and logs.
- Define generous MVP performance budgets from measured behavior, not guesses.

**Automated proof**

- Fail on case/recommendation variance after normalization.
- Fail if forbidden seeded sensitive markers appear in persisted or generated artifacts.
- Report, but do not prematurely optimize, measured import/replay timings unless accepted budgets are exceeded.

```bash
uv run pytest tests/integration/test_reproducibility.py tests/integration/test_privacy_boundaries.py -q
uv run python scripts/operational_check.py
```

**Manual review**

- Review `artifacts/mvp-operational-check.json` containing timings, repeated hashes, variance, and privacy scan result.

**Accept when:** reviewers have evidence that the MVP is reproducible, privacy-safe, and operationally understandable.

## MVP completion gate

The MVP is complete only after Checkpoints 0.1–9.5 are individually accepted and one reviewed support failure passes through:

```text
LangSmith or fixture trace
  -> strict canonical trace
  -> explainable proposed failure group
  -> human-confirmed failure
  -> privacy-safe versioned regression case
  -> deterministic baseline/candidate replay
  -> constraint-checked evidence-backed recommendation
```

The final review must confirm:

- the quality gate passes from a clean checkout;
- the offline demo needs no model or LangSmith credentials;
- live LangSmith export/import is opt-in and has a documented smoke test;
- every recommendation links to cases, source traces, metrics, and versioned configuration;
- no recommendation changes production;
- deferred features have not leaked into the MVP implementation.

---

# Post-MVP checkpoints

Post-MVP work follows the same one-checkpoint, test-and-stop rule.

## Phase 10 — Voice

### Checkpoint 10.1 — Voice contracts and deterministic fixtures

- Define transcription, synthesis, and cancellation contracts plus typed results/errors.
- Add versioned audio/transcript fixtures and a deterministic fake.
- **Proof:** contract tests cover streaming order, errors, cancellation, and no network access.
- **Review:** transcribe and synthesize one fixture entirely offline.

### Checkpoint 10.2 — One provider adapter

- Add an ElevenLabs adapter or another selected provider; confine direct SDK imports to this module.
- **Proof:** mocked-client contract tests plus a credentials-gated smoke test.
- **Review:** compare fake and live output metadata without committing raw sensitive audio.

### Checkpoint 10.3 — Streaming workflow path

- Connect transcript input and synthesized response to the accepted text workflow.
- **Proof:** a recorded fixture follows the same route/evidence/action rules as text.
- **Review:** inspect one end-to-end voice turn transcript and trace.

### Checkpoint 10.4 — Barge-in and cancellation

- Wire interruption through a LangGraph interrupt and stop consuming synthesis output.
- **Proof:** deterministic concurrency tests prove no post-cancel audio is emitted and duplicate cancellation is safe.
- **Review:** run a fixture that interrupts mid-response.

### Checkpoint 10.5 — Voice failures in the regression loop

- Extend the taxonomy with transcription/synthesis failures and trace confidence, time-to-first-audio, interruptions, and provider errors.
- **Proof:** one confirmed voice failure becomes an offline regression case and replay result.
- **Review:** inspect its full failure-to-recommendation evidence chain.

## Phase 11 — Direct OpenTelemetry source

### Checkpoint 11.1 — Recorded OTLP fixture source

- Capture sanitized OTLP fixtures and map them to the existing canonical model.
- **Proof:** the reusable `TraceSource` contract and golden canonical mapping tests pass.
- **Review:** compare equivalent LangSmith and OTLP canonical trees.

### Checkpoint 11.2 — Collector fan-out in a test environment

- Configure one OTLP stream to LangSmith and a test canonical-relevant sink.
- **Proof:** integration tests assert both sinks receive the same trace identity and allowed fields only.
- **Review:** inspect a fan-out trace and field-policy report.

### Checkpoint 11.3 — OpenTelemetryTraceSource

- Implement live lookup/listing behind `TraceSource` without changing consumers.
- **Proof:** run the identical source contract against fixture, LangSmith, and OTel implementations.
- **Review:** run the same failure analysis using each equivalent source.

### Checkpoint 11.4 — Evidence-based storage decision

- Measure actual Phase 9/11 trace volume, query patterns, retention, latency, and operating cost.
- Compare PostgreSQL and ClickHouse only against those measurements.
- **Proof:** versioned benchmark scripts and result artifact.
- **Review:** accept a written decision record; do not migrate storage solely on projected scale.

## Research backlog

Each research item must begin with a hypothesis, fixed dataset, baseline, metric, and stop condition. Research output is an artifact or decision record, not an unmeasured production dependency.

- Compare alternative explainable failure representations and grouping methods.
- Add counterfactual model and retrieval replay.
- Generate prompt and retrieval candidates.
- Test whether changes generalize across failure groups.
- Define canary recommendations and rollback criteria.
- Export reviewed datasets for fine-tuning.
- Fine-tune only after prompt, retrieval, and workflow baselines are measured.
- Add trace adapters and domain-specific reliability policies.

## References

- LangSmith OpenTelemetry tracing: <https://docs.langchain.com/langsmith/trace-with-opentelemetry>
- LangSmith trace queries: <https://docs.langchain.com/langsmith/export-traces>
- LangSmith evaluation: <https://docs.langchain.com/langsmith/evaluation>
- LangSmith annotation queues: <https://docs.langchain.com/langsmith/annotation-queues>
- LangSmith automation rules: <https://docs.langchain.com/langsmith/rules>
- PydanticAI agents and models: <https://ai.pydantic.dev/agents/>
- LangGraph low-level concepts: <https://langchain-ai.github.io/langgraph/concepts/low_level/>
