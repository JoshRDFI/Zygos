# RFC-0011: React UI — Frontend Architecture and Application Skeleton

- **Status:** Review (2026-07-16)
- **Author:** Zygos maintainers
- **Created:** 2026-07-16
- **Governs:** the `frontend/` web application — its technology stack, project
  layout, application shell and information architecture, the theming system,
  the typed client that speaks the runtime's HTTP + WebSocket protocol, and the
  per-surface split between live and placeholder wiring for the first
  (skeleton) increment
- **Depends on:**
  [RFC-0001](RFC-0001-Service-Architecture.md) (the constitutional rule that the
  runtime never depends on the UI; the multiplexed WebSocket and channel-tagged
  binary frames §7),
  [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md)
  (the runtime manifest and health surfaced by the Inspect / Doctor / Models /
  Tools surfaces),
  [RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md) (browser-side audio
  capture/playback, VAD, and the duck-then-stop barge-in this UI drives),
  [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) (the session lifecycle
  and WebSocket frame envelope the client speaks), and
  [RFC-0008](RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md) (the
  tools/permission channel the chat surface renders).
- **Relates to:** [RFC-0009](RFC-0009-Model-Routing-and-Multimodal-Capabilities.md)
  (the Models surface will grow selection + hardware gating when that lands) and
  [RFC-0010](RFC-0010-User-Personalization-and-Assistant-Identity.md) (theme and
  preference persistence migrate from `localStorage` to the backend store).
- **Implementation status:** tracked in [ROADMAP.md](../../ROADMAP.md). This RFC
  governs the **first, broad skeleton increment**; the deeper per-surface
  backends it names as out of scope (Files library, Memory browser, model
  selection/gating) are separate future increments, each with its own spec.

## Summary

Define the architecture of Zygos's self-hosted web frontend: a **React +
TypeScript + Tailwind + Vite** application, served locally or on a droplet (not
Electron), that speaks the runtime's existing HTTP + WebSocket protocol. The
first increment is a **broad, seeable skeleton** — every primary surface (Chat,
Files, Tools, Memory, Inspect, Models, Doctor, Settings) is laid out and
navigable, surfaces backed by an existing endpoint are wired **live**, and the
rest are visually complete **placeholders** clearly marked as such. The visual
identity is built as **swappable design tokens** with three named themes —
`instrument` (default), `study`, `quiet-os` — each in light and dark mode,
switchable from Settings; color only ever comes from the active token set, which
structurally forbids a generic "SaaS" look. This increment is the first real
consumer of the voice audio channels, so it also **proves the live barge-in
seam** end to end for the first time.

## Motivation

Zygos 2.0 requires a fully integrated, openable web page hosted on the user's own
machine or a droplet — a stated completion requirement, and the only surface
through which a person actually uses the assistant. The backend turn loop, tools
and permission channel, runtime manifest, health probes, and the full voice
audio path (STT ingest, TTS output, single-session gate, duck-then-stop barge-in,
and the barge-in drain-to-terminal correctness fix) are all built and seam-ready;
nothing has yet been a real **consumer** of them. The maintainer wants to *see*
the whole thing to make design choices, so the first increment deliberately
favors **breadth** — a real layout across every surface — over depth in any one.
Building the identity as themeable tokens lets those aesthetic choices be made
and changed against the running skeleton rather than guessed up front.

## Problem Statement

There is no `frontend/` today; the entire product is reachable only through the
CLI and raw HTTP/WebSocket calls. The runtime exposes a lean, stable surface —
`POST/GET/DELETE /sessions`, `GET /runtime` (capability + runtime manifest),
`GET /runtime/health` (with an optional `probe`), and `WS /ws` (the turn loop:
streaming chat text, the tools/permission channel, `audio.in`/`audio.out` binary
frames, TTS control, and VAD/duck frames) — but no graphical client consumes it.
Several product surfaces the UI must eventually expose (a Files library, a Memory
browser, model **selection** with hardware-aware gating) have **no backend yet**.
The frontend must therefore be honest about what is real: wire live everything
the current backend supports, and present the rest as clearly-labeled
placeholders that establish layout and navigation without pretending to function.

## Proposed Design

### Technology stack and project layout

A new top-level **`frontend/`** directory with its own `package.json`, managed
with **npm** (simplest "download and run" story). Stack: **React 18 +
TypeScript**, **Vite** dev server and bundler, **Tailwind CSS** for styling,
**React Router** for the rail surfaces, and small, concern-scoped **Zustand**
stores (session, connection, voice, theme) for state. The Vite dev server
**proxies** `/sessions`, `/runtime`, and `/ws` to the backend so the app runs at
`localhost:<port>` against a locally running `zygos serve`. The runtime never
imports or depends on `frontend/` — the dependency points one way only, as
RFC-0001 requires.

