# Zygos Architecture Decision Records

Architecture Decision Records (ADRs) document decisions that have already been made — the choice taken, the context that made it necessary, and the consequences that follow from it. They are not proposals. For proposed changes that require discussion and approval before implementation begins, see [../rfcs/README.md](../rfcs/README.md).

## Format

Each ADR contains the following sections in order:

| Section | Contents |
|---|---|
| **Status** | `Accepted`, `Superseded by ADR-NNNN`, or `Deprecated` |
| **Date** | The date the decision was made (`YYYY-MM-DD`) |
| **Context** | What circumstances, constraints, and alternatives existed when the decision was made |
| **Decision** | A one-paragraph statement of exactly what was decided |
| **Consequences** | What the decision enables, what it costs, and any constraints it imposes going forward |

## Numbering

ADRs are numbered sequentially using the format `ADR-NNNN`, zero-padded to four digits (e.g., `ADR-0001`, `ADR-0042`). Numbers are never reused, even if a record is superseded. File names follow `ADR-NNNN-short-title.md`.

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001-python-for-v2.md) | Python for the v2 Runtime | Accepted |
| [ADR-0002](ADR-0002-constructor-injection.md) | Constructor Injection with a Single Composition Root | Accepted |
| [ADR-0003](ADR-0003-config-declared-plugins.md) | Config-Declared Plugins | Accepted |
| [ADR-0004](ADR-0004-multiplexed-websocket.md) | One Multiplexed WebSocket per Session | Accepted |
| [ADR-0005](ADR-0005-apache-2-license.md) | Apache-2.0 License | Accepted |
