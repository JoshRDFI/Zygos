# Zygos Roadmap

Zygos v1 (the TypeScript CLI runtime) is frozen at Stage 0: bugfix-only, no new
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
| M2 Providers + ModelService | Ollama/OpenAI/Anthropic/vLLM plugins, router, RouterState | Next |
| M3 RDT reasoning engine | Prelude/recurrent/coda pipeline, attention routing, ReasoningState | Planned |
| M4 Layered memory (SQLite WAL + FTS5) | Working, episodic, semantic, and procedural memory; compaction | Planned |
| M5 Tools (4-phase contract) | Executor, permissions, streaming, fallback; cleanup guaranteed | Planned |
| M6 Learning → SkillService (manual approval only) | Proposals, A/B testing (sandboxed), human-approval gate | Planned |
| M7 Workflows (interviewer first) | Workflow plugins starting with the interviewer pattern | Planned |
| M8 FastAPI adapter + WebSocket protocol | REST + multiplexed WS; typed frames for chat, tools, trace, audio | Planned |
| React UI | React + Tailwind + Vite frontend; WebSocket streaming | Planned (own RFC) |
| Voice interaction (STT + TTS) | Local-first transcription and synthesis over the WS audio channel; **required before 2.0 is called complete** | Planned (own RFC) |
| Scheduler & autonomy | SchedulerService with human-in-the-loop guards | Planned |
| Single-command installer | Bootstrap Python env, frontend build, database init, health check | Planned |
| Community ecosystem | Entry-point plugins, skill sharing, public SDK | Planned |

## Principles

- **RFC gate.** No milestone whose scope requires a new RFC may begin
  implementation until that RFC is accepted. Where RFC-0001 already governs a
  milestone, that acceptance carries through; subsequent milestones (React UI,
  Voice, and the community ecosystem) each need their own RFC.
- **v1 stays frozen.** The TypeScript runtime remains Stage 0 (bugfix-only)
  throughout the v2 build. It is the reference, not the runway.
- **Constitution defaults never weaken.** Learning and self-modification ship
  with `approval_mode: manual` and `auto_apply_low_risk: false` as the only
  defaults; no milestone may loosen them. See [ARCHITECTURE.md](ARCHITECTURE.md)
  for the full constitutional constraints on the runtime.

## v1

The v1 architecture is documented in [ARCHITECTURE.md](ARCHITECTURE.md)
(Appendix A) and will be preserved in `docs/v1/` as the v1 documentation is migrated. Until then, the TypeScript source under `src/` and
the current [ARCHITECTURE.md](ARCHITECTURE.md) serve as the v1 record. The
[docs/rfcs/](docs/rfcs/) directory is the decision log that governs everything
built from here.
