# Zygos Vision

Zygos is an open, modular AI runtime designed to serve as the infrastructure layer for intelligent applications — not a chatbot, not an assistant, and not a monolithic framework. It gives developers a composable foundation of independently replaceable services that together support reasoning, memory, skill execution, tool use, and self-improvement, all under continuous human oversight.

## Philosophy

Zygos is built on a single organizing conviction: everything required to run an intelligent system should be modular, inspectable, replaceable, and understandable. That conviction shapes every design decision. There is no hidden state. Every decision is traceable back to the inputs and context that drove it. Every subsystem exposes a clean, stable interface. Every model can be swapped without touching the rest of the runtime. Every memory can be inspected by the operator. Every skill lives as a discrete, auditable artifact. Every tool can be replaced with an alternative implementation. Every workflow is composable from smaller, well-defined pieces.

These principles are captured in their immutable form in [CONSTITUTION.md](CONSTITUTION.md), which governs all changes to the runtime's core behavior.

## What Zygos Is Not

Understanding what Zygos refuses to become is as important as understanding what it is:

- Zygos is not a chatbot.
- Zygos is not a monolithic framework.
- Zygos is not a no-code platform.
- Zygos is not a hidden orchestration layer.
- Zygos is not a black box.
- Zygos is not an autonomous system that rewrites itself without oversight.
- Zygos is not tied to any single model provider.
- Zygos is not dependent on any single interface — CLI, web, and desktop are all equally valid clients.

## The Runtime Model

The Zygos runtime is a collection of independently replaceable services, each hidden behind a stable interface so that any single service can be upgraded, swapped, or extended without breaking the others.

- **Memory** maintains and retrieves the persistent state the runtime reasons over.
- **Models** routes tasks to the most appropriate language model, abstracting away provider differences.
- **Skills** discovers, selects, and executes named capability bundles that extend what the runtime can do.
- **Tools** provides safe, structured access to external systems, files, and APIs.
- **Plugins** loads optional capability bundles that extend the runtime without modifying its core.
- **Scheduler** manages deferred and recurring tasks on behalf of the runtime and its clients.
- **Tracing** records every significant action so that every outcome can be explained and audited.
- **Configuration** supplies declarative settings and resolves them consistently at startup and at runtime.
- **Voice** bridges spoken language to the runtime, accepting speech input and producing spoken responses.

## Memory Model

Zygos organizes memory into four layers, each serving a distinct purpose in the reasoning cycle.

- **Working memory** holds the active context and scratchpad for the current task.
- **Episodic memory** stores session histories, project records, and conversation logs.
- **Semantic memory** accumulates facts, documents, and long-lived knowledge.
- **Procedural memory** retains skills, recipes, and reusable templates for repeatable tasks.

## Skills

A skill is a self-contained capability artifact that bundles a human-readable description, worked examples, automated tests, a version identifier, trigger conditions that govern when the skill applies, and a declaration of which tools it requires. Skills are discrete and auditable, which means they can be reviewed, versioned, and replaced individually without disturbing the rest of the runtime.

Skills follow a deliberate lifecycle: **Reflection → Proposal → Human Review → Test → Publish → Monitor → Improve**. No skill reaches production without passing through human review and automated testing, and no deployed skill is exempt from ongoing performance monitoring that feeds back into the next improvement cycle.

## Self-Improvement

Zygos can improve itself, but never autonomously. After a meaningful task, the runtime analyzes its own execution trace, identifies patterns worth learning from, and proposes improvements — new skills, refined prompts, or updated workflows. Proposals are surfaced for human review and must be approved before they take effect.

This proposal-only discipline is not a feature toggle; it is a constitutional constraint. [CONSTITUTION.md](CONSTITUTION.md) establishes that human approval is required for any behavioral mutation to the runtime, and no version of Zygos is permitted to circumvent that requirement.

## Voice

Speaking to Zygos and hearing it respond is a first-class goal of the platform, not an afterthought. Voice is an equal peer of the web and CLI interfaces: speech-to-text carries input into the runtime, and text-to-speech carries responses back out. Local-first speech engines are preferred, keeping voice interaction available without sending audio to a remote service. Voice support is a required capability before Zygos reaches version 2.0.

## Deployment

Zygos is designed to run wherever its operator chooses: on a personal machine or on a modest hosted virtual machine. The result is an openable web page served locally — no cloud account required, no mandatory external dependency. The installation goal is a single command: given Git and Python, a new user should be able to clone the repository and have a running Zygos instance without any further manual setup. Everything else — environment preparation, database initialization, optional local model downloads, and runtime launch — is handled automatically by the installer.

## Introspection

Transparency is not limited to source code; the runtime itself must be legible while it runs. Zygos exposes an introspection console that shows the active model, the current reasoning profile, the memories retrieved for the current task, the candidate skills considered, the tools that have been called, current context usage, the full execution trace, and the runtime's confidence in its output. Operators should never have to guess what Zygos is doing or why.

## Governance

Every significant change to Zygos — new service, new protocol, breaking interface change — requires a Request for Comments (RFC) before implementation begins. RFCs create a searchable, versioned record of why the system looks the way it does, and they force proposals to be articulated clearly enough for the community to evaluate them.

Before an RFC can be accepted, it must pass the **Architectural Fitness Test** by answering all nine questions satisfactorily:

1. Does it make the runtime more modular?
2. Does it introduce hidden state?
3. Can it be replaced later?
4. Is it observable?
5. Does it increase coupling?
6. Can it be tested independently?
7. Does it preserve backwards compatibility?
8. Does it require new configuration?
9. Does it increase cognitive load?

If a proposal cannot answer those questions well, it is not ready.

## Success Criteria

Zygos succeeds when it has become an open-source AI runtime that is modular, transparent, inspectable, extensible, and self-contained — one that any developer can adopt as the foundation for an intelligent application, confident that it will stay out of the way, stay under their control, and grow with them over time.
