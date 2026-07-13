# RFC-0009: Best-Model-Per-Task Routing and Multimodal Capabilities

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-13
- **Governs:** how Zygos routes each turn to the **best-suited model** and reaches
  **non-text capabilities** (vision input, image generation) without losing the
  working conversation — the per-turn selection of the authoring text model, the
  capability contracts for `VISION` and `IMAGE_GENERATION`, the three routing
  triggers (runtime-decided input routing, model-decided output tools, config-declared
  text-specialist routing), backend-agnostic capability binding (local / cloud /
  future remote-ephemeral), local model-residency (swap) orchestration, and the
  inspection surface for every routing decision.
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `Provider`/`ModelService`
  contract §2, `Message` typing §7, and the `Tool` contract §5),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (the event bus and
  `ExecutionContext` used to make routing decisions inspectable),
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md) (the
  capability registry, its `VISION`/`IMAGE_GENERATION` reserved-but-uncontracted
  enum slots this RFC fills, and pull-based health-ranked resolution),
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the turn loop and session
  thread that this RFC selects an authoring model for), and
  [RFC-0008](RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md) (the agentic loop,
  permission resolver, and `tools` channel that the image-generation path reuses).
- **Amends** [RFC-0001](RFC-0001-Service-Architecture.md) **§2**: makes
  `ModelService` per-turn model selection **load-bearing** — `select_model` currently
  computes a `RouteChoice` that `generate`/`stream` ignore; this RFC threads a
  selected route through generation. It does **not** change the `Provider` wire
  contract or `Message` typing. It **fills** (does not expand) the closed capability
  set from [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  as amended by [RFC-0006](RFC-0006-Embedding-Contract-and-Hybrid-Memory-Retrieval.md):
  the `VISION` and `IMAGE_GENERATION` members already exist; this RFC only adds their
  contracts.
- **Does not govern:** hardware-feasibility scoring (which local models *fit* — the
  model-picker task and its own RFC), remote-ephemeral provisioning (RunPod/DO
  spin-up→teardown — its own RFC, for which this RFC establishes the backend seam),
  voice STT/TTS ([RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md)), and adaptive
  reasoning-gated escalation (the reasoning-gating redesign RFC). Each is a named,
  deferred hook here.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md). This RFC is
  design-complete but built incrementally in four phases (see Migration Plan).

## Summary

No single model does everything, so stop pretending one does. Select the **authoring
text model per turn** (the "orchestrator" role is a role, not a fixed instance), and
bridge non-text work through **capability contracts** that convert to and from text at
the session-thread boundary. The **session owns a provider-agnostic message thread**;
"switching models" for text is a provider swap over that thread, so context is never
migrated. Three triggers, matched to three genuinely different situations:
**input modality** (an attached PDF/image) is detected by the runtime and routed to a
`VISION` satisfier; **output modality** (image generation) is a model-decided tool
(RFC-0008) backed by an `IMAGE_GENERATION` satisfier; **text-specialist routing**
(code / reasoning / fast models) is config-declared and **conservative by default** —
one chat model authors all text unless the operator declares task routes. Capability
satisfiers are **backend-agnostic**: local, cloud API, or (future) remote-ephemeral all
satisfy the same contract, so a heavy image model too large for local VRAM is bound to
a non-local backend without changing the calling path. When a satisfier *is* local, a
thin **model-residency** step swaps it in and out. Every routing decision is emitted on
the trace surface — no invisible switching.

## Motivation

Zygos is local-first, and local hardware is finite. A user on a single consumer GPU
cannot hold a chat model, a vision model, and an image-generation model in VRAM at
once — yet the work they want spans all three: "summarize this PDF," "make me an
image," "write this function." The current runtime assumes one text model per session
and has no path to a non-text capability at all.

The machinery is half-present and points the right way. `DefaultModelService` already
has `classify_task()` and `select_model()` — but `select_model` is **vestigial**: it
returns a `RouteChoice` that `generate`/`stream` throw away, always doing full failover
over every configured route. The `CapabilityRegistry` (RFC-0003) already **reserves**
`VISION` and `IMAGE_GENERATION` enum members but leaves them **uncontracted** — a
satisfier cannot be registered because no interface type exists for them. This RFC
makes the selection seam load-bearing and defines the two missing contracts.

Two forces shape the design. First, **context is sacred**: the user's explicit concern
is keeping the working conversation intact across a model change. The cleanest guarantee
is to never move context — keep it in the session and swap models around it. Second,
**honesty over theater** (the project constitution): routing that silently sends a turn
to the wrong model is a quality regression the user cannot see. So routing is
conservative by default and every decision is inspectable.

