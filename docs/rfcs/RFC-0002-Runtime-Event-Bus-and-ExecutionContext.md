# RFC-0002: Runtime Event Bus and ExecutionContext

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-04
- **Governs:** the runtime event bus, the `ExecutionContext` object, and the
  single-loop concurrency model that keeps snapshotable state correct
- **Depends on:** [RFC-0001](RFC-0001-Service-Architecture.md) — this RFC revises
  its `TraceService` contract (§2) and builds on its explicit-state design (§4)
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); scheduled
  to land before Milestone 3 (RDT engine)

## Summary

Introduce three coupled runtime primitives: a strictly **observational event
bus** onto which services emit facts, an **`ExecutionContext`** that threads
correlation identity, a bus-bound emitter, and a cancellation signal through the
runtime, and an explicit **single-loop concurrency model** that makes
snapshotable state (starting with `RouterState`) correct by construction. The
concurrency model resolves three defects the Milestone 2 review carried forward:
rate-limit over-admission, circuit-breaker last-writer-wins, and half-open
admitting more than one probe.

## Motivation

[RFC-0001](RFC-0001-Service-Architecture.md) established that all runtime state
becomes named, snapshotable objects and that "state the console cannot see is an
architecture bug." It named a `TraceService` with a `record_event` method and
described — but deferred — the event model and `ExecutionContext`. Two forces now
make that deferred design due:

1. **Observation must decouple from emission.** Tracing, metrics, and future
   plugins should learn what the runtime did without any emitting service
   importing or depending on them. Today a service that wants to be observed must
   call `TraceService.record_event` directly — the exact service-to-service
   coupling the architecture is meant to remove.
2. **The concurrency model is now load-bearing, not hypothetical.** Milestone 2
   shipped `ProviderRouter` with real circuit-breaker and rate-limit state and
   real `await` points. Its review found three concurrency defects (see Problem
   Statement) whose correct fix is not three local patches but a stated model for
   how snapshotable state is mutated. RFC-0001's Risks section already flagged
   "Python asyncio complexity" as a migration risk; this RFC discharges it.

`ExecutionContext` is folded in because it is the object that carries the
bus-bound emitter: emission, correlation, and the concurrency rules that govern
when emission may happen are one design, not three.

## Problem Statement

**1. Emission is coupled to observation.** With only `TraceService.record_event`,
every service that wants its actions recorded takes a dependency on
`TraceService`. A second observer (a metrics exporter, the Introspection Console,
a third-party plugin) cannot be added without either widening that dependency or
teaching each emitting service about the new observer. RFC-0001's own goal —
"subscribe to events instead of coupling to service internals" — has no mechanism.

**2. There is no correlation carrier.** Nothing threads a run/session identity
through nested operations. A tool executed inside an RDT step inside a request
has no shared handle by which its events, traces, and cancellation are tied to
the request that caused them. RFC-0001 passes `ToolContext` to tools but defines
no runtime-wide context and no cancellation path for barge-in or graceful
shutdown.

**3. Snapshotable state has no stated concurrency discipline, and the M2 router
proves it matters.** `backend/zygos/services/router.py` exhibits three defects the
Milestone 2 review carried to this RFC:

- **Rate-limit over-admission (TOCTOU).** Eligibility is computed by
  `_eligible()` (which reads `_RateLimiter.allows()`) and the slot is consumed
  later by `_RateLimiter.record()`. The check and the mutation are separated, so
  the invariant "at most `max_per_minute` admitted" holds only by accident of the
  current call ordering, not by construction.
- **Circuit-breaker last-writer-wins.** A request that began while a breaker was
  closed can call `record_success()` and reset a breaker that a concurrent
  failure just opened, masking the failure. Admission and outcome-recording are
  not serialized against each other.
- **Half-open admits every attempt.** `_CircuitBreaker.allows()` returns `True`
  for `half_open`, so on cooldown expiry all `max_attempts` flow through as
  probes. The design intent is exactly one probe; the code admits many.

These are not three unrelated bugs. They are three symptoms of one missing rule:
*check-then-mutate on shared state is not guaranteed atomic.*

## Proposed Design

The three primitives are presented foundation-first: the concurrency model, then
the event bus, then `ExecutionContext`, then how they compose.

### 1. Single-loop concurrency model (the foundation)

**Invariant.** The runtime runs on one asyncio event loop. Every snapshotable
state object (`RouterState` now; `SessionState` and `ReasoningState` in later
milestones) is owned by one task, and **every check-then-mutate on it executes as
a single synchronous critical section — with no `await` between the decision and
the record.** Because asyncio does not preempt synchronous code, that section is
atomic without any lock.

