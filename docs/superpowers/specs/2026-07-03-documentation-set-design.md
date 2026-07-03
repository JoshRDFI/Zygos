# Zygos Documentation Set — Design

**Date:** 2026-07-03
**Status:** Approved by maintainer (this session)

## Goal

Build the canonical document set that ZYGOS_VISION.md enumerates ("Initial
Document Set"), distilling the two working blueprints — `ZYGOS_VISION.md` and
`ZYGOS_V2_IMPLEMENTATION.md` — into polished, single-source-of-truth documents,
then remove the blueprints. Finish documentation before v2 Milestone 2 begins.

## Decisions (locked with maintainer)

1. **Absorb and remove.** The two blueprint files are fully distilled into the
   new set, then deleted. Git history is the archive. Same for
   `docs/ARCHITECTURE_V2.md` (a v1 phase log) — its useful content becomes the
   v1 appendix of ARCHITECTURE.md.
2. **Public open-source audience, written for it now.** Docs address strangers
   finding the repo. A LICENSE file is added.
3. **License: Apache-2.0.** Copyright holder line: "Zygos contributors".
4. **v2-forward, v1 as stable reference.** README leads with vision and v2;
   an honest status section says v1 is the working runtime today (frozen,
   bugfix-only) and v2 is in development per RFC-0001. v1 user guides move to
   `docs/v1/` unmodified.

## Document requirements

### README.md (rewrite)
- What Zygos is (AI runtime, not a chatbot/framework) and why; the ζυγός name
  story (keep from current README).
- Status table: v1 TypeScript — stable, frozen (Stage 0, bugfixes only),
  installable today; v2 Python — active development, Milestone 1 complete
  (link ROADMAP.md).
- v1 quick start (retain current 5-minute block; link docs/v1/QUICKSTART.md).
- v2 one-liner dev setup (backend/, venv, pytest) for contributors.
- Documentation map: VISION, ARCHITECTURE, ROADMAP, CONSTITUTION, CONTRIBUTING,
  STYLE_GUIDE, docs/rfcs/, docs/v1/.
- License notice (Apache-2.0).

### VISION.md (new; absorbs ZYGOS_VISION.md)
- Philosophy and design principles (no hidden state, traceable, replaceable…).
- Project identity; "Zygos is not" list.
- Runtime services model; layered memory model (working/episodic/semantic/
  procedural); skills lifecycle (Reflection → Proposal → Human Review → Test →
  Publish → Monitor → Improve); model routing; reflection engine
  (never self-deploys); introspection console; plugins; workflows;
  self-contained installation goal; RFC process + Architectural Fitness Test;
  success criteria.
- Voice interaction (STT + TTS) and self-hosted web deployment (local machine
  or droplet) added as first-class goals — these postdate the blueprint.
- No implementation details (those live in ARCHITECTURE.md/RFCs).

### ARCHITECTURE.md (new, canonical; distills RFC-0001 + v2 spec)
- Layering diagram and the dependency rule (runtime core never imports
  adapters; mechanically enforced).
- Service table (the nine Protocols incl. Voice) with one-line contracts.
- Wiring: constructor injection, composition root, config-declared plugins.
- Explicit state objects / TraceService as the introspection source.
- Tool contract (4-phase, optional hooks, guaranteed cleanup).
- API surface: REST + one multiplexed WebSocket (JSON + binary audio frames,
  barge-in via control channel).
- Error taxonomy and typed message model.
- Deployment model: self-hosted page, local or droplet.
- Appendix A — v1 reference implementation: subsystem map of src/ (providers,
  RDT, context, tools, learning, interviewer) absorbed from
  docs/ARCHITECTURE_V2.md, framed as the frozen reference for migration.
- Links to docs/rfcs/ as the decision log; RFC-0001 governs; this document
  summarizes and must not contradict accepted RFCs.

### ROADMAP.md (new; reconciles vision phases with RFC-0001 milestones)
- Single phased plan (do not present two competing numbering schemes):
  M1 config foundation (✅ complete, date), M2 providers+router, M3 RDT,
  M4 memory, M5 tools, M6 learning/skills, M7 workflows, M8 FastAPI adapter +
  WebSocket, then React UI, voice interaction (RFC-gated), scheduler/autonomy,
  installer (single-command), community/ecosystem (entry-point plugins).
- Status column per item; explicit note that voice must land before 2.0 is
  "complete" and that v1 remains frozen throughout.

### CONTRIBUTING.md (new)
- Dev setup for both runtimes (npm for v1; backend/.venv + pytest for v2).
- Ground rules: v1 is Stage-0 (bugfix-only); every significant architectural
  change requires an RFC before implementation (template included: Motivation,
  Problem Statement, Proposed Design, Alternatives, Migration Plan, Risks,
  Acceptance Criteria); TDD is the working method; constitution defaults must
  never be weakened.
- PR workflow: branch, tests green (both suites), conventional-commit style
  messages (feat/fix/docs/test with (v2) scope where applicable).
- Where to propose ideas (issues / RFC drafts).

### STYLE_GUIDE.md (new)
- Python: 3.12+, PEP 8 baseline; typing.Protocol for service interfaces;
  frozen dataclasses for assemblies/state snapshots; Pydantic models with
  extra="forbid" for config; ZygosError subclasses with stable `code` strings;
  module docstrings cite the governing RFC section.
- Tests: pytest; TDD (RED evidence expected in reviews); test names describe
  behavior; monkeypatch for env; tmp_path for files; no mocks where a real
  object serves.
- TypeScript (v1): frozen — match surrounding style in bugfixes; no new deps.
- Documentation: one source of truth per topic; relative links; RFCs are
  immutable once accepted (amend via new RFC).

### LICENSE (new)
- Apache License 2.0, verbatim standard text.

### CONSTITUTION.md
- Untouched.

## Moves and deletions

- Move unmodified into `docs/v1/`: QUICKSTART.md, CONFIGURATION.md,
  EXAMPLES.md, docs/CONTEXT_MANAGEMENT_GUIDE.md, docs/INTERVIEWER_WORKFLOW_GUIDE.md,
  docs/LEARNING_SYSTEM_GUIDE.md, docs/PROVIDER_HARDENING.md,
  docs/RDT_REASONING_GUIDE.md, docs/TOOL_DEVELOPMENT_GUIDE.md.
- Add `docs/v1/README.md`: short index; states v1 is frozen (Stage 0) and
  links each guide.
- Delete after absorption: ZYGOS_VISION.md, ZYGOS_V2_IMPLEMENTATION.md,
  docs/ARCHITECTURE_V2.md.
- Remove empty dirs docs/philosophy, docs/architecture, docs/developer-guide
  (recreate when content exists).
- CONFIGURATION.pdf at root: delete (duplicate of CONFIGURATION.md; PDF of a
  moved doc would immediately be stale).

## Verification

- Link check: every relative markdown link in new/changed root docs and
  docs/v1/README.md resolves to an existing file.
- Reference check: `grep -rn "ZYGOS_VISION\|ZYGOS_V2_IMPLEMENTATION\|ARCHITECTURE_V2\|\./QUICKSTART\|\./CONFIGURATION\|\./EXAMPLES"` over tracked
  markdown finds no stale references to deleted/moved paths (excluding
  docs/superpowers/ history and git-ignored files).
- README quick-start commands remain accurate for v1 (`npm install`, `npm run
  verify`, `npm run dev`).

## Out of scope

- No changes to code, tests, or CI.
- No mkdocs/site generator.
- No rewriting of the nine v1 guides (moved verbatim).
- AGENTS.md / CLAUDE.md untouched (tooling instructions, not project docs).
- docs/superpowers/ (plans/specs) untouched.