## Problem Statement

1. **One model can't cover the workload.** Text chat, document/image understanding, and
   image generation need different models; the runtime supports only the first.
2. **The selection seam is dead.** `ModelService.select_model` computes a choice that
   generation ignores; there is no load-bearing per-turn model selection.
3. **Two capabilities are named but unreachable.** `VISION` and `IMAGE_GENERATION` exist
   in the enum with no contract, so nothing can satisfy them.
4. **Local VRAM is a hard limit.** Specialists generally cannot coexist locally with the
   chat model; the runtime has no notion of model residency or swapping, and image
   generation is the worst case (a full chat-model unload).
5. **Placement is not abstracted.** There is no way to say "this capability runs in the
   cloud (or on rented compute) because it won't fit locally" without special-casing the
   caller.
6. **Switching would be invisible.** Nothing today would let a user see which model
   authored a turn or why a specialist was invoked.

## Proposed Design

### 1. The session thread is the context; the authoring model is per-turn

The session (RFC-0007) already holds the message history. This RFC makes that the
**single, provider-agnostic source of truth** for conversation context. Because all
text providers consume the same `Message` list (RFC-0001 §7, extended by RFC-0008),
handing the thread to a different text provider is a **provider swap, not a context
migration**. Context preservation across text models is therefore intrinsic — nothing
moves.

At turn start, `api/turn.py` asks `ModelService` for the **authoring route** for this
turn and generates against it. The "orchestrator" that holds the conversation and may
call tools is whichever text model authors the current turn.

### 2. `ModelService` selection becomes load-bearing (amends RFC-0001 §2)

`select_model(classification)` stays, but generation now honors a selected route:

```python
class ModelService(Protocol):
    def classify_task(self, prompt: str) -> TaskClassification: ...
    def select_model(self, classification: TaskClassification | None = None) -> RouteChoice: ...
    async def generate(
        self, ctx: ExecutionContext, request: GenerationRequest, *, route: RouteChoice | None = None
    ) -> GenerationResult: ...
    def stream(
        self, ctx: ExecutionContext, request: GenerationRequest, *, route: RouteChoice | None = None
    ) -> AsyncIterator[GenerationChunk]: ...
```

When `route` is given, the router authors the turn with that route (its own retry
policy applies) and, on hard failure of that route, falls back to the default chat
route — failover is preserved but **anchored to the selected route** rather than always
starting from the first configured one. When `route` is `None` (the default), behavior
is exactly today's: full failover from the first eligible route. This is the entire
behavioral amendment to RFC-0001 — additive and default-preserving.

### 3. Two new capability contracts (fills RFC-0003 reserved slots)

```python
class VisionAnalyzer(Protocol):
    name: str
    async def analyze(self, request: VisionRequest) -> VisionResult: ...   # media + text  -> text

class ImageGenerator(Protocol):
    name: str
    async def generate_image(self, request: ImageRequest) -> ImageResult: ...  # prompt -> image artifact
```

- `VisionRequest` carries text plus image/document parts; `VisionResult` returns **text**
  (extraction/description) that the session thread can hold. A multimodal `Provider` may
  satisfy `VisionAnalyzer` directly.
- `ImageRequest` carries a prompt and parameters; `ImageResult` returns an **image
  artifact** (bytes or a stored handle), **not** text.

`CAPABILITY_CONTRACTS` gains `VISION → VisionAnalyzer` and
`IMAGE_GENERATION → ImageGenerator`. Registration, health-ranking, and resolution use
the existing RFC-0003 registry unchanged. No satisfier is registered by default.

### 4. Three routing triggers, matched to three situations

**Path A — input modality (runtime-decided).** When a turn's input carries non-text
parts, the runtime resolves `VISION` and either (i) routes the whole turn to a
multimodal authoring model if one is bound and healthy, or (ii) runs a scoped
`VisionAnalyzer.analyze` sub-call, injects the returned text into the thread, and lets
the normal authoring model proceed. The preference between (i) and (ii) is configurable.
**No `VISION` satisfier → an explicit notice; the attachment is never silently dropped.**

**Path B — output modality (model-decided tool).** `IMAGE_GENERATION` is surfaced as an
RFC-0008 tool (`generate_image`), **offered to the authoring model only when an
`ImageGenerator` is bound and healthy** — dynamic tool availability driven by capability
resolution. The model calls it through the existing agentic loop; the call passes the
existing permission resolver; the returned artifact folds back as a tool result on the
thread and the `tools` channel. No new invocation machinery.