### Application shell and information architecture

- **Header** (thin, persistent): the **Zygos** wordmark far-left; a **Settings**
  gear far-right that opens the Settings surface.
- **Left rail** (persistent, icon + label): **Chat · Files · Tools · Memory ·
  Inspect · Models · Doctor**. Chat is the home surface.
- **Main content**: the active surface. Chat dominates and is the anchor; the app
  reads as a personal assistant, not a dashboard.
- **Right context panel** (collapsible, **default-closed**): surfaces the current
  turn's inner state — reasoning / confidence, tool calls and permission prompts,
  and live voice / VAD state.

### Theming

The visual identity is a set of **design tokens** expressed as CSS custom
properties, not hard-coded colors. A **theme** is a named set of token values;
**mode** (light / dark / system) is orthogonal, and each theme supplies both its
light and dark values. Three themes ship:

- **`instrument`** (default) — muted, dark-first, precise; low-chroma surface,
  monospace for data/labels, humanist sans for prose, one restrained accent.
- **`study`** — warm, editorial, light-first; paper neutrals, humanist serif for
  reading, generous margins.
- **`quiet-os`** — near-neutral, system-native; restrained grayscale with a
  single accent, high whitespace.

Settings exposes a theme picker and a mode toggle, **persisted to
`localStorage`** for now (migrating to the RFC-0010 backend preferences store
later). Tailwind is configured to consume the tokens, so every component is
theme-agnostic by construction and color can only come from the active token set.
The root carries `data-theme` and `data-mode` attributes that select the token set.

### The runtime client

A single typed client module wraps the backend protocol: a thin `fetch` layer for
the REST endpoints (`/sessions`, `/runtime`, `/runtime/health`) and a **native
`WebSocket`** wrapper for `/ws` that speaks the RFC-0007 frame envelope —
dispatching inbound frames by channel/type (chat text, tools/permission, TTS
control, VAD/duck, and the channel-tagged `audio.in`/`audio.out` binary frames)
and exposing a typed send API. Voice capture and playback (mic → `audio.in`,
`audio.out` → speaker) and browser-side VAD driving barge-in live behind this
client per RFC-0005.

### Surfaces — live vs. placeholder (first increment)

| Surface | Depth | Backing |
|---|---|---|
| **Chat** | Live | `WS /ws` turn loop, streaming assistant text |
| **Voice** | Live | mic → `audio.in`; `audio.out` playback; browser VAD → duck-then-stop barge-in |
| **Inspect** | Live (read-only) | `GET /runtime` manifest |
| **Doctor** | Live (read-only) | `GET /runtime/health` (+ `probe`) |
| **Models** | Semi-live | list from the manifest; **selection / hardware gating is placeholder** (future, Archon `20203394` / RFC-0009) |
| **Tools** | Semi-live | list from the manifest; live call activity shown in the right context panel during chat |
| **Memory** | Placeholder | no browse endpoint yet — mock layout |
| **Files** | Placeholder | no library endpoint yet — mock layout + chat drag-drop affordance |
| **Settings** | Live (client) | theme + mode now; other preferences placeholder |

### Voice affordances (from RFC-0005)

Beside the chat text input: a **mic toggle**; an **always-on / continuous**
switch; a **master voice on/off**; and a **speaker (audio-out) toggle**. Browser
VAD drives the duck-then-stop barge-in against `control:audio.vad`. This is the
increment that first exercises the live barge-in path against the real STT/TTS
engines.

### Files handling

Two distinct affordances, because they are two different jobs: **drag-drop into
chat** for ad-hoc, per-turn attachments ("use this now"), and a dedicated
**Files** surface for the persistent document library ("this is part of what
Zygos knows about me" — the corpus that will feed memory, embedding retrieval,
and the writing-voice feature). In this increment the Files surface is a
placeholder layout and the chat drop is a UI affordance; both wait on a backend
library/upload endpoint, delivered in a later increment.

## Alternatives Considered

- **Thin vertical slice (chat + voice only).** Smallest surface, proves the
  end-to-end path fastest. Rejected for the first increment because the maintainer
  wants to *see* the whole product to make layout and aesthetic choices; breadth
  is the explicit goal here. The slice's depth is still achieved for Chat and
  Voice within the broad skeleton.
