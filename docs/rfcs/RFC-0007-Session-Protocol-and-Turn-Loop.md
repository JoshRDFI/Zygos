# RFC-0007: Session Protocol and Turn Loop (FastAPI/WebSocket Adapter)

- **Status:** Accepted (2026-07-11)
- **Author:** Zygos maintainers
- **Created:** 2026-07-11
- **Governs:** the HTTP/WebSocket wire protocol between a browser (or any client)
  and the Zygos runtime — the REST resource surface, the multiplexed
  per-session WebSocket, its frame envelope and channel set — and the
  **turn loop**: how an incoming user message drives Memory, Reasoning/Model,
  and Tools to produce a streamed response, including cancellation/barge-in,
  the interactive permission round-trip, session identity and lifetime, and the
  runtime's startup/shutdown sequence once a server owns the event loop.
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the service contracts this layer
  consumes — `ModelService`, `MemoryService`, `ToolService`, §2; the
  layering/dependency rule §1; explicit state objects §4),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (the
  `ExecutionContext`, the `CancelToken`, the single-event-loop concurrency model,
  and the **observational-bus invariant** — dropping every subscriber must not
  change behavior),
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  (the pure `runtime_manifest()` §5, whose `GET /runtime` render surface was
  deferred to this milestone), and
  [RFC-0006](RFC-0006-Embedding-Contract-and-Hybrid-Memory-Retrieval.md) (the now
  async `MemoryService.retrieve()`/`search()`, `resume()`, and `embed_backlog()`
  that this layer is the first to await).
- **Amends** [RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md) — reconciles
  its §4 WebSocket channel naming (`text` → `chat`) and its flat
  "all-frames-are-control" sketch into the channel-typed envelope specified here.
  RFC-0005 is in **Review**, so it is updated to match before either RFC is
  accepted; RFC-0005 remains the authority for **audio payload semantics**, which
  this RFC only reserves envelope space for.
- **Completes deferred surfaces:** RFC-0003 `GET /runtime` and RFC-0005 §4's
  "specified there, built in M8" WebSocket protocol.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); this RFC
  locks the protocol and turn-loop design. It is **Milestone 8**, and the build
  is expected to decompose into cycles (server/lifecycle/inspection surface →
  WebSocket + session + chat turn loop → tools/permissions/trace/memory
  integration), decided when the RFC is accepted.

## Summary

Give Zygos a **server and a turn loop**. Specify one REST surface for resources
(sessions, runtime manifest, health) and one **multiplexed WebSocket per session**
carrying a `{channel, type, payload}` JSON envelope over four channels —
`chat`, `tools`, `trace`, `control` — plus two reserved binary audio channels.
Specify the **turn loop** that an incoming `chat:user_message` drives: retrieve
memory, run reasoning (or stream the model directly when reasoning is off),
invoke tools with an interactive permission prompt over the socket, stream the
result back, and record the exchange. The runtime becomes the thing that owns the
async event loop: it drains memory at startup, advances the lifecycle to *Accept
Requests*, and closes gracefully. The full wire protocol is **frozen now** so it
never needs a versioned migration; the build implements every channel **except
audio**, whose frames are reserved for the voice milestone to fill in without a
protocol change.

## Motivation

Every service Zygos has built so far — providers, the reasoning engine, the
layered memory system, the tool suite, the capability registry — has been a
**library with no caller**. `MemoryService` and `ToolService` are explicitly "not
load-bearing"; the reasoning engine runs only from the eval harness; the
capability manifest renders to a CLI but not to the `GET /runtime` its own RFC
promised. Milestone 8 is where all of it becomes a running system a person can
talk to.

The milestone order was resequenced specifically to reach this point cleanly.
Memory (M4), tools (M5), and semantic retrieval (RFC-0006) were built **before**
M8 precisely so the turn loop is written once, against final service shapes,
rather than reworked as each producer lands. This RFC honors that intent: it is
the first consumer of the async `MemoryService.retrieve()`, the first caller of
`ToolService.execute_stream()`, the first thing to construct a real
`ExecutionContext` per user turn and trip its `CancelToken`, and the first
subscriber to the event bus that turns observations into something a human sees.