**Path C — text-specialist routing (config-declared, conservative default).** Per-turn
authoring selection among text models (code / reasoning / fast / default) via
`classify_task` → `task_routes`. **By default there are no task routes**, so one chat
model authors every text turn; specialist routing activates only when the operator
declares routes in config (the ADR-0003 config-declared pattern). This bounds the blast
radius of a crude classifier: misrouting cannot silently degrade an unconfigured
install.

### 5. Backend-agnostic capability binding (the placement seam)

A satisfier is bound the same way regardless of **where it runs**. Placement —
`local` (e.g. Ollama), `cloud` (an API), or (future) `remote-ephemeral` (rented
GPU, provisioned then torn down) — is a property of the **backend config**, not of the
contract or the caller. `generate_image` looks identical whether the `ImageGenerator`
is a local Stable-Diffusion process or a cloud endpoint. The future remote-ephemeral
RFC adds a third backend kind with a `provision → use → deprovision` lifecycle **behind
these same contracts**; this RFC guarantees the calling path never encodes local-vs-cloud
so that RFC needs no changes here.

### 6. Model-residency (swap) orchestration

Before invoking a **local** model (authoring or specialist), an `ensure_resident` step
loads it and may unload another to free VRAM (for Ollama, via `keep_alive` / explicit
load-unload). Cloud and remote backends are no-ops. Swap latency is surfaced as a trace
event and a user-visible notice ("loading vision model…"). This RFC owns the swap
**mechanism**; it **defers feasibility scoring** — "can this GPU run model X, and what
must be evicted" — to the model-picker task and its RFC, exposing an advisory hook the
residency step consults when present. **Image generation is the canonical heavy case**:
a local text→image model typically forces a *full* chat-model unload, so it has the
highest swap latency of any path and is the flagship motivator for cloud or
remote-ephemeral placement.

### 7. Context-fit across models

This RFC does **not** reinvent context management. The canonical thread stays put; when
a turn is authored by a model with a smaller window, the existing memory /
retrieve / compaction seam (M4) and per-model token limits (ADR-0006) govern what is
included. Switching the authoring model only changes which token limit applies.

### 8. Inspectability

Routing is never invisible. Two additions to the RFC-0002 event taxonomy (closed union,
extensible by RFC):

- `AuthoringModelSelected(provider, model, classification, reason)` — emitted at turn
  start.
- `CapabilityInvoked(capability, provider, placement, swapped)` — emitted when a
  specialist (vision / image-gen) is invoked, reusing RFC-0003 resolution.

Both appear on the `trace` channel (RFC-0007) and in runtime snapshots. The runtime
manifest (RFC-0003) reports which of `VISION` / `IMAGE_GENERATION` have healthy
satisfiers, so `zygos doctor` / `GET /runtime` show what the install can actually do.

## Alternatives Considered

- **Fixed orchestrator instance, specialists always tools.** One pinned chat model calls
  a `code_model` / `analyze_document` tool for everything. Rejected: awkward for input
  the user already provided (the model must "call a tool" to see an attachment), and it
  forces text-specialist work through a tool round-trip when a plain provider swap over
  the shared thread is simpler and cheaper.
- **True handoff / modes (primary model changes and drives).** The session's primary
  model changes and inherits the conversation. Rejected as the default: it makes context
  continuity the hard case (re-formatting/re-fitting per model) — the opposite of the
  user's priority — and muddies "who is in charge." Kept available conceptually but not
  built; the per-turn-authoring model subsumes its common cases.
- **Aggressive classify-and-route by default.** Route every text turn automatically.
  Rejected as default: a crude classifier silently misroutes, an unobservable quality
  regression. Offered as opt-in config instead.
- **Fold hardware-feasibility scoring into this RFC.** Rejected: much larger scope that
  merges a separate effort (model-picker). This RFC consumes an advisory hook instead.
- **Special-case cloud vs local at the call site.** Rejected: it would hardcode placement
  and block the remote-ephemeral RFC. Backend-agnostic binding is the seam instead.

## Migration Plan