This is deliberately *not* `asyncio.Lock` and *not* an actor/queue (see
Alternatives). It adds no primitive and no `await` point; correctness becomes a
structural property that a reviewer can verify by inspection — "is there an
`await` inside this critical section?" — rather than a runtime property that only
manifests under load. It honors the Constitution's "simplicity is preferred over
cleverness."

**Consequence for emission (a rule this RFC states explicitly).** `emit()` is
async (§2). Therefore **events are never emitted from inside a synchronous
critical section** — doing so would introduce an `await` and break atomicity.
State-change events are emitted *after* the critical section returns, at an
await-safe point. This interaction between §1 and §2 is a review-checkable rule,
not a convention.

**Application to the router.** The split `allows()` … later `record()` becomes a
single atomic claim:

```python
@dataclass(frozen=True)
class RouteClaim:
    route: RouteChoice
    probe: bool  # this claim is the single half-open probe

class ProviderRouter:
    def _try_claim(self, route: RouteChoice) -> RouteClaim | None:
        """Atomically decide admission AND record it. No await inside."""
        breaker = self._breakers[route]
        limiter = self._limiters[route.provider]
        if not limiter.allows():
            return None
        admit, probe = breaker.admit()   # sync; sets 'probing' if half-open
        if not admit:
            return None
        limiter.record()                 # consume the slot in the same section
        return RouteClaim(route=route, probe=probe)
```

`generate()`/`stream()` iterate routes, and for each call `_try_claim`; a `None`
claim means "skip this route." The claim's outcome is recorded exactly once:

```python
            claim = self._try_claim(route)
            if claim is None:
                continue
            try:
                result = await provider.generate(routed)   # the only await
            except ProviderError as error:
                self._breakers[route].record_failure(error.code)  # sync section
                ...
            else:
                self._breakers[route].record_success()            # sync section
                return result
```

Admission and outcome-recording now pass through the same owning object with no
interleaving `await` between decision and record, so over-admission and
last-writer-wins are impossible by construction.

**Half-open = one probe.** `_CircuitBreaker` gains an explicit `admit()` that
both decides and marks:

- `closed` → `(admit=True, probe=False)`.
- `open` and cooldown not elapsed → `(admit=False, probe=False)`.
- `open` and cooldown elapsed → transition to half-open by setting `probing =
  True`, return `(admit=True, probe=True)`. **While `probing` is `True`, further
  `admit()` calls return `(False, False)`** — exactly one probe is outstanding.
- Probe **success** → `record_success()` clears `probing` and closes the breaker.
- Probe **failure** → `record_failure()` clears `probing` and re-opens the
  breaker with a fresh cooldown.

`probing` is always cleared by whichever outcome the claim records, in a
`finally`-style path, so a probe task that dies cannot wedge the breaker
half-open forever.

`RouterSnapshot`/`RouteStatus` (RFC-0001 §4) are unchanged in shape; the transient
`probing` state is reported within the existing `half_open` circuit value.

### 2. Event bus (strict, observational)

**`Event`** is an immutable Pydantic model:

```python
class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str            # closed, past-tense taxonomy (see below)
    run_id: str
    session_id: str | None
    span_id: str
    parent_span_id: str | None
    source: str          # emitting service/component name
    payload: Mapping[str, object]  # event-type-specific shape, documented per type
```

Event `type` is a **closed, past-tense taxonomy** — facts that already happened,
never commands. It is seeded from the ARCHITECTURE Event Model examples plus the
obvious lifecycle events, and is **extensible only by a future RFC** (it is not
claimed exhaustive now):

`request.started`, `request.finished`, `model.selected`, `route.claimed`,
`circuit.opened`, `circuit.closed`, `memory.retrieved`, `tool.completed`,
`skill.executed`, `trace.finalized`.

**`EventBus`** delivers synchronously, in-loop, with error isolation:

```python
class EventBus(Protocol):
    def subscribe(self, handler: Subscriber) -> None: ...
    async def emit(self, event: Event) -> None: ...

# Subscriber = Callable[[Event], Awaitable[None]]
```

`emit()` awaits each subscriber **in registration order**, each wrapped so a
raising subscriber is logged and never breaks the emitter or the other
subscribers (graceful degradation). Delivery is causally tied to the action,
ordering is guaranteed, and tests are deterministic — there is no out-of-band
queue to drain. A subscriber that needs to do heavy work must offload to its own
task; the bus contract is that subscribers are fast and observational.

**Subscribers are config-declared and resolved at bootstrap**, consistent with
[ADR-0003](../adr/ADR-0003-config-declared-plugins.md): reading the config tells
you exactly which observers are attached. There is no hidden dynamic
subscription.

**The load-bearing invariant (normative).** *Drop every subscriber and runtime
behavior is identical.* Subscribers observe and record; they never drive
behavior. Any subscriber whose removal changes what the runtime does is an
architecture bug. Commands remain direct service calls; only facts are events.

