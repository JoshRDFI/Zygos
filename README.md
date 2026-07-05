# Zygos

Zygos is an open, modular, and inspectable AI runtime. It provides multi-provider reasoning, layered memory, tools, and skills through a composable architecture — and is gaining, in v2, a self-hosted web UI with voice. Whether you need a local-first CLI agent or a production-grade orchestration layer, Zygos is built to be understood, extended, and trusted.

## Why "Zygos"?

**Zygos** (ζυγός) comes from Ancient Greek and means **yoke**, **coupling**, or **joining**.

For this project, the name captures the core design philosophy:

- Binding multiple forces (providers, tools, reasoning) into coordinated motion
- Balance, alignment, and synchronization between components
- A control interface between independent actors (LLMs, tools, memory)

The name is more than a label; it reflects how the system orchestrates independent capabilities into one coherent, reliable agent runtime.

## Project Status

| Runtime | Language | Status |
|---------|----------|--------|
| v1 | TypeScript | Stable and usable today; frozen (bugfixes only) |
| v2 | Python | In development — Milestone 1 complete ([roadmap](./ROADMAP.md)) |

v2 is an architectural migration of v1, governed by [RFC-0001](./docs/rfcs/RFC-0001-Service-Architecture.md).

## Quick Start (v1)

```bash
git clone <your-repo-url>
cd zygos
npm install
cp .env.example .env
npm run verify
npm run dev -- "Hello Zygos"
```

For the full walkthrough, see [docs/v1/QUICKSTART.md](./docs/v1/QUICKSTART.md).

## Working on v2

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for branch conventions, code standards, and the full contributor workflow.

## Documentation

- [Vision](./VISION.md)
- [Architecture](./ARCHITECTURE.md)
- [Roadmap](./ROADMAP.md)
- [Constitution](./CONSTITUTION.md)
- [Compatibility](./COMPATIBILITY.md)
- [ADRs](./docs/adr/)
- [Contributing](./CONTRIBUTING.md)
- [Style Guide](./STYLE_GUIDE.md)
- [RFCs](./docs/rfcs/)
- [v1 Guides](./docs/v1/)

## How Zygos Is Built

Zygos is developed AI-native, and deliberately so. Architecture, design review, and
direction are human: the RFCs, the governance gates, and every decision about what is
correct and what ships originate with the maintainer. The code is primarily authored by
Claude (Anthropic) under that direction, and research and ideation draw on a range of LLM
tools upstream of implementation. Commit trailers reflect this split — the human is the
commit author and the accountable party, and the assistant is credited as co-author.

This is a methodology, not an accident of tooling. Zygos treats human judgment as the
scarce input and AI as leverage on it — the same principle of coordinated, inspectable
orchestration that the runtime itself is built to embody.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
