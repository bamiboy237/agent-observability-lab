# Graph Report - .  (2026-08-14)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 4348 nodes · 12126 edges · 176 communities (148 shown, 28 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 1444 edges (avg confidence: 0.57)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2ea005ba`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- simulator.py
- RoutingDecision
- SimulationEvent
- ReferenceExpectation
- workflow/service.py
- cli/main.py
- suite/schemas.py
- user_simulator/events.py
- TextualSimulatorApp
- langsmith.py
- PostgresSupportSandbox
- feedback.py
- suite/runner.py
- pydantic_ai_agent.py
- simulation/runner.py
- runs_router.py
- test_simulator.py
- db.py
- SupportRequest
- run_reference_case
- test_cli_ui.py
- agent/service.py
- ci_triage/fixtures.py
- load_simulation_catalog
- evidence/schemas.py
- FaultScript
- FailureGroupProposal
- simulate.py
- SimulationEventCollector
- claims_denial/fixtures.py
- incident_response/fixtures.py
- evidence/service.py
- failures/schemas.py
- compiler.py
- test_regression_service.py
- support/schemas.py
- OrderRead
- support/seed.py
- FlowRegistry
- ForbiddenDataError
- SimulationScenario
- onboarding.py
- test_regression_cases.py
- nodes.py
- StateMutation
- SimulationBundle
- fixture_source.py
- disputes.py
- run_bundle
- RetrievalHit
- Settings
- test_experiment.py
- returns_resolution.py
- EnvironmentProfileLike
- ExecutionService
- TraceRecorder
- comparison/compare.py
- recorded.py
- LangSmithSource
- compile_bundle
- live/test_scenarios.py
- comparison/test_model_lab.py
- build_tracer
- storage.py
- failures/service.py
- FixtureTraceSource
- SupportService
- failures/dataset.py
- TraceEvidence
- StatefulSupportAdapter
- DisplayEvent
- test_nodes.py
- order_status_plan
- cases_router.py
- DependencyCoverageRequirement
- TraceImportService
- StatefulSupportProvisioner
- CliError
- retrieval/evaluate.py
- offline.py
- SimulationState
- answers.py
- app/errors.py
- scan_payload
- app/config.py
- SourceDocument
- OpenAIEmbeddingProvider
- test_runs_api.py
- test_suite_runner.py
- RecordedOrderLookup
- test_compare.py
- UUID
- test_contract.py
- ObservedSupportRepository
- InMemorySupportRepository
- test_cases_api.py
- DependencyAdapter
- DependencyCallResult
- test_dataset_split.py
- create_app
- _bundle
- SimulationAdapterRegistry
- BraintrustRecordedSource
- test_logging.py
- ReferenceRun
- agent/test_scenarios.py
- env.py
- command
- RunClient
- SeedRepository
- Vector
- tracing.py
- test_fault_scripts.py
- test_fixtures.py
- support/test_api.py
- test_lab_api.py
- VectorType
- health_router.py
- Any
- mutation_event_attributes
- 0001_baseline.py
- test_database.py
- .reset
- domain/user_simulator/__init__.py
- .replace
- adapters/__init__.py
- sources/__init__.py
- domain/agent/__init__.py
- domain/audit/__init__.py
- bundle/__init__.py
- comparison/__init__.py
- execution/__init__.py
- domain/__init__.py
- domain/reference/__init__.py
- ci_triage/__init__.py
- claims_denial/__init__.py
- incident_response/__init__.py
- workflows/__init__.py
- reference_workflows/__init__.py
- .destroy
- .mutations
- .record
- .snapshot
- _as_dict
- domain/regression/__init__.py
- simulation/__init__.py
- .mutations
- domain/suite/__init__.py
- fakes/__init__.py
- live/__init__.py
- simulate

## God Nodes (most connected - your core abstractions)
1. `TraceRecorder` - 114 edges
2. `Settings` - 90 edges
3. `compile_bundle()` - 80 edges
4. `RoutingDecision` - 74 edges
5. `FaultScript` - 72 edges
6. `TextualSimulatorApp` - 70 edges
7. `StateMutation` - 69 edges
8. `ModelConfig` - 68 edges
9. `SupportOutcome` - 68 edges
10. `OrderRead` - 68 edges

## Surprising Connections (you probably didn't know these)
- `SeedRepository` --uses--> `ModelConfig`  [INFERRED]
  scripts/manual_agent.py → src/app/adapters/pydantic_ai_agent.py
- `SeedRepository` --uses--> `PydanticAISupportAgent`  [INFERRED]
  scripts/manual_agent.py → src/app/adapters/pydantic_ai_agent.py
- `SeedRepository` --uses--> `Settings`  [INFERRED]
  scripts/manual_agent.py → src/app/config.py
- `SeedRepository` --uses--> `SupportRequest`  [INFERRED]
  scripts/manual_agent.py → src/app/domain/agent/schemas.py
- `SeedRepository` --uses--> `TraceRecorder`  [INFERRED]
  scripts/manual_agent.py → src/app/telemetry/recorder.py

## Import Cycles
- None detected.

## Communities (176 total, 28 thin omitted)

### Community 0 - "simulator.py"
Cohesion: 0.05
Nodes (73): Agent, async_sessionmaker, EnvironmentRequest, This class carries what a provisioner factory needs to build an environment., EventEmitter, Sequence + factory + fan-out for one run., FlowMetadata, FlowRunRequest (+65 more)

### Community 1 - "RoutingDecision"
Cohesion: 0.06
Nodes (73): OriginalProductionBehavior, AnswerContext, StrEnum, This module defines the typed contract for the reference agent and its instrumen, This enum defines the possible intents for a support turn., This enum defines the stable outcome values for every response and trace., This enum defines stable reason codes for responses and trace attributes., This class stores structured model output that routes a support request. (+65 more)

### Community 2 - "SimulationEvent"
Cohesion: 0.05
Nodes (60): Message, PlainEventSink, Responsive, append-only operational timeline with semantic colors., Non-TTY / ``--no-live`` mode: one plain line per event, ready for tailing., Discards output but records run identity; used with --json.      stdout stays pu, RichTimelineSink, _SilentSink, EventCategory (+52 more)

