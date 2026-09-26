# RFC-0010: User Personalization and Assistant Identity

- **Status:** Draft
- **Author:** Zygos maintainers
- **Created:** 2026-07-13
- **Governs:** how a user personalizes the assistant — the name the assistant calls
  the user, the name the user gives the assistant, and a short persona/tone — and how
  those preferences reach generation. Covers the authoritative **preferences store**,
  the first-run **onboarding compile-and-review flow** (natural-language description →
  structured preferences + a reviewed persona snippet), the **identity system-prompt
  injection** into the turn loop, the per-turn **interaction-modality context** (telling
  the model when a turn was spoken and/or will be read aloud), and default/degradation
  behavior.
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the `Message` typing §7 the identity
  system message uses, and `ModelService` §2 which performs the one-shot compile call),
  and [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the turn loop's
  `build_messages()` system-message seam, left deliberately empty in M8 C2, that this
  RFC fills).
- **Relates to:**
  [RFC-0009](RFC-0009-Model-Routing-and-Multimodal-Capabilities.md) (not required, but
  synergistic: because the identity lives in `build_messages`, it applies to whichever
  per-turn authoring model writes the turn — B works standalone with a single model),
  [RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md) (TTS greeting/address is a
  consumer of the same preferences; the STT→turn and turn→TTS paths are what the §3a
  modality context describes to the model), and the React UI RFC (the settings page is the
  runtime editor for the store). None is built here; this RFC only exposes the store
  they consume.
- **Amends:** nothing. It **fills** the `build_messages()` system-message seam that
  RFC-0007 left empty by design; it does not change any published contract.
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md). Small,
  single-cycle build; default-preserving until a user personalizes.

## Summary

Let a user make the assistant theirs: set what the assistant calls them (e.g. "Josh"),
name the assistant (e.g. "Rommie"), and give it a short persona/tone. Preferences live
in a small, single-user, runtime-editable **preferences store** that is the
authoritative, deterministic source — **not** memory, which is relevance-gated and wrong
for something that must always apply. Rather than make the user hand-write a system
prompt, a first-run **onboarding flow** takes a natural-language description
("call me Josh; I'd like a concise assistant named Rommie with a little dry wit"), runs
**one structured model call** to extract the bounded fields *and* draft a short persona
snippet, and lets the user **review and edit before it is saved** — the raw description
is never stored, only the reviewed result. Every turn, `build_messages()` prepends an
**identity system message** rendered from the stored preferences, ahead of the memory
message. Because it lives in `build_messages`, the identity applies no matter which
per-turn authoring model (RFC-0009) writes the turn. With preferences unset, nothing is
injected and behavior is exactly as today.

Alongside identity, `build_messages()` adds a short, runtime-authored **modality context**
on voice turns: when the user's words arrived as a speech-to-text transcript and/or the
reply will be spoken by TTS. It is derived from the turn itself, not stored as a
preference, and typed turns with spoken output off get nothing — unchanged from today.

## Motivation

There has been no user-interaction design between Zygos and the user. The first, concrete
thing a personal assistant should do is address its user by name and answer to a name the
user chose — "Hi Josh, what can I help you with?" from an assistant the user calls
"Rommie." This is table stakes for a personal-assistant framing, and it is the first real
content for the system-prompt seam that M8 C2 intentionally left empty.

Two forces shape the design. First, **identity must be deterministic**: a name is not a
"relevant memory" to be retrieved when it seems apt — it must be present every turn, so
it needs an authoritative store, not the probabilistic memory layer. Second, **expressive
but bounded and honest**: users should be able to *describe* the assistant they want in
plain language, but Zygos should not become a freeform prompt-authoring tool. Compiling a
description into bounded fields plus a **human-reviewed** persona snippet keeps the
feature warm and personal without turning it into unmoderated system-prompt authoring.

## Problem Statement

1. **No home for user preferences.** `ZygosConfig` has no user/persona section, and
   config is operator/deployment-oriented — the wrong place for a runtime, user-editable
   preference.
2. **Memory is the wrong source.** `build_messages()` injects memory only when relevant
   (`retrieve(query=…)`); identity must always apply, so it cannot ride the memory path.
3. **The system-message seam is empty.** M8 C2 left `build_messages()` with no identity
   system prompt; there is no personalization at generation time.
4. **Raw prompt authoring is undesirable.** Letting a user type the system prompt is a
   large, quality/safety-sensitive surface; there is no guided, bounded alternative.