- **Chat-centric with slide-in drawers (shell C).** Maximally conversation-focused
  but hides every non-chat surface until invoked — which works against a skeleton
  meant to be seen. Rejected.
- **Full main-content swap without a persistent context panel (shell B).** Simple,
  but the conversation stops being the anchor and the app reads as an admin
  console. Rejected in favor of the chat-centric shell (A) with a collapsible
  context panel.
- **A single hard-coded aesthetic.** Simpler to build, but bets the identity on one
  look and cannot honor "let me see it and choose." Rejected in favor of swappable
  token themes, which also structurally enforce the no-SaaS-color constraint.
- **Electron / desktop shell.** Explicitly a v2 non-goal; the deployment target is
  a self-hosted web page (local or droplet). Rejected.
- **Heavier state/data libraries (Redux, React Query).** Unnecessary for a
  single-user app against a lean, mostly-streaming backend. Rejected in favor of
  small Zustand stores and the native WebSocket.

## Migration Plan

There is no existing frontend to migrate from; this is additive. The backend
protocol is unchanged — the UI is a new consumer of already-shipped endpoints,
so no backend contract changes are required for this increment. Theme and
preference persistence begins in `localStorage` and migrates to the backend
preferences store when RFC-0010 is implemented. The placeholder surfaces (Files,
Memory, Models selection) become live in later increments as their backends land;
each swaps its placeholder for real wiring without changing the shell.

## Risks

- **Placeholders read as finished.** Mitigation: placeholder surfaces are visibly
  and consistently marked (not-yet-wired affordances are labeled), so no surface
  silently pretends to function.
- **Live barge-in has never run end to end.** This increment is its first real
  test; the browser VAD → duck-then-stop path may surface timing issues the
  backend seam work could not prove without a real audio consumer. Mitigation:
  the audio path is built behind the typed client so it can be exercised and
  hardened incrementally, and the backend's drain-to-terminal invariant already
  bounds cross-turn corruption.
- **Scope creep into the deferred backends.** Mitigation: the live/placeholder
  table is the contract for this increment; Files/Memory/model-gating backends are
  explicitly out of scope and tracked separately.
- **Theme abstraction overhead.** Building three themes up front costs more than
  one. Mitigation: the token layer is small and is what makes "see it and choose"
  possible; the incremental cost per theme is low once the token contract exists.

## Acceptance Criteria

1. `frontend/` exists with React + TypeScript + Tailwind + Vite, runs via
   `npm run dev`, and is viewable at `localhost:<port>` against a running backend.
2. The shell renders: header (Zygos left, Settings gear right), left rail
   (Chat · Files · Tools · Memory · Inspect · Models · Doctor), main content, and
   a default-closed collapsible right context panel.
3. **Chat** streams a live assistant turn over `WS /ws`.
4. **Voice** captures the mic to `audio.in`, plays `audio.out`, and performs
   browser-VAD duck-then-stop barge-in against the real engines.
5. **Inspect** and **Doctor** render live data from `GET /runtime` and
   `GET /runtime/health`; **Models** and **Tools** render their lists from the
   manifest.
6. **Memory** and **Files** present clearly-marked placeholder layouts; the chat
   surface offers a drag-drop affordance.
7. **Settings** switches between `instrument` / `study` / `quiet-os` themes and
   light / dark / system mode, persisted across reloads; `instrument` is the
   default.
8. All color is sourced from theme tokens — no component hard-codes color values.

## Architectural Impact

- **Coupling.** The frontend depends on the runtime's published HTTP + WebSocket
  contract; the runtime gains **no** dependency on the frontend. The one-way
  dependency required by RFC-0001 ("the runtime never depends on the UI") is
  preserved.
- **Hidden state.** None at a service boundary. UI-local state (open panel, active
  surface, theme selection) lives entirely in the client; theme/preference
  persistence is explicit (`localStorage`, later the RFC-0010 store).
- **Service boundaries.** The UI crosses none; it consumes existing endpoints only
  and introduces no new backend surface for this increment.
- **Constitution.** Consistent with local-first and single-user framing; the app
  is self-hosted and speaks only to the local (or droplet) runtime.
- **Independent testability.** The frontend is testable independently (component
  and client-module tests, and against a running backend); the runtime's own tests
  are unaffected.
- **New service?** No new backend service. A new **frontend** deliverable, which
  belongs in its own top-level directory rather than inside any backend service.
- **Removability.** The entire `frontend/` can be removed without affecting the
  runtime core; the CLI and API remain fully functional without it.
