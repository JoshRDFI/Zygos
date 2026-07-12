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
- **`[v2 · built]`** — implemented and tested in the Python backend, but not yet
  assembled into a runnable app (the web server and turn loop that tie the services
  together arrive in Milestone 8).
- **`[v2 · planned]`** — designed, often with an accepted RFC, but not yet built.

So a `[v2 · built]` subsystem is real code with tests — you just can't talk to it
through a UI yet. That assembly is what v2 is working toward now.

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
frontend (React + Tailwind + Vite)          [v2 · planned]
        │  HTTP / WebSocket
adapters — web server / CLI                  web [v2 · planned] · CLI [v2 · built]
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

Letting a model *call tools* uses native function-calling normalized across providers;
the design is locked in [RFC-0008](./docs/rfcs/RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md).
`[v2 · planned]`

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

### Tools — a safe execution contract
Tools implement a four-phase contract — **prepare → execute → verify → cleanup** —
where `cleanup` always runs (even on failure) and a malformed result is never silently
accepted. Execution carries permission checks, timeouts, retries, and one-level
fallback. A starter suite (file read/write, HTTP fetch, shell command) ships with
permission defaults set by risk. `[v1]` `[v2 · built]`

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
`zygos inspect` / `zygos doctor`. `[v2 · built]` The guiding principle: *state the
console cannot see is an architecture bug*. The graphical **Introspection Console** that
renders all of this for auditing — verifying what context was used and what left your
machine — arrives with the web UI. `[v2 · planned]`

### Voice — on your machine
The service and transport layers are shaped for voice from the start (a `VoiceService`
interface and audio channels on the WebSocket protocol). Local-first engines
(Whisper-family transcription, Piper/Kokoro-class synthesis) with optional cloud
fallback are scoped in the voice RFC. `[v2 · planned]`

## How it runs

Every run moves through a fixed lifecycle — bootstrap, load configuration, resolve
plugins, initialize services, register capabilities, load skills, load memory, start
scheduler, accept requests, execute, graceful shutdown. Stages never reorder; each
milestone fills one in. Today the runtime reaches *Register Capabilities* and the
services are wired; *Accept Requests* (the web server + WebSocket turn loop) is
Milestone 8, the point at which v2 becomes a usable app. The wire protocol for that turn
loop is locked in
[RFC-0007](./docs/rfcs/RFC-0007-Session-Protocol-and-Turn-Loop.md). `[v2 · built]`
lifecycle-so-far; `[v2 · planned]` the request-serving stages.

Zygos is deployed as a **self-hosted web application** — targets are your own machine or
a droplet-class VM, no Electron wrapper and no managed-platform assumption. A single
install command is planned to verify Python, create an isolated environment, install
dependencies, build the frontend, initialize the database, and launch the server.
`[v2 · planned]`

It is designed to run **fully offline** with local models once they are downloaded; that
is a design goal of the local-first path, not yet a verified guarantee across every
configuration.

## Going deeper

- [ARCHITECTURE.md](./ARCHITECTURE.md) — the authoritative v2 design: service
  Protocols, wiring, lifecycle, event model, tool contract, and the v1 reference
  implementation.
- [`docs/rfcs/`](./docs/rfcs/) — the decision log; every architectural choice above is
  governed by an RFC.
- [ROADMAP.md](./ROADMAP.md) — milestone-by-milestone status.
- [VISION.md](./VISION.md) — why Zygos exists and where it is headed.
