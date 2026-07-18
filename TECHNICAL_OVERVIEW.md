# Zygos — Technical Overview

This is the middle layer of Zygos's documentation: enough to understand **how the
system actually works** without reading the full design spec. If you want the
one-paragraph pitch, start with the [README](./README.md). If you want the
authoritative design — service Protocols, the runtime lifecycle, the event model —
read [ARCHITECTURE.md](./ARCHITECTURE.md); every decision behind it is recorded as an
RFC in [`docs/rfcs/`](./docs/rfcs/).

Zygos exists in two runtimes. **v1** is a TypeScript CLI — stable, usable today,
frozen except for bug fixes. **v2** is a Python migration of the same ideas into a
service-oriented, self-hosted runtime with a web UI and voice. This document describes
v2's design and marks, honestly, what already runs versus what is still being built.

## Status legend

Every capability below carries one of these tags:

- **`[v1]`** — usable today in the TypeScript CLI.
- **`[v2 · built]`** — implemented and tested in the Python backend. The web server and
  WebSocket turn loop that tie the services together (Milestone 8) now run, so a built
  subsystem is reachable over the socket — the tag no longer implies "not yet runnable."
- **`[v2 · planned]`** — designed, often with an accepted RFC, but not yet built.

So a `[v2 · built]` subsystem is real code with tests, now driven by a live turn loop over
WebSocket (start it with `zygos serve`). The **React web UI and voice I/O are now built**
too — early, with a few surfaces (files, memory, model picker) still placeholders. What
remains before v2 is a finished product is the fuller UI, learning and workflows (M6/M7),
the scheduler, and a single-command installer.

## What Zygos is, technically

Zygos is a **composable AI runtime**: a set of independent services — model routing,
reasoning, memory, tools, skills, tracing — wired together at a single composition
root and driven through one adapter (a CLI today, a web/WebSocket server in v2). It is
**self-hosted**: it runs on your own machine or your own cloud VM, with no managed
platform in the loop.

Two design commitments run through everything:

- **Private or public, your choice — and visible.** Zygos routes to local models
  (Ollama, vLLM) or public providers (OpenAI, Anthropic) based on your configuration.
  Nothing is welded to one vendor, and which model handled a request is inspectable,
  not hidden. `[v1]` `[v2 · built]`
- **Replaceable everything.** Every component — model, memory backend, tool, plugin —
  is defined by an interface and bound at startup, so you can swap one without
  rebuilding the rest. `[v2 · built]`

## The shape

v2 is layered, and the dependency rule points **one way only**:

```
frontend (React + Tailwind + Vite)          [v2 · built] (early — some surfaces are placeholders)
        │  HTTP / WebSocket
adapters — web server / CLI                  web [v2 · built] · CLI [v2 · built]
        │  imports (downward only)
runtime — composition root, session loop, state objects
services — interfaces + default implementations
plugins — config-declared implementations (providers, tools, voice…)
```

The runtime core never imports an adapter or a web framework; a test enforces the rule
so a violation fails the build rather than passing review. **Plugins are
config-declared**: the config file names the exact module that runs for each provider,
tool, or voice engine. Nothing auto-activates by scanning your filesystem or installed
packages — reading the config tells you precisely what code will run. `[v2 · built]`

## The subsystems

### Model routing — private or public providers
A model-routing service picks a backend by *capability* and configuration rather than
by a hard-coded vendor SDK, with per-route credential checks, circuit breakers, and
failover between routes. Local backends (Ollama, vLLM) and public ones (OpenAI,
Anthropic) sit behind the same interface, so switching — or keeping some traffic local
and some public — is a config change. `[v1]` `[v2 · built]`

Letting a model *call tools* uses native function-calling normalized across providers
([RFC-0008](./docs/rfcs/RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md)); tool calls
run live inside the turn loop, and every side-effecting call is permission-gated with an
interactive prompt sent over the WebSocket. `[v2 · built]`

### Reasoning — adaptive, above the model
An orchestration layer runs a **Prelude → Recurrent → Coda** reasoning pipeline with
confidence gating and adaptive compute — spending more iterations on harder problems
and stopping early when confident. It works entirely *above* the model API (it needs no
access to model internals), so it applies to any provider. `[v1]` `[v2 · built]`

### Layered memory — local by default
Memory is separated into layers — working (current task), episodic (past sessions),
semantic (facts and knowledge), and procedural (reusable workflows) — so different
kinds of information stay distinct and inspectable rather than blended into one opaque
store. It persists to **local SQLite** (WAL mode, full-text search), on your machine.
Retrieval is pluggable: lexical full-text today, with vector and hybrid semantic
retrieval added by
[RFC-0006](./docs/rfcs/RFC-0006-Embedding-Contract-and-Hybrid-Memory-Retrieval.md) —
and embeddings **default to running locally**, decoupled from whichever model handles
chat, so semantic memory costs no tokens and leaves no data unless you opt into a cloud
embedder. `[v1]` `[v2 · built]`