### Community 3 - "ReferenceExpectation"
Cohesion: 0.10
Nodes (66): BaseModel, This module defines the bounded reference workflow contract.  A reference workfl, This class stores what the workflow observer derived from evidence., This class wires one approved reference workflow into the harness.      The obse, This class stores what one workflow case must produce.      ``permitted_transiti, This class stores one declared baseline/candidate variable., This class stores one planned tool call of the deterministic agent.      An argu, This class stores the deterministic agent behavior for one side.      The plan c (+58 more)

### Community 4 - "workflow/service.py"
Cohesion: 0.06
Nodes (54): Lock, confirm_workflow(), get_workflow_service(), inspect_workflow(), _psycopg_url(), AsyncSession, BaseModel, Depends (+46 more)

### Community 5 - "cli/main.py"
Cohesion: 0.05
Nodes (79): Insert, SessionFactory, build_parser(), cmd_audit(), cmd_bundle_compile(), cmd_cases_list(), cmd_compare(), cmd_import_trace() (+71 more)

### Community 6 - "suite/schemas.py"
Cohesion: 0.06
Nodes (61): get_suite(), list_suites(), BaseModel, Depends, ge, le, MAX_LIST_LIMIT, Query (+53 more)

### Community 7 - "user_simulator/events.py"
Cohesion: 0.05
Nodes (44): _format_kind_cell(), Render a restrained event label., CompositeSink, DisplayMemory, EventFactory, EventKind, EventSink, EventSource (+36 more)

### Community 8 - "TextualSimulatorApp"
Cohesion: 0.05
Nodes (17): Changed, ComposeResult, FlowPlugin, Resize, RowHighlighted, Scenario, SimulationEvent, Preserve the primary task at narrow widths. (+9 more)

### Community 9 - "langsmith.py"
Cohesion: 0.06
Nodes (47): _parse_time(), datetime, This module maps one recorded Braintrust trace through the evidence contract.  T, This function converts one Braintrust span into a neutral source run.      Brain, source_run_from_braintrust_span(), flatten_run_tree(), _json_response(), langsmith_run_url() (+39 more)

### Community 10 - "PostgresSupportSandbox"
Cohesion: 0.05
Nodes (32): EnvironmentRunError, MalformedResponseError, MissingSimulationCoverageError, This class represents an environment failure while provisioning a run., This class represents an expected failure during scenario simulation., This class represents a tool that one adapter does not offer., This class represents arguments that no recorded response matches., This class represents state that an adapter cannot simulate. (+24 more)

### Community 11 - "feedback.py"
Cohesion: 0.06
Nodes (37): FixtureLangSmithFeedbackSource, Any, Path, Fixture-backed LangSmith annotation source adapter., Read local LangSmith-shaped annotations for offline imports., FeedbackError, FeedbackImportService, FeedbackStore (+29 more)

### Community 12 - "suite/runner.py"
Cohesion: 0.07
Nodes (51): _candidate_config(), ConfigurationVersions, This class stores the workflow, model, prompt, tool, and policy versions., ConfigurationChangeType, StrEnum, This enum defines the one major dimension an experiment may change., This module runs saved cases and suite comparisons in background tasks.  An exec, This module defines the versioned regression case library schemas.  A regression (+43 more)

### Community 13 - "pydantic_ai_agent.py"
Cohesion: 0.05
Nodes (41): Model, RunContext, Span, SpanContext, SpanListener, build_pydantic_ai_model(), _confirm_refund(), _escalate() (+33 more)

### Community 14 - "simulation/runner.py"
Cohesion: 0.06
Nodes (51): ModelConfig, BaseModel, This class stores settings for a hosted model that supports both providers., Evaluator, EvaluatorReport, This class binds one versioned criterion to its code check., This class stores the versioned evaluator results of one run., This property reports whether every evaluator passed. (+43 more)

### Community 15 - "runs_router.py"
Cohesion: 0.11
Nodes (34): get_case_service(), get_execution_service(), get_suite_service(), AsyncSession, Depends, Request, This function builds the case service from one database session., This function returns the app-scoped execution service.      The service owns th (+26 more)

### Community 16 - "test_simulator.py"
Cohesion: 0.08
Nodes (39): UserTurn, SimpleNamespace, _answer(), _CaptureSink, _FailingRendererSink, FakePersonaAgent, FakeSettings, _install_persona_model() (+31 more)

### Community 17 - "db.py"
Cohesion: 0.06
Nodes (35): AsyncEngine, main(), This script adds seed data for support operations to the configured database., This module builds the Phase 7 application services for HTTP routes., get_settings(), get_engine(), This module provides database connection utilities., This function creates the application engine when the application first uses the (+27 more)

### Community 18 - "SupportRequest"
Cohesion: 0.08
Nodes (41): AgentDeps, AnswerDraft, PydanticAISupportAgent, This class stores the model's final answer without model identifiers., This class stores dependencies for one turn.      The application binds the cust, This class provides a typed support agent through Pydantic AI., This method runs one complete support turn and returns its typed response., This method builds the trusted response from the model draft and service state. (+33 more)

### Community 19 - "run_reference_case"
Cohesion: 0.07
Nodes (53): _capture_result(), _check_transitions(), _observed_transitions(), ReferenceTool, This module runs one bounded reference workflow case.  The runner seeds the disp, This function maps one recorded mutation to its transition string., This function resolves ``$tool.key`` references from captured values., This function extracts ``key=value`` captures from one tool result. (+45 more)

### Community 20 - "test_cli_ui.py"
Cohesion: 0.12
Nodes (49): This package implements the lab command-line workflow., catalog_dir(), _FakePlugin, _interrupt_args(), _ok_preflight(), Path, Focused tests for the generic simulate CLI and setup wizard.  The fake third-par, A conflicting remote root DATABASE_URL must never reach the plugin. (+41 more)

