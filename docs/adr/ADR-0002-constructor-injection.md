# ADR-0002: Constructor Injection with a Single Composition Root

**Status:** Accepted
**Date:** 2026-07-03

## Context

The v1 review identified bootstrap coupling as a root structural problem: `bootstrap.ts` hardcodes 21 concrete constructions, including every provider. Swapping a provider required a code edit, which violated the project constitution's requirement that providers be swappable via configuration alone. Making the system testable and extensible required a new wiring approach for v2.

Two alternatives were evaluated, as recorded in [RFC-0001](../rfcs/RFC-0001-Service-Architecture.md):

- **A DI framework** (e.g., `dependency-injector`): provides automatic wiring but adds framework indirection that makes dependencies harder to follow when reading the code — the opposite of the constitution's "simplicity over cleverness" principle.
- **A service locator / service registry**: lets modules pull their dependencies on demand, but this means dependencies disappear from function signatures and become hidden state by another name, re-creating the problem the design is trying to solve.

## Decision

v2 uses plain constructor injection throughout: every service declares its dependencies as constructor parameters typed against `typing.Protocol` interfaces. A single composition root, `runtime/bootstrap.py`, reads validated Pydantic configuration, resolves plugin classes via the config-declared plugin map, and assembles the complete object graph. `bootstrap.py` is the only module permitted to construct concrete service implementations; it must remain construction-only and must never accumulate logic beyond assembly.

## Consequences

The explicit wiring in `bootstrap.py` grows linearly with the number of services and plugins. This is an accepted cost: the composition root is the single file a developer reads to understand what runs. Every dependency is visible in function signatures, which makes the object graph trivially inspectable in code review and trivially mockable in tests. A standing review rule guards `bootstrap.py` against accreting logic beyond assembly; violations are review-blocking. No new framework dependency is introduced.
