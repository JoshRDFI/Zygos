# RFC-0001: Service Architecture

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-03
- **Governs:** Zygos 2.0 runtime core, service contracts, wiring, and API adapter design

## Motivation

Zygos 2.0 migrates the proven TypeScript v1 runtime to a Python-first AI runtime
(ZYGOS_V2_IMPLEMENTATION.md). The migration's core principle is "do not rewrite —
migrate": preserve the concepts that work (provider routing, RDT reasoning,
layered context, learning, tools) while fixing the architectural debts the v1
code review identified. This RFC defines the service architecture every
subsequent RFC and implementation phase builds on.

Two requirements sharpen the design beyond the original vision documents:

1. **Voice interaction (STT input, TTS output) must land before 2.0 is
   complete.** The transport and service layers must be voice-shaped from day
   one, not retrofitted.
2. **Deployment target is a self-hosted web page** — a user's own machine or a
   droplet-class cloud VM. No Electron, no managed-platform assumptions.

## Problem Statement

The v1 review (2026-07-03) found good service concepts undermined by five
structural problems, all of which this RFC must resolve for v2:

1. **Tool contract gap.** The vision specifies `prepare/execute/verify/cleanup`;
   v1 only ever implemented `execute`. The gap had real cost: v1's A/B test
   mutated the live tool registry and needed a hand-rolled `try/finally` restore
   (the exact guarantee a `cleanup` phase provides).
2. **Bootstrap coupling.** v1's `bootstrap.ts` hardcodes 21 concrete
   constructions, including every provider. "Swappable providers" requires code
   edits, violating the constitution.
3. **Hidden state.** Engine event queues (`__queuedEvents`), router
   circuit-breaker/rate-limit maps, and confidence history are private mutable
   state with no accessors — which also makes the planned Introspection Console
   unbuildable.
4. **Provider-specific coupling in generic code.** The router checks
   OpenAI/Anthropic credential env vars by name.
5. **Type-unsafe seams.** Tool results serialized to JSON strings inside
   message history; unvalidated casts.

## Proposed Design

### 1. Layering and the dependency rule

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

- The runtime core (`runtime/`, `services/`) imports **nothing** from `api/`,
  `cli/`, or any web framework. FastAPI never appears below the adapter layer.