5. **The model doesn't know a turn is spoken.** A voice turn reaches the model as a bare
   user string, indistinguishable from typing. In the live voice smoke test (2026-09-26)
   the user said "Can you hear…?" and the model — seeing only text and a tool list with no
   audio tool — answered "I can't hear anything, as I don't have access to audio input."
   It also formats spoken replies with markdown lists/headings that TTS reads aloud, and it
   has no cue that the input may contain recognition errors.

## Proposed Design

### 1. Preferences store

A small, single-user store — the authoritative source, read deterministically each turn
and writable at runtime (by a command now, the settings page later). Backed by the
existing local SQLite (a single-row `personalization` table) or an equivalent local doc;
single-user, so no keying by user id is required.

```python
class Personalization(BaseModel):
    user_name: str | None = None       # what the assistant calls the user
    address: str | None = None         # optional honorific / form of address
    pronouns: str | None = None
    assistant_name: str | None = None  # what the user calls the assistant
    tone: str | None = None            # short descriptor, e.g. "concise, dry wit"
    persona: str | None = None         # reviewed snippet, a few sentences

class PreferencesStore(Protocol):
    def get(self) -> Personalization: ...
    def set(self, prefs: Personalization) -> None: ...
```

All fields optional; an all-`None` store means "not personalized."

### 2. Onboarding compile-and-review flow

On first run with an empty store (and re-runnable anytime via a command / the settings
page), the runtime invites a natural-language description and compiles it:

```python
async def compile_personalization(
    ctx: ExecutionContext, model: ModelService, description: str
) -> Personalization: ...
```

`compile_personalization` performs **one** model call whose output conforms to the
`Personalization` schema — extracting the bounded fields and drafting a short `persona`
snippet from the description. The result is **presented to the user to review and edit**;
only on approval is it written via `PreferencesStore.set`. The raw description is not
stored. Onboarding is **skippable**: skipping leaves the store empty (unpersonalized).

Direct editing (settings page, or a `zygos` command) may set fields without the compile
step — the compile flow is the guided on-ramp, not the only path.

### 3. Identity injection (fills the RFC-0007 seam)

`build_messages()` gains an identity system message rendered from the stored preferences,
prepended **before** the memory system message:

```python
def render_identity(prefs: Personalization) -> str | None:
    # None when nothing is set -> no message injected (default-preserving)
    ...

def build_messages(prefs: Personalization, context: tuple[str, ...], text: str) -> tuple[Message, ...]:
    messages: list[Message] = []
    identity = render_identity(prefs)
    if identity:
        messages.append(Message(role="system", content=identity))
    if context:
        messages.append(Message(role="system", content=f"Relevant memory:\n{'\\n'.join(context)}"))
    messages.append(Message(role="user", content=text))
    return tuple(messages)
```

The template renders names/address deterministically and appends the approved `persona`
snippet. Because this is in `build_messages`, the identity applies for **every** turn and
**every** per-turn authoring model (RFC-0009) — one seam, all models.

### 3a. Interaction-modality context (voice turns)

A voice turn needs the model to know two independent facts, each derived **per turn**
from the turn loop — not from the preferences store, because they describe *how this turn
is happening*, not who the user is:

```python
@dataclass(frozen=True)
class TurnModality:
    spoken_input: bool = False   # text is an STT transcript (turn started from audio.in)
    spoken_output: bool = False  # reply will be synthesized (session.speak and TTS available)

def render_modality(m: TurnModality) -> str | None:
    # None when both are False -> no message injected (default-preserving)
    ...
```

- `spoken_input` is set by the caller that starts the turn: the audio path (the STT
  `final` handler in `api/audio.py`) passes `True`; typed `user_message` passes `False`.
  `run_turn` gains the modality as a parameter rather than inferring it.
- `spoken_output` mirrors the gate `run_turn` already uses before `speak_reply`
  (`session.speak` and `voice_service.tts_available`). Typed-in/spoken-out is valid (the
  Speaker toggle on while typing) and gets only the output half.

`render_modality` is a **fixed, runtime-authored template** — no user text, no model
call. Indicative content (exact wording is an implementation detail, tested for presence
of each clause, not verbatim):

- *spoken_input:* "The user is speaking to you. Their words reach you as a speech-to-text
  transcript, so treat them as heard speech and allow for recognition errors (misheard or
  missing words); interpret charitably and ask for clarification only when the meaning is
  genuinely unclear."