### Community 21 - "agent/service.py"
Cohesion: 0.07
Nodes (40): AgentError, ModelNotConfigured, This module defines typed errors for deterministic guards in the reference agent, This class represents a request for an agent without a configured hosted model., This class represents a refund request without explicit matching confirmation., This class represents an expected failure from the agent., RefundNotConfirmed, This module provides deterministic guards for the reference agent's tools.  This (+32 more)

### Community 22 - "ci_triage/fixtures.py"
Cohesion: 0.06
Nodes (52): CheckConclusion, CheckRun, CheckStatus, CiState, Commit, ComparisonVariable, compute_content_hash(), Confirmation (+44 more)

### Community 23 - "load_simulation_catalog"
Cohesion: 0.09
Nodes (49): EnvironmentProfiles, _default_plugin_ids(), load_environment_profiles(), load_simulation_catalog(), Any, Exception, Path, Load and strictly validate the grouped simulation catalogs.      ``paths`` defau (+41 more)

### Community 24 - "evidence/schemas.py"
Cohesion: 0.08
Nodes (48): DependencyCall, _aggregate_timing(), _aggregate_tokens(), _allowlisted_attributes(), _build_evidence(), _dependency_calls(), _duration_ms(), _fail() (+40 more)

### Community 25 - "FaultScript"
Cohesion: 0.08
Nodes (29): offline_fault_script(), This function returns the approved fault script for one scenario.      The scrip, Protocol, This protocol defines the minimum emit operation of an event sink.      Environm, SimulationEventSink, FaultInjectingRepository, FaultScript, FaultScriptEntry (+21 more)

### Community 26 - "FailureGroupProposal"
Cohesion: 0.07
Nodes (24): FailureGroupProposalRecord, FailureGroupReviewRecord, One deterministic group proposal and its current review state., Immutable audit record for one proposal review., FailureReviewRepository, InMemoryFailureReviewRepository, AsyncSession, Protocol (+16 more)

### Community 27 - "simulate.py"
Cohesion: 0.09
Nodes (47): Console, _build_catalog(), build_simulate_parser(), _build_sink(), _choose_scenario(), _cleanup_status(), _cmd_list(), _cmd_list_json() (+39 more)

### Community 28 - "SimulationEventCollector"
Cohesion: 0.05
Nodes (31): _FaultInjection, This class applies the approved fault script once per entry., This method raises or sleeps for one matching unconsumed entry.          An entr, Scalar, StrEnum, This module defines the versioned live simulation event stream.  A run emits ord, This class collects one ordered simulation transcript.      ``emit`` appends the, This method records one event and hands it to every subscriber. (+23 more)

### Community 29 - "claims_denial/fixtures.py"
Cohesion: 0.06
Nodes (48): Appeal, AppealStatus, Claim, ClaimsRequest, ClaimsState, ClaimStatus, ClinicalNote, ComparisonVariable (+40 more)

### Community 30 - "incident_response/fixtures.py"
Cohesion: 0.06
Nodes (47): ComparisonVariable, compute_content_hash(), Confirmation, DependencyCall, DependencyCoverage, ExpectedBehavior, ExpectedStateTransition, Incident (+39 more)

### Community 31 - "evidence/service.py"
Cohesion: 0.08
Nodes (31): UUID, This module defines models that store imported trace evidence., TraceImport, ImportResult, ImportStatus, BaseModel, datetime, StrEnum (+23 more)

### Community 32 - "failures/schemas.py"
Cohesion: 0.08
Nodes (41): build_artifact(), main(), Evaluate the deterministic Phase 6 grouping baseline., _accepted_success(), _event_values(), extract_candidates(), extract_failure_candidate(), _kind_and_events() (+33 more)

### Community 33 - "compiler.py"
Cohesion: 0.07
Nodes (37): compile_confirmed_failure_bundle(), _compile_coverage(), _compile_tool_versions(), This module implements the deterministic bundle compiler.  The compiler links ev, This function derives tool versions from the adapters that serve them., Build the portable scenario projection from reviewer-approved input., Compile an incident-derived bundle from a human-confirmed group only., This function computes the coverage of one scenario and returns its report. (+29 more)

### Community 34 - "test_regression_service.py"
Cohesion: 0.09
Nodes (37): compute_bundle_hash(), This function returns a stable hash for one bundle.      The hash excludes the d, CaseNotFoundError, InvalidCaseBundleError, UUID, This module defines typed failures for the regression case library.  The service, This class represents an expected failure in the case library., This class represents a bundle that is not approved by a reviewer. (+29 more)

### Community 35 - "support/schemas.py"
Cohesion: 0.10
Nodes (26): This module defines the dependency adapter contract for simulations.  An adapter, This module defines typed failures for the simulation contract.  Adapters fail c, This module defines the versioned fault-script contract and boundary wrapper.  A, Run support scenarios through the real application code and PostgreSQL., This module defines the ephemeral environment provisioner contract.  A provision, This module defines the versioned vendor-neutral SimulationScenario schema.  A s, This module implements the fast in-memory support test adapter.  This adapter is, This module defines the persistence boundary for the support domain. (+18 more)

### Community 36 - "OrderRead"
Cohesion: 0.07
Nodes (16): Return the real SQL repository path for a hosted-model agent., This module defines the eight fixed Phase 4 simulation scenarios.  Each scenario, _state(), AsyncSession, Protocol, UUID, Atomically refund one delivered order owned by the customer., SqlAlchemySupportRepository (+8 more)

### Community 37 - "support/seed.py"
Cohesion: 0.10
Nodes (32): DeclarativeBase, Base, This class provides the declarative base for application models that the databas, This method captures the disposable state after the run., Customer, Order, PolicyDocument, This module defines models that store customer support data. (+24 more)

### Community 38 - "FlowRegistry"
Cohesion: 0.07
Nodes (29): KeyError, FlowNotFoundError, FlowRegistrationError, FlowRegistry, ValueError, Raised when a plugin cannot be registered., Raised when no plugin is registered for a flow id., Registers flow plugins and fails loudly on duplicate flow ids. (+21 more)

