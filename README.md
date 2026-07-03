# Zygos

A production-oriented, TypeScript-based AI orchestration runtime.

## Why the name **Zygos**?

**Zygos** (ζυγός) comes from Ancient Greek and means **yoke**, **coupling**, or **joining**.

For this project, the name captures the core design philosophy:

- Binding multiple forces (providers, tools, reasoning) into coordinated motion
- Balance, alignment, and synchronization between components
- A control interface between independent actors (LLMs, tools, memory)

Zygos is not just a name change; it reflects how the system orchestrates independent capabilities into one coherent, reliable agent runtime.

## Core capabilities

- Multi-provider routing (OpenAI, Anthropic, Ollama, vLLM, custom fallback provider)
- Robust provider hardening (retry, circuit breaker, rate limiting, graceful fallback)
- RDT reasoning runtime (prelude → recurrent refinement → coda)
- Tool execution framework (streaming tools + registry)
- Conversation context management with SQLite persistence
- Self-learning system for proposing and applying tool improvements
- Interactive interviewer workflow for requirement gathering and build plan generation

---

## Quick Start (TL;DR: ~5 minutes)

```bash
git clone <your-repo-url>
cd zygos
npm install
cp .env.example .env
npm run verify
npm run dev -- "Hello Zygos"
```

For the fastest path, see **[QUICKSTART.md](./QUICKSTART.md)**.

---

## Prerequisites

- **Node.js 20+** (recommended: latest LTS)
- **npm 10+**
- OS: macOS, Linux, or Windows (WSL recommended on Windows)
- Optional for local-first usage:
  - **Ollama** running at `http://127.0.0.1:11434`

Check versions:

```bash
node -v
npm -v
```

---

## Installation

1. Clone the repository:

```bash
git clone <your-repo-url>
cd zygos
```

2. Install dependencies:

```bash
npm install
```

3. Create your env file:

```bash
cp .env.example .env
```

4. (Optional) Update provider config or env values:
   - Default config: `config/default.yaml`
   - Provider example: `config/providers.example.yaml`

---

## Configuration Guide (Essential)

Zygos supports both **environment variables** and **YAML config**.

### 1) Environment variables

Set keys in `.env` (or your deployment environment):

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `ZYGOS_CONTEXT_DB`
- `ZYGOS_LEARNING_DB`
- `ZYGOS_INTERVIEW_DB`
- `ZYGOS_DEBUG`

See **[.env.example](./.env.example)** for full list and examples.

### 2) Provider and runtime config

Edit `config/default.yaml` to choose:

- primary and fallback providers/models
- retry/circuit breaker/rate limit settings
- RDT behavior
- learning feature behavior
- interview workflow behavior

For full details, read **[CONFIGURATION.md](./CONFIGURATION.md)**.

---

## First Run Example

Run the built-in verification first:

```bash
npm run verify
```

Then start a conversation:

```bash
npm run dev -- "Summarize what Zygos can do"
```

Run with explicit provider/model override:

```bash
npm run dev -- "Explain retry strategy" --provider custom --model demo
```

---

## Basic Usage Examples

### Standard turn

```bash
npm run dev -- "Create a test plan for a Node.js API"
```

### RDT reasoning enabled

```bash
npm run dev -- "Design a scalable chat architecture" --rdt true --rdt-profile deep
```

### Search prior conversation history

```bash
npm run dev -- --history-search "auth" --session session_123
```

### Interview workflow

```bash
npm run dev -- --interview --interview-action start --session project_42 "Build an internal analytics dashboard"
npm run dev -- --interview --interview-action answer --session project_42 --stakeholder pm "MVP should include SSO and exports"
npm run dev -- --interview --interview-action complete --session project_42 "Generate final plan"
```

More practical scenarios: **[EXAMPLES.md](./EXAMPLES.md)**.

---

## CLI Command Reference

Main command:

```bash
npm run dev -- "<message>" [flags]
```

### Common flags

- `--config <path>`: custom config file
- `--provider <provider>`: route override (e.g., `openai`, `anthropic`, `ollama`, `vllm`, `custom`)
- `--model <model>`: model override
- `--session <session_id>`: use existing session
- `--rdt true|false`: enable/disable RDT at runtime
- `--rdt-profile shallow|balanced|deep`: RDT profile

### Learning flags

- `--learning-list`
- `--learning-apply <proposal_id>`
- `--learning-rollback <tool[:versionId]>`
- `--learning-metrics`

### Interview flags

- `--interview`
- `--interview-action start|answer|complete|status|plan_export`
- `--stakeholder <stakeholder_id>`
- `--interview-override`

### History search

```bash
npm run dev -- --history-search "<query>" --session <session_id>
```

---

## Detailed Documentation

- Quick start: **[QUICKSTART.md](./QUICKSTART.md)**
- Configuration reference: **[CONFIGURATION.md](./CONFIGURATION.md)**
- Practical examples: **[EXAMPLES.md](./EXAMPLES.md)**
- Architecture: `docs/ARCHITECTURE_V2.md`
- Provider hardening: `docs/PROVIDER_HARDENING.md`
- Context management: `docs/CONTEXT_MANAGEMENT_GUIDE.md`
- RDT reasoning: `docs/RDT_REASONING_GUIDE.md`
- Learning system: `docs/LEARNING_SYSTEM_GUIDE.md`
- Interview workflow: `docs/INTERVIEWER_WORKFLOW_GUIDE.md`
- Tool development: `docs/TOOL_DEVELOPMENT_GUIDE.md`

---

## Troubleshooting

### 1) "No enabled providers are configured"
- Ensure at least one provider is enabled in `config/default.yaml` under `providers.credentials`.
- Or run with deterministic local provider:
  ```bash
  npm run dev -- "Hello" --provider custom --model demo
  ```

### 2) Authentication/provider errors
- Confirm API keys in `.env` (OpenAI/Anthropic).
- Check model names exist for your provider.

### 3) Ollama connection failure
- Verify Ollama is installed and running:
  ```bash
  ollama serve
  ```
- Confirm base URL in config (default: `http://127.0.0.1:11434`).

### 4) SQLite / DB path issues
- Ensure write permissions to project directory or override DB paths:
  - `ZYGOS_CONTEXT_DB`
  - `ZYGOS_LEARNING_DB`
  - `ZYGOS_INTERVIEW_DB`

### 5) TypeScript build/test issues
```bash
npm run typecheck
npm run build
npm test
```

---

## Contributing (Optional)

1. Create a feature branch.
2. Run quality checks before PR:

```bash
npm run verify
npm run typecheck
npm run test
```

3. Keep docs in sync when changing behavior.
4. Open a PR with a short test plan and sample CLI commands.

---

## License

Add your project license here (for example, MIT).