- *spoken_output:* "Your reply will be read aloud by text-to-speech. Write it as natural
  conversational speech: no markdown, headings, bullet lists, tables, code blocks, or raw
  URLs; keep it concise; spell out anything that would read badly aloud."

Message order in `build_messages`: **identity → modality → memory → user**. Identity is
stable across turns, modality varies per turn, memory is relevance-gated; putting the
per-turn and relevance-gated parts last keeps the stable prefix cache-friendly.

```python
def build_messages(prefs: Personalization, modality: TurnModality,
                   context: tuple[str, ...], text: str) -> tuple[Message, ...]:
    messages: list[Message] = []
    for system in (render_identity(prefs), render_modality(modality)):
        if system:
            messages.append(Message(role="system", content=system))
    if context:
        messages.append(Message(role="system", content=f"Relevant memory:\n{'\\n'.join(context)}"))
    messages.append(Message(role="user", content=text))
    return tuple(messages)
```

**Seam coverage — reasoning path.** Today `build_messages` is used only on the tools and
direct-generate paths; when `reasoning_enabled` is on, `run_turn` hands
`ReasoningInput(prompt=text, context=context)` to the reasoning service and never calls
`build_messages`. Both the identity (§3) and modality (§3a) messages must reach that path
too, or reasoning turns silently lose them. The build therefore carries the rendered
system messages into `ReasoningInput` (e.g. a `system: tuple[str, ...]` field threaded to
the prelude/coda generation requests) — the same content, one rendering site.

**Honesty note.** The modality message tells the model the true mechanics (speech arrives
as a transcript; the reply is synthesized). It must not claim the model can perceive
audio itself (tone, non-speech sounds) — it cannot.

### 4. Consumers (named, not built here)

- **Voice (RFC-0005):** the TTS greeting/address reads `user_name`/`address` from the
  same store.
- **Settings UI (React UI RFC):** the runtime editor for the store; also the review
  surface for step 2 once a UI exists (pre-UI, review happens in the CLI/chat flow).

This RFC exposes the store and `render_identity`; consumers bind to them.

## Alternatives Considered

- **Store the name in semantic memory.** Rejected: memory is relevance-gated and
  non-deterministic; identity must always apply. Memory may still *suggest* a name it
  learns, but the store is authoritative.
- **Put preferences in `ZygosConfig`.** Rejected as the authoritative home: config is
  operator/deployment-oriented and edited by file+reload, not a user runtime preference.
  Config may still **seed** initial defaults into the store.
- **Let the user write the system prompt directly (freeform).** Rejected: large
  quality/safety surface; turns a preference into prompt authoring. The compile-to-fields
  + reviewed-snippet path is expressive without being unmoderated.
- **Compile with no review step.** Rejected: an LLM drafting the persona unseen could
  misrepresent intent; human review before save is the guardrail.
- **Skip the compile flow; forms only.** Rejected as the sole path: describing what you
  want in plain language is friendlier than filling fields; but direct field editing is
  kept as the non-guided alternative.
- **Store voice mode as a preference / always inject a voice note.** Rejected: whether a
  turn is spoken changes turn by turn (the user can type, then talk); a stored flag would
  be wrong half the time. Deriving it per turn is exact.
- **Strip markdown from the reply before TTS instead of prompting.** Rejected as the sole
  fix: it removes symbols but not list-shaped, visually structured prose, and does nothing
  for the "can you hear me" misunderstanding. A sanitizer may still be added as
  defense-in-depth in the TTS path (RFC-0005), independent of this RFC.
- **Mark spoken input inside the user message (e.g. a `[spoken]` prefix).** Rejected:
  pollutes the stored transcript/memory with transport metadata; a system message keeps
  the user's words verbatim.

## Migration Plan

Additive and **default-preserving**, single build cycle:

1. Add the `Personalization` model + `PreferencesStore` (SQLite-backed) + wiring so the
   turn loop can read it.
2. Thread `prefs` into `build_messages` and add `render_identity` (returns `None` when
   unset → no behavior change).
3. Add `compile_personalization` + the first-run/re-runnable onboarding-and-review flow
   (CLI/chat pre-UI).
4. Expose the store for the voice and settings-page consumers (seam only).
5. Add `TurnModality` + `render_modality`; thread the modality from the turn's caller
   (audio STT-final path vs typed `user_message`) into `run_turn` and `build_messages`.