### Community 39 - "ForbiddenDataError"
Cohesion: 0.11
Nodes (38): _contains_forbidden_substring(), _contains_forbidden_value(), _is_sensitive_key(), This module defines the privacy allowlist for bundle content.  The compiler reje, This function validates one owned-system resource seed record.      The allowlis, This function validates one recorded response payload.      Only JSON-safe scala, This function rejects secrets and forbidden source text in one string., This function scans typed bundle metadata for secret-like values. (+30 more)

### Community 40 - "SimulationScenario"
Cohesion: 0.05
Nodes (26): _private_source_values(), Return source values that a portable bundle must not repeat., CoverageReport, BaseModel, This class lists supported dependencies and missing coverage., This property reports whether every requirement is covered., This method reports supported coverage and missing requirements., compute_scenario_hash() (+18 more)

### Community 41 - "onboarding.py"
Cohesion: 0.06
Nodes (39): Candidate, ChecklistPolicyVersion, ChecklistTemplate, ComparisonVariable, content_hash(), DependencyCoverage, OnboardingCase, OnboardingCaseStatus (+31 more)

### Community 42 - "test_regression_cases.py"
Cohesion: 0.07
Nodes (29): This module defines the model that stores immutable regression case versions., This class stores one immutable version of one regression case.      The case id, RegressionCaseRecord, Protocol, UUID, This module defines the persistence boundary for the regression case library., This method inserts one immutable case version.          If a concurrent transac, This class stores one immutable case version with its serialized bundle. (+21 more)

### Community 43 - "nodes.py"
Cohesion: 0.14
Nodes (36): BaseCheckpointSaver, A permanent or unsafe condition that must be escalated., UnsafeWorkflowError, _after_confirmation(), _after_evidence(), _after_execution(), _after_proposal(), _after_response() (+28 more)

### Community 44 - "StateMutation"
Cohesion: 0.21
Nodes (38): This function runs every versioned evaluator against one run., run_evaluators(), This class reports one accepted mutation of disposable state., StateMutation, This class stores the explicit performance budgets of one scenario., SimulationBudgets, make_bundle(), make_metrics() (+30 more)

### Community 45 - "SimulationBundle"
Cohesion: 0.13
Nodes (32): This class stores one portable privacy-safe simulation bundle.      Every derive, This method returns every tool that the scenario declares., This method returns every dependency that the scenario declares., This method derives the bundle identifier from the content hash.          The ha, This method rejects bundles whose review is not approved., This function returns resource seeds grouped by resource type., resources_by_type(), SimulationBundle (+24 more)

### Community 46 - "fixture_source.py"
Cohesion: 0.09
Nodes (23): flatten_fixture_runs(), This module provides a local fixture trace source for offline development.  The, This function flattens one fixture run tree into pre-order (parents first)., This method returns one explicit bounded cohort from local fixtures., evidence_matches_query(), BaseModel, Protocol, This module defines the vendor-neutral trace source contract.  A trace source fe (+15 more)

### Community 47 - "disputes.py"
Cohesion: 0.06
Nodes (36): Account, ComparisonVariable, content_hash(), Customer, DependencyCoverage, DisputeCase, DisputeCategory, DisputeState (+28 more)

### Community 48 - "run_bundle"
Cohesion: 0.15
Nodes (37): CleanupRunError, InvalidSimulationBundleError, ModelRunError, This class represents a bundle that cannot drive a simulation run., This class represents a hosted-model failure that aborts a run., This class represents a failure to destroy a simulated environment., ProvisionerFactory, This function rejects dependencies the reference agent cannot reach.      The re (+29 more)

### Community 49 - "RetrievalHit"
Cohesion: 0.09
Nodes (24): Return the optional measured policy retriever., EmbeddingProvider, Protocol, Vendor-neutral contracts used by the retrieval pipeline., One ranked chunk returned by a retriever., The one contract that retrieval code uses for embeddings., Embed texts in the same order as the input sequence., A retriever returns ranked, source-cited chunks. (+16 more)

### Community 50 - "Settings"
Cohesion: 0.06
Nodes (25): BaseSettings, PostgresDsn, This property returns the direct database URL that schema migrations require., This class stores validated settings for the application., This method removes database credentials from serialized settings and logs., This method accepts complete model configurations or none at all., This property reports whether these settings build a hosted model., This property reports whether a second hosted model is configured. (+17 more)

### Community 51 - "test_experiment.py"
Cohesion: 0.14
Nodes (32): ConfigurationSet, _difference(), ExperimentError, model_config_from_version(), BaseModel, ValueError, This module defines the one-variable experiment contract.  An experiment compare, This function rejects an experiment whose baseline is not the bundle config. (+24 more)

### Community 52 - "returns_resolution.py"
Cohesion: 0.07
Nodes (34): ComparisonVariable, content_hash(), Customer, DependencyCoverage, Order, OrderStatus, StrEnum, UUID (+26 more)

### Community 53 - "EnvironmentProfileLike"
Cohesion: 0.11
Nodes (31): DatabaseProbe, Secret-safe runtime config resolved from the selected profile.      Values are n, RuntimeEnvironment, _artifact_issue(), _database_url(), EnvironmentProfileLike, _migration_fix(), _migration_head() (+23 more)

### Community 54 - "ExecutionService"
Cohesion: 0.10
Nodes (22): _build_execution_service(), This function builds the execution service from the deployed settings.      Simu, ExecutionError, ExecutionNotFoundError, UUID, This module defines typed failures for background case executions., This class represents an expected failure in case execution., This class represents an execution id that does not exist. (+14 more)

### Community 55 - "TraceRecorder"
Cohesion: 0.15
Nodes (31): This class records sanitized spans.      If the application disables tracing, th, This method returns the hexadecimal trace ID of the current span.          If no, TraceRecorder, build_live_repository(), make_agent(), This fixture returns a factory.      The factory creates live agents that use a, This function returns an in-memory repository with records from the Phase 1 seed, all_attributes() (+23 more)

