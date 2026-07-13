# Zygos RFCs

Every significant architectural change to Zygos requires an accepted RFC before any implementation begins. This directory is the project's decision log — a permanent, auditable record of what was built, why, and what alternatives were considered.

## Process

Anyone may write an RFC. Submit it as a pull request that adds a single file named `RFC-NNNN-Title-Case.md` with status **Draft**. Discussion happens on the pull request; the maintainer advances the RFC to **Review** once it is ready for broader evaluation, then to **Accepted** or **Rejected** based on the outcome.

An RFC is required before implementing:

- a new subsystem or service
- a change to an existing published service contract
- any behavior that cuts across multiple services

After the work ships, the maintainer updates the status to **Implemented**. The RFC document itself remains unchanged; implementation progress is tracked in [ROADMAP.md](../../ROADMAP.md).

## Statuses

**Draft** — the RFC is being written; not yet ready for maintainer review.

**Review** — the RFC is under active discussion; the maintainer has determined it is complete enough to evaluate.

**Accepted** — the RFC is approved and the design is locked. From this point on the document is immutable. Amendments must be made via a new superseding RFC.

**Implemented** — the work described by the RFC has shipped; see [ROADMAP.md](../../ROADMAP.md) for milestone tracking.

**Superseded** — this RFC was replaced by a later RFC (which must be named in the document).

**Rejected** — the proposal was not accepted; kept in this directory for the historical record.

**Reserved** — the RFC number has been allocated and the title is locked; no document exists yet.

Amendments to Accepted or later RFCs may only be made by writing a new RFC that supersedes the original.

## Numbering

RFCs are numbered sequentially using the format `RFC-NNNN`, zero-padded to four digits (e.g., `RFC-0001`, `RFC-0042`). Numbers are never reused, even if an RFC is rejected or superseded.

## Template

Every RFC must contain the following sections in order:

| Section | Contents |
|---|---|
| **Summary** | A one- or two-sentence plain-language description of what is proposed. |
| **Motivation** | Why this change matters; what goal or constraint drives it. |
| **Problem Statement** | What is broken, missing, or insufficient in the current design. |
| **Proposed Design** | The concrete solution with enough detail to implement, including interfaces and data flows. |
| **Alternatives Considered** | What else was evaluated and why each alternative was rejected. |
| **Migration Plan** | How existing consumers move from the old design to the new one. |
| **Risks** | What could go wrong and how those risks are mitigated. |
| **Acceptance Criteria** | The observable conditions that confirm the RFC is fully implemented. |
| **Architectural Impact** | See [Architectural Impact](#architectural-impact) below — required in every RFC. |

## Architectural Impact

> "Architectural debt is treated as seriously as technical debt."

Every RFC must end with an **Architectural Impact** section that answers, at minimum, the following questions:

- Does this increase coupling between services or components?
- Does this create hidden state that is not visible at service boundaries?
- Does this bypass a service boundary established by a prior RFC?
- Does it violate the [Constitution](../../CONSTITUTION.md)?
- Can it be tested independently of the services it touches?
- Does it require a new service, or does it belong in an existing one?
- Can it be removed later without affecting the runtime core?

## Index

| RFC | Title | Status |
|---|---|---|
| [RFC-0001](RFC-0001-Service-Architecture.md) | Service Architecture | Accepted — implementation in progress ([ROADMAP](../../ROADMAP.md)); §8 amended by RFC-0004, §2/§7 amended by RFC-0008 |
| [RFC-0002](RFC-0002-Runtime-Event-Bus-and-ExecutionContext.md) | Runtime Event Bus and ExecutionContext | Implemented (M3 Cycle 1) |
| [RFC-0003](RFC-0003-Capability-Registry-Runtime-Manifest-and-Inspection.md) | Capability Registry, Runtime Manifest, and Inspection | Implemented (M3 Cycle 3) |
| [RFC-0004](RFC-0004-Secret-Storage-and-Key-Entry.md) | Secret Storage and Key Entry | Accepted — amends RFC-0001 §8; not an M3 gate |
| [RFC-0005](RFC-0005-Voice-Interaction-STT-and-TTS.md) | Voice Interaction — Local STT and TTS | Review — §4 WS protocol reconciled to RFC-0007's envelope |
| [RFC-0006](RFC-0006-Embedding-Contract-and-Hybrid-Memory-Retrieval.md) | Embedding Contract and Hybrid Memory Retrieval | Accepted — amends RFC-0003 closed capability set; does not amend RFC-0001; build precedes M8 |
| [RFC-0007](RFC-0007-Session-Protocol-and-Turn-Loop.md) | Session Protocol and Turn Loop (FastAPI/WebSocket Adapter) | Accepted (2026-07-11) — Milestone 8; reconciles RFC-0005 §4 channel naming; completes RFC-0003 `GET /runtime` |
| [RFC-0008](RFC-0008-Tool-Calling-Protocol-and-Tool-Authoring.md) | Tool-Calling Protocol and Tool Authoring | Accepted (2026-07-11) — native function-calling normalized at the provider seam; amends RFC-0001 §2/§7 |
| [RFC-0009](RFC-0009-Model-Routing-and-Multimodal-Capabilities.md) | Best-Model-Per-Task Routing and Multimodal Capabilities | Draft — per-turn authoring-model selection (amends RFC-0001 §2, makes it load-bearing); fills RFC-0003 `VISION`/`IMAGE_GENERATION` contracts; backend-agnostic capability binding + local swap; built in 4 phases |
| [RFC-0010](RFC-0010-User-Personalization-and-Assistant-Identity.md) | User Personalization and Assistant Identity | Draft — preferences store (user name + assistant name + persona); NL onboarding compiled to bounded fields + reviewed snippet; fills the RFC-0007 `build_messages()` system-prompt seam; default-preserving |

> **Note on RFC-0001:** This RFC predates the Summary and Architectural Impact sections. Its Architectural Fitness Test table served that role and remains the authoritative impact record for that decision.
