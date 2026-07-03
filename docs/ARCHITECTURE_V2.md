# Architecture Reference

Zygos follows the design blueprint from `/home/ubuntu/zygos_design/ARCHITECTURE_V2.md`.

## Phase 4 Context Management Additions

### New modules
- `src/context/storage.ts`: SQLite-backed persistent context storage with WAL mode, migration table, and FTS5 index.
- `src/context/manager.ts`: orchestration layer for retrieval, token planning, compaction, memory extraction, caching, and session snapshots.
- `src/context/budget.ts`: token budgeting, next-turn prediction, hard-limit enforcement, and analytics reporting.
- `src/context/compaction.ts`: compaction + summarization engine preserving recent and critical turns.
- `src/context/search.ts`: FTS5 query and memory retrieval integration.
- `src/types/context.types.ts`: type-safe context contracts.

### Runtime integration
- `QueryEngine` now prepares context before model streaming when a `ContextManager` dependency is present.
- Turn artifacts (user/assistant/tool) are persisted through `ContextManager.postTurnUpdate`.
- Tool execution receives context snapshots/facts in execution context.
- CLI supports history retrieval via `--history-search <query> --session <session_id>`.

### Persistence model
- SQLite schema includes: `sessions`, `turns`, `turns_fts`, `memories`, `conversation_clusters`, `session_cluster_links`, and `schema_migrations`.
- Context compaction marks stale turns as compacted and inserts summary turns.
- Backup/restore supported through database-level backup/restore operations.

## Phase 5 RDT Runtime Additions

### New modules
- `src/reasoning/rdt-runtime.ts`: Runtime orchestration for Prelude → Recurrent → Coda reasoning.
- `src/reasoning/confidence.ts`: Confidence metrics (coherence, completeness, consistency), adaptive thresholding, early-exit/revision decisions.
- `src/reasoning/attention.ts`: Attention mode control (MLA/GQA simulation), sparse MoE expert routing, load balancing, adaptive compute heuristics.
- `src/types/rdt.types.ts`: Type-safe contracts for RDT configuration, stage state, progress events, loop controls, and quality metrics.

### Runtime integration
- `QueryEngine` executes the optional `RDT_OPTIONAL` stage when `config.rdt.enabled === true`.
- `QueryEngine` emits:
  - `rdt_progress` for stage/iteration/backtrack/parallel-path/quality/trace events.
  - `rdt_observability` for summarized RDT metrics.
- `TurnResult` now optionally includes `rdt` summary metadata (loops, confidence, early halt, quality averages).
- `createEngine` wires RDT into provider routing with profile-aware configuration (`shallow`, `balanced`, `deep`).

### Orchestration pattern (model-agnostic)
- Because Ollama/vLLM endpoints do not expose model internals, RDT is implemented as a runtime prompt-orchestration layer:
  1. **Prelude** prompt initializes state and decomposes the problem.
  2. **Recurrent** prompts iteratively refine latent summaries using shared-weight simulation patterns.
  3. **Coda** prompt synthesizes final answer from best reasoning state.
- Confidence gating and adaptive compute govern loop depth and early exit.

### Observability and quality
- RDT traces can be streamed in-progress without exposing chain-of-thought.
- Quality metrics are tracked per iteration and aggregated in final results.
- `src/providers/observability.ts` includes `RdtMetrics` for runtime rollups.


## Phase 6 Self-Learning Additions

### New modules
- `src/learning/manager.ts`: orchestrates observation, proposal generation, approval/apply workflows, A/B test checks, rollback, and metrics.
- `src/learning/modification.ts`: computes tool performance metrics and creates tool modification proposals from runtime outcomes.
- `src/learning/creation.ts`: detects repeated unresolved patterns and generates template-based tools with safety checks.
- `src/learning/versioning.ts`: SQLite persistence for observations, proposals, versions, A/B tests, audit trail, and learning state.
- `src/types/learning.types.ts`: strongly-typed learning contracts for persistence, approvals, proposals, and version metadata.

### Runtime integration
- `createEngine` now initializes `LearningManager` and injects it into `QueryEngine` dependencies.
- `QueryEngine` records tool observations after batch execution and triggers a learning cycle.
- New engine events:
  - `learning_cycle` (proposals generated/applied)
  - `learning_applied` (proposal-level application event)
- `ToolRegistry` supports dynamic update/remove to allow safe runtime modification and creation.

### Persistence and audit model
- Learning state is persisted in `.zygos/learning.db` (or `ZYGOS_LEARNING_DB`).
- Key SQLite tables:
  - `learning_observations`
  - `learning_proposals`
  - `tool_versions`
  - `learning_ab_tests`
  - `learning_audit`
  - `learning_state`

### Safety and rollback
- Generated tools are constrained to allowlisted templates and safe metadata checks.
- Modification proposals are validated with side-by-side A/B checks before apply.
- Tool version history supports rollback to prior states with audit logging.
- The learning subsystem is enabled by default, with bounded proposal/test parameters from config.


## Phase 7 Interactive Interviewer Workflow Additions

### New modules
- `src/interviewer/interviewer.ts`: interview session orchestration (multi-turn Q&A, adaptive follow-ups, completion logic, gating checks, SQLite transcript + plan persistence, provider-assisted question polishing).
- `src/interviewer/plan-generator.ts`: transcript-to-plan conversion (requirements/constraints/risks extraction, complexity/effort estimation, phase/task roadmap creation, JSON + Markdown export).
- `src/types/interviewer.types.ts`: strongly-typed contracts for sessions, questions, answers, extracted requirements, build plans, templates, exports, metrics, and manager APIs.

### Runtime integration
- `createEngine` now initializes `Interviewer` and injects it into `QueryEngine` dependencies.
- `QueryEngine.runTurn` intercepts:
  - explicit interview mode (`mode: 'interview'`), and
  - complex standard requests when interview gating is enabled.
- New engine events:
  - `interview_progress`
  - `interview_plan_generated`
  - `interview_metrics`
- Interview turns are also persisted via context post-turn updates for searchable transcript continuity.

### Gating + workflow behavior
- Complexity scoring is applied to incoming build requests.
- For complex requests, interview completion is required before build execution unless override is explicitly enabled and provided.
- Supports actioned interview commands: start, answer, status, complete, plan export.

### Persistence model
- Interview data is persisted to SQLite (default `.zygos/context.db`, override via `ZYGOS_INTERVIEW_DB`):
  - `interview_sessions`
  - `interview_turns`
  - `build_plans` (versioned)

### Configuration and templates
- New `interview` config block controls enablement, gating threshold, max question count, override behavior, and template selection.
- Built-in templates: `web_app`, `data_pipeline`, `api_service`, `tool_utility`, `general`.
- Template override supports fixed-template execution for customized org workflows.
