# RFC-0003: Capability Registry, Runtime Manifest, and Inspection

- **Status:** Accepted (2026-07-04)
- **Author:** Zygos maintainers
- **Created:** 2026-07-04
- **Governs:** the capability registry, how plugins advertise capabilities, the
  runtime manifest, and the static inspection surface (`zygos inspect`,
  `zygos doctor`)
- **Depends on:** [RFC-0001](RFC-0001-Service-Architecture.md) (PluginService,
  snapshotable state, the composition root) and
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (this RFC pulls
  health from snapshotable state and adds two events to RFC-0002's taxonomy)
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); the
  registry mechanism can land as an early increment, render surfaces attach as
  their adapters arrive

## Summary

Introduce a **capability registry** that lets a consumer ask "who can satisfy the
*vision* capability?" instead of importing a specific implementation; a
**runtime manifest** that projects the wired runtime as pure, pull-only data; and
a **static inspection** surface (`zygos inspect`, `zygos doctor`) that renders it.
Capabilities are a closed, typed set bound to contracts; plugins self-declare
which they satisfy; resolution is pull-based, health-ranked, and never driven by
event subscription — so it composes with RFC-0002's strict observational bus.

## Motivation

The [Constitution](../../CONSTITUTION.md) states "all capabilities are modular
services" and "every component must be replaceable," and
[ARCHITECTURE.md](../../ARCHITECTURE.md) reserves a Capability Registry whose
purpose is that consumers "bind to capabilities, never to implementations — which
is also what makes capability renegotiation possible when a provider fails." Two
concrete needs make the mechanism due now:

1. **Replaceability needs a lookup seam.** Without a registry, a consumer that
   wants "speech" must import a concrete engine or a specific service,
   re-creating the bootstrap coupling RFC-0001 removed for construction but not
   for *use*. The registry is the use-time analog of the composition root.
2. **Graceful degradation needs renegotiation.** RFC-0002 gave the router a
   circuit breaker; when a provider's circuit opens, a capability consumer should
   be able to fall back to another satisfier of the same capability. That
   requires a place that knows *all* satisfiers of a capability and their live
   health.

The manifest and inspection surface are folded in because they are the natural
readers that prove the registry — and the rest of the wired runtime — is
inspectable ("nothing magical"). They are read projections over the registry,
`PluginService`, config, and `snapshot_state()`; building the registry without
its reader would leave the inspectability goal unmet.

`zygos trace` (dynamic execution inspection) is **out of scope**: it reads
`TraceService`, which is not yet built. It is named here and deferred to the
TraceService milestone.

## Problem Statement

1. **No capability lookup exists.** Nothing answers "which loaded plugin provides
   capability X?" `PluginService.resolve(kind, name)` (RFC-0001 §2) loads code by
   *name*, not by *what it can do*. A consumer therefore has no way to bind to a
   capability without knowing an implementation, defeating replaceability at use
   time.
2. **No renegotiation path.** When a provider fails (RFC-0002 opens its circuit),
   there is no component that enumerates the other satisfiers of the same
   capability, so failover across implementations cannot happen above the level
   of a single service's internal fallback.
3. **The runtime is not inspectable.** There is no answer to "what is wired right
   now — which plugins, which capabilities, is the primary route credentialed?"
   The planned `GET /runtime`, `zygos inspect`, and `zygos doctor` have no data
   source. The "Register Capabilities" lifecycle stage
   ([ARCHITECTURE.md](../../ARCHITECTURE.md)) is a placeholder.

## Proposed Design

### 1. Capability model — closed, typed, RFC-extensible

A capability is a **named marker bound to a contract**. The core set is defined in
the runtime; each entry names the Protocol a satisfier must fulfill:

```python
class Capability(StrEnum):
    LOCAL_INFERENCE = "local_inference"
    VISION = "vision"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    WEB_SEARCH = "web_search"
    IMAGE_GENERATION = "image_generation"
    SCHEDULING = "scheduling"
    FILESYSTEM_ACCESS = "filesystem_access"

# Each capability binds to the contract a satisfier must implement.
CAPABILITY_CONTRACTS: Mapping[Capability, type] = {
    Capability.LOCAL_INFERENCE: Provider,
    Capability.SPEECH_TO_TEXT: VoiceService,   # transcribe_stream
    Capability.TEXT_TO_SPEECH: VoiceService,   # synthesize_stream
    # ... one contract per capability
}
```