6. Carry the rendered identity + modality system messages into the reasoning path
   (`ReasoningInput`) so reasoning-enabled turns receive them too.

Steps 5–6 do not depend on steps 1–4 (an empty store renders no identity), so the
modality context can land first if voice needs it before onboarding is built.

Existing installs are unaffected until a user personalizes: with an empty store,
`build_messages` output for **typed turns with spoken output off** is byte-for-byte
today's. Voice turns intentionally change (they gain the modality message).

## Risks

- **Compile misreads intent.** Mitigated by mandatory human review/edit before save and
  by keeping fields bounded.
- **Over-long/injected persona.** Mitigated by a length-bounded `persona`, the reviewed
  snippet (not raw text), and rendering through a fixed template rather than
  concatenating user text as instructions verbatim.
- **Scope creep to a full profile system.** Mitigated by the bounded field set; richer
  profile/preferences are a future RFC if ever needed.
- **Determinism regressions in `build_messages`.** Mitigated by `render_identity`
  returning `None` when unset, holding today's behavior exactly, and testing the
  injected-vs-empty paths independently.
- **Models ignore the spoken-output guidance** (small local models still emit lists).
  Mitigated partially; a TTS-side markdown sanitizer is the backstop (see Alternatives).
  The modality message is still required for the input-side misunderstanding.
- **Modality drift across paths.** A new turn-starting path that forgets to pass
  `TurnModality` silently defaults to typed. Mitigated by making it a required
  `run_turn` parameter (no default) and testing both callers.

## Acceptance Criteria

1. `Personalization` + `PreferencesStore` exist; `get`/`set` round-trip through the local
   store; an empty store returns all-`None`.
2. `compile_personalization` turns a natural-language description into populated fields
   **and** a drafted `persona` snippet via one model call; the raw description is not
   persisted.
3. The onboarding flow presents the compiled result for review/edit and only saves on
   approval; it is skippable, and skipping leaves the store empty.
4. `build_messages` injects an identity system message (before the memory message) when
   preferences are set, and injects **nothing** when unset — the unset output is
   identical to today (proven by test).
5. The identity applies regardless of which per-turn authoring model (RFC-0009) writes
   the turn.
6. Direct field editing (bypassing compile) writes the same store.
7. The store and `render_identity` are reachable by the voice and settings-page consumers
   (seam present), without those consumers being built here.
8. A turn started from an STT final carries `spoken_input=True`; a typed `user_message`
   carries `False`; `spoken_output` is `True` exactly when the reply would be synthesized.
   Both callers are tested.
9. `build_messages` injects the modality message (after identity, before memory) when
   either flag is set, containing the input clause and/or output clause as applicable,
   and injects **nothing** when both are false — the typed/no-speaker output is identical
   to today (proven by test).
10. Reasoning-enabled turns receive the same identity and modality system content as the
    tools/direct paths (proven by test against a fake reasoning service).

## Architectural Impact

- **Coupling.** Minimal: a small store plus one turn-loop read and one optional model
  call. No new service-to-service dependencies; consumers (voice, UI) bind to a narrow
  store interface.
- **Hidden state.** None hidden: preferences are explicit in the store, inspectable, and
  the injected identity and modality are plain system messages visible in the
  thread/trace. Modality is derived per turn and never stored. The raw
  description is deliberately not retained.
- **Service boundaries.** Respects them: fills the RFC-0007 `build_messages` seam rather
  than routing personalization around the turn loop; does not touch the memory or
  provider contracts.
- **Constitution.** Serves "honest, inspectable" (reviewed, bounded, visible identity;
  no unmoderated prompt authoring) and the single-user, local-first, personal-assistant
  framing (preferences live locally, user-owned).
- **Independent testing.** Yes — store round-trip, compile (with a fake model),
  `render_identity`, and the injected-vs-empty `build_messages` paths are each testable in
  isolation; the onboarding flow tests against a fake model.
- **New service?** A small store, analogous in weight to the RFC-0004 `SecretStore`; not
  a new long-lived subsystem. The compile step reuses `ModelService`.
- **Removability.** Yes: with an empty store the RFC is inert and the runtime core behaves
  exactly as before; the store and the `prefs` parameter can be removed without affecting
  unrelated services. With voice off, the modality context is inert too; removing it
  means dropping one parameter and one template.