### Community 56 - "comparison/compare.py"
Cohesion: 0.09
Nodes (29): _comparable(), compare_runs(), ComparisonVerdict, CriterionDelta, _deltas(), _evaluator_map(), _measured(), _missing_measurements() (+21 more)

### Community 57 - "recorded.py"
Cohesion: 0.08
Nodes (22): InvalidSimulationFixture, This class represents captured data that the sanitizer rejects., _contains_sensitive_key(), _json_safe(), This module implements recorded-read simulation adapters.  A recorded adapter re, This base class replays approved responses for one dependency.      Requests mat, This method loads approved captured data after strict sanitization., Recorded reads carry no state; seeding is a no-op. (+14 more)

### Community 58 - "LangSmithSource"
Cohesion: 0.16
Nodes (24): HTTPStatusError, LangSmithSource, This class provides the TraceSource contract for LangSmith., FakeLangSmithClient, Any, Exception, This module provides a fake LangSmith API client for unit tests., This fake serves recorded run trees or raises configured HTTP failures. (+16 more)

### Community 59 - "compile_bundle"
Cohesion: 0.14
Nodes (31): ReviewState, compile_bundle(), _compile_review(), ExpectedBehavior, ReviewDecision, Replace identifiers in expected transitions with stable synthetic values., This function compiles one reviewed scenario into a portable bundle.      The sa, This function builds one review decision, rejecting unapproved states. (+23 more)

### Community 60 - "live/test_scenarios.py"
Cohesion: 0.10
Nodes (27): BaseModel, This module defines eight fixed Phase 2 scenarios.  Each scenario defines one re, This class stores one fixed scenario and its evidence contract., ScenarioDefinition, InMemorySpanExporter, This fixture returns a trace recorder and an exporter that stores spans in memor, span_capture(), all_attributes() (+19 more)

### Community 61 - "comparison/test_model_lab.py"
Cohesion: 0.14
Nodes (30): ModelLabTotals, ModelSideTotals, _policy_outcome(), ReasonCode, This class stores one model's cohort totals., This class stores the cohort totals for both models., _recommendation(), _lab_with_scripted_runs() (+22 more)

### Community 62 - "build_tracer"
Cohesion: 0.11
Nodes (28): OTLPSpanExporter, SpanProcessor, build_trace_provider(), build_tracer(), _fingerprint(), langsmith_export_config(), LangSmithExportConfig, Tracer (+20 more)

### Community 63 - "storage.py"
Cohesion: 0.13
Nodes (21): DeterministicChunker, Deterministic token-aware document chunking., Split documents by explicit token size and overlap.      This deliberately uses, SQLAlchemy persistence models for versioned retrieval chunks., One indexed document chunk and its reproducible source identity., RetrievalChunk, _hit(), KeywordRetriever (+13 more)

### Community 64 - "failures/service.py"
Cohesion: 0.08
Nodes (36): get_failure_review_service(), Build the failure proposal review service from one database session., get_failure_group(), list_failure_groups(), BaseModel, Depends, Query, UUID (+28 more)

### Community 65 - "FixtureTraceSource"
Cohesion: 0.13
Nodes (23): FixtureTraceSource, Path, This class serves selected traces and bounded cohorts from local fixtures., This method returns one selected trace from a versioned fixture., This method lists the fixture trace ids available in this directory., test_fixture_source_returns_not_found_for_unknown_trace(), test_fixture_source_serves_every_scenario_fixture(), _all_attributes() (+15 more)

### Community 66 - "SupportService"
Cohesion: 0.14
Nodes (21): description, examples, create_ticket(), get_order(), get_support_service(), AsyncSession, Depends, Query (+13 more)

### Community 67 - "failures/dataset.py"
Cohesion: 0.12
Nodes (25): compute_content_hash(), This function returns a stable hash for one piece of evidence.      The hash exc, load_failure_dataset(), _load_manifest(), Load the versioned, deterministic Phase 6 labeled trace dataset., Return the complete canonical dataset in manifest order.      Existing accepted, Return the manifest payload generated from current canonical fixtures., Return labels keyed by canonical source trace ID. (+17 more)

### Community 68 - "TraceEvidence"
Cohesion: 0.11
Nodes (24): EvidenceSummary, This class stores one normalized selected trace.      The schema is vendor-neutr, This method rejects broken event order and invalid parent references., This class stores the core facts that downstream code reads from evidence., This function reduces one trace to the core contract for measurement code., summarize_evidence(), TraceEvidence, _assert_equivalent() (+16 more)

### Community 69 - "StatefulSupportAdapter"
Cohesion: 0.13
Nodes (20): Simulate the support database and ticket store for unit tests.      Reads answer, Stateful adapters take approved seeds, not captured responses., This method copies the approved state into disposable memory., This method restores the exact initial state snapshot., StatefulSupportAdapter, This module tests the disposable stateful support adapter for checkpoint 4.4.  R, _scenario_state(), test_bad_arguments_are_rejected() (+12 more)

### Community 70 - "DisplayEvent"
Cohesion: 0.09
Nodes (18): escape_value(), _fit(), _label_of(), _model_text(), SimulationEvent, Escape control characters so timeline values are terminal-safe., Collapse whitespace, escape, and cap one value at 160 characters., Truncate one line to ``width`` characters with an ellipsis. (+10 more)

### Community 71 - "test_nodes.py"
Cohesion: 0.12
Nodes (15): Exception, A model failure that is safe for LangGraph to retry., A retrieval failure that is safe for LangGraph to retry., TransientModelError, TransientRetrievalError, dependencies(), FailingRetriever, Noop (+7 more)

### Community 72 - "order_status_plan"
Cohesion: 0.15
Nodes (24): RequestUsage, order_status_plan(), policy_plan(), policy_without_tool_plan(), UUID, Scripted hosted-model boundary for offline runner tests.  The scripted model is, This function plans a grounded policy turn., This function plans an ungrounded policy answer without any tool call. (+16 more)

### Community 73 - "cases_router.py"
Cohesion: 0.11
Nodes (22): get_case(), list_cases(), BaseModel, Depends, ge, le, MAX_LIST_LIMIT, Query (+14 more)