### 3. ExecutionContext

An immutable object threaded through the runtime carrying **correlation identity,
a bus-bound emitter, and a cancellation signal — and no service references**:

```python
@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    session_id: str | None
    span_id: str
    parent_span_id: str | None
    _bus: EventBus
    _cancel: CancelToken

    async def emit(self, type: str, source: str, **payload: object) -> None:
        await self._bus.emit(Event(
            type=type, run_id=self.run_id, session_id=self.session_id,
            span_id=self.span_id, parent_span_id=self.parent_span_id,
            source=source, payload=payload,
        ))

    def child(self, span_id: str) -> "ExecutionContext":
        return replace(self, span_id=span_id, parent_span_id=self.span_id)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()
```

- `emit()` auto-stamps the context's correlation ids onto every event, so a
  service emits a fact without ever handling ids by hand.
- `child(span_id)` derives a read-only sub-context for each nested operation
  (per-tool execution, per-RDT-step), preserving the parent/child span chain.
- It holds **no service references** — services still receive their dependencies
  through constructors (RFC-0001 §3). This is what keeps `ExecutionContext` from
  degrading into the service-locator RFC-0001 explicitly rejected.
- `CancelToken` wraps a single-loop `asyncio.Event`. It is tripped by **barge-in**
  (a `control` frame cancelling in-flight work, RFC-0001 §6) and by **graceful
  shutdown**. Cooperative cancellation: long-running services check `cancelled`
  (or await the token) at their own yield points.

`ToolContext` (RFC-0001 §5) becomes a derivation of `ExecutionContext` — a tool
receives a child context plus tool-specific fields, rather than a parallel,
unrelated context type.

### 4. TraceService contract revision (amends RFC-0001 §2)

`record_event` **leaves the public `TraceService` contract**. TraceService
becomes a **bus subscriber** that records the event stream. This replaces the
service→`TraceService` coupling with service→bus / `TraceService`←bus — the
decoupling that is the entire point of introducing the bus.

- `snapshot_state()` **stays** as a separate pull API: state is point-in-time and
  read on demand, not a past-tense fact pushed onto the bus. Events (push) and
  snapshots (pull) are complementary.
- `begin_trace`, `finish_trace`, and `reflect` **stay** on `TraceService`; the
  end of a trace additionally surfaces as a `trace.finalized` event for other
  subscribers.

The `TraceService` Protocol is authored in its own milestone; this RFC revises
the *contract* RFC-0001 published so that implementation, when it lands, subscribes
rather than exposes `record_event`.

### 5. Layering

The result is a clean split RFC-0001's dependency rule already wants:

```
observation layer   TraceService, metrics exporter, Introspection Console
      │  subscribe(handler)     ▲  emit(event)
runtime core        services emit facts via ctx; never import a subscriber
```

The observation layer depends on the bus; the runtime core depends on the bus
*primitive* (the `emit` API) but on **no subscriber**. With zero subscribers,
`emit()` is a no-op loop and the runtime behaves identically — which is the
load-bearing invariant restated as a layering fact.

## Alternatives Considered

| Decision | Rejected alternative | Why rejected |
|---|---|---|
| Bus semantics | Reactive bus (subscribers may trigger actions) | Reintroduces implicit control flow: behavior depends on which subscribers are attached — the hidden-coupling class RFC-0001 fought. Auto-reactions, if ever wanted, get their own RFC. |
| Delivery | Async queue (out-of-band drainer) | Adds backpressure/unbounded-queue concerns, cross-emitter ordering complexity, eventual (post-action) delivery, and test nondeterminism — more machinery than observational events need. |
| Delivery | Sync fan-out, async per-subscriber task | Loses per-subscriber ordering and breaks test determinism — worst of both for an observational bus. |
| Concurrency | `asyncio.Lock` per state object | Adds `await` points, lock overhead, and deadlock surface the single-loop model does not need; allowing `await` inside the critical section reintroduces the interleaving being removed. Justified only if leaving the single-loop model. |
| Concurrency | Single owning task / actor (command queue) | Strongest isolation but heavy machinery and added latency; the cleverness the Constitution steers away from for a local-first runtime. Overkill here. |
| Context | Carry clock + deadline | Clock belongs in constructors (as the router already injects `now`); a foundational type is the wrong place to grow features. Addable later via a superseding RFC if a real need appears. |
| Context | Emitter-only (cancellation stays a loose param) | Only half-solves the loose-param problem the single-context direction was meant to fix; barge-in/shutdown threading stays ad hoc. |
| Trace | Keep `record_event` and the bus both | Two ways to report the same fact — redundant double-pathing that drifts, and leaves the coupling the bus removes. |
| Trace | `TraceService` owns the bus | Couples a runtime primitive to one service, making TraceService load-bearing for all observation and awkward to replace. Inverts ownership. |

