# RFC-0012: Native Thinking Controls — Per-Turn Toggle, Re-Ask, and Voice Phrases

- **Status:** Accepted (2026-11-03)
- **Author:** Zygos maintainers
- **Created:** 2026-11-03
- **Governs:** how a user turns the model's **native thinking** (hidden reasoning
  tokens, e.g. Ollama `think`) on for a turn or a session, re-asks a question with
  thinking, and does both by voice; how the effective setting reaches every turn
  path; how the model's thinking text and the thinking state are shown; and how
  support is detected per model so unsupported models say so.
- **Depends on:**
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the session, the turn
  loop, and the WebSocket frame set this RFC extends),
  [RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md) (the STT-final → turn path
  the voice phrases sit on), and
  [ADR-0007](../adr/ADR-0007-native-thinking-off-by-default.md) (thinking is off
  by default; `providers.think` and `GenerationRequest.think` already exist).
- **Relates to:**
  [RFC-0011](RFC-0011-React-UI-Frontend-Architecture.md) (the chat surface gains
  the toggle, the re-ask button, and the reasoning disclosure),
  [RFC-0010](RFC-0010-User-Personalization-and-Assistant-Identity.md) (the voice
  phrases run before the turn, so the §3a modality context still describes the
  turn correctly), and the reasoning-gating RFC tracked in Archon `cbb2e0ef`
  (model-decided RDT orchestration — a different layer, left open here).
- **Amends:** RFC-0007 §2 **additively**: new `control:think`, `control:think.state`
  and `chat:voice_command` frame types, and new optional fields on
  `chat:user_message`, `chat:turn.start` and `chat:turn.end`. No existing frame
  changes meaning; RFC-0007's rule that clients ignore unknown `(channel, type)`
  pairs keeps older clients working. Refines ADR-0007's "later a per-turn UI toggle
  or voice command" into a design.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md).

## Summary

Thinking stays **off by default** (ADR-0007), and becomes cheap to reach for when
an answer needs it. Three controls set it, all per turn underneath:

1. **Re-ask with thinking** — every assistant answer gets a "Think it through"
   action that asks the same question again as a new turn with thinking on. The
   quick answer stays visible; the new one is labelled. This is the main path:
   get the fast answer, decide it isn't enough, think it through.
2. **Session toggle** — a Think toggle beside Speaker makes every turn think until
   it is turned off. It starts off in every new session and is not persisted.