### Community 74 - "DependencyCoverageRequirement"
Cohesion: 0.14
Nodes (25): InvalidBundleFixtureError, This class represents a fixture that fails allowlist sanitization., extract_dependency_fixtures(), This function validates the recorded fixtures for one scenario.      Every fixtu, DependencyFixture, fixtures_by_dependency(), This function returns dependency fixtures grouped by dependency., This class stores one recorded response for an unsafe external dependency. (+17 more)

### Community 75 - "TraceImportService"
Cohesion: 0.18
Nodes (19): This function returns the stable evidence id for one source trace.      The same, stable_evidence_id(), This class imports evidence without creating duplicates.      Reimporting unchan, TraceImportService, InMemoryEvidenceStore, datetime, UUID, This module provides an in-memory evidence store for unit tests. (+11 more)

### Community 76 - "StatefulSupportProvisioner"
Cohesion: 0.12
Nodes (14): This function reconstructs the synthetic disposable state from the seeds., This function reconstructs the runnable scenario from one bundle.      The reque, scenario_from_bundle(), state_from_bundle(), This class provides the in-memory substitute provisioner for tests., StatefulSupportProvisioner, MonkeyPatch, test_postgres_saves_lists_versions_and_runs_one_saved_case() (+6 more)

### Community 77 - "CliError"
Cohesion: 0.14
Nodes (20): MockTransport, LangSmithClient, LangSmithSourceConfig, This class stores credentials and endpoints for one LangSmith source., This class talks to the LangSmith API and raises provider failures raw.      The, CliError, Exception, This class represents a safe command failure with a stable code. (+12 more)

### Community 78 - "retrieval/evaluate.py"
Cohesion: 0.14
Nodes (22): evaluate_retriever(), load_dataset(), main(), Any, Path, Versioned retrieval evaluation command and artifact writer., Load a JSONL retrieval dataset with strict, stable fields., Evaluate one retriever and return metrics plus failed queries. (+14 more)

### Community 79 - "offline.py"
Cohesion: 0.12
Nodes (23): AgentInfo, ModelMessage, ModelResponse, _install_offline_proof(), This function installs distinct offline plans for the proof.      The baseline a, _answer_scripted(), build_offline_model(), install_offline_proof_model() (+15 more)

### Community 80 - "SimulationState"
Cohesion: 0.15
Nodes (22): _customer_records(), extract_resource_seeds(), _order_records(), _policy_records(), UUID, This module extracts state and fixtures for one simulation bundle.  The extracto, This function records the default redaction decisions for one seed set.      Eve, This function returns a stable synthetic value for one identifier.      The same (+14 more)

### Community 81 - "answers.py"
Cohesion: 0.13
Nodes (18): build_cited_policy_answer(), CitedPolicyAnswer, BaseModel, Grounded policy answer assembly with strict citation validation., A policy answer whose citations resolve to retrieval hits., Resolve model citation IDs against the supplied hits.      Unknown IDs fail clos, EmbeddingDimensionMismatch, EmbeddingProviderUnavailable (+10 more)

### Community 82 - "app/errors.py"
Cohesion: 0.13
Nodes (18): FastAPI, application_exception_handler(), Exception, JSONResponse, Request, This module provides safe application error responses., This function maps expected and unexpected failures to stable, safe responses., _fake_session() (+10 more)

### Community 83 - "scan_payload"
Cohesion: 0.13
Nodes (18): _audit_markdown(), AuditReport, BaseModel, This module defines the stable Phase 7 audit report.  The report separates obser, This class stores one complete privacy, isolation, and reproducibility audit., _flag(), This module scans saved bundles and reports for secrets and forbidden data.  The, This function scans one JSON document and returns every finding. (+10 more)

### Community 84 - "app/config.py"
Cohesion: 0.13
Nodes (17): This module loads application configuration from environment variables., build_live_settings(), live_model_config(), live_settings(), This module defines fixtures for live Phase 2 checks that require credentials., If the environment lacks model settings, this function returns None.      Otherw, This module tests live span export through LangSmith and OpenTelemetry.  If the, live_lab_models() (+9 more)

### Community 85 - "SourceDocument"
Cohesion: 0.14
Nodes (17): chunk_document(), Split text into stable whitespace tokens., Return stable chunks in source order., Chunk one document with explicit deterministic settings., _tokens(), DocumentChunk, BaseModel, UUID (+9 more)

### Community 86 - "OpenAIEmbeddingProvider"
Cohesion: 0.14
Nodes (13): FakeEmbeddingProvider, _normalise(), OpenAIEmbeddingProvider, Any, Embedding providers.  Only this module imports the OpenAI SDK.  The rest of the, A deterministic local embedding provider for tests and offline replay., The sanctioned OpenAI embedding adapter with a pinned model contract., FakeClient (+5 more)

### Community 87 - "test_runs_api.py"
Cohesion: 0.16
Nodes (20): build_scripted_model(), FunctionModel, This function builds a scripted model that follows one plan.      The first invo, build_scripted_model(), _client(), _fixtures(), install_scripted_model(), _make_app() (+12 more)

### Community 88 - "test_suite_runner.py"
Cohesion: 0.25
Nodes (21): escalate_plan(), This function plans an escalation turn with no tool calls., _bundle(), _candidate_model(), install_keyed_scripted_model(), _measurementless_copy(), MonkeyPatch, This module tests the baseline/candidate suite comparison for checkpoint 7.2.  A (+13 more)

### Community 89 - "RecordedOrderLookup"
Cohesion: 0.20
Nodes (20): normalize_arguments(), This function canonicalizes tool arguments for exact matching.      Equivalent s, This adapter replays approved order lookup responses.      Tool ``get_order_stat, RecordedOrderLookup, _order_table(), This module tests recorded-read adapters for checkpoint 4.3.  Recorded reads mat, test_malformed_response_returns_stable_error(), test_non_normalizable_arguments_fail_closed() (+12 more)