`speech` is split into `SPEECH_TO_TEXT` and `TEXT_TO_SPEECH` to mirror
`VoiceService`'s `transcribe_stream` / `synthesize_stream` split (RFC-0001 §2) and
to let a deployment mix engines per direction. The concrete voice **engines** are
out of scope here — they are defined by the dedicated voice RFC; this RFC only
names the two capabilities.

The set is **closed and extended only by a future RFC** — the same rule RFC-0002
applies to its event taxonomy. This keeps the meaning of every capability
governed and inspectable; the Phase-8 ecosystem RFC may later open it.

### 2. Declaration — plugins self-declare, the registry aggregates

Each plugin carries static capability metadata, a sibling to `Tool.meta`
(RFC-0001 §5) and `Provider.name`:

```python
class OllamaProvider:
    name = "ollama"
    capabilities: frozenset[Capability] = frozenset({Capability.LOCAL_INFERENCE})
```

The **source of truth for what a plugin can do is the plugin**. Config decides
*which* plugins load ([ADR-0003](../adr/ADR-0003-config-declared-plugins.md)); it
may **disable** a binding but cannot invent one a plugin does not declare. Reading
config plus plugin metadata yields the entire capability map — surfaced verbatim
in the manifest.

### 3. CapabilityRegistry — pull-based, health-ranked resolution

```python
@dataclass(frozen=True)
class Binding:
    capability: Capability
    provider: str          # the satisfying plugin/service name
    priority: int          # lower = preferred (config-assigned)

class CapabilityRegistry(Protocol):
    def register(self, capability: Capability, provider: str, *, priority: int) -> None: ...
    def resolve(self, capability: Capability) -> tuple[Binding, ...]: ...
    def snapshot(self) -> "CapabilitySnapshot": ...
```

`register()` validates that the provider satisfies `CAPABILITY_CONTRACTS[capability]`
(a `runtime_checkable` Protocol check): a plugin that *declares* a capability whose
contract it does not implement is rejected at the Register Capabilities stage,
never silently trusted. Declaration is explicit (§2); conformance is verified.

`resolve()` returns the satisfiers of a capability **ranked by config priority and
filtered by live health pulled at call time** from snapshotable state — the
router's `RouterSnapshot` for model providers, each provider's own health snapshot
otherwise. It **never subscribes to events** to track availability. A consumer
binds to a capability, receives an ordered, currently-healthy list typed against
the capability's contract, and tries them in order; **renegotiation is
try-next / re-resolve**. This is the router's `_eligible()` (RFC-0002 §1)
generalized from one service to all capabilities.