M8 also exposes a **real network server that can run shell, file, and HTTP tools**.
That raises the protocol from a convenience to a security boundary: the permission
gate must become interactive without becoming a soft touch, and the default bind
must not put `run_command` on the network. The design treats both as first-class.

Finally, voice (RFC-0005) and the React UI depend on this protocol. RFC-0005
already **specifies** its audio channels but defers building them to M8's adapter.
Freezing the whole envelope now — audio channels included, even though M8 does not
build them — means voice and the UI extend a stable contract rather than forcing a
protocol revision the moment they arrive.

## Problem Statement

The runtime has no server, no session concept, and no turn loop. Concretely:

1. **No HTTP/WebSocket layer exists at all.** There is no FastAPI app, no route,
   no frame codec. `GET /runtime` (RFC-0003) and the `/ws/session/{id}` protocol
   (RFC-0005 §4, ARCHITECTURE §API Surface) are documented but uncoded.

2. **The two governing docs disagree on the wire.** ARCHITECTURE.md names JSON
   channels `chat`/`tools`/`trace`/`control`; RFC-0005 §4 names `text`/`trace`/
   `control` and models `turn.start`/`partial`/`final`/`tts.*` as flat control
   frames. There is no single authoritative frame taxonomy.

3. **`build_runtime()` is synchronous and stops early.** It returns a
   `RuntimeAssembly` at the `register_capabilities` lifecycle stage; it does
   **not** await `MemoryService.resume()` or `embed_backlog()` (a comment defers
   that to "the async consumer, M8") and never advances the lifecycle further.
   Nothing owns the async loop, the startup memory drain, or graceful shutdown.

4. **`ReasoningService` cannot be shared across concurrent turns.**
   `DefaultReasoningService.run()` raises `RuntimeError` if re-entered because it
   holds per-run state, yet bootstrap builds exactly one instance. A turn loop
   that reuses it across sessions would corrupt state or crash.

5. **Key seams are missing or unexposed.** `ToolService` is never built in
   bootstrap and is absent from `RuntimeAssembly`; the `ProviderRouter` (which
   holds live circuit state) is buried inside `DefaultModelService`; no session
   concept, `SessionState`, or server config section exists.

6. **The interactive permission resolver was deferred here.** The tool
   permission model has a `PermissionResolver` seam whose only implementations
   deny (headless) or allow (dev). The `ask` decision — the entire point of an
   interactive tool — has no producer; M5-C2 explicitly reserved "M8 wires a
   WebSocket resolver."

7. **The trace channel has no producer.** No `TraceService` exists. The only live
   observations are six event payloads on the bus; nothing turns them into frames.

8. **The manifest cannot report embedder health honestly.** `runtime_manifest()`
   is pure and static; the registry's health source only knows chat-route circuit
   state, so off-route embedding backends (the default `local` embedder has no
   route) render as `unhealthy` even when embedding works — RFC-0006's carried
   T7 finding.

## Proposed Design

### 1. Transport and framing

Two surfaces, one authoritative envelope.

- **REST** handles request/response resources (§4). **One WebSocket per session**
  at `/ws/session/{id}` carries all real-time traffic, so there is one connection,
  one (future) auth handshake, and no cross-socket ordering to coordinate — a
  property that matters on a self-hosted, single-user deployment.

- **JSON text frames** use the envelope `{channel, type, payload}`. `channel` is
  one of `chat`, `tools`, `trace`, `control`. `type` is a channel-scoped
  discriminator; `payload` is a channel/type-specific JSON object. Every frame is
  self-describing: a client dispatches on `(channel, type)` alone.

