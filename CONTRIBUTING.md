# Contributing to Zygos

Welcome, and thank you for your interest in Zygos. Before you write a single line of code,
please read [CONSTITUTION.md](CONSTITUTION.md) and [VISION.md](VISION.md). Those two
documents define the hard constraints that all contributions must respect. Everything
below is practical process built on top of those principles.

## Ground Rules

**v1 (`src/`) is frozen.** The TypeScript implementation receives bugfixes only. No new
features, no new dependencies, and no structural refactoring. If you find a bug in v1,
fix it in the narrowest way possible — match the surrounding code's existing style exactly.

**Significant architectural changes require an accepted RFC before any implementation
begins.** "Significant" means: a new subsystem, a change to a published service contract,
or any cross-cutting behavioral change. If you are unsure whether your idea qualifies,
open an issue and ask. It is always cheaper to clarify early.

**Test-driven development is the working method.** A failing test must precede every
piece of production code. Reviewers expect to see RED/GREEN evidence: the failing test
run (RED) should appear in the pull request alongside the implementation that makes it
pass (GREEN). Submitting tests only after the implementation is a review-blocking smell.

**Constitution defaults must never be weakened.** The defaults `approval_mode="manual"`
and `auto_apply_low_risk=False` exist to enforce the constitutional requirement that
human approval is required for any behavioral mutation to the runtime. No contribution
may weaken either default. Changing them even in tests requires explicit justification.

Code and documentation conventions are catalogued in the [Style Guide](./STYLE_GUIDE.md).

## Development Setup

### v2 (Python backend)

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

A clean setup should report **28 passed** as of milestone M1. If you see fewer, your
environment is incomplete.

### v1 (TypeScript, bugfixes only)

```bash
npm install
npm run verify
npm test
```

All commands run from the repository root.

## The RFC Process

An RFC is required before implementing:

- a new subsystem or service
- a change to an existing published service contract
- any behavior that cuts across multiple services

RFCs are numbered sequentially and live in [`docs/rfcs/`](docs/rfcs/). File your RFC as
`docs/rfcs/RFC-NNNN-Title-Case.md`, where `NNNN` is the next available number.

The process, available statuses, and canonical section template are documented in [docs/rfcs/README.md](./docs/rfcs/README.md). Every RFC ends with an **Architectural Impact** section answering whether the change increases coupling, creates hidden state, bypasses a service boundary, or violates the Constitution.

Open a pull request with the RFC document only. The RFC must be reviewed and merged
before any implementation code is written. Once an RFC is accepted it is **immutable**
— the record of the original decision must not be altered. If the accepted design turns
out to be wrong, write a new RFC that supersedes it.

## Pull Requests

1. **Branch from `main`.**
2. **Keep both test suites green.** Every PR must pass `npm test` (v1) and
   `backend/.venv/bin/pytest` (v2) before review. Failing tests are not acceptable
   as a work-in-progress signal — use a draft PR for that instead.
3. **Follow the commit style.** Commits use the form `type(scope): subject`, where
   `type` is one of `feat`, `fix`, `docs`, `test`, or `chore`, and `scope` identifies
   the affected module or subsystem. Backend (v2) work uses `(v2)` as the scope;
   documentation-only changes use `docs` with no scope; v1 bugfixes use `fix` with
   no scope or `fix(v1)`. Examples:
   - `feat(v2): add PluginRegistry.list method`
   - `fix(v2): reject duplicate provider routes`
   - `docs: add CONTRIBUTING.md and STYLE_GUIDE.md`
4. **Describe what and why, not just how.** The PR description should explain the
   motivation for the change so that a reviewer who has no context can evaluate
   whether the approach is correct. A PR that only says "updated the loader" is not
   sufficient.
5. **One logical change per PR.** Combining an RFC with its implementation, or
   bundling unrelated fixes, makes review harder and history harder to read.

## Proposing Ideas

If you have an idea but are not yet ready to write an RFC, open an issue describing
the problem you want to solve. Discussion at the issue stage is free — no code
investment required. If the idea involves a new subsystem or a service-contract change,
the issue will eventually need to become an RFC before any implementation can proceed.

Alternatively, open a draft RFC as a pull request. Draft RFCs are welcome early;
they signal intent and invite design feedback before the author has committed to a
final direction.
