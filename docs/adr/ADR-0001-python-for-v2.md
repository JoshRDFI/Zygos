# ADR-0001: Python for the v2 Runtime

**Status:** Accepted
**Date:** 2026-07-03

## Context

Zygos v1 is a working TypeScript CLI runtime located in `src/`. It implements the core concepts — provider routing, RDT reasoning, layered context, learning, and tools — and remains the validated reference for what the system must do.

The v2 vision calls for a self-hosted AI runtime with first-class support for local inference, voice (STT/TTS), Pydantic-validated data contracts, and an asyncio-native execution model. The frameworks most naturally suited to that goal — FastAPI, Pydantic, Whisper-family inference libraries, and the broader Python ML ecosystem — are Python-first. Maintaining the TypeScript runtime while simultaneously building a Python runtime that depended on interop layers or a shared language would increase both complexity and contributor overhead with no architectural benefit.

The primary alternative evaluated was continuing in TypeScript with Node.js ML bindings and an ONNX runtime. That path would have required third-party bindings for every inference library, and it would have cut the project off from the PyPI ecosystem that community AI tooling overwhelmingly targets.

(This decision was evaluated at project inception; no RFC covers this decision.)

## Decision

Zygos v2 is implemented in Python 3.12+. All new feature work, service definitions, plugin interfaces, and runtime code targets the Python codebase under `backend/`. The v1 TypeScript runtime is frozen at Stage 0 (bugfixes only) and serves as the migration reference: concepts and semantics proven in v1 are ported to v2; v1 is not extended.

## Consequences

The repository carries a dual-runtime structure — TypeScript in `src/` and Python in `backend/` — until v2 reaches feature parity and v1 is formally retired. During this period there are two independent test suites, two dependency manifests, and two CI jobs. Contributors must understand which side of the codebase is relevant to a given change. The benefit is that v2 can adopt the Python ML and inference ecosystem without binding layers, and that FastAPI and Pydantic become first-class primitives rather than workarounds. The Stage-0 freeze on v1 keeps that side stable while v2 catches up.
