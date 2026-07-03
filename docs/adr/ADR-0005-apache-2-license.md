# ADR-0005: Apache-2.0 License

**Status:** Accepted
**Date:** 2026-07-03

## Context

Zygos is released as public open-source software. The project anticipates corporate users operating it as infrastructure and a plugin ecosystem where third parties publish extensions. The license choice needed to be adoption-friendly while providing explicit intellectual property protections appropriate for an infrastructure runtime.

Two alternatives were evaluated:

- **MIT**: maximally permissive and familiar, but provides no explicit patent grant. Corporate legal teams evaluating infrastructure software frequently flag the absence of a patent grant as a compliance risk; MIT's brevity becomes a liability in that context.
- **AGPL-3.0**: provides the strongest copyleft protection and would require anyone operating a modified version as a network service to publish their changes. This is appropriate for some projects but deters corporate adoption of infrastructure components, which runs counter to the goal of building a widely-used plugin ecosystem.

## Decision

Zygos is licensed under the Apache License, Version 2.0. Apache-2.0 includes an explicit patent grant from all contributors, making the license safe for corporate infrastructure use. It permits commercial use, modification, and distribution with minimal conditions (preservation of notices), which keeps the plugin ecosystem adoption-friendly. The `LICENSE` file at the repository root is authoritative.

## Consequences

The license text is longer than MIT, which is a minor friction for contributors reading it for the first time. All contributors implicitly grant patent rights to users of the software under the terms of Apache-2.0, which is the intended guarantee. Community plugin authors publishing to PyPI may choose any compatible license for their own packages; Apache-2.0 for Zygos core does not impose copyleft obligations on downstream plugins.