**Composition with RFC-0002 (normative).** The registry is a *puller*, not a
subscriber: resolution reads snapshots synchronously and depends on **no**
subscriber, preserving RFC-0002's load-bearing invariant ("drop every subscriber →
identical behavior"). The registry additionally **emits** two observational facts
— `capability.resolved` and `capability.renegotiated` — which this RFC adds to the
RFC-0002 event taxonomy (each with a frozen payload model, per that RFC's rule).
Emitting these facts changes nothing about resolution; they are for observers
only.

### 4. Snapshotability

`CapabilityRegistry` is a named, snapshotable state object (RFC-0001 §4),
registered with `TraceService` and exposed through `snapshot_state()`. Its
snapshot is the capability→bindings map with priorities and last-known health:

```python
@dataclass(frozen=True)
class CapabilityBinding:
    provider: str
    priority: int
    healthy: bool          # last-known, from the pulled source

@dataclass(frozen=True)
class CapabilitySnapshot:
    bindings: Mapping[Capability, tuple[CapabilityBinding, ...]]
```

This snapshot is the shared data source for the manifest and `zygos inspect` — a
capability the manifest cannot see would be an architecture bug, exactly as
RFC-0001 §4 requires of all runtime state.

**Relationship to `PluginService`.** `PluginService.resolve(kind, name) -> type`
loads code by name; `CapabilityRegistry.resolve(capability)` answers "which loaded
plugin satisfies X, healthily." Complementary axes: the registry is populated
*from* the plugins `PluginService` resolved, at the Register Capabilities stage.

### 5. Runtime manifest — a pure pull view

```python
def runtime_manifest(runtime: Runtime) -> Manifest: ...
```

`runtime_manifest()` aggregates, with **no side effects and no network**:

- registered capabilities and their bindings (from the registry snapshot),
- loaded plugins (kind, name, module path — from config/`PluginService`),
- service wiring summary,
- non-secret config summary and component versions,
- the lifecycle stage reached (RFC-0001 / ARCHITECTURE lifecycle).

Two thin surfaces render the same `Manifest` data: `GET /runtime` (lands with the
FastAPI adapter, M8) and `zygos inspect` (CLI). **The manifest data is built with
the registry; the renderers attach as their adapters arrive.**

### 6. Inspection surface

- **`zygos inspect`** — passive render of the manifest: what is wired, which
  capabilities are covered by which bindings, last-known health. No side effects.
- **`zygos doctor`** — passive validation from **local state only** by default:
  is the config valid, is the primary model route credentialed (RFC-0001 §8), did
  every declared plugin resolve, is every capability the config marks *required*
  covered by at least one binding? An explicit **`--probe`** flag opts into active
  provider pings.
  `doctor` exits non-zero on a validation failure, so it is usable as a deploy
  gate.
- **`zygos trace`** — **deferred** to the TraceService milestone; out of scope
  here.

### 7. The Register Capabilities lifecycle stage

This RFC fills the placeholder stage in the runtime lifecycle
([ARCHITECTURE.md](../../ARCHITECTURE.md)): after **Initialize Services** and
before **Load Skills**, the composition root aggregates each resolved plugin's
declared capabilities into the `CapabilityRegistry`, assigning priorities from
config. The manifest is available from this stage onward.

## Alternatives Considered

| Decision | Rejected alternative | Why rejected |
|---|---|---|
| Capability model | Open, plugin-declared string tags | Invites name sprawl, typos, and un-inspectable meaning; premature (RFC-0001 defers the plugin ecosystem to Phase 8). Strains "nothing magical." |
| Capability model | Closed set but bare tags (no contract) | A consumer resolving a capability would still need its shape out-of-band, re-opening the coupling the registry closes. |
| Declaration | Config maps capability → plugin | Duplicates a code fact into config; config could claim a capability a plugin cannot satisfy (drift); two places to maintain. |
| Declaration | Derive from Protocol conformance | `runtime_checkable` conformance is coarse (implementing `Provider.generate` does not reveal vision vs text) and fragile; hides semantic sub-capabilities. |
| Resolution | Event-driven availability cache (subscribe to `circuit.opened`) | **Violates RFC-0002:** makes a bus subscriber load-bearing; resolution would change based on which subscribers are attached. |
| Resolution | Static lookup, no health filtering | Drops the renegotiation goal ARCHITECTURE states; the registry degenerates into a lookup table. |
| Inspection | `doctor` probes live by default | Surprising network calls, slow, can hang on a bad droplet link; active checks belong behind `--probe`. Strains "local-first." |
| Scope | Include `zygos trace` now | Reads `TraceService`, which does not exist yet; would force a stub or block the RFC. |

## Migration Plan

v1 stays frozen; TDD per RFC-0001 §9. Because nothing today consumes capabilities,
adding the registry is behavior-preserving.

1. **Capability model + declaration metadata.** Add the `Capability` enum,
   `CAPABILITY_CONTRACTS`, and `capabilities` metadata to the existing M2
   providers (all declare `local_inference`). No consumer yet.
2. **CapabilityRegistry + snapshot.** Implement register/resolve/snapshot with
   pull-based health ranking; register it with `TraceService`; contract tests with
   fake providers.
3. **Register Capabilities stage.** Wire aggregation into `bootstrap.py` at the
   lifecycle stage; add `capability.resolved` / `capability.renegotiated` to the
   RFC-0002 taxonomy with their payload models.
4. **`runtime_manifest()`.** The pure aggregation function + its `Manifest` type.
5. **Render surfaces, as adapters land:** `zygos inspect` / `zygos doctor` with
   the CLI adapter; `GET /runtime` with the FastAPI adapter (M8); `zygos trace`
   with `TraceService`.

## Risks

- **Health source coupling.** Pulling health from `RouterSnapshot` couples the
  registry to router internals. Mitigation: the registry depends on the *snapshot
  type* (a published, RFC-0001-mandated surface), not on router internals; other
  capabilities expose their own health snapshot behind the same shape.
- **Capability granularity churn.** Splitting/merging capabilities later (e.g.,
  `vision` into sub-modes) is a taxonomy change. Mitigation: the set is
  explicitly RFC-extensible; `CAPABILITY_CONTRACTS` keeps each addition typed and
  additive.
- **Manifest leaking secrets.** A naive manifest could serialize API keys.
  Mitigation: the manifest carries a **non-secret** config summary by
  construction; a test asserts no credential material appears in manifest output.
- **`doctor --probe` on a self-hosted link.** Active probes can hang.
  Mitigation: probing is opt-in, bounded by the provider timeout (RFC-0001 §8),
  and reported per-provider so one slow provider does not fail the whole report.

## Acceptance Criteria

1. `CapabilityRegistry.resolve()` returns satisfiers **ranked by priority and
   filtered by live health pulled at call time**; an unhealthy top-priority
   provider is skipped in favor of a healthy lower-priority one — test-proven with
   fakes.
2. The registry holds **no** event subscription; resolution behavior is identical
   whether or not any subscriber is attached (RFC-0002 invariant) — test-proven.
3. A plugin that declares a capability it does not actually implement (contract
   mismatch) is rejected at registration — test-proven.
4. Config can **disable** a binding but cannot register a capability a plugin does
   not declare — test-proven.
5. `runtime_manifest()` is pure (no network, no mutation) and contains **no**
   secret material — test-proven.
6. `zygos doctor` (passive) exits non-zero when the primary route lacks
   credentials or a required capability has no binding, and zero on a healthy
   local config — test-proven; `--probe` performs bounded active pings.
7. `capability.resolved` and `capability.renegotiated` exist in the RFC-0002
   taxonomy with frozen payload models validated at construction — test-proven.
8. The full suite proving 1–7 runs with no server, no network, and no API keys
   (RFC-0001 §9); `--probe` behavior is tested against fake providers only.

## Architectural Impact

- **Coupling:** *decreased.* Consumers bind to capabilities, not implementations —
  the use-time analog of the composition root and the mechanism behind "every
  component must be replaceable." The registry depends on published snapshot
  shapes, not service internals.
- **Hidden state:** *none introduced.* The registry is a snapshotable state object
  visible through `snapshot_state()`; capabilities are declared in code and
  aggregated visibly; resolution **pulls** health rather than maintaining an
  event-driven cache, so there is no observer-dependent hidden state.
- **Bypasses a prior boundary:** no. It builds on RFC-0001 (`PluginService`,
  snapshotable state) and RFC-0002 (pulls snapshots, emits observational facts,
  never a load-bearing subscriber), and it extends the RFC-0002 taxonomy through
  the amendment path that RFC provides.
- **Constitution:** aligns with "all capabilities are modular services," "every
  component must be replaceable," "the runtime should degrade gracefully"
  (renegotiation), "execution is fully traceable / hidden state is discouraged"
  (snapshotable, inspectable), and "local-first is preferred" (passive default,
  opt-in probe).
- **Independently testable:** yes. Resolution/ranking/health-filtering with fake
  providers; the manifest is a pure function; `doctor` validation is serverless.
- **New service or existing:** the `CapabilityRegistry` is a runtime primitive
  alongside `PluginService`; `runtime_manifest()` is a pure function; `inspect` /
  `doctor` are CLI-adapter surface.
- **Removable later:** yes. The registry is replaceable behind its Protocol;
  removing it reverts consumers to direct wiring (losing renegotiation) without
  affecting the runtime core.
