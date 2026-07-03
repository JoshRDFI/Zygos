# Quickstart: Zygos (Under 5 Minutes)

This guide gets you from zero to your first successful run as fast as possible.

## 1) Install and run

```bash
git clone <your-repo-url>
cd zygos
npm install
cp .env.example .env
npm run verify
```

> `npm run verify` checks Node version, dependencies, config loading, SQLite paths, and a smoke-test engine run.

## 2) Start your first conversation

```bash
npm run dev -- "Hello! Give me a 3-step plan to build a notes app"
```

You should see streamed output and a `[done]` line.

---

## Minimal configuration example

If you want local deterministic behavior with no external API keys:

```bash
npm run dev -- "Explain the system" --provider custom --model demo
```

If you want local model inference with Ollama:

1. Start Ollama (`ollama serve`)
2. Pull a model (example):
   ```bash
   ollama pull llama3.1:8b
   ```
3. Run:
   ```bash
   npm run dev -- "Summarize this architecture" --provider ollama --model llama3.1:8b
   ```

---

## First conversation example (session-based)

```bash
npm run dev -- "We are building an internal analytics dashboard" --session demo_project
npm run dev -- "Now break that into milestones" --session demo_project
npm run dev -- --history-search "milestones" --session demo_project
```

---

## Common use cases

### A) Fast architecture brainstorming
```bash
npm run dev -- "Design a scalable webhook processing service" --rdt true --rdt-profile balanced
```

### B) Requirement interview + generated plan
```bash
npm run dev -- --interview --interview-action start --session proj_101 "Build an AI support assistant"
npm run dev -- --interview --interview-action answer --session proj_101 --stakeholder pm "Need SSO, audit logs, and analytics"
npm run dev -- --interview --interview-action complete --session proj_101 "Generate final implementation plan"
npm run dev -- --interview --interview-action plan_export --session proj_101 "Export the plan"
```

### C) Learning system visibility
```bash
npm run dev -- --learning-list
npm run dev -- --learning-metrics
```

---

## What to try next

1. Read **[CONFIGURATION.md](./CONFIGURATION.md)** to tune providers, RDT, learning, and interview behavior.
2. Explore **[EXAMPLES.md](./EXAMPLES.md)** for practical workflows.
3. Run full quality checks:
   ```bash
   npm run typecheck
   npm run build
   npm test
   ```