### Tools — a safe execution contract, called live
Tools implement a four-phase contract — **prepare → execute → verify → cleanup** —
where `cleanup` always runs (even on failure) and a malformed result is never silently
accepted. Execution carries permission checks, timeouts, retries, and one-level fallback.
A starter suite (file read/write, HTTP fetch, shell command) ships **enabled by default**
with permission defaults set by risk: reading is frictionless, while writing files and
running commands ask you first — in real time, over the socket — and you can loosen or
tighten any tool in config. The model invokes these tools inside the live turn loop. A tool
that reaches the network (fetching a page you asked for) does so by your request and in
plain view — privacy here means your data stays local, not that the assistant can't act.
`[v1]` `[v2 · built]`

### Skills and learning — you approve the changes
Zygos can observe its own work, generate proposals, test candidates, and keep a
versioned, audited history — but self-improvement is **never autonomous**. The shipping
defaults are manual approval and no auto-apply; a change to behavior requires human
review and testing. `[v1]` The v2 `SkillService` that carries this forward is
`[v2 · planned]` (Milestone 6).

### Tracing and inspection — auditable, not opaque
Significant runtime actions emit events onto an in-process **event bus**, and runtime
state — which route was chosen, what was retrieved, the reasoning trajectory — lives in
named, snapshotable objects rather than hidden fields. A **capability registry** and a
**runtime manifest** answer "what can this runtime do, and is it healthy?", surfaced by
`zygos inspect` / `zygos doctor`. A per-session **`trace` channel** now streams these
events live over the WebSocket as a turn runs. `[v2 · built]` The guiding principle: *state
the console cannot see is an architecture bug*. The web UI already renders the read-only
slice of this — **Inspect** (runtime manifest), **Doctor** (live health), **Models**, and
**Tools** panels driven off `GET /runtime` and `/runtime/health`. `[v2 · built]` The fuller
graphical **Introspection Console** — per-turn reasoning trajectory, memory retrieved, and
what left your machine — is expanding from that base. `[v2 · planned]`

### Voice — on your machine
Voice runs end to end. The service and transport layers were shaped for it from the start
(a `VoiceService` interface and binary audio channels on the WebSocket protocol), and the
engines now sit behind that seam: **local Whisper-family transcription (faster-whisper) and
Kokoro synthesis**, selected by config like any other plugin — **opt-in and defaulting to a
silent `fake` engine**, so voice adds no dependencies or model downloads unless you turn it
on. In the web UI you speak to Zygos hands-free: a browser voice-activity detector (Silero,
served locally — no CDN) brackets your utterances for transcription, and **barge-in** lets
you talk over a reply — the assistant ducks, then stops, when your speech is confirmed
([RFC-0005](./docs/rfcs/RFC-0005-Voice-Interaction-STT-and-TTS.md), delivered through the
RFC-0011 web UI). The engines and the pure audio logic are unit-tested; the real-engine
browser round-trip is validated by a documented manual smoke test. `[v2 · built]`

## How it runs

Every run moves through a fixed lifecycle — bootstrap, load configuration, resolve
plugins, initialize services, register capabilities, load skills, load memory, start
scheduler, accept requests, execute, graceful shutdown. Stages never reorder; each
milestone fills one in. The runtime now reaches *Accept Requests* and *Execute*: Milestone
8 built the FastAPI/WebSocket adapter, per-session turn loop, live tool-calling, and
graceful shutdown, so v2 is a usable — if still headless — app: `zygos serve` and hold a
chat-and-tools conversation over the socket. The wire protocol is locked in
[RFC-0007](./docs/rfcs/RFC-0007-Session-Protocol-and-Turn-Loop.md) (multiplexed
`chat`/`tools`/`trace`/`control` channels, plus reserved binary audio channels) and
tool-calling in
[RFC-0008](./docs/rfcs/RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md). `[v2 · built]`
the turn loop, tools, the React web UI, and voice; `[v2 · planned]` the scheduler, learning
(M6), and workflows (M7).

Zygos is deployed as a **self-hosted web application** — targets are your own machine or
a droplet-class VM, no Electron wrapper and no managed-platform assumption. A single
install command is planned to verify Python, create an isolated environment, install
dependencies, build the frontend, initialize the database, and launch the server.
`[v2 · planned]`

Its **core chat and memory run fully offline** with a local model once it's downloaded —
a design goal of the local-first path, not yet a verified guarantee across every
configuration. Tools you invoke (a web fetch, a search) reach the network by design and in
plain view; "offline" here means Zygos needs no external service to think and remember, not
that it refuses to act on your behalf.

## Going deeper

- [ARCHITECTURE.md](./ARCHITECTURE.md) — the authoritative v2 design: service
  Protocols, wiring, lifecycle, event model, tool contract, and the v1 reference
  implementation.
- [`docs/rfcs/`](./docs/rfcs/) — the decision log; every architectural choice above is
  governed by an RFC.
- [ROADMAP.md](./ROADMAP.md) — milestone-by-milestone status.
- [VISION.md](./VISION.md) — why Zygos exists and where it is headed.