Additive and **default-preserving**; built in four phases, each its own build cycle
(the project's protocol-complete / build-incremental pattern):

1. **Contracts + routing spine.** Define `VisionAnalyzer` / `ImageGenerator`, wire them
   into the registry, make per-turn authoring selection load-bearing (Path C mechanism,
   conservative default = no task routes), and add the two trace events. Lands with
   existing/fake backends — no new model required. Default behavior is byte-for-byte
   unchanged (no task routes, no satisfiers → single chat model, no capabilities).
2. **Path A — vision input routing**, with a real `VisionAnalyzer` backend.
3. **Path B — image-generation tool**, with a real `ImageGenerator`. Ships first against
   an **already-resident or cloud** generator; a **local heavy** image model needs
   phase 4 or the remote-ephemeral RFC (an honest dependency, not a surprise).
4. **Swap orchestration** — local model residency / unload.

Existing installs are unaffected until an operator opts in by configuring task routes or
capability satisfiers — mirroring the default-OFF posture of RFC-0006.

## Risks

- **Misrouting (Path C).** Mitigated by the conservative default (opt-in) and full
  routing inspectability, so a bad route is diagnosable from the trace.
- **Swap latency / thrash (Path B, local).** A chat↔image swap can be slow and, if
  alternated, thrashy. Mitigated by surfacing latency, keep-alive tuning, and steering
  heavy generators to cloud / remote placement; feasibility scoring (deferred) will
  refine eviction.
- **Silent capability gaps.** Mitigated by explicit notices, never dropping input, and
  manifest/doctor reporting of satisfier health.
- **Selection amendment regressions.** Threading `route` through `generate`/`stream`
  touches the router hot path; mitigated by keeping `route=None` exactly today's
  behavior and testing the anchored-failover path independently.
- **Scope creep toward feasibility/remote.** Mitigated by hard boundaries: this RFC owns
  routing + swap mechanism only; feasibility and remote-ephemeral are named, deferred
  RFCs with defined seams.

## Acceptance Criteria

1. `VisionAnalyzer` and `ImageGenerator` contracts exist; `CAPABILITY_CONTRACTS` maps
   `VISION`/`IMAGE_GENERATION` to them; a conforming satisfier can be registered and a
   non-conforming one is rejected (as with existing contracts).
2. `ModelService.generate`/`stream` accept an optional `route`; with `route=None`
   behavior is identical to today (full failover from first eligible); with a `route`,
   the turn is authored by that route and falls back to the default chat route on hard
   failure — both proven by test.
3. `api/turn.py` selects the authoring model per turn and emits
   `AuthoringModelSelected`.
4. **Default install is unchanged:** with no task routes and no satisfiers, one chat
   model authors every turn, no capabilities are advertised, and no image tool is
   offered.
5. **Path A:** an attached non-text part with a healthy `VISION` satisfier is routed
   (multimodal turn or scoped analyze→inject); with no satisfier, an explicit notice is
   produced and the attachment is not dropped.
6. **Path B:** `generate_image` is offered to the model only when a healthy
   `ImageGenerator` is bound; a call runs through the RFC-0008 loop and permission
   resolver and folds the artifact back onto the thread and `tools` channel; a failure
   yields a tool-error result.
7. **Path C:** with operator-declared task routes, turns are authored by the mapped
   model; the decision is visible in the trace.
8. Capability binding is placement-agnostic: the same satisfier interface is invoked
   identically for a local vs cloud backend (proven with two backends behind one
   contract), and a `placement` attribute is carried without the call site branching on
   it.
9. For a local satisfier, `ensure_resident` loads it (and may evict another) before
   invocation and emits `CapabilityInvoked(..., swapped=…)`; cloud/remote are no-ops.
10. The runtime manifest / `zygos doctor` report healthy-satisfier presence for
    `VISION` and `IMAGE_GENERATION`.

## Architectural Impact

- **Coupling.** Adds no service-to-service coupling: routing decisions live in
  `ModelService`/`api/turn.py`, capabilities resolve through the existing registry, and
  image-gen reuses the tool loop. The two new contracts are narrow protocols, not
  concrete dependencies.
- **Hidden state.** None at boundaries. The authoring route, capability resolution, and
  residency swaps are all emitted as events and visible in snapshots; the session thread
  is the single explicit context store.
- **Service boundaries.** Respects them: it fills RFC-0003's reserved capability slots
  through the registry rather than around it, and honors the RFC-0002 invariant (the
  registry still never subscribes; routing reads health via the pulled source).
- **Constitution.** Serves "honest, inspectable" (no silent switching; conservative
  default) and "local-first" (swap orchestration; placement abstraction for offload).
- **Independent testing.** Yes — contracts, anchored-failover selection, each path, and
  the residency step are separately testable with fake backends; phase 1 needs no real
  model.
- **New service?** No new long-lived service. `ensure_resident` is a thin lifecycle
  concern attached to invocation, not a subsystem. Everything else extends existing
  services (`ModelService`, `CapabilityRegistry`, turn loop).
- **Removability.** Yes. With no task routes and no satisfiers the RFC is inert and the
  runtime core behaves exactly as before; the contracts and selection parameter can be
  removed without touching unrelated services.