### Community 90 - "test_compare.py"
Cohesion: 0.29
Nodes (20): compare_runs(), make_bundle(), make_run(), ReasonCode, This module tests the evidence-linked comparison (checkpoint 6.6).  A comparison, Bind test runs to the supplied bundle before exercising comparison behavior., test_budget_regression_counts_as_regression(), test_candidate_passes_when_it_fixes_a_failed_evaluator() (+12 more)

### Community 91 - "UUID"
Cohesion: 0.12
Nodes (12): RefundProposal, _error_code(), Exception, UUID, This method returns the pending proposal for one order.          If no proposal, This method returns the confirmed refund result for one order.          If no re, This method returns the order after the bound customer passes the ownership chec, Retrieve the policy and, when configured, exact evidence for the query. (+4 more)

### Community 92 - "test_contract.py"
Cohesion: 0.17
Nodes (18): plan_turn(), This function decides the next step from the routing decision alone.      If a r, make_routing(), make_settings(), Any, This module checks the typed contract for the agent.  This module checks the rou, test_confidence_out_of_range_rejected(), test_invalid_route_intent_rejected() (+10 more)

### Community 93 - "ObservedSupportRepository"
Cohesion: 0.15
Nodes (6): ObservedSupportRepository, UUID, Delegate to the real repository and report accepted database writes.      An opt, UUID, This class rejects every access to simulate a failing boundary., _RejectingRepository

### Community 94 - "InMemorySupportRepository"
Cohesion: 0.19
Nodes (12): InMemorySupportRepository, UUID, PostgreSQL checkpoint acceptance for the controlled workflow., make_order(), make_request(), Request, UUID, test_forbidden_maps_to_safe_http_body_without_order_data() (+4 more)

### Community 95 - "test_cases_api.py"
Cohesion: 0.18
Nodes (12): InMemorySuiteRepository, UUID, This module provides an in-memory regression suite repository for unit tests., _bundle(), _client(), _fixtures(), TestClient, This module tests the HTTP routes for cases and suites for checkpoint 7.3.  A tr (+4 more)

### Community 96 - "DependencyAdapter"
Cohesion: 0.12
Nodes (7): DependencyAdapter, Protocol, This method returns the registered adapters in construction order., This method returns the adapter that offers one tool, if any., This method describes every registered adapter., This protocol defines the minimum operations of every adapter.      Recorded ada, test_recorded_and_stateful_adapters_satisfy_the_same_contract()

### Community 97 - "DependencyCallResult"
Cohesion: 0.18
Nodes (6): DependencyCallResult, This method routes one simulated dependency call.          An unknown tool raise, This class stores the outcome of one simulated dependency call., This method routes one dependency call through the real support path., UUID, This method handles one simulated support dependency call.

### Community 98 - "test_dataset_split.py"
Cohesion: 0.18
Nodes (14): build_dataset_manifest(), DatasetCaseRef, BaseModel, Deterministic, leakage-safe regression dataset manifests.  A source trace family, One immutable regression case version included in a dataset., A versioned deterministic train/evaluation split., Return the stable source family used to prevent evaluation leakage., Group immutable cases by source family and assign each family once. (+6 more)

### Community 99 - "create_app"
Cohesion: 0.19
Nodes (12): create_app(), make_test_settings(), test_domain_error_maps_to_safe_stable_response(), test_unexpected_error_does_not_leak_message_in_production(), HealthySession, make_test_settings(), StalledSession, test_healthz_stays_live_when_database_dependency_is_broken() (+4 more)

### Community 100 - "_bundle"
Cohesion: 0.23
Nodes (16): _bundle(), ReviewDecision, This module tests the SimulationBundle schema for checkpoint 5.1.  The schema in, _review(), test_bundle_derives_identifier_from_content(), test_bundle_hash_is_stable_and_content_sensitive(), test_bundle_rejects_forbidden_resource_seed(), test_bundle_rejects_forged_identifier() (+8 more)

### Community 101 - "SimulationAdapterRegistry"
Cohesion: 0.23
Nodes (15): This class routes simulated calls by tool name and reports coverage., SimulationAdapterRegistry, This module tests coverage reports and path selection for checkpoint 4.5.  The r, test_alternate_supported_path_uses_stateful_adapter(), test_coverage_report_flags_missing_requirements(), test_coverage_report_lists_stateful_transitions(), test_coverage_report_lists_supported_dependencies(), test_duplicate_tool_across_adapters_is_rejected() (+7 more)

### Community 102 - "BraintrustRecordedSource"
Cohesion: 0.19
Nodes (9): BraintrustRecordedSource, Path, This method returns the recorded Braintrust trace as evidence., This method returns the recorded trace when it matches the query., This class serves one recorded Braintrust trace from a JSON fixture., This module tests adapter portability for checkpoint 3.5.  One recorded Braintru, test_braintrust_cohort_fetch_matches_same_query(), test_braintrust_recorded_trace_maps_to_valid_evidence() (+1 more)

### Community 103 - "test_logging.py"
Cohesion: 0.20
Nodes (10): LogRecord, configure_logging(), JsonFormatter, This module provides structured application logging., This class formats each application log record as one JSON object per line., This function configures the request logger once for the process., HealthySession, make_test_settings() (+2 more)

### Community 104 - "ReferenceRun"
Cohesion: 0.14
Nodes (8): Protocol, This protocol defines one tool of a reference workflow., This protocol defines the disposable state container of one workflow., ReferenceRepository, ReferenceTool, BaseModel, This class stores one normalized reference workflow run.      The final state an, ReferenceRun

### Community 105 - "agent/test_scenarios.py"
Cohesion: 0.15
Nodes (4): StrEnum, ScenarioCategory, This module checks the eight fixed scenario definitions., test_scenarios_cover_eight_distinct_layers()

### Community 106 - "env.py"
Cohesion: 0.23
Nodes (9): apply_migrations(), database_configuration(), This module configures Alembic for asynchronous PostgreSQL migrations., This function runs migrations without a database connection., This function connects through the asynchronous driver.      This function appli, run_async_migrations(), run_migrations_offline(), run_migrations_online() (+1 more)