- **Binary frames** carry a **1-byte channel tag** prefix for `audio.in`
  (`0x01`) and `audio.out` (`0x02`), followed by the raw payload (PCM baseline;
  Opus optional, negotiated in the `control` handshake). **These channels are
  frozen in this RFC but not built in M8** — they are the voice milestone's to
  implement, and RFC-0005 governs their payload semantics.

Rationale: a single channel-tagged envelope is the taxonomy ARCHITECTURE.md
already commits to. Making each channel type-tagged (rather than RFC-0005's flat
control frames) lets the React UI render an independent conversation pane, tools
pane, and trace pane off one socket without inferring structure.

### 2. Channels and frame types (frozen now)

| Channel | Direction | `type` values | Notes |
|---|---|---|---|
| `chat` | both | `user_message` (→srv); `turn.start`, `token`, `turn.end`, `error` (→cli) | The conversation. STT `partial`/`final` map here in the voice build. |
| `tools` | both | `call`, `chunk`, `result`, `permission` (→cli); `permission_response` (→srv) | Tool-call lifecycle + the interactive permission round-trip. |
| `trace` | →cli | `event` | Mirrors one emitted bus payload; `payload` carries the event's own `type` + fields. |
| `control` | both | `hello`/handshake, `auth` (reserved), `cancel`, `error`, `ping`/`pong` | Session/codec negotiation, barge-in/abort, protocol errors. |
| `audio.in` | →srv | *(binary)* | **Reserved** — voice build (RFC-0005). |
| `audio.out` | →cli | *(binary)* | **Reserved** — voice build (RFC-0005). |

The frame **set** is frozen; a frame `type` a build does not yet produce (e.g.
audio, STT `partial`) is simply never sent. Clients must ignore unknown
`(channel, type)` pairs — the one forward-compatibility rule.

### 3. Sessions

A **session** is one conversation. It owns exactly one stable root
`ExecutionContext` minted on the event bus; that context's **`run_id` is the
memory trail id**, so a session is a memory trail and every turn within it is a
`ctx.child(turn_id)` span — episodic memory naturally groups by conversation.

- Sessions live in an in-memory **`SessionRegistry`**. Each has a
  **`SessionState`** exposed only as a **pull-snapshot** (RFC-0002 puller
  precedent): id, created-at, turn count, current turn status, connection state.
- **One live WebSocket per session.** A second connection to the same id replaces
  the socket (the runtime is single-user; this is reconnect, not multiplexing).
- The session retains the turn's **`CancelToken`** so a `control:cancel` frame can
  trip it (§6).
- Conversation state is **in-memory for the connection's lifetime**. Durable
  experience still persists through the memory layer (episodic writes). **Persisted,
  re-openable conversation threads** that survive a restart are deferred to a later
  increment; the memory layer, not the session layer, owns durability.

### 4. REST surface

| Method + path | Purpose |
|---|---|
| `POST /sessions` | Mint a session; returns `{ id }`. Server-authoritative id. |
| `GET /sessions` | List live sessions (snapshots). |
| `GET /sessions/{id}` | One `SessionState` snapshot. |
| `DELETE /sessions/{id}` | Close a session (cancels an active turn, drops the socket). |
| `GET /runtime` | The **pure** `runtime_manifest()` render (RFC-0003 §5) — static config, no network. |
| `GET /runtime/health` | **Live** status (§8): router circuit snapshot, tri-state embedder health, active-session count. |

### 5. The turn loop

On a `chat:user_message` frame for session *S*:

1. **Mint a turn context** — `ctx = S.root.child(turn_id)`; emit `chat:turn.start`.
2. **Retrieve memory** (if enabled) — `await memory_service.retrieve(ctx,
   query=message)`; fold results into the prompt context. Retrieval is
   **advisory** (RFC-0006): a transient failure degrades, never aborts the turn.
