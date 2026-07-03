
# ZYGOS 2.0 IMPLEMENTATION SPEC

## Purpose

This document translates the long-term vision into an implementation strategy. The goal is an architectural migration from the current TypeScript CLI runtime to a Python-first AI runtime without discarding the proven concepts already developed.

## Core Principle

Do not rewrite. Migrate.

Preserve the ideas. Improve the architecture.

## Migration Strategy

Stage 0 - Freeze Features
- Avoid adding major new functionality to the TypeScript runtime.
- Fix bugs only.
- Treat the existing implementation as the reference.

Stage 1 - Python Runtime
- Establish a Python package layout.
- Create Runtime, Services, and Provider abstractions.
- Port provider routing and RDT.

Stage 2 - FastAPI
- Expose runtime through a REST and WebSocket API.
- Runtime must not depend on FastAPI.

Stage 3 - React UI
- React + Tailwind frontend.
- WebSocket streaming.
- No Electron.

## Architectural Rule

The runtime never depends on the UI.

Runtime <- FastAPI <- React
Runtime <- CLI
Runtime <- Tests
Runtime <- Future SDK

The runtime is the product. Everything else is an adapter.

## Proposed Directory Layout

backend/
  runtime/
  services/
  providers/
  memory/
  skills/
  tools/
  workflows/
  plugins/
  tracing/
  scheduler/
  api/
frontend/
  src/
  components/
  pages/
  hooks/
  services/
docs/
  rfcs/

## Service Contracts

Each service exposes a minimal, stable interface.

MemoryService
- store()
- retrieve()
- search()
- summarize()

ModelService
- classify_task()
- select_model()
- generate()

SkillService
- discover()
- rank()
- execute()
- propose()

ToolService
- prepare()
- execute()
- verify()
- cleanup()

TraceService
- begin_trace()
- record_event()
- finish_trace()
- reflect()

## Runtime Pipeline

User Request
-> Context Assembly
-> Memory Retrieval
-> Skill Discovery
-> Task Classification
-> Model Selection
-> Planning (RDT)
-> Tool Execution
-> Response
-> Execution Trace
-> Reflection
-> Improvement Proposal

## Self-Improvement Policy

The runtime never changes itself automatically.

Pipeline:
Execution Trace
-> Reflection
-> Proposal
-> Tests
-> Benchmark
-> Human Approval
-> Deploy

## Installer Goals

Single command installation should:
- Verify Python.
- Create virtual environment.
- Install Python dependencies.
- Install frontend dependencies.
- Build frontend.
- Initialize database.
- Generate config.
- Optionally install Ollama.
- Perform health check.
- Launch Zygos.

## Development Philosophy

Every subsystem should be:
- Modular
- Inspectable
- Replaceable
- Testable
- Independently evolvable

## RFC Process

Every significant architectural change requires an RFC before implementation.

Template:
- Motivation
- Problem Statement
- Proposed Design
- Alternatives Considered
- Migration Plan
- Risks
- Acceptance Criteria

## Near-Term Milestones

1. RFC-0001: Service Architecture
2. Python runtime skeleton
3. Port provider layer
4. Port RDT engine
5. FastAPI adapter
6. React UI
7. Execution tracing
8. Layered memory
9. Skills
10. Reflection engine
11. Plugin SDK
12. Stable 2.0 release

## Guiding Question

Before adding any feature, ask:
"Does this make Zygos more modular, inspectable, replaceable, and understandable?"

If the answer is no, redesign the feature.