### Community 107 - "command"
Cohesion: 0.17
Nodes (11): command, enabled, type, mcp, browsermcp, plugin, $schema, @browsermcp/mcp@0.1.3 (+3 more)

### Community 108 - "RunClient"
Cohesion: 0.33
Nodes (3): Protocol, This protocol defines the network operations the source adapter needs., RunClient

### Community 109 - "SeedRepository"
Cohesion: 0.25
Nodes (7): main(), _make_request(), UUID, This script runs one order-status or refund case manually with a hosted model., This repository stores minimal records for manual runs.      The repository does, SeedRepository, This module defines versioned instructions for the reference agent.  The constan

### Community 110 - "Vector"
Cohesion: 0.24
Nodes (5): Any, Small SQLAlchemy adapter for PostgreSQL's pgvector type.      Keeping this type, SQLAlchemy type for PostgreSQL's generated full-text vector., Tsvector, Vector

### Community 111 - "tracing.py"
Cohesion: 0.29
Nodes (8): query_hash(), Helpers for safe retrieval span attributes., Return a stable non-reversible identifier for a query., Record query identity without storing raw user text., Record safe hit IDs, ranks, and scores for a stage., record_retrieval_hits(), record_retrieval_query(), test_retrieval_tracing_uses_query_hash_and_safe_hit_attributes()

### Community 112 - "test_fault_scripts.py"
Cohesion: 0.38
Nodes (9): _linked_scenario(), This module tests how bundles carry versioned fault scripts safely.  Fault scrip, test_bundle_schema_rejects_undeclared_fault_tool_on_load(), test_compile_bundle_carries_the_fault_script_deterministically(), test_compile_bundle_rejects_fault_script_for_undeclared_dependency(), test_compile_bundle_rejects_secret_like_fault_arguments(), test_compile_bundle_rejects_undeclared_fault_tool(), test_compile_bundle_scans_fault_arguments_for_forbidden_content() (+1 more)

### Community 113 - "test_fixtures.py"
Cohesion: 0.22
Nodes (3): This module verifies the reference workflow fixtures are deterministic and self-, _scenario_hash(), test_scenario_content_hashes_are_stable()

### Community 114 - "support/test_api.py"
Cohesion: 0.44
Nodes (8): make_client(), make_service(), Exception, TestClient, test_order_lookup_route_returns_public_order(), test_refund_route_returns_refunded_order(), test_support_routes_return_typed_errors(), test_ticket_route_creates_open_ticket()

### Community 115 - "test_lab_api.py"
Cohesion: 0.36
Nodes (7): AsyncClient, apply_lab_api_migrations(), _bundle(), MonkeyPatch, This module tests the Phase 7 HTTP routes against isolated PostgreSQL.  A truste, test_lab_api_saves_suite_runs_and_streams(), _wait_for()

### Community 116 - "VectorType"
Cohesion: 0.33
Nodes (4): Migration-only declaration for the pgvector column., upgrade(), VectorType, UserDefinedType

### Community 117 - "health_router.py"
Cohesion: 0.38
Nodes (5): AsyncSession, JSONResponse, This module defines routes that check the application's health., readiness(), readiness_check()

### Community 118 - "Any"
Cohesion: 0.29
Nodes (6): _append(), _mutate(), Any, This function appends one record to a tuple field of the state., This function records one observed state transition., _state()

### Community 119 - "mutation_event_attributes"
Cohesion: 0.33
Nodes (5): mutation_event_attributes(), Scalar, This function keeps short scalar values for the event transcript., This function maps one state mutation to allowlisted event attributes., _scalar_or_none()

### Community 120 - "0001_baseline.py"
Cohesion: 0.40
Nodes (4): downgrade(), This function creates the initial revision without tables for product data., This function returns the database to a schema that excludes product tables., upgrade()

### Community 121 - "test_database.py"
Cohesion: 0.70
Nodes (4): current_revision(), database_url_or_skip(), test_migrations_upgrade_downgrade_and_reapply(), test_session_executes_select_one()

### Community 123 - "domain/user_simulator/__init__.py"
Cohesion: 0.50
Nodes (3): __getattr__(), Any, Hosted-model user simulation with allowlisted run artifacts.  The package root s

## Knowledge Gaps
- **8 isolated node(s):** `$schema`, `opencode-browser`, `type`, `npx`, `-y` (+3 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **28 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TraceRecorder` connect `TraceRecorder` to `simulator.py`, `RoutingDecision`, `workflow/service.py`, `PostgresSupportSandbox`, `pydantic_ai_agent.py`, `simulation/runner.py`, `test_simulator.py`, `SupportRequest`, `agent/service.py`, `support/schemas.py`, `support/seed.py`, `nodes.py`, `run_bundle`, `RetrievalHit`, `live/test_scenarios.py`, `build_tracer`, `test_nodes.py`, `UUID`, `ObservedSupportRepository`, `SeedRepository`, `tracing.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `SimulationEvent` connect `SimulationEvent` to `RoutingDecision`, `FlowRegistry`, `user_simulator/events.py`, `TextualSimulatorApp`, `ReferenceRun`, `suite/runner.py`, `simulation/runner.py`, `test_simulator.py`, `run_reference_case`, `ExecutionService`, `simulate.py`, `SimulationEventCollector`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `TextualSimulatorApp` connect `TextualSimulatorApp` to `simulator.py`, `SimulationEvent`, `FlowRegistry`, `EnvironmentProfileLike`, `simulate.py`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 63 inferred relationships involving `TraceRecorder` (e.g. with `main()` and `SeedRepository`) actually correct?**
  _`TraceRecorder` has 63 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `Settings` (e.g. with `SeedRepository` and `AgentTurnCommand`) actually correct?**
  _`Settings` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `compile_bundle()` (e.g. with `make_bundle()` and `make_policy_bundle()`) actually correct?**
  _`compile_bundle()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `RoutingDecision` (e.g. with `AgentDeps` and `AnswerDraft`) actually correct?**
  _`RoutingDecision` has 43 INFERRED edges - model-reasoned connections that need verification._