- The rule is enforced mechanically: an
  [import-linter](https://import-linter.readthedocs.io) contract in CI fails the
  build on an inward-pointing violation. Convention alone demonstrably decayed
  in v1.

### 2. Service contracts

Each service is defined as a `typing.Protocol` (structural interface) with one
default implementation. Consumers type against the Protocol only; services never
import each other's concrete classes.

| Service | Contract (abridged) | Ports from v1 |
|---|---|---|
| ModelService | `classify_task`, `select_model`, `generate`, `stream` | provider router, protocol adapters |
| MemoryService | `store`, `retrieve`, `search`, `summarize` | context manager/storage/compaction (layered: working, episodic, semantic, procedural) |
| ToolService | `register`, `execute`, `execute_stream` | tool registry/executors, permissions, validation |
| SkillService | `discover`, `rank`, `execute`, `propose` | learning manager concepts |
| TraceService | `begin_trace`, `record_event`, `snapshot_state`, `finish_trace`, `reflect` | provider observability (extended) |
| ConfigService | `load`, `validate`, `get` | config loader/schema (Pydantic) |
| PluginService | `resolve(kind, name) -> type` | — (new) |
| SchedulerService | `schedule`, `cancel`, `list` | — (interface only; implementation deferred to Phase 7) |
| VoiceService | `transcribe_stream(audio) -> text events`, `synthesize_stream(text) -> audio` | — (interface only; engines arrive in the voice RFC) |

VoiceService is defined **now** so the architecture is voice-shaped from the
start; concrete STT/TTS engines (local-first Whisper-family and Piper/Kokoro-class,
with optional cloud fallbacks) are scoped in the dedicated voice RFC.

### 3. Wiring: constructor injection + composition root

- Every service takes its dependencies as constructor parameters typed against
  Protocols.
- One composition root (`runtime/bootstrap.py`) reads validated Pydantic
  config, resolves plugin classes, and assembles the object graph. It is the
  only module allowed to construct concrete service implementations.
- **Plugins are config-declared**: config maps a plugin kind and name to a
  module path (`providers.ollama: "zygos_plugins.providers.ollama:OllamaProvider"`).
  Reading the config tells you exactly what code runs. Pip-installable
  entry-point discovery is deferred to the Phase 8 ecosystem RFC.
- No DI framework, no service locator. Plain constructors keep the wiring
  inspectable and testable, per the constitution's "simplicity over cleverness."

### 4. Explicit state objects (no hidden state)

All runtime state that v1 hid becomes named, immutable-snapshot state objects:

- `RouterState` — per-route circuit-breaker status, rate-limit windows.
- `SessionState` — message history (typed, see §7), pending events.
- `ReasoningState` — RDT iteration history, confidence trajectory.

Each is registered with TraceService and exposed via
`TraceService.snapshot_state()`, which is what the Introspection Console (and
tests) read. A component holding state the console cannot see is an
architecture bug by definition.

### 5. Tool contract: four phases, optional hooks

```python
class Tool(Protocol):
    meta: ToolMeta
    def prepare(self, ctx: ToolContext) -> None: ...        # optional; default no-op
    async def execute(self, input: BaseModel, ctx: ToolContext) -> Any: ...  # required
    def verify(self, output: Any, ctx: ToolContext) -> VerifyResult: ...
        # optional; default = output-schema validation
    def cleanup(self, ctx: ToolContext) -> None: ...        # optional; default no-op
```

- Only `execute` is mandatory; trivial tools carry zero boilerplate.
- The executor guarantees `cleanup` runs **whether or not execute/verify
  raised** (`finally` semantics). This formalizes the guarantee v1 had to
  hand-roll for A/B-test rollback.
- `verify` failures produce a failed ToolResult, never a silently-accepted
  malformed output.
- v1 semantics preserved: retry policy, timeouts, permission checks,
  streaming execution, and one-level fallback tools (cycle-proof).

### 6. API adapter: REST + one multiplexed WebSocket

- REST for request/response resources: sessions, config, skills, plans,
  proposals.
- One WebSocket per session, `/ws/session/{id}`, multiplexing typed frames:
  - **JSON frames** `{channel, type, payload}` on channels `chat`, `tools`,
    `trace`, `control`.
  - **Binary frames** with a 1-byte channel tag prefix for `audio.in` /
    `audio.out` (PCM or Opus; negotiated in a `control` handshake).
  - **Barge-in** is a `control` frame that cancels in-flight TTS synthesis —
    trivial on a single socket, painful across two.
- One connection means one auth handshake and no cross-socket ordering
  problems on a self-hosted deployment.

### 7. Error handling and message typing

- A unified `ZygosError` exception hierarchy carries the error-code taxonomy
  ported from v1 (`tool_timeout`, `tool_permission_denied`, …). Adapters map it
  to HTTP/WS error frames; the runtime never raises bare exceptions across a
  service boundary.
- Session messages are typed, immutable Pydantic models. Tool results are
  structured members of the message union — never JSON strings spliced into
  content (v1's engine.ts:282 defect class is unrepresentable).

### 8. Constitution-inherited defaults

- Learning/skill self-modification ports with `approval_mode: manual` and
  `auto_apply_low_risk: false` as the only shipped defaults (constitution:
  "self-improvement is proposal-based, never autonomous").
- Missing credentials on the **primary** model route fail at startup; optional
  fallback routes degrade with a logged warning. Keyless local-first providers
  (Ollama-class) remain the zero-config default.

### 9. Testing strategy

- **Contract tests per Protocol**: one reusable suite per service interface;
  any implementation (default or plugin) must pass it.
- **Runtime tests need no server**: the composition root assembles a runtime
  with fake providers entirely in-process.
- **Adapter tests** cover REST/WS framing against a stub runtime.
- TDD is the working method for all v2 code, as it was for the v1 Stage-0
  fixes.

## Alternatives Considered

| Decision | Rejected alternative | Why rejected |
|---|---|---|
| Tool contract | All four phases required | Boilerplate tax on every trivial tool; optional hooks give the same guarantees where they matter |
| Tool contract | `execute`-only (amend vision) | Loses lifecycle guarantees the A/B-rollback incident proved necessary |
| Wiring | DI framework (dependency-injector) | Framework indirection makes wiring harder to inspect; unnecessary dependency |
| Wiring | Service registry / locator | Dependencies vanish from signatures — hidden state by another name |
| Streaming | Separate sockets per concern | Two auth handshakes, cross-socket sync, barge-in coordination pain |
| Streaming | WebRTC for audio | Best latency, but STUN/TURN + SDP is heavy for self-hosted droplets; revisit in the voice RFC if WS latency proves inadequate |
| Plugins | Entry-points discovery now | Auto-activation of installed-but-unlisted code weakens inspectability; premature before a community exists |
| Plugins | Drop-in plugins directory | Filesystem-implicit behavior; awkward for image-based droplet deploys |

## Migration Plan

Order of porting, each step a working, tested milestone (v1 stays frozen as the
reference; Stage 0 bugfix-only policy continues):

1. **Config** — Pydantic schema + loader (port fail-fast credential semantics).
2. **Providers + router** — ModelService with Ollama/OpenAI/Anthropic/vLLM
   plugins; RouterState explicit.
3. **RDT engine** — prelude/recurrent/coda pipeline, attention routing,
   confidence evaluation; ReasoningState explicit.
4. **Memory/context** — SQLite (WAL, FTS5) layered memory; compaction.
5. **Tools** — four-phase contract, executor, permissions, streaming, fallback.
6. **Learning → SkillService** — proposals, A/B testing (registry never mutated
   in place; candidate runs in a sandboxed copy), manual approval default.
7. **Interviewer/workflows** — as workflow plugins.
8. **FastAPI adapter + WS protocol**, then the React UI (separate RFC).

## Risks

- **Multiplexed WS latency for audio** on high-RTT droplet links. Mitigation:
  channel-tagged binary frames keep the option of moving `audio.*` channels to
  a dedicated transport (or WebRTC) behind the same VoiceService interface.
- **Protocol contracts drift from implementations.** Mitigation: contract test
  suites are part of the definition of done for every service.
- **Composition root grows into a god-module.** Mitigation: it may only
  construct and connect — any logic beyond assembly is a review-blocking smell.
- **Python asyncio complexity** replacing v1's promise-chain locking.
  Mitigation: standard asyncio primitives (locks, task groups) only; no custom
  scheduling.

## Acceptance Criteria

1. `import-linter` CI contract proves the runtime core has no adapter/framework
   imports.
2. Every service in §2 has a Protocol, a default implementation, and a passing
   contract test suite.
3. Providers are swappable via config alone — demonstrated by switching
   primary Ollama → OpenAI with zero code changes.
4. `TraceService.snapshot_state()` exposes router, session, and reasoning
   state; nothing in the runtime holds state invisible to it.
5. A tool that raises mid-execute still has `cleanup()` invoked (test-proven).
6. A WS client can stream chat + tool progress + trace events and exchange
   binary audio frames on one connection, including cancelling TTS mid-stream
   via a `control` frame.
7. Learning defaults ship as `approval_mode: manual`,
   `auto_apply_low_risk: false`.
8. The full runtime test suite runs with no server, no network, and no API keys.

## Architectural Fitness Test

| Question | Answer |
|---|---|
| More modular? | Yes — Protocol-per-service, plugins config-declared, one composition root |
| Introduces hidden state? | No — all runtime state in named snapshotable objects via TraceService |
| Replaceable later? | Yes — any service/plugin swaps behind its Protocol; contract tests define compatibility |
| Observable? | Yes — TraceService events + state snapshots are the Introspection Console's data source |
| Increases coupling? | No — one-directional dependency rule, mechanically enforced |
| Independently testable? | Yes — contract suites per Protocol; runtime runs serverless in tests |
| Preserves backwards compatibility? | v1 concepts and semantics preserved (routing, RDT, memory, tools, learning); v1 remains the frozen reference |
| Requires new configuration? | Yes — plugin declarations and WS settings; all declarative, validated by Pydantic |
| Increases cognitive load? | Net decrease — plain constructors and explicit state replace framework magic and hidden maps |