3. **Voice phrases** — a small, fixed, deterministic set of spoken phrases ("think
   it through, …", "think harder", "turn thinking on/off") is recognized on the
   STT transcript before the turn runs. The UI shows when a phrase was heard.

The model's thinking text, which the Ollama provider currently discards, is kept
and made observable **step by step on the trace channel** (one event per model
call), where the Inspect surface shows it. The chat window stays clean: a thinking
answer carries only a small "thought for N s" label that links to that turn in
Inspect. Thinking text is never spoken and never stored in memory. Each turn records whether it thought. The controls are enabled
only when the active model declares thinking support; otherwise they are disabled
with a reason.

## Motivation

ADR-0007 turned native thinking off by default because it costs seconds before the
first word (qwen3:8b 0.03 s vs 1.60 s to first answer token) — fatal for voice. It
also measured what thinking buys on hard problems (qwen3:8b 23/32 → 31/32 on
`reasoning-seed-v1`). Both are real, and which one a user wants depends on the
question, often only *after* seeing the quick answer. Today the only way to get
thinking is a config change that applies to every request and needs a restart.

## Problem Statement

1. **No runtime control.** `GenerationRequest.think` exists but nothing sets it;
   `providers.think` is global, file-edited, restart-bound.
2. **No "try again, harder."** The natural workflow — quick answer first, deeper
   answer on demand — needs re-typing the question and editing config.
3. **No voice path.** A voice user has no hands on a toggle.
4. **Thinking is invisible.** Ollama returns `message.thinking` alongside the
   answer; `ollama.py` drops it, and nothing records whether a turn thought —
   against the "inspectable" principle.
5. **Silent no-ops.** Only Ollama reads `think`, and only some Ollama models can
   think; a toggle that silently does nothing would mislead.

## Proposed Design

### 1. Effective thinking per turn

Each turn resolves one boolean, `think`, in this precedence (first defined wins):

1. the turn's **explicit request** — `user_message.think`, a re-ask, or a voice
   per-turn phrase;
2. the **session toggle** (`session.think`, default `None` = not set);
3. the config default `providers.think` (ADR-0007, default `false`).

If the active model does not support thinking (§5), the effective value is
`false` and the turn records `think_unsupported_reason`.

The resolved value is passed as `GenerationRequest.think` on **every** model call
the turn makes: the direct streaming path, every iteration of the agentic tool
loop, and the RDT reasoning path (prelude, recurrent, judge, coda). `run_turn`
gains a required keyword `think: bool | None` resolved by its caller site in the
same way as `spoken_input` (RFC-0010 Risks): no silent default.

### 2. Wire protocol (additive to RFC-0007 §2)

| Frame | Direction | Payload | Meaning |
|---|---|---|---|
| `control:think` | →srv | `{enabled: bool}` | Set the session toggle. |
| `control:think.state` | →cli | `{enabled: bool, supported: bool, reason: str \| null}` | Current toggle + support. Sent after `hello`, after every change from any source (UI or voice), and when support changes. |
| `chat:user_message` | →srv | existing `{text}` + optional `think: bool`, optional `rethink_of: turn_id` | Per-turn override; `rethink_of` marks a re-ask. |
| `chat:turn.start` | →cli | existing + `think: bool`, `rethink_of: turn_id \| null` | Lets the UI show "Thinking…" from the start. |
| `chat:turn.end` | →cli | existing + `think: bool`, `thinking_ms: int \| null`, `think_unsupported_reason: str \| null` | What actually happened; `thinking_ms` drives the "thought for N s" label. No thinking text. |
| `chat:voice_command` | →cli | `{command: "think_turn" \| "rethink" \| "think_on" \| "think_off", phrase: str}` | A voice phrase was recognized (§4). |

`control:think.state` is the single source of truth for the UI toggle, so a voice
"turn thinking on" and a click stay in sync.

### 3. Re-ask with thinking

The UI's "Think it through" action on an answer sends
`chat:user_message{text: <that turn's user text>, think: true, rethink_of: <turn_id>}`.
It is an ordinary new turn: retrieval, tools, memory recording and (if Speaker is
on) speech all happen as usual. The UI renders it directly after the original
answer, labelled "with thinking". The action is shown on every assistant answer
whose turn did not already think, and is disabled while a turn is running or when
thinking is unsupported.

The server keeps `session.last_user_text` (the most recent turn's user text,
typed or spoken) for the voice "think harder" re-ask (§4); the UI's action always
sends the text explicitly.

### 4. Voice phrases (deterministic, spoken turns only)

A pure function `parse_voice_command(text) -> VoiceCommand | None` runs on the STT
final transcript in `api/audio.py`, before `run_turn`. Matching is
case-insensitive, ignores leading/trailing punctuation and filler punctuation the
STT engine adds ("Think it through, what's…"), and matches only at the **start**
of the utterance:

| Spoken | Command | Effect |
|---|---|---|
| "think about this …", "think about it …", "think it through …", "think carefully …" followed by a question | `think_turn` | Phrase stripped; the rest runs as this turn with `think=true`. |
| "think harder", "think about that", "think it through" with **nothing after** | `rethink` | Re-ask `session.last_user_text` with `think=true`, `rethink_of` = last turn. No previous turn → a short spoken/written "There's nothing to think about yet." |
| "turn thinking on", "thinking on" | `think_on` | Session toggle on; short confirmation ("Thinking on."). No model call. |
| "turn thinking off", "thinking off" | `think_off` | Session toggle off; "Thinking off." No model call. |

Every match emits `chat:voice_command` so the UI shows what was heard. Typed text
is **never** parsed for phrases — typed users have the button and toggle, and a
typed "think about this" is just text. The phrase list is a constant in one
module, unit-tested, and documented in the README; adding phrases is a code
change, not configuration.

When a spoken turn thinks and the reply will be spoken, TTS first says a fixed
"Let me think about that." so the user is not left in seconds of silence.

### 5. Support detection

A turn may think only if the active route supports it:

- **Ollama:** query `POST /api/show {model}` once per model (cached for the process
  lifetime) and read its `capabilities` list; `"thinking"` present → supported.
  Query failure → `supported: false`, reason `"couldn't check the model"` — the
  controls disable rather than guess.
- **Every other provider:** `supported: false`, reason
  `"thinking controls aren't available for <provider> yet"`. Mapping to Anthropic
  extended thinking, OpenAI reasoning effort, and vLLM chat-template flags is
  future work in this same shape (ADR-0007 Consequences).

Support is exposed in the runtime manifest (`GET /runtime`, `zygos inspect`) as
`thinking: {supported, reason}` for the primary route, and in
`control:think.state`.

### 6. Thinking text

`GenerationResult` and `GenerationChunk` gain `thinking: str | None` (default
`None`). The Ollama provider fills it from `message.thinking` (non-streaming) and
from each chunk's `message.thinking` (streaming).

**Observation, not chat.** After each model call that returned thinking, the turn
emits one bus event, `model.thinking`, mirrored on the existing `trace:event`
channel (RFC-0007 §10):

```
{type: "model.thinking", turn_id, step, index, text, truncated, chars, elapsed_ms}
```

- `step` names where in the turn it happened: `direct`, `tool_loop`, or the RDT
  stage (`prelude`, `recurrent`, `judge`, `coda`); `index` orders events within
  the turn (tool-loop iteration / RDT pass).
- `text` is capped at `MAX_THINKING_EVENT_CHARS = 32_000` per event and works
  as a **rolling buffer that keeps the tail**: when a call's thinking is longer,
  the oldest text is dropped and the most recent 32,000 characters are kept, so
  the end of the thinking (where the model settles on its answer) is always
  shown. `truncated: true` marks a cut, `chars` gives the full length, and
  Inspect shows "… N earlier characters not kept" above the text. When the
  provider streams thinking, the buffer is a bounded deque filled chunk by
  chunk, so memory stays at the cap however long the model thinks.
- `elapsed_ms` is that call's time to its first answer token, summed into
  `turn.end.thinking_ms`.

The Inspect surface groups these events by turn and shows them in order, so the
user can follow the model's thinking through tool calls and reasoning passes. The
chat surface shows only the "thought for N s" label, which opens that turn in
Inspect. Thinking events are emitted when they happen (not held to `turn.end`),
so Inspect fills in while a long turn runs.

Thinking text is:

- never in chat frames (`turn.end` carries only `thinking_ms`);
- never sent to TTS;
- never written to memory (`format_exchange` records the answer only);
- kept only where trace events already go (local, in-process; RFC-0007 §10), so
  it is the user's data on the user's machine like the rest of the trace.

### 7. Relationship to RDT reasoning

`ReasoningConfig.enabled` (multi-pass RDT orchestration) is unchanged and
independent. When RDT is on, the turn's effective `think` is carried into every
RDT model call, so "think it through" also deepens each RDT pass. Making RDT
itself model-decided remains the separate reasoning-gating work (`cbb2e0ef`).

## Alternatives Considered

- **Let the model decide (a "think harder" tool).** Rejected: it costs a model
  call to decide, is unpredictable, and hides the trigger. Deterministic phrases
  are honest and free. The model-decided layer is `cbb2e0ef`'s question.
- **Persist the toggle.** Rejected for now: the default is off because thinking is
  slow; a remembered "on" would silently bring back multi-second voice turns.
  Revisit if users ask; it would be a browser-local setting, not runtime state.
- **Per-message flag only, no session toggle.** Rejected: voice turns have no
  message payload to carry it, and a user doing a run of hard questions wants a
  mode.
- **Route to a separate "thinking model."** Out of scope; that is per-turn model
  routing (RFC-0009). This RFC only flips the active model's own thinking.
- **Stream thinking tokens live.** Deferred: the tools path (the default) is
  non-streaming today, and a live reasoning pane is a UI design question of its
  own. One trace event per model call, as each call finishes, is enough to
  follow the thinking step by step.
- **Show thinking in the chat window** (collapsed under each answer). Rejected:
  chat is for answers; thinking belongs with the other observation data (model,
  memory, tools) in Inspect, where it can be shown per step rather than as one
  merged block.
- **Parse phrases in typed text too.** Rejected: typed users have direct controls;
  parsing typed text would surprise anyone who types "think about this" as part of
  a question.
- **Replace the quick answer with the thinking one.** Rejected: keeping both lets
  the user compare, which is the point of re-asking.

## Migration Plan

Additive. Existing clients that never send `control:think` or `think` get exactly
today's behavior (config default, off). Order:

1. `thinking` on `GenerationResult`/`GenerationChunk`; Ollama fills it.
2. Support detection + manifest field.
3. Effective-`think` resolution in `run_turn` (required keyword) threaded through
   the direct, tool-loop and RDT paths; `turn.start`/`turn.end` fields.
4. `control:think` / `control:think.state`; `session.think`, `session.last_user_text`.
5. `parse_voice_command` + the audio-path wiring + `chat:voice_command` + the
   "Let me think about that." prefix.
6. Frontend: Think toggle, "Think it through" action, "Thinking…" state,
   "thought for N s" label linking to Inspect, Inspect grouping of
   `model.thinking` events by turn, voice-command notice, unsupported-state copy.
7. README: the controls and the spoken phrases.

## Risks

- **Mis-heard phrases.** STT may produce "think harder" from something else, or
  miss it. Mitigated by start-of-utterance matching only, a short fixed list, and
  the visible `chat:voice_command` notice; the worst case is one slower turn or a
  toggle the UI shows plainly.
- **A question that genuinely starts with "think about this".** It still runs as a
  question, just with thinking on — the cost is latency, not a wrong answer.
- **Duplicate memory records on re-ask.** A re-ask records a second exchange for
  the same question. Acceptable: the deeper answer is the one most worth
  recalling, and recency weighting favors it. Revisit if memory quality suffers.
- **Large thinking text.** Reasoning can run to thousands of tokens per call and
  several calls per turn. Mitigated by one event per call, a per-event rolling
  buffer (`MAX_THINKING_EVENT_CHARS`) that keeps the tail and flags the cut, and
  keeping it out of chat frames, TTS and memory. Cost: the start of a very long
  thinking block is lost; the tail is kept because it is where the model reaches
  its conclusion.
- **Support cache goes stale** if the user swaps the model behind the same name.
  Accepted for a process lifetime; restarting the server refreshes it.
- **Toggle drift between tabs.** The toggle is per session; a second tab has its
  own session and state. Matches how Speaker behaves.

## Acceptance Criteria

1. With no new frames sent, every turn's requests carry the config default and
   output is unchanged from today (tested).
2. `user_message.think=true` makes that turn's model calls carry `think=true` on
   the direct, tools and RDT paths; the next turn reverts to the session/config
   value (tested per path).
3. `control:think{enabled:true}` makes subsequent turns think until
   `{enabled:false}`; every change emits `control:think.state` (tested).
4. A re-ask (`rethink_of`) runs as a new turn with `think=true`, and `turn.start`
   and `turn.end` carry `rethink_of` and `think` (tested).
5. `parse_voice_command` recognizes exactly the listed phrases at the start of an
   utterance, tolerant of case and STT punctuation, and nothing elsewhere
   (table-tested, including near-misses). Typed text is never parsed.
6. A spoken `think_turn` strips the phrase; `rethink` re-asks the last user text
   (and handles "no previous turn"); `think_on`/`think_off` change the toggle
   without a model call; each emits `chat:voice_command` (tested).
7. `run_turn` requires the `think` argument; both production callers pass it
   explicitly (tested).
8. Each model call that returns thinking emits one `model.thinking` trace event
   with the right `step`/`index`; past the cap it keeps exactly the **last**
   `MAX_THINKING_EVENT_CHARS` characters with `truncated` and `chars` set; the
   text is absent from every chat frame, TTS input and memory record; and
   `turn.end.thinking_ms` is set on thinking turns (tested on the direct, tools
   and RDT paths).
9. An Ollama model without the `thinking` capability, or any non-Ollama provider,
   reports `supported: false` with a reason in the manifest and
   `control:think.state`, and a requested think on it runs with `think=false` and
   `think_unsupported_reason` set (tested with a fake `/api/show`).
10. The UI shows the toggle, the per-answer "Think it through" action, a
    "Thinking…" state, a "thought for N s" label that opens the turn in Inspect,
    `model.thinking` events grouped by turn in Inspect, the voice-command notice,
    and disabled controls with the reason when unsupported (component tests).

## Architectural Impact

- **Coupling.** Low. One new boolean threads through the existing request seam
  (`GenerationRequest.think`); the provider contract gains one optional field.
  Voice phrase parsing is a pure function at the audio-path edge.
- **Hidden state.** None hidden: the session toggle is announced on every change
  (`control:think.state`), each turn reports what it did, and support is in the
  manifest. The support cache is process-local and documented.
- **Service boundaries.** Respected: the turn loop resolves the setting and passes
  it down; providers translate it; the UI only sends frames.
- **Constitution.** Serves "inspectable" (thinking is observable step by step in
  Inspect; the thinking state is on every turn)
  and user choice (the user decides per turn; nothing is forced on a model that
  can't do it). Keeps ADR-0007's default.
- **Independent testing.** Yes: phrase parsing, effective-value resolution,
  provider mapping and support detection are each unit-testable with fakes.
- **New service?** No — additions to the turn loop, the Ollama provider, the
  audio path and the chat surface.
- **Removability.** Yes: without the new frames the runtime behaves exactly as
  under ADR-0007; dropping the controls removes a parameter, three frame types and
  one pure module.