3. **Generate:**
   - **Reasoning off** — `model_service.stream(ctx, request)` yields
     `GenerationChunk`s → emitted as `chat:token` frames, live.
   - **Reasoning on** — construct a **fresh** `DefaultReasoningService(
     model_service, config.reasoning)` for this turn and `await run(ctx, input)`.
     The final answer is delivered at `chat:turn.end`; reasoning progress
     (`request.started`, `model.selected`, loop/confidence) is visible on the
     `trace` channel throughout. *(Streaming the final reasoning pass as
     `chat:token` frames is a noted enhancement, not required for M8.)*
   Constructing per turn means no shared reasoning state, no lock, and concurrent
   sessions with no head-of-line blocking; the re-entrancy guard becomes a
   belt-and-suspenders invariant never hit in normal flow.
4. **Tools** (§7) run inline where the model requests them, framed on `tools`.
5. **Record** the exchange — `memory_service.store(...)` (synchronous, episodic;
   consolidation and `embed_backlog` stay deferred).
6. **Finish** — emit `chat:turn.end` (final text + a turn-end `ReasoningState`/
   confidence summary when reasoning ran).

`chat` and `tools` frames are produced **directly by the turn loop as
load-bearing output** — never routed through the event bus. Routing the user's
actual reply through an observational bus would make output depend on a
subscriber, violating RFC-0002's core invariant. Output is not observation.

### 6. Cancellation and barge-in

A `control:cancel` frame trips the active turn's `CancelToken`. The router,
reasoning engine, and tool executor already poll `ctx.cancelled` cooperatively
and abort; a cancelled tool returns `tool_cancelled`. This is the single mechanism
behind both a UI "stop" button and RFC-0005 voice barge-in (which aborts in-flight
TTS the same way). Disconnecting the socket cancels the session's active turn and
denies any pending permission prompt.

### 7. Tools, permissions, and wiring

- **Framing.** The turn loop drives `ToolService.execute` / `execute_stream` and
  emits `tools` frames directly: `call` when a tool is invoked, `chunk` for
  streamed output, `result` on completion.

- **Interactive permission — `WebSocketPromptResolver`** (net-new, per the M5-C2
  seam). When a tool's permission is `ask`, the resolver sends a
  `tools:permission` frame carrying the tool name and `args_summary`
  (`PermissionRequest` already provides this; **no secrets**), then awaits a
  `tools:permission_response` correlated by `call_id`. **A timeout, or the socket
  dropping mid-prompt, resolves to `deny`** — the deny-floor honest-threat-model
  posture; silent execution on inaction is exactly what the floor prevents. One
  shared resolver routes each prompt to the right socket via `ctx.session_id`
  through the `SessionRegistry`. Sticky per-session "always allow" is a noted
  later refinement.

- **Wiring.** Bootstrap builds `ToolService` and exposes it on `RuntimeAssembly`.
  A new **`ToolsConfig`** (§9) declares which in-tree tools are enabled and
  per-tool permission/timeout overrides — config declares what activates, nothing
  auto-activates (ADR-0003). External/entry-point tool-plugin **discovery** stays
  deferred: the MCP-connectivity RFC is the home for external tool sources.

- **Out of scope — a future RFC.** *How the model signals a tool call* (native
  provider function-calling vs. a ReAct-style text protocol) and *how tools are
  authored* (the conventions and contract for writing a tool) are their own
  concern, deferred to a dedicated future RFC. This RFC specifies only that a
  requested tool call runs through `ToolService`, is permission-gated, and is
  framed on the `tools` channel — not the mechanism by which the model decides to
  call one.

### 8. Manifest and live health (RFC-0006 T7)

`GET /runtime` renders the **pure, static** `Manifest` unchanged — RFC-0003's
"no side effects, no network" invariant is preserved.

A **separate** live surface, `GET /runtime/health` (and the equivalent
`zygos doctor --probe` posture over HTTP), reports what the static manifest cannot:

- the **live router circuit snapshot** (per-route breaker state), read from the
  now-exposed router;
- a **tri-state `EMBEDDING` health** — `healthy | unhealthy | not_probed` — whose
  **passive default is `not_probed`**. This resolves T7: an off-route embedding
  backend reads `not_probed`, never a false `unhealthy`. An **opt-in probe**
  (`--probe`) actively embeds a sentinel and flips the state to `healthy`/
  `unhealthy`. A small `Embedder` health-probe seam supports this;
