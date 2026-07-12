# RFC-0008: Tool-Calling Protocol and Tool Authoring

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-11
- **Governs:** how a model **signals a tool call** — the mechanism by which an LLM
  requests a tool, how the runtime detects and dispatches it, and how the result
  is fed back so the model can continue — and how **tools are authored** so the
  model can select and call them well. Covers the normalized provider tool-calling
  contract, the tool-schema derived from a tool's input model, the standalone
  agentic loop, result feedback, loop-safety bounds, and the authoring conventions.
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `Provider`/`ModelService`
  contract §2, the message typing §7, and the four-phase `Tool` contract §5 this
  RFC's execution side reuses unchanged),
  [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) (the
  `ExecutionContext`/`CancelToken` the loop threads and the single-event-loop
  concurrency model under which parallel tool calls are gathered), and
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the turn loop that drives
  the agentic loop, the `tools` WebSocket channel that frames its lifecycle, and
  the interactive permission resolver each tool call passes through).
- **Amends** [RFC-0001](RFC-0001-Service-Architecture.md) **§2 and §7**: adds
  tool-schema input and normalized tool-call output to the `Provider`/`ModelService`
  contract, and a `"tool"` role plus tool-call/tool-result fields to the `Message`
  model. It does **not** change RFC-0001 §5 (the four-phase tool execution
  contract) — that stays as built.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md); this RFC
  locks the tool-calling design. The work lands as its own build cycle; it is a
  producer for the M8 turn loop's `tools` channel (RFC-0007 §7), which specifies
  only that a requested tool call runs through `ToolService` — not the mechanism
  by which the model decides to call one. That mechanism is this RFC.

## Summary

Let the model **actually call tools**. Adopt **native function-calling**,
normalized at the provider seam: amend the `Provider`/`ModelService` contract so a
request can carry tool schemas and a result can carry normalized tool-calls, with
each provider translating to and from its own native format (OpenAI `tool_calls`,
Anthropic `tool_use`, Ollama `tool_calls`, vLLM OpenAI-compatible). A tool's schema
is **derived automatically** from its Pydantic `input_model` and `ToolMeta`, so
authors write one definition, not two. A small, reusable **agentic loop** wraps the
model-interaction step — call the model with tools, dispatch any `tool_calls`
through the already-built `ToolService`, feed the results back, repeat until the
model stops or a bound is hit — with parallel calls run concurrently, cancellation
inherited from the turn, and a configurable iteration cap that degrades gracefully.
The RFC also sets the **authoring conventions** that make a tool legible to a model:
a selection-oriented description, per-field schema descriptions, and clear
side-effect and permission defaults.

## Motivation

Zygos has a complete, well-tested tool subsystem — `ToolService`, the registry,
the four-phase execution contract, permissions, retry/timeout, one-level fallback,
streaming, and a starter suite of real tools — and **none of it can be reached by a
model.** The provider layer is strictly text-in/text-out; nothing turns a model's
output into a `ToolCall`. The `ToolCall` type exists and has no producer.

RFC-0007 built the turn loop and the `tools` WebSocket channel but deliberately
deferred *this* question: "how the model signals a tool call … and how tools are
authored … are their own concern, deferred to a dedicated future RFC." This is that
RFC. It must land before the M8 build cycle that wires real tool use into the turn
loop, so that cycle is built against a settled mechanism rather than an invented one.

Two forces shape the design. First, **honesty over theater**: every provider Zygos
ships (OpenAI, Anthropic, Ollama, vLLM) exposes a native tool-calling API that its
models are trained for — including the default local `qwen3` via Ollama.
Reconstructing that in prose we prompt-inject and re-parse would rebuild, fragile
and second-rate, a capability the models already offer natively. This mirrors the
milestone-3 steer: don't fake the intent in text, build the real mechanism. Second,
**authoring is half the problem**: a tool the model cannot understand from its name,
description, and parameter schema will not be called, or will be called wrong. The
conventions are as load-bearing as the wire format.

## Problem Statement