## Migration Plan

This RFC precedes Milestone 3. When accepted, implementation proceeds as a
tested, self-contained change (v1 stays frozen; TDD per RFC-0001 §9):

1. **Add primitives.** New modules for `Event`/`EventBus`, `ExecutionContext`/
   `CancelToken`. No consumer yet — contract tests define behavior.
2. **Refactor the M2 router to `_try_claim`** with the half-open `admit()` and
   probing flag, replacing the split `_eligible()`/`record()`. `RouterSnapshot`
   shape is preserved, so existing snapshot consumers/tests are unaffected.
3. **Wire the bus at the composition root** (`runtime/bootstrap.py`): construct
   the `EventBus`, resolve config-declared subscribers, and subscribe them. The
   router (and later services) emit `route.claimed`/`circuit.*` after their
   critical sections.
4. **Revise the `TraceService` contract** in RFC-0001's published interface: drop
   `record_event`; the (future) implementation subscribes. No `TraceService`
   implementation exists yet, so the revision is limited to the contract.

Because the bus starts with zero or observation-only subscribers, every step
preserves runtime behavior; the router refactor is behavior-preserving except
that it *fixes* the three defects, each proven by a new test.

## Risks

- **A critical section accidentally gains an `await`.** Mitigation: the "no
  `await` in a critical section; no `emit()` inside one" rule is stated
  normatively and is checkable by inspection and in review; the router's atomic
  `_try_claim` keeps the section small and lock-free by design.
- **Taxonomy churn.** A closed event taxonomy could invite frequent RFCs.
  Mitigation: seed it from real needs, mark it explicitly extensible by future
  RFC, and document `payload` shape per event type so additions are additive.
- **Subscriber latency on the hot path.** Synchronous delivery means a slow
  subscriber slows the emitter. Mitigation: the bus contract requires subscribers
  to be fast and observational; heavy work offloads to a subscriber-owned task;
  error isolation already prevents a subscriber from breaking the path.
- **Single-loop assumption is load-bearing.** If the runtime ever moves off one
  event loop, the lock-free model is invalidated. Mitigation: the assumption is
  documented as an explicit invariant here, and revisiting it is a
  superseding-RFC event, not a silent change.

## Acceptance Criteria

1. `EventBus.emit()` delivers to subscribers in registration order, and a
   subscriber that raises is logged without breaking the emitter or other
   subscribers — both test-proven.
2. **Drop-all-subscribers invariant:** a runtime assembled with zero subscribers
   produces identical observable behavior to one with subscribers attached —
   test-proven.
3. `ExecutionContext.emit()` stamps correlation ids automatically, and
   `child()` preserves the parent/child span chain — test-proven.
4. The router admits **at most** `max_per_minute` under concurrent `generate()`
   calls (no over-admission) — test-proven with a deliberately concurrent case.
5. A circuit-breaker opened by a failure is **not** reset by a concurrent
   in-flight success — test-proven.
6. On cooldown expiry, **exactly one** probe is admitted in half-open;
   concurrent claims are denied until the probe resolves — test-proven.
7. `TraceService`'s revised contract exposes no `record_event`; the trace record
   is produced by subscribing to the bus, and `snapshot_state()` remains a pull
   API — reflected in the revised contract and its contract test.
8. The full suite proving 1–7 runs with no server, no network, and no API keys
   (RFC-0001 §9).

## Architectural Impact

- **Coupling:** *decreased.* service→bus/`TraceService`←bus replaces
  service→`TraceService`; the runtime core imports no subscriber.
- **Hidden state:** *none introduced.* Subscribers are config-declared and
  resolved at bootstrap; events carry explicit correlation ids; router state
  remains snapshotable, and the previously-implicit atomicity is now an explicit,
  reviewable rule. The concurrency model *removes* an accidental-correctness
  hazard.
- **Bypasses a prior boundary:** no. It *tightens* RFC-0001's boundaries and
  formally revises one published contract (`TraceService`) through the RFC process
  that exists for exactly that.
- **Constitution:** aligns with "execution is fully traceable," "hidden state is
  discouraged," "simplicity is preferred over cleverness," "the runtime should
  degrade gracefully," and "every component must be replaceable."
- **Independently testable:** yes. Bus, context, and the router's atomic claim
  each have deterministic, serverless tests.
- **New service or existing:** neither is a service. The bus and
  `ExecutionContext` are **runtime primitives**; the concurrency rule is a
  property of how services mutate their own state.
- **Removable later:** yes. The load-bearing invariant guarantees that removing
  the bus (and all subscribers) changes no runtime behavior; `ExecutionContext`
  is replaceable behind its construction at the composition root.