- the **active-session count**.

The `trace` channel is the streaming complement to this REST snapshot: live
circuit transitions arrive as `trace:event` frames as they happen.

### 9. Bootstrap, config, and assembly deltas

- **`RuntimeAssembly` gains:** the built `ToolService`; a router-snapshot accessor
  (for `GET /runtime/health` and the trace bridge); a reasoning factory (or the
  `model_service` + `config.reasoning` needed to construct one per turn).
  `build_runtime()` **stays synchronous** — the server, owning the loop, performs
  all async startup itself.

- **Startup (the server owns the loop):** `build_runtime()` → `await
  memory_service.resume(ctx)` and `await embed_backlog(ctx)` to drain deferred
  memory work → advance `lifecycle_stage` through *Load Skills* (no-op today) →
  *Load Memory* → *Accept Requests*.

- **Shutdown (graceful):** stop accepting new turns → trip active `CancelToken`s →
  `await assembly.aclose()` (closes the memory store and HTTP client).

- **New config**, all additive and `extra="forbid"`:
  - **`ServerConfig`** — `host` (default `127.0.0.1`), `port`, request/prompt
    timeouts, and reserved codec/sample-rate defaults for the audio handshake.
  - **`ToolsConfig`** — enabled in-tree tools + per-tool permission/timeout
    overrides.

### 10. Trace channel

A per-session **bus-subscriber bridge** subscribes to the `InProcessEventBus` and
mirrors each emitted payload into a `trace:event` frame, filtered by the event
envelope's `run_id`/`session_id` so it reaches the right socket. The six live
payloads (`route.claimed`, `circuit.opened`/`closed`, `request.started`/
`finished`, `model.selected`) become a live inspection stream with **zero new
service and zero new event types**. The subscriber is a pure observer: dropping it
changes no behavior, exactly the consumer RFC-0002's observational invariant was
written for. A full `TraceService` (state registry, `snapshot_state`,
`zygos trace`) remains deferred to its own milestone.

### 11. Auth

**Default bind `127.0.0.1`, no auth on loopback** — the OS user boundary is the
trust boundary, the same honest-threat-model posture the tool suite takes. The
protocol **reserves** a `control:auth` handshake frame so authentication can be
added later without a wire change, but building real auth (token issuance, TLS,
secret provisioning via RFC-0004) is **deferred to the Deployment/Installer RFC**,
which owns droplet exposure. Binding to a non-loopback interface without that work
is out of scope and should be gated behind explicit configuration when it lands.

## Alternatives Considered

**Text-first, minimal envelope (defer tools/trace/audio channels to later RFCs).**
Smaller and faster to accept, but the wire protocol would then churn every time a
channel is added, forcing client-side protocol versioning and the "reworked twice"
arch debt the milestone order exists to avoid. Rejected in favor of freezing the
full envelope once and building incrementally behind it.

**Feed the tools channel from new `tool.*`/`memory.*` bus events.** Appealing
given the bus is a first-class abstraction, but to make the tools channel reliable
those events would have to be load-bearing — contradicting RFC-0002's rule that
dropping every subscriber changes nothing. The turn loop already orchestrates tool
calls, so it frames them directly; the bus stays observational. `tool.*`/`memory.*`
events can be added later, purely for a future audit/trace consumer, when one
exists.

**Build a `TraceService` now as the trace producer.** It would pull a whole
prospective milestone into M8 for ~80% of the value the six already-emitted events
give through a subscriber. Deferred; the bridge ships the channel now.

**Enrich `runtime_manifest()` with live health (one endpoint).** Simpler surface,
but health probing is IO/network and would break RFC-0003's "pure, no network"
invariant, requiring an amendment. A separate `/runtime/health` surface keeps the
manifest pure.