1. **No producer of tool calls exists.** `providers/` is text-only:
   `GenerationRequest` carries no `tools`, `GenerationResult` carries no
   `tool_calls`/`finish_reason`, and `Message.role` is a closed
   `Literal["system","user","assistant"]` with `extra="forbid"` — no `"tool"` role,
   no tool-result shape. `ReasoningService` (the only in-turn model caller) consumes
   `result.text` and nothing else.

2. **No schema seam.** `input_model`/`output_model` are Pydantic models, but nothing
   turns an `input_model` into the JSON Schema a function definition needs; the
   material exists (`model_json_schema()`) but the seam is unbuilt.

3. **No agentic loop.** Nothing calls the model with tools, detects a tool request,
   dispatches through `ToolService`, feeds results back, or bounds the iteration.
   The `tools` channel (RFC-0007) has a transport but no producer.

4. **No authoring guidance.** The starter tools show a mechanical pattern
   (`ToolMeta` + `input_model` + `execute`), but nothing specifies how to write a
   description or field schema a model can act on, or how a result is rendered back.

## Proposed Design

### 1. Native function-calling, normalized at the provider seam

The runtime speaks **one** normalized tool-calling vocabulary; each provider
translates it to and from its native API. Two new provider-level types
(`providers/types.py`):

```python
class ToolSchema(BaseModel):        # a tool, as the model sees it
    name: str
    description: str
    parameters: dict[str, Any]      # JSON Schema (from the tool's input_model)

class ToolInvocation(BaseModel):    # a tool call, as the model requests it
    id: str                         # provider-issued; correlates the result back
    name: str
    arguments: dict[str, Any]
```

`ToolInvocation` is a **provider-layer** concept, deliberately distinct from the
tools package's `ToolCall`. The orchestration layer maps one to the other
(`ToolInvocation → ToolCall(tool=name, args=arguments, call_id=id)`), so
`providers/` gains **no dependency** on `tools/`.

### 2. Contract amendment (RFC-0001 §2 and §7)

All additions are defaulted, so every existing text-only call site keeps working:

```python
class GenerationRequest(BaseModel):
    ...
    tools: tuple[ToolSchema, ...] = ()
    tool_choice: Literal["auto", "none", "required"] = "auto"

class GenerationResult(BaseModel):
    ...
    tool_calls: tuple[ToolInvocation, ...] = ()
    finish_reason: Literal["stop", "tool_calls", "length"] = "stop"
```

`Message` (RFC-0001 §7) is **extended, not replaced** — one message type, new
optional fields:

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]     # + "tool"
    content: str = ""
    tool_calls: tuple[ToolInvocation, ...] = ()              # on an assistant turn
    tool_call_id: str | None = None                          # on a "tool" turn
