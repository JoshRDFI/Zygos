# Zygos Architecture

This document describes the v2 system design. Architectural decisions are recorded as
RFCs in [`docs/rfcs/`](./docs/rfcs/); the governing decision record for this design is
[RFC-0001: Service Architecture](./docs/rfcs/RFC-0001-Service-Architecture.md). The v1
TypeScript runtime, which v2 migrates from, is documented in
[Appendix A](#appendix-a--v1-reference-implementation).

---

![Zygos runtime architecture: Browser → Adapters (web server + CLI) → Runtime (composition root, per-session turn loop) → Event Bus → Services (model routing, memory, tools, reasoning) → Providers → Models, with the Capability Registry above the services](./docs/assets/architecture.svg)

## Layering

```
frontend (React + Tailwind + Vite)
        │  HTTP / WebSocket
backend/api        ── FastAPI adapter (REST + WS)
backend/cli        ── CLI adapter
        │  imports (one direction only)
backend/runtime    ── composition root, session loop, state objects
backend/services   ── service Protocols + default implementations
backend/plugins    ── config-declared implementations (providers, tools, voice…)
```

The dependency rule is strict and unidirectional: the runtime core (`runtime/`,
`services/`) imports nothing from `api/`, `cli/`, or any web framework. FastAPI never
appears below the adapter layer. Experience with v1 showed that convention alone is not
sufficient; the rule is therefore enforced mechanically by
`backend/tests/test_architecture.py` today, and will be supplemented by an
[import-linter](https://import-linter.readthedocs.io) contract in CI once
`zygos/api` exists. A failing build is the signal — not a code review comment.

---

## Services

Each service is defined as a `typing.Protocol` (structural interface) with one default
implementation. Consumers type against the Protocol only; no service imports another
service's concrete class. The nine service contracts are:

| Service | Contract (abridged) | Ports from v1 |
|---|---|---|
| `ModelService` | `classify_task`, `select_model`, `generate`, `stream` | provider router, protocol adapters |
| `MemoryService` | `store`, `retrieve`, `search`, `summarize`, `embed_backlog` | context manager/storage/compaction (layered: working, episodic, semantic, procedural); retrieval pluggable — lexical (FTS5) / vector / hybrid ([RFC-0006](./docs/rfcs/README.md#index)) |
| `ToolService` | `register`, `execute`, `execute_stream` | tool registry/executors, permissions, validation |
| `SkillService` | `discover`, `rank`, `execute`, `propose` | learning manager concepts |
| `TraceService` | `begin_trace`, `record_event`, `snapshot_state`, `finish_trace`, `reflect` | provider observability (extended) |
| `ConfigService` | `load`, `validate`, `get` | config loader/schema (Pydantic) |
| `PluginService` | `resolve(kind, name) -> type` | — (new) |
| `SchedulerService` | `schedule`, `cancel`, `list` | — (interface only; implementation deferred to the scheduler and autonomy milestone) |
| `VoiceService` | `transcribe_stream(audio) -> text events`, `synthesize_stream(text) -> audio` | — (new; engines built per RFC-0005 — faster-whisper STT, Kokoro TTS, opt-in, default `fake`) |

`VoiceService` was defined from the start so that the transport and service layers were
voice-shaped before concrete STT/TTS engines were selected. Those engines are now built
per [RFC-0005](./docs/rfcs/RFC-0005-Voice-Interaction-STT-and-TTS.md): local-first
faster-whisper transcription and Kokoro synthesis, run through the sidecar seam as
config-declared plugins. They are **opt-in** — the default is a silent `fake` engine, so
voice pulls no extra dependencies or model weights unless enabled — and each is
byte-identical to the fake on its non-voice path. Optional cloud fallbacks remain scoped
in the RFC. The engines drive the live web UI (RFC-0011): mic capture → STT, TTS playback,
a browser Silero VAD for hands-free turn-taking, and duck-then-stop barge-in.

---

## Wiring

All services take their dependencies as constructor parameters typed against Protocols.
There is no DI framework and no service locator — plain constructors keep the wiring
inspectable and testable.

One module, `backend/zygos/runtime/bootstrap.py`, is the composition root. It reads
validated Pydantic config, resolves plugin classes via `backend/zygos/plugins/resolver.py`,
and assembles the object graph. It is the only module permitted to construct concrete
service implementations. Any logic beyond construction and connection is a
review-blocking smell.

Plugins are **config-declared**: the config file maps a plugin kind and name to a
fully-qualified module path. For example:

```yaml
providers:
  ollama: "zygos_plugins.providers.ollama:OllamaProvider"
```

Reading the config tells you exactly what code runs. Nothing auto-activates from the
filesystem or installed entry points. Entry-point discovery is deliberately deferred to
the community-ecosystem milestone and its RFC, after a community exists to need it.

---

## Runtime Lifecycle

Every run of the runtime moves through the same fixed sequence of stages. The
lifecycle is the backbone the milestones fill in: stages never reorder, they
only gain implementations.

```
Bootstrap
  → Load Configuration
  → Resolve Plugins
  → Initialize Services
  → Register Capabilities
  → Load Skills
  → Load Memory
  → Start Scheduler
  → Accept Requests
  → Execute
  → Graceful Shutdown
```

| Stage | Status |
|---|---|
| Bootstrap | Implemented — `backend/zygos/runtime/bootstrap.py` (M1) |
| Load Configuration | Implemented — Pydantic schema + loader (M1) |
| Resolve Plugins | Implemented — config-declared resolver (M1, [ADR-0003](./docs/adr/ADR-0003-config-declared-plugins.md)) |
| Initialize Services | Implemented — constructor injection at the composition root (M1, [ADR-0002](./docs/adr/ADR-0002-constructor-injection.md)) |
| Register Capabilities | Implemented — capability registry (M3 Cycle 3, [RFC-0003](./docs/rfcs/README.md#index)) |
| Load Skills | Planned — M6 (`SkillService`) |
| Load Memory | Implemented — `MemoryService` wired at bootstrap (M4); `resume()`/`embed_backlog()` drained at server startup (M8 Cycle 1) |
| Start Scheduler | Planned — scheduler & autonomy milestone |
| Accept Requests | Implemented — FastAPI adapter + `/ws/session/{id}` turn loop; `chat`, `tools`, and `trace` channels live (M8 Cycles 1–3) |
| Execute | Implemented — per-session chat-and-tools turn loop with reasoning and live, permission-gated tool-calling (M8 Cycles 2–3) |
| Graceful Shutdown | Implemented — lifespan drains deferred work, trips active turns, and closes resources (M8 Cycles 1–2); reverse-order teardown extends as later stages gain state |

One deliberate naming choice: the stage is **Resolve Plugins**, not "Discover
Plugins". Zygos loads exactly the plugins declared in configuration and never
scans the filesystem or installed packages for code
([ADR-0003](./docs/adr/ADR-0003-config-declared-plugins.md)). Detecting the
environment at install time, or reading user files as data at run time, is
unaffected — code is declared; data is discovered.

Graceful shutdown tears the stack down in reverse order. The guarantee the
[Tool Contract](#tool-contract) makes per-tool — `cleanup` always runs — applies
to the runtime as a whole.

---

## State and Introspection

All runtime state that v1 kept as hidden private fields becomes named, snapshotable
objects in v2:

- `RouterState` — per-route circuit-breaker status, rate-limit windows.
- `SessionState` — message history (typed, immutable Pydantic models), pending events.
- `ReasoningState` — RDT iteration history, confidence trajectory.

Each object is registered with `TraceService` and exposed via
`TraceService.snapshot_state()`. This is the data source the Introspection Console and
the test suite both read. The principle is direct: **state the console cannot see is an
architecture bug**.

---

## Event Model (implemented — RFC-0002)

> **Implemented (M3 Cycle 1, 2026-07-05).** The event schema, delivery
> semantics, and the relationship to `ExecutionContext` are decided by RFC-0002
> ("Runtime Event Bus and ExecutionContext",
> [Accepted](./docs/rfcs/README.md#index)) and live in
> `backend/zygos/runtime/events.py` and `context.py`. Delivery is synchronous
> and error-isolated; observability is pull-based, so dropping every subscriber
> leaves behavior unchanged (the load-bearing puller invariant).

Every significant runtime action emits an event onto a runtime event bus:
request started, memory retrieved, skill executed, tool completed, model
selected, trace finalized. Facts are emitted as events; commands stay direct
service calls.

The event bus is first-class because of what it removes. Tracing, metrics, and
future plugins subscribe to events instead of coupling to service internals, so
a new subscriber — the Introspection Console, a metrics exporter, a third-party
extension — is added without modifying any emitting service.

## Capability Registry (implemented — RFC-0003)

> **Implemented (M3 Cycle 3, 2026-07-09).** The registry contract is decided by
> RFC-0003 ("Capability Registry, Runtime Manifest, and Inspection",
> [Accepted](./docs/rfcs/README.md#index)) and lives in
> `backend/zygos/runtime/capabilities.py` and `manifest.py`, surfaced by the
> `zygos inspect`/`zygos doctor` CLI. Resolution is pull-based and health-ranked
> — it never subscribes, honoring the RFC-0002 puller invariant.

Services ask the registry "who can satisfy the *Vision* capability?" rather
than asking a specific provider "do you support vision?". Capabilities are a
closed, RFC-extensible set that includes local inference, embedding (added by
[RFC-0006](./docs/rfcs/README.md#index)), web search, speech (STT/TTS), image
generation, scheduling, and filesystem access.

The registry is the mechanism behind the Constitution's "Every component must
be replaceable": consumers bind to capabilities, never to implementations —
which is also what makes capability renegotiation possible when a provider
fails.

---

## Tool Contract

Tools implement a four-phase Protocol. Only `execute` is mandatory; the other three
phases default to no-ops, so trivial tools carry zero boilerplate.

```python
class Tool(Protocol):
    meta: ToolMeta
    def prepare(self, ctx: ToolContext) -> None: ...        # optional; default no-op
    async def execute(self, input: BaseModel, ctx: ToolContext) -> Any: ...  # required
    def verify(self, output: Any, ctx: ToolContext) -> VerifyResult: ...
        # optional; default = output-schema validation
    def cleanup(self, ctx: ToolContext) -> None: ...        # optional; default no-op
```

The executor guarantees that `cleanup` runs whether or not `execute` or `verify`
raised — `finally` semantics. This formalizes the guarantee v1 had to hand-roll for
A/B-test rollback. `verify` failures produce a failed `ToolResult`; a malformed output
is never silently accepted. v1 semantics for retry policy, timeouts, permission checks,
streaming execution, and one-level fallback tools are preserved.

In v2 the model invokes tools through this contract inside the live turn loop, via native
function-calling normalized across providers
([RFC-0008](./docs/rfcs/RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md)). Config
declares which in-tree tools are active (the starter suite is enabled by default), and each
side-effecting call is permission-gated with an interactive prompt over the WebSocket. A
config rule can loosen a tool's default `ask` to `allow`, but a tool declared `deny` is a
hard floor config cannot lift.

---

## API Surface

REST handles request/response resources: sessions, config, skills, plans, proposals.

**Live (M8):**

- `GET /runtime` — renders the pure static runtime `Manifest` (config summary,
  capabilities, routes, versions); no network, no mutation. (Cycle 1)
- `GET /runtime/health` — live status: per-route circuit snapshot, tri-state embedder
  health (`healthy`/`unhealthy`/`not_probed`; default `not_probed`, `?probe=1` actively
  probes), and active-session count. (Cycle 1)
- `POST /sessions` → session id; `GET /sessions` — the in-memory session registry. (Cycle 2)

Each session has one multiplexed WebSocket at `/ws/session/{id}`. All real-time traffic
flows over that single connection:

- **JSON frames** — `{channel, type, payload}` on channels `chat`, `tools`, `trace`, and
  `control`.
  - `chat` — `user_message` in; `turn.start` / `token` (streaming, non-tool turns) /
    `turn.end` / `error` out.
  - `tools` — the turn loop emits `call` and `result` frames as each tool runs; when a tool
    needs approval it emits a `permission` frame (tool name + argument summary, **never
    secrets**), answered by a `permission_response` correlated by `call_id`. A prompt
    timeout or a dropped socket resolves to **deny** — the deny-floor. (Cycle 3)
  - `trace` — a per-session bridge mirrors emitted bus events for live inspection.
  - `control` — `cancel` / `ping` / `hello`; a mid-turn `user_message` is a barge-in.
- **Binary frames** — prefixed with a 1-byte channel tag: `0x00` for `audio.in` (mic → STT,
  PCM s16 mono LE @ 16 kHz) and `0x01` for `audio.out` (TTS → speaker, PCM s16 @ 24 kHz).
  **Built (RFC-0005 / RFC-0011).** Capture is bracketed by `control` frames `audio.start` /
  `audio.endpoint`; `control:audio.output {enabled}` toggles the speaker; and the `audio.out`
  channel carries `tts.begin` / `tts.end` plus `tts.duck {gain}` / `tts.unduck {gain}` for
  barge-in attenuation. The codec is PCM today; Opus negotiation remains a reserved extension.
- **Barge-in** — a mid-turn `user_message` (or a `control` cancel) trips the active turn.
  For voice, the browser sends `control:audio.vad {state: onset|speech|silence}`: an onset
  **ducks** in-flight TTS (a reversible gain drop), confirmed **speech stops** the turn, and
  silence (or a timeout) restores full volume — a two-stage duck-then-stop that drains each
  utterance to exactly one terminal frame so turns never desync. Because all channels share
  one socket, barge-in requires no cross-socket coordination.

One connection means one auth handshake and no cross-socket ordering problems — a
property that matters on self-hosted, single-user deployments.

---

## Errors and Messages

A unified `ZygosError` exception hierarchy carries a stable, machine-readable error-code
taxonomy ported from v1 (e.g. `tool_timeout`, `tool_permission_denied`). Adapters map
`ZygosError` to HTTP status codes or WebSocket error frames; the runtime never raises
bare exceptions across a service boundary.

Session messages are typed, immutable Pydantic models. Tool results are structured
members of the message union — never JSON strings spliced into content. The v1 defect
class where `engine.ts:282` serialized tool results into free-text content is
unrepresentable in the v2 type system.

---

## Deployment

Zygos is a self-hosted web application. The intended targets are a user's own machine
and droplet-class cloud VMs. There is no Electron wrapper and no managed-platform
assumption. A single install command verifies Python, creates a virtual environment,
installs dependencies, builds the frontend, initialises the database, and launches the
server.

---

## Current Implementation Status

Milestones 1–5 and Milestone 8 are complete: config schema/loader and config-declared
plugin resolver (M1), provider router + `ModelService` (M2), the adaptive reasoning engine
plus the RFC-0002 event bus and RFC-0003 capability registry (M3), layered `MemoryService`
(M4), and `ToolService` with the starter tool suite (M5) — together with RFC-0006 embedding
+ hybrid retrieval, and **M8**, the FastAPI/WebSocket adapter with a live per-session turn
loop and native tool-calling (RFC-0007 session protocol + RFC-0008 tool-calling), M8's first
consumer of `MemoryService` and `ToolService`. M8 ran as four cycles: server/lifecycle/inspection,
WebSocket/session/chat turn loop, the tool-calling library, and live tool-calling in the turn loop.

Since M8, **voice** and the **React web UI** have landed (as of 2026-07-17):
[RFC-0005](./docs/rfcs/RFC-0005-Voice-Interaction-STT-and-TTS.md) engines — faster-whisper STT
and Kokoro TTS behind the `VoiceService` seam (opt-in, default `fake`), a single-session voice
gate, and duck-then-stop barge-in; and [RFC-0011](./docs/rfcs/RFC-0011-React-UI-Frontend-Architecture.md)'s
`frontend/` (React + TS + Vite + Tailwind) delivering the shell, token themes, live chat over
the turn loop, read-only Inspect/Doctor/Models/Tools panels, and live voice controls (mic → STT,
TTS playback, browser Silero VAD for hands-free + barge-in). Files/Memory surfaces and model
selection are still placeholders. The backend suite has 735 tests passing; the frontend adds a
Vitest suite (71 tests). Next are M6 (learning) and M7 (workflows), the scheduler, and a
single-command installer. See [ROADMAP.md](./ROADMAP.md) for the full milestone plan.

---

## Appendix A — v1 Reference Implementation

The v1 TypeScript runtime is frozen (Stage 0: bugfixes only). It is the reference the
Python migration ports from; concepts that worked are preserved, structural problems
identified in the v1 review are fixed. Six subsystems make up the frozen runtime:

**Providers + router + protocol adapters** (`src/providers/`). Model routing with
Ollama, OpenAI, Anthropic, and vLLM backends; per-route credential validation;
observability metrics including `RdtMetrics`. Protocol adapters normalise
provider-specific request/response shapes. The v2 counterpart is `ModelService`.
See [docs/v1/PROVIDER_HARDENING.md](./docs/v1/PROVIDER_HARDENING.md).

**RDT runtime** (`src/reasoning/`). Prompt-orchestration layer implementing a
Prelude → Recurrent → Coda reasoning pipeline, confidence gating (coherence,
completeness, consistency metrics), adaptive compute heuristics, and attention mode
control. Operates entirely above the model API — no access to model internals required.
The v2 counterpart is `ReasoningState` and the RDT milestone (M3).
See [docs/v1/RDT_REASONING_GUIDE.md](./docs/v1/RDT_REASONING_GUIDE.md).

**Context management** (`src/context/`). Layered memory with SQLite in WAL mode and an
FTS5 full-text index. Modules cover persistent storage (`storage.ts`), orchestration
(`manager.ts`), token budgeting and hard-limit enforcement (`budget.ts`), compaction and
summarisation (`compaction.ts`), and FTS5 retrieval (`search.ts`). The v2 counterpart is
`MemoryService`.
See [docs/v1/CONTEXT_MANAGEMENT_GUIDE.md](./docs/v1/CONTEXT_MANAGEMENT_GUIDE.md).

**Tool framework** (`src/tools/`). Tool registry, permission checks, retry policy,
timeouts, and streaming execution. The A/B-test incident — where a hand-rolled
`try/finally` was needed to restore the live registry — directly motivated the four-phase
`prepare/execute/verify/cleanup` contract in v2.
See [docs/v1/TOOL_DEVELOPMENT_GUIDE.md](./docs/v1/TOOL_DEVELOPMENT_GUIDE.md).

**Learning system** (`src/learning/`). Observation collection, proposal generation,
A/B testing against sandboxed tool candidates, approval workflows, version history, and
audit logging. Ships with `approval_mode: manual` and `auto_apply_low_risk: false` as the
only defaults — self-improvement is never autonomous. The v2 counterpart is `SkillService`.
See [docs/v1/LEARNING_SYSTEM_GUIDE.md](./docs/v1/LEARNING_SYSTEM_GUIDE.md).

**Interviewer** (`src/interviewer/`). Multi-turn requirements-gathering sessions with
adaptive follow-up questions, complexity-gated build-request interception, and
transcript-to-plan conversion (requirements, constraints, risks, effort estimation, phase
roadmap). Persisted to SQLite; exportable as JSON or Markdown. Ports to v2 as an
interviewer workflow plugin.
See [docs/v1/INTERVIEWER_WORKFLOW_GUIDE.md](./docs/v1/INTERVIEWER_WORKFLOW_GUIDE.md).