**Share one `ReasoningService` with a global lock, or one per session.** A global
lock serializes unrelated turns (a voice turn blocks a text turn) and reintroduces
the locking RFC-0002 avoids. One-per-session relies on a serialization invariant
that, if violated by a bug, crashes on the re-entrancy guard. Constructing per turn
is cheapest to reason about and degrades most gracefully.

**Persisted sessions/threads now; connection-implicit (client-chosen) session
ids.** Persistence duplicates what the memory layer already stores durably and
exceeds what the wire protocol needs frozen; client-chosen ids surrender
server-authoritative identity and complicate later auth. Both rejected for M8.

**Interactive permission that defaults to allow on timeout, or a pure config-flag
mode with no prompt.** The former silently runs an `ask`-gated tool the user never
approved; the latter removes interactive tools entirely (a regression to headless).
Both rejected against the honest threat model.

**Build shared-secret auth now; or bind `0.0.0.0` with no auth.** The first
overlaps and likely reworks the Deployment/Installer RFC's remit; the second puts
`run_command` on the network by default. Loopback-default with a reserved auth
frame is the honest, minimal stance.

## Migration Plan

This RFC adds a new top-level adapter; it changes no existing service contract, so
there are no consumers to migrate. The concrete moves:

1. **RFC-0005 reconciliation.** Update RFC-0005 §4's channel naming (`text` →
   `chat`) and fold its flat control-frame list into the channel-typed envelope
   here. RFC-0005 is in Review, so this happens before either RFC is accepted; its
   audio-payload semantics are unchanged.
2. **Bootstrap additions** (§9) are additive: new `RuntimeAssembly` fields, new
   config sections (`extra="forbid"` means an unknown key already fails loudly, so
   these are safe to introduce). `build_runtime()` stays sync; existing callers
   (the CLI, the eval harness) are unaffected because they never needed the async
   drain.
3. **The lifecycle** advances past `register_capabilities` for the first time —
   the ARCHITECTURE.md lifecycle table's "Planned — M8" stages become real.
4. **ARCHITECTURE.md doc-pass** owed at M8 (SVG redraw, API Surface section,
   Runtime Lifecycle narrative) is folded into the build.

Existing tests and the headless CLI/eval paths keep working; the server is purely
additive and the core services remain usable without it.

## Risks

- **A network server that can run shell/file/HTTP tools.** Mitigated by the
  loopback-default bind, the deny-floor interactive permission gate, and the tool
  suite's own defense-in-depth (root confinement, SSRF guard, no-shell argv). Real
  network exposure is explicitly deferred to the Deployment/Installer RFC.
- **The permission round-trip stalls a turn.** A tool waiting on a human could
  hang; mitigated by the configurable prompt timeout that resolves to `deny`, and
  by disconnect-denies-pending-prompts.
- **Per-turn `ReasoningService` construction hides a shared-state assumption.**
  Mitigated by constructing over the already-atomic `ModelService`/router (whose
  concurrency is RFC-0002-governed) and keeping the re-entrancy guard as a backstop.
- **The trace bridge subscribes to a process-global bus.** A mis-filtered frame
  could leak one session's trace to another's socket; mitigated by strict
  `run_id`/`session_id` filtering and covered by test.
- **Freezing audio frames before building them.** If the voice build discovers the
  reserved envelope is wrong, the protocol churns anyway. Mitigated by RFC-0005
  having already specified those frames concretely; this RFC only reserves the
  space it described.
- **Startup memory drain latency.** `resume()`/`embed_backlog()` on a large store
  could delay *Accept Requests*; mitigated by draining being resumable/idempotent
  (RFC-0006) so it can run in the background past readiness if needed.

## Acceptance Criteria

1. A client can `POST /sessions`, open `/ws/session/{id}`, send a
   `chat:user_message`, and receive `chat:turn.start` … `chat:token`\* …
   `chat:turn.end` for a complete turn, with reasoning **off** (model streaming)
   and **on** (per-turn `ReasoningService`).
