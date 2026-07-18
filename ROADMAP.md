# Zygos Roadmap

Zygos v1 (the TypeScript CLI runtime) is frozen at Stage 0: bugfixes only, no new
features. It serves as the reference implementation — the proven concepts to
migrate, not the architecture to extend.

Zygos v2 is built milestone by milestone, each governed by [RFC-0001 and the RFCs
that follow](docs/rfcs/RFC-0001-Service-Architecture.md). No milestone is
considered complete until its test suite is green. Every significant architectural
decision requires an accepted RFC before implementation begins.

## Status

| Milestone | Deliverable | Status |
|---|---|---|
| M1 Config foundation | Schema, loader, plugins, composition root, guard, CI | ✅ Complete (2026-07-03) |
| M2 Providers + ModelService | Ollama/OpenAI/Anthropic/vLLM plugins, router, RouterState | ✅ Complete (2026-07-04) |
| M3 RDT reasoning engine | Prelude/recurrent/coda pipeline, real adaptive compute (iteration/temperature/token/model by complexity+confidence), snapshotable ReasoningState | ✅ Complete (2026-07-06) — ran as three cycles: RFC-0002 foundation, RDT engine, RFC-0003 registry |
| M4 Layered memory (SQLite WAL + FTS5) | Working, episodic, and semantic memory; deferred consolidation; multi-factor retrieval (procedural memory = named seam → M6/SkillService) | ✅ Complete (2026-07-10) |
| M5 Tools (4-phase contract) | Executor, permissions, streaming, fallback; cleanup guaranteed | ✅ Complete (2026-07-11) — ran as three cycles: contract + core executor, permissions/streaming/retry/timeout/fallback, starter tool suite |
| M6 Learning → SkillService (manual approval only) | Proposals, A/B testing (sandboxed), human-approval gate | Planned (lands after M8) |
| M7 Workflows (interviewer first) | Workflow plugins starting with the interviewer pattern | Planned (lands after M8) |
| M8 FastAPI adapter + WebSocket protocol | REST + multiplexed WS; live per-session chat-and-tools turn loop; typed frames for chat, tools, trace (audio reserved for voice) | ✅ Complete (2026-07-13) — four cycles: server/lifecycle/inspection, WS/session/chat turn loop, tool-calling library (RFC-0008), live tool-calling |
| RFC-0002: Runtime Event Bus and ExecutionContext | Design RFC — implemented in M3 (Cycle 1) | ✅ Implemented (2026-07-05) |
| RFC-0003: Capability Registry, Runtime Manifest, and Inspection | Design RFC — implemented in M3 (Cycle 3); render surfaces GET /runtime → M8, zygos trace → TraceService | ✅ Implemented (2026-07-09) |
| RFC-0004: Secret Storage and Key Entry | Design RFC — amends RFC-0001 §8; not an M3 gate | ✅ Accepted (2026-07-04) |
| RFC-0005: Voice Interaction — Local STT and TTS | Design RFC — governs voice engines behind the RFC-0003 capabilities; audio WS channels built in M8, engines after; a 2.0-complete gate | ✅ Accepted (2026-07-13); engines implemented 2026-07-16 (faster-whisper STT, Kokoro TTS, opt-in) and live in the web UI (RFC-0011 1b/1c) |
| RFC-0006: Embedding Contract and Hybrid Memory Retrieval | Design RFC — adds the `Embedder` contract + `EMBEDDING` capability (amends RFC-0003 closed set); does not amend RFC-0001; builds as its own cycle before M8 | ✅ Implemented (2026-07-11, own cycles) |
| RFC-0007: Session Protocol and Turn Loop | Design RFC — the M8 wire protocol: multiplexed WS frames (chat/tools/trace/control + reserved audio) + REST sessions; reconciles RFC-0005 §4 | ✅ Implemented (2026-07-13, M8) |
| RFC-0008: Tool-Calling Protocol and Tool Authoring | Design RFC — native function-calling normalized at the provider seam + the agentic loop; amends RFC-0001 §2/§7 | ✅ Implemented (2026-07-13, M8) |
| RFC-0009: Model Routing and Multimodal Capabilities | Design RFC — per-turn best-model routing + VISION/IMAGE_GENERATION contracts; amends RFC-0001 §2 | ✏️ Draft (2026-07-13) |
| RFC-0010: User Personalization and Assistant Identity | Design RFC — bounded preferences store + NL onboarding; fills the RFC-0007 `build_messages` system-prompt seam | ✏️ Draft (2026-07-13) |
| RFC-0011: React UI — Frontend Architecture and Application Skeleton | Design RFC — self-hosted React+TS+Tailwind+Vite `frontend/`; chat-centric shell + token themes (`instrument`/`study`/`quiet-os`); broad-skeleton first increment; first live consumer of the RFC-0005 audio channels | ✅ Accepted (2026-07-16); building — increment 1a (skeleton + live chat + read-only surfaces) and 1b/1c (live voice: audio round-trip, then hands-free + barge-in) implemented 2026-07-17 |
| React UI | React + Tailwind + Vite frontend; WebSocket streaming | 🚧 In progress (2026-07-17) — RFC-0011 increment 1a: `frontend/` shell + token themes, live chat over the WS turn loop, read-only Inspect/Doctor/Models/Tools surfaces, and live voice controls (increments 1b/1c). Remaining: Files/Memory surfaces, model selection |
| Voice interaction (STT + TTS) | Local-first transcription and synthesis over the WS audio channel; **required before 2.0 is called complete** | ✅ Built (2026-07-17) — real STT (faster-whisper) + TTS (Kokoro) behind the `VoiceService` seam (opt-in `.[voice]`, default `fake`); single-session gate; duck-then-stop barge-in (drain-to-terminal); live in the web UI — mic capture → STT, TTS playback, browser Silero VAD hands-free + barge-in (RFC-0011 1b/1c). Real-engine browser round-trip covered by automated tests + a documented manual smoke test |
| Scheduler & autonomy | SchedulerService with human-in-the-loop guards | Planned |
| Single-command installer | Bootstrap Python env, frontend build, database init, health check | Planned |
| Community ecosystem | Entry-point plugins, skill sharing, public SDK | Planned |

## Principles

- **RFC gate.** No milestone whose scope requires a new RFC may begin
  implementation until that RFC is accepted. Where RFC-0001 already governs a
  milestone, that acceptance carries through; subsequent milestones (React UI,
  Voice, and the community ecosystem) each need their own RFC.
- **v1 stays frozen.** The TypeScript runtime remains Stage 0 (bugfixes only)
  throughout the v2 build. It is the reference, not the runway.
- **Constitution defaults never weaken.** Learning and self-modification ship
  with `approval_mode: manual` and `auto_apply_low_risk: false` as the only
  defaults; no milestone may loosen them. See [ARCHITECTURE.md](ARCHITECTURE.md)
  for the full constitutional constraints on the runtime.

## v1

The v1 architecture is documented in [ARCHITECTURE.md](ARCHITECTURE.md)
(Appendix A). The v1 guides live in [docs/v1/](./docs/v1/), and the TypeScript
source under `src/` remains the authoritative implementation reference. The
[docs/rfcs/](docs/rfcs/) directory is the decision log that governs everything
built from here.
