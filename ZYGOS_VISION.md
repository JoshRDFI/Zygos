# Zygos Vision \& Architecture Blueprint



## Philosophy

Everything required to run an intelligent system should be modular, inspectable, replaceable, and understandable.

Design principles:

* No hidden state.
* Every decision is traceable.
* Every subsystem has a clean interface.
* Every model can be swapped.
* Every memory is inspectable.
* Every skill is a file.
* Every tool is replaceable.
* Every workflow is composable.



Zygos is not:

* A chatbot.
* A monolithic framework.
* A no-code platform.
* A hidden orchestration layer.
* A black box.
* An autonomous system that rewrites itself without oversight.
* Tied to any single model provider.
* Dependent on any single interface (CLI, web, desktop).



## Project Identity

Zygos is an AI Runtime rather than a chatbot or a single agent. It provides the infrastructure for intelligent systems through modular runtime services.

Zygos remains the open, extensible runtime and experimentation platform.



## High-Level Architecture

Browser (React + Tailwind)
-> FastAPI
-> Runtime API
-> Runtime Core
-> Services
- MemoryService
- ModelService
- SkillService
- ToolService
- TraceService
- SchedulerService
- PluginService
- ConfigService

Clients:

* Web UI
* CLI
* REST API
* Future Python SDK



## Technology Stack

Backend:

* Python 3.12+
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* WebSockets
* SQLite initially, optional PostgreSQL/pgvector

Frontend:

* React
* Tailwind CSS
* Vite

AI:

* Ollama
* vLLM
* OpenAI-compatible APIs
* Anthropic
* Hugging Face where appropriate

## 

## Migration Strategy

This is an architectural migration, not a rewrite.

Keep:

* Provider routing
* RDT engine
* Context management
* Learning concepts
* Tool framework
* Prompt assets
* Utilities

Refactor:

* Conversation orchestration
* Runtime loop
* Memory interfaces
* Tool invocation

Replace:

* Electron
* Monolithic CLI-first application shell

## 

## Runtime Services

* Runtime
* Memory
* Skills
* Models
* Tools
* Plugins
* Scheduler
* Tracing
* Configuration

Each service exposes a stable interface and is independently replaceable.

## 

## Memory Model

Working Memory

* Active context
* Scratchpad

Episodic Memory

* Sessions
* Projects
* Conversation history

Semantic Memory

* Facts
* Documents
* Knowledge

Procedural Memory

* Skills
* Recipes
* Templates

## 

## Skills

Each skill contains:

* SKILL.md
* metadata
* examples
* tests
* version
* trigger conditions
* required tools

Lifecycle:
Reflection -> Proposal -> Human Review -> Test -> Publish -> Monitor -> Improve

## 

## Model Routing

Task classification chooses the most appropriate model. Providers are abstracted behind ModelService.

## 

## Tool Framework

Every tool implements:

* prepare()
* execute()
* verify()
* cleanup()

## 

## Execution Traces

Record:

* Prompt
* Plan
* Model
* Retrieved memories
* Skills
* Tool calls
* Timing
* Errors
* Corrections
* Reflection
* Outcome

Execution traces become the foundation for debugging and future self-improvement.

## 

## Reflection Engine

After meaningful tasks:

* Analyze execution trace
* Suggest improvements
* Propose new skills
* Recommend prompt updates
* Never self-deploy without approval

## 

## Plugins

Everything beyond the runtime core is a plugin:

* Memory backends
* Providers
* Tools
* Skills
* Workflows

## 

## Workflows

Generalized workflows include:

* Interview
* Research
* Code Review
* Architecture
* Brainstorming
* Planning

## 

## Introspection Console

Expose:

* Active model
* Reasoning profile
* Retrieved memories
* Candidate skills
* Tool activity
* Context usage
* Execution trace
* Confidence

## 

## Self-Contained Installation

A user should be able to clone Zygos onto a clean machine and be productive with a single installation command.

Goal: one installation command.

Installer responsibilities:

* Install Python environment
* Create virtual environment
* Install backend dependencies
* Install frontend dependencies
* Build frontend
* Initialize database
* Download optional local models
* Validate providers
* Launch runtime

A new user should only need Git and Python installed. Everything else should be bootstrapped automatically by Zygos.

## 

## RFC Process

Create docs/rfcs with sequential RFCs.

Initial RFCs:

* RFC-0001 Service Architecture
* RFC-0002 Memory Model
* RFC-0003 Skill Specification
* RFC-0004 Model Routing
* RFC-0005 Tool API
* RFC-0006 Plugin System
* RFC-0007 Execution Traces
* RFC-0008 Reflection Engine
* RFC-0009 Web UI
* RFC-0010 Public SDK



Architectural Fitness Test:

A set of questions every RFC has to answer before it's accepted.

* Does it make the runtime more modular?
* Does it introduce hidden state?
* Can it be replaced later?
* Is it observable?
* Does it increase coupling?
* Can it be tested independently?
* Does it preserve backwards compatibility?
* Does it require new configuration?
* Does it increase cognitive load?

If a proposal can't answer those questions well, it probably isn't ready.

## 

## Development Roadmap

Phase 1: Python migration and FastAPI foundation.
Phase 2: React/Tailwind UI.
Phase 3: Service architecture.
Phase 4: Layered memory.
Phase 5: Skills and plugin ecosystem.
Phase 6: Execution traces and reflection.
Phase 7: Scheduler and autonomy.
Phase 8: Community ecosystem.

## 

## Miscellaneous Design Info

* The runtime never depends on the UI.
* Services never depend on each other directly; they communicate through defined interfaces.
* Models are selected through ModelService, never called directly.
* Tool execution always goes through ToolService.
* Every significant action is traceable.
* Configuration is declarative.
* Every new subsystem requires an RFC before implementation.



Initial Document Set:

* README.md — What Zygos is and why it exists.
* VISION.md — Long-term direction and philosophy.
* CONSTITUTION.md — Immutable principles and architectural values.
* ARCHITECTURE.md — Canonical system design.
* ROADMAP.md — Phased development plan.
* STYLE\_GUIDE.md — Coding and documentation standards.
* CONTRIBUTING.md — Workflow for contributors.
* docs/rfcs/ — The decision log that governs evolution.



Project Architecture:

/

├── README.md

├── VISION.md

├── CONSTITUTION.md

├── ARCHITECTURE.md

├── ROADMAP.md

├── CONTRIBUTING.md

├── \[CODE/SUBDIRECTORIES]

├── docs/

│   ├── rfcs/

│   │   ├── RFC-0001-Service-Architecture.md

│   │   ├── RFC-0002-Memory.md

│   │   ├── RFC-0003-Skills.md

│   │   ├── RFC-0004-Model-Routing.md

│   │   └── ...

│   │

│   ├── philosophy/

│   ├── architecture/

│   └── developer-guide/





## Success Criteria

Zygos should become an open-source AI runtime that is modular, transparent, inspectable, extensible, self-contained, and suitable as the foundation for intelligent applications.