2. The JSON envelope `{channel, type, payload}` and the frozen channel/type set
   (§2) are implemented for `chat`, `tools`, `trace`, `control`; `audio.in`/
   `audio.out` are reserved (tagged, unbuilt); unknown `(channel, type)` pairs are
   ignored by the client contract.
3. A `control:cancel` frame (and a socket disconnect) trips the turn's
   `CancelToken` and aborts an in-flight generation/tool within the cooperative
   cancellation points.
4. A tool with permission `ask` produces a `tools:permission` prompt (no secrets),
   proceeds on `allow`, and is **denied on timeout and on disconnect**; the
   resolver routes to the correct session.
5. In-tree tools are registered from `ToolsConfig`; a disabled tool is absent and a
   per-tool permission override is honored.
6. The `trace` channel streams `trace:event` frames mirroring the six emitted bus
   payloads, correctly scoped to the originating session; with **all** subscribers
   dropped, turn behavior is byte-identical (RFC-0002 invariant test).
7. `GET /runtime` renders the pure static `Manifest` with no network access;
   `GET /runtime/health` reports live router circuit state, a tri-state `EMBEDDING`
   health whose passive default is `not_probed` (no false `unhealthy` for an
   off-route embedder), and the active-session count.
8. On startup the server drains `resume()`/`embed_backlog()` and advances the
   lifecycle to *Accept Requests*; on shutdown it cancels active turns and calls
   `aclose()`.
9. `ServerConfig` defaults to binding `127.0.0.1`; there is no auth on loopback and
   a `control:auth` frame is reserved but unenforced.
10. The core services remain usable headless (the CLI and eval harness paths pass
    unchanged); the server layer is additive.

## Architectural Impact

- **Does this increase coupling between services?** It adds one **top-level adapter**
  (`api`/`server`: FastAPI app, WebSocket handler, `SessionRegistry`/`SessionState`,
  the turn loop, `WebSocketPromptResolver`, the trace bridge, the health surface)
  that depends on the existing services. The coupling is **one-way**: the adapter
  depends on Model/Memory/Tools/Reasoning/registry; **no service gains a dependency
  on the adapter**. This is the intended shape of a composition/adapter layer and
  mirrors the eval-harness precedent.
- **Does this create hidden state at service boundaries?** Session state is held in
  the `SessionRegistry` but exposed only as a **pull-snapshot** (`SessionState`),
  and per-turn `ExecutionContext`/`CancelToken` are explicit objects, not ambient
  globals. No hidden mutable state escapes a boundary.
- **Does this bypass a service boundary from a prior RFC?** No. It consumes
  `ExecutionContext`, the bus, and the service contracts as designed. Framing
  `chat`/`tools` output **directly** (not via the bus) is a deliberate honoring of
  RFC-0002 — output must not be observational — not a bypass of it.
- **Does it violate the Constitution?** No. It advances **inspectability**
  (trace channel + manifest + live health), the **honest threat model** (deny-floor
  permission, loopback default, no security theater), and **stable interfaces**
  (the whole wire protocol is frozen once). It **amends RFC-0005** (channel-name
  reconciliation, while it is still in Review) and **completes** deferred surfaces
  of RFC-0003 and RFC-0005 rather than reopening them.
- **Can it be tested independently?** Yes. The frame codec, `SessionRegistry`, the
  turn loop, the prompt resolver, the trace bridge, and the health surface are each
  testable with fakes — `FakeProvider`, a fake WebSocket, `FakeEmbedder` — with no
  network, following the no-key test discipline.
- **New service, or existing one?** A new **adapter layer**, plus net-new
  `SessionRegistry`/`SessionState` and one `WebSocketPromptResolver`. No new *domain*
  service: no `TraceService` (bridge instead), no `SessionService` persistence layer
  (in-memory registry instead) — both deferred to their own future RFCs.
- **Can it be removed later without affecting the runtime core?** Yes. The core
  services already run headless (CLI, eval harness). Removing the server removes the
  turn loop and the network surface, not the runtime.