```

This lets the conversation history hold a valid tool exchange — the assistant turn
that *requested* the calls, followed by one `"tool"` message per result — which the
native APIs require before the model will continue.

Each provider's request builder attaches its native tools array when
`request.tools` is non-empty, and its response parser emits `ToolInvocation`s and a
`finish_reason`:

| Provider | Native inbound | Native outbound |
|---|---|---|
| OpenAI / vLLM | `tools`, `tool_choice` | `choices[].message.tool_calls`, `finish_reason` |
| Anthropic | `tools`, `tool_choice` | `tool_use` content blocks, `stop_reason` |
| Ollama | `tools` | `message.tool_calls`, `done_reason` |
| Fake | scripted | scripted `tool_calls` (for tests) |

### 3. Tool-schema generation

A tool's `ToolSchema` is derived, never hand-written:

- `name`, `description` ← `ToolMeta`.
- `parameters` ← `input_model.model_json_schema()`, with `$defs`/`$ref` **inlined**
  into a single flat schema object (many local-model tool parsers handle `$ref`
  poorly).

This keeps the tool's execution-time validation model and its model-facing schema
as **one source of truth**.

### 4. The agentic loop

A standalone, reusable orchestration component wraps the **model-interaction** step:

1. Build the request with the enabled tools' `ToolSchema`s and the running message
   history; call `model_service.generate(ctx, request)`.
2. If `result.tool_calls` is empty (`finish_reason=stop`), the loop is done — the
   text is the answer.
3. Otherwise, append the assistant turn (carrying `tool_calls`), then **dispatch
   each call concurrently** through `ToolService.execute` (each on its own
   `ctx.child`), gather the `ToolResult`s, append one `"tool"` message per result
   (§5), and go to step 1.

Because the loop wraps the model interaction, the model's **native thinking and
tool-calling happen together** in one loop, available on every turn independent of
the RDT reasoning-orchestration config gate. Wiring tools into the RDT engine's own
passes (so the orchestration layer can act mid-reasoning) is a **reserved seam,
deferred** — it ties into the reasoning-experts work and a separate reasoning-gating
question, and is out of scope here.

Each tool call passes through `ToolService`'s existing permission gate (RFC-0007's
`WebSocketPromptResolver` when interactive), retry/timeout, and one-level fallback —
this RFC adds no execution behavior, only the caller.

### 5. Result feedback

Each `ToolResult` becomes the `content` of a `"tool"` message correlated by
`tool_call_id`:

- **Success:** the output serialized as JSON — `output_model.model_dump_json()`, or
  the raw output dict for a schemaless tool.
- **Failure** (execution error, permission-denied, timeout, cancelled): a structured
  `{"error": <code>, "message": <text>}`.

The model **sees failures** and decides what they mean — retry differently, take
another path, or tell the user. This matches `ToolService`'s deliberate contract of
*returning* failures as a `ToolResult` rather than raising, and keeps the agent
recoverable.

### 6. Loop bounds and safety

- **Iteration cap.** `ToolLoopConfig.max_iterations` (default 8) bounds
  generate→execute rounds. On reaching it, the loop makes **one final `generate`
  with `tool_choice="none"`** to force a text answer (graceful degradation); if that
  also fails, the turn ends with an error frame.
- **Concurrency.** Multiple `tool_calls` in one response run concurrently
  (`asyncio.gather` over independent `ToolService.execute` calls, each with its own
  `ctx.child`) — consistent with RFC-0002's single-loop model. Ordering across
  parallel calls is not guaranteed; a model that needs ordering issues calls
  sequentially across rounds.
- **Cancellation.** `ctx.cancelled` (an RFC-0007 `control:cancel`/barge-in) aborts
  the loop between steps and inside a cooperatively-cancellable tool.
- **Permission.** Each call is gated per-call as today; RFC-0007's deferred sticky
  "always-allow" would later reduce repeat prompts for a tool the model calls
  repeatedly.

### 7. Native-tool-support signal and the ReAct fallback (reserved)

A provider declares native tool-calling support via a **simple provider attribute**
(e.g. `supports_native_tools: bool`) — **not** a member of the RFC-0003 `capabilities`
set, so the closed capability set is untouched. Every shipped provider declares it. A
model/provider **without** native support would use a **ReAct-style text fallback**
— prompt-inject the schemas, parse `ToolInvocation`s out of `result.text` — behind
the same agentic-loop interface. That fallback is a **reserved, deferred seam**: no
shipped provider needs it, so building it now would be speculative.

### 8. Tool authoring conventions (normative)

How a tool is written determines whether a model can use it. Authors MUST:

- Give a **selection-oriented `ToolMeta.description`** — it is the primary text the
  model reads to decide whether to call the tool; describe *what it does and when to
  use it*, not how it is implemented.
- Put a **`Field(description=...)` on every `input_model` field** — these become the
  parameter schema the model sees; an undescribed field is an unusable one.
- Prefer **flat input models**; nested models are inlined but deep nesting degrades
  small-model reliability.
- Declare an **`output_model`** when the result is structured (it shapes the JSON the
  model gets back and enables verification); leave it unset only for genuinely
  free-form output.
- Set **`permission`** by side-effect risk (`allow` for read-only, `ask`/`deny` for
  writes/exec) and **document side-effects and idempotency** in the description.

These conventions are normative here and may later graduate into
[STYLE_GUIDE.md](../../STYLE_GUIDE.md) or a dedicated tool-authoring guide.

### 9. Streaming and config

- **Streaming.** The loop uses `generate()` per step (it needs the structured
  `tool_calls`); the **final, tool-free answer** may be streamed via `stream()` to
  the `chat` channel. Streaming *tool-call assembly* (incremental deltas) is
  **deferred/reserved** — the first increment resolves tool calls from a completed
  `generate`.
- **Config.** `ToolLoopConfig` (`max_iterations`, default `tool_choice`) is
  additive and sits alongside RFC-0007's `ToolsConfig`.

## Alternatives Considered

**ReAct-style text protocol above unchanged providers.** Prompt-inject schemas,
parse tool calls from `result.text`, leaving RFC-0001 untouched and working
uniformly on any model. Rejected as the primary mechanism: it reconstructs in
fragile prose-parsing what the providers expose natively, degrades on smaller local
models, and forgoes native parallel calls — the "fake it in text" pattern the
project has explicitly chosen to avoid. Kept as a **reserved fallback** (§7) for a
future text-only provider.

**Capability-gated hybrid, both paths built now.** Native where available, ReAct
where not. The most robust, but every shipped provider supports native tool-calling,
so the fallback has no present consumer — building and testing two paths now
violates YAGNI. Native-now with a reserved fallback seam captures the value without
the cost.

**Reuse `tools.ToolCall` directly in the provider contract.** Fewer types, but it
makes `providers/` import `tools/`, a coupling edge RFC-0001's dependency rule
avoids; a normalized provider-layer `ToolInvocation` plus a one-line mapping in the
orchestration layer keeps the layers clean.

**Discriminated `Message` union.** Elegant typing for the tool exchange, but a
larger §7 change touching every provider's serialization and all existing call
sites, for a clarity the extended single `Message` already delivers.

**Integrate the loop into the RDT reasoning engine now.** Lets the orchestration
layer act mid-reasoning, but reopens the scope and coupling the design deliberately
defers: refactoring a single-run, text-only, parse-pipeline engine while also
defining tool-calling. Deferred to a seam.

**Feed only successful results; abort the turn on failure.** Simpler, but the model
cannot recover from a recoverable failure, and it contradicts `ToolService`'s
return-don't-raise contract.

**No iteration cap.** A stuck or adversarially-prompted loop would burn tokens and
run side-effecting tools until a human cancels. A bounded loop with graceful
degradation is the responsible default.

## Migration Plan

1. **Provider contract (RFC-0001 §2/§7):** add the defaulted fields and the two new
   types; extend `Message`. Every existing caller (the reasoning engine, the eval
   harness) passes no tools and reads only `text`/`tool_calls=()`, so behavior is
   unchanged until a caller opts in.
2. **Per-provider translation:** implement inbound tools + outbound `tool_calls`
   parsing in each of OpenAI, Anthropic, Ollama, vLLM, and Fake. Text-only paths are
   untouched when `tools` is empty.
3. **New components:** the schema generator, the agentic loop, and `ToolLoopConfig`.
   The `ToolService` execution side (RFC-0001 §5) is reused **unchanged**.
4. **M8 consumption:** the M8 turn-loop cycle that handles tool use drives the
   agentic loop and frames its lifecycle on the `tools` channel (RFC-0007 §7). The
   `ToolInvocation → ToolCall` mapping lives in that orchestration layer.

No existing behavior is removed; the feature is additive and off until a turn
supplies tools.

## Risks

- **Small local models emit malformed tool calls or ignore tools.** Mitigated by
  schema flattening, the authoring conventions, and the graceful-final-answer cap;
  the reserved ReAct fallback is the escape hatch if a target model has no usable
  native support.
- **Per-provider native formats drift** (e.g. Anthropic `tool_use` blocks vs OpenAI
  `tool_calls`). Mitigated by confining translation to each provider and testing
  each against its native shape; the runtime only ever sees `ToolInvocation`.
- **Runaway or expensive loops.** Bounded by `max_iterations` and cancellation;
  side-effecting tools remain permission-gated per call.
- **Parallel tool execution interleaves side-effects.** Concurrency is only applied
  to the calls the model chose to parallelize; ordering-sensitive work is expressed
  as sequential rounds, and this is documented as an authoring/behavior note.
- **Extending `Message` is an RFC-0001 §7 change.** Mitigated by keeping it additive
  (defaulted fields, one new role) so no existing message construction breaks.

## Acceptance Criteria

1. `GenerationRequest` carries `tools`/`tool_choice` and `GenerationResult` carries
   `tool_calls`/`finish_reason`; `Message` supports a `"tool"` role, assistant
   `tool_calls`, and `tool_call_id`. Existing text-only calls behave identically.
2. Each provider (OpenAI, Anthropic, Ollama, vLLM, Fake) sends native tool schemas
   when `tools` is non-empty and parses native tool-calls back into
   `ToolInvocation`s with a normalized `finish_reason`.
3. A tool's `ToolSchema` is generated from its `ToolMeta` + `input_model` with
   `$defs` inlined; no tool hand-writes a JSON Schema.
4. The agentic loop, given a `FakeProvider` scripted to request a tool then answer,
   dispatches the call through `ToolService`, feeds the result back, and returns the
   final text — with a tool **failure** rendered as a structured error the model
   receives.
5. Multiple `tool_calls` in one response execute concurrently; `ctx.cancelled`
   aborts the loop; reaching `max_iterations` triggers one final
   `tool_choice="none"` generate.
6. The `ToolService` execution contract (RFC-0001 §5) is unchanged — no new
   execution behavior, only a new caller.
7. Native-tool support is declared per provider via a simple provider attribute
   (no new RFC-0003 capability); the ReAct fallback is documented as reserved and
   not built.
8. The authoring conventions (§8) are documented normatively, and the starter tools
   conform (selection-oriented descriptions, per-field `Field(description=...)`).

## Architectural Impact

- **Does this increase coupling between services?** It amends the
  `Provider`/`ModelService` contract and adds one **orchestration component** (the
  agentic loop) that depends on both `providers/` and `tools/`. Crucially,
  `providers/` gains **no** dependency on `tools/` — the normalized `ToolInvocation`
  is a provider-layer type and the `ToolInvocation → ToolCall` mapping lives in the
  orchestration layer, which is above both. Coupling is one-directional and lands in
  the layer whose job is composition.
- **Does this create hidden state at service boundaries?** No. The loop's state is
  the explicit message history it threads; `ExecutionContext`/`CancelToken` are
  explicit; `ToolService` remains stateless-per-call with a pull-only snapshot.
- **Does this bypass a service boundary from a prior RFC?** No. Tool execution still
  goes through `ToolService` and its permission gate (RFC-0007); the model is still
  reached through `ModelService`. The RFC *extends* the provider contract rather than
  routing around it.
- **Does it violate the Constitution?** No. It advances the honest-engineering
  principle (use the models' native mechanism rather than prose theater) and
  inspectability (tool calls and results are framed on the `tools` channel and
  visible). It **amends RFC-0001 §2/§7** — an explicit, additive contract change of
  the kind the RFC process exists to govern (RFC-0006 precedent) — and leaves
  RFC-0001 §5 intact.
- **Can it be tested independently?** Yes. `FakeProvider` scripts `tool_calls`, fake
  tools exercise the loop, and the schema generator and per-provider translation are
  unit-testable without a network — the no-key discipline holds.
- **New service, or existing one?** No new *service*: a new orchestration component
  plus contract fields and a schema helper. Execution, permissions, and the tool
  contract are reused unchanged.
- **Can it be removed later without affecting the runtime core?** The contract
  fields are additive and default to empty (text-only behavior). The agentic loop is
  an orchestration component the turn loop opts into; removing it returns the runtime
  to text-only generation without disturbing the providers or the tool subsystem.